from __future__ import annotations
"""
memory_reader.py · 记忆文件读取层

职责：
  - 解析 Claude Code 的记忆目录路径
  - 扫描记忆文件，提取 frontmatter（不调 LLM）
  - 读取单条记忆的完整内容
  - 检测 MEMORY.md 索引健康状态

关键设计（来自 Claude Code 源码分析，见 CLAUDE_CODE_INTERNALS.md）：
  - 单文件单记忆：每个 .md 文件 = 一条记忆，MEMORY.md 只是索引
  - 只读前 30 行即可获取 frontmatter，不需要读全文
  - 路径不能硬编码为 ~/.claude/，用户可在 settings.json 自定义
  - MEMORY.md 上限：200 行 / 25KB，超出会被截断
"""

import json
import os
import re
import warnings
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional


# ── 常量（与 Claude Code 源码保持一致）─────────────────────────────────────────

MEMORY_DIRNAME = "memory"
MEMORY_INDEX_NAME = "MEMORY.md"
FRONTMATTER_MAX_LINES = 30       # 只读前 30 行，与源码一致
MAX_MEMORY_FILES = 200           # 扫描上限，与源码一致
MAX_INDEX_LINES = 200            # MEMORY.md 行数上限
MAX_INDEX_BYTES = 25_000         # MEMORY.md 字节上限（约 25KB）
VALID_MEMORY_TYPES = {"user", "feedback", "project", "reference"}


# ── 数据结构 ───────────────────────────────────────────────────────────────────

@dataclass
class MemoryHeader:
    """单条记忆的 frontmatter 摘要，扫描阶段产出，不包含正文。"""
    filename: str           # 相对于 memory 目录的路径，如 user_role.md
    file_path: Path         # 绝对路径
    mtime_ms: int           # 文件修改时间（毫秒时间戳）
    name: Optional[str]     # frontmatter 的 name 字段
    description: Optional[str]  # frontmatter 的 description 字段
    memory_type: Optional[str]  # user / feedback / project / reference / None


@dataclass
class MemoryFile:
    """单条记忆的完整内容，read_memory_file() 产出。"""
    header: MemoryHeader
    raw_content: str        # 文件完整原始内容
    body: str               # frontmatter 之后的正文部分
    has_why: bool           # 是否包含 **Why:** 结构
    has_how_to_apply: bool  # 是否包含 **How to apply:** 结构


@dataclass
class IndexHealth:
    """MEMORY.md 索引文件的健康状态。"""
    exists: bool
    line_count: int
    byte_count: int
    is_line_truncated: bool   # 是否已超过 200 行上限
    is_byte_truncated: bool   # 是否已超过 25KB 上限
    warning: Optional[str]    # 有问题时的提示文本


@dataclass
class ScanResult:
    """scan_memory_files() 的完整返回值。"""
    memory_dir: Path
    headers: list[MemoryHeader]
    index_health: IndexHealth
    project_name: str = ""          # 项目名（用于多项目展示）
    warnings: list[str] = field(default_factory=list)


@dataclass
class MultiProjectScanResult:
    """scan_all_projects() 的完整返回值。"""
    projects: list[ScanResult]      # 每个项目的独立扫描结果
    total_headers: list[MemoryHeader]  # 所有项目合并后的记忆列表
    total_count: int
    project_count: int


# ── 路径解析 ───────────────────────────────────────────────────────────────────

def get_memory_dir(cwd: Optional[Path] = None) -> Path:
    """
    解析单个项目的 Claude Code Auto Memory 目录路径。

    解析优先级（与 Claude Code 源码 paths.ts 一致）：
      1. CLAUDE_CODE_REMOTE_MEMORY_DIR 环境变量（远程模式全路径覆盖）
      2. ~/.claude/settings.json 的 autoMemoryDirectory 字段
      3. 默认：~/.claude/projects/<sanitized-cwd>/memory/

    Args:
        cwd: 当前工作目录（用于计算默认路径），None 时使用 os.getcwd()

    注意：MCP Server 进程的 CWD 不一定是用户工作的项目目录。
    如果需要扫描所有项目，请使用 get_all_memory_dirs()。
    """
    # 优先级 1：远程模式环境变量
    remote_override = os.environ.get("CLAUDE_CODE_REMOTE_MEMORY_DIR")
    if remote_override:
        return Path(remote_override)

    # 优先级 2：settings.json 自定义路径
    settings_override = _get_memory_dir_from_settings()
    if settings_override:
        return settings_override

    # 优先级 3：默认路径
    base_dir = _get_claude_config_home()
    target_cwd = cwd or Path(os.getcwd())
    sanitized = _sanitize_path(target_cwd)
    return base_dir / "projects" / sanitized / MEMORY_DIRNAME


def get_all_memory_dirs() -> list[Path]:
    """
    返回本机所有存在记忆文件的项目目录列表。

    遍历 ~/.claude/projects/*/memory/，找出实际存在且非空的目录。
    这是 P0 Bug 的修复方案：不依赖 MCP Server 的 CWD，
    直接枚举所有项目，让用户看到完整的记忆库全景。

    Returns:
        按最近修改时间降序排列的记忆目录列表（只包含实际存在的）
    """
    # 优先级 1：远程模式 / settings.json 覆盖（走单目录逻辑）
    remote_override = os.environ.get("CLAUDE_CODE_REMOTE_MEMORY_DIR")
    if remote_override:
        p = Path(remote_override)
        return [p] if p.exists() else []

    settings_override = _get_memory_dir_from_settings()
    if settings_override:
        return [settings_override] if settings_override.exists() else []

    # 默认：枚举 ~/.claude/projects/*/memory/
    base_dir = _get_claude_config_home()
    projects_dir = base_dir / "projects"

    if not projects_dir.exists():
        return []

    memory_dirs = []
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue
        mem_dir = project_dir / MEMORY_DIRNAME
        if not mem_dir.exists():
            continue
        # 排除空目录（只有 MEMORY.md 但无记忆文件的也算有效）
        try:
            any_md = any(mem_dir.rglob("*.md"))
        except OSError:
            continue
        if any_md:
            memory_dirs.append(mem_dir)

    # 按最近修改时间降序（最活跃的项目排在前面）
    def _latest_mtime(d: Path) -> float:
        try:
            return max(
                (f.stat().st_mtime for f in d.rglob("*.md")),
                default=0.0,
            )
        except OSError:
            return 0.0

    memory_dirs.sort(key=_latest_mtime, reverse=True)
    return memory_dirs


def get_project_name_from_memory_dir(memory_dir: Path) -> str:
    """
    从记忆目录路径反推项目名称，用于展示。

    ~/.claude/projects/-Users-maavis-my-project/memory/
    → my-project（取最后一段，去掉前缀连字符）
    """
    # 取 projects/<sanitized-project-name>/memory 中间那段
    try:
        sanitized = memory_dir.parent.name  # e.g. "-Users-maavis-my-project"
        # 还原：把连字符分隔的路径取最后有意义的部分
        parts = sanitized.strip("-").split("-")
        # 过滤掉 "Users" "home" 这类通用词，取最后 1-2 个有意义的段
        meaningful = [p for p in parts if p and p.lower() not in ("users", "home", "root")]
        if meaningful:
            return "-".join(meaningful[-2:]) if len(meaningful) >= 2 else meaningful[-1]
        return sanitized
    except Exception:
        return memory_dir.parent.name


def _get_claude_config_home() -> Path:
    """返回 ~/.claude 目录（Claude Code 的配置根目录）。"""
    claude_config = os.environ.get("CLAUDE_CONFIG_DIR")
    if claude_config:
        return Path(claude_config)
    return Path.home() / ".claude"


def _get_memory_dir_from_settings() -> Optional[Path]:
    """
    读取 ~/.claude/settings.json 中的 autoMemoryDirectory 字段。
    只读取用户级 settings（user/local/flag/policy），不读取项目级（安全原因）。
    """
    settings_files = [
        _get_claude_config_home() / "settings.json",
        _get_claude_config_home() / "settings.local.json",
    ]
    for settings_path in settings_files:
        if not settings_path.exists():
            continue
        try:
            with open(settings_path) as f:
                settings = json.load(f)
            auto_mem_dir = settings.get("autoMemoryDirectory")
            if auto_mem_dir:
                p = Path(auto_mem_dir).expanduser()
                if p.is_absolute():
                    return p
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _sanitize_path(path: Path) -> str:
    """
    把路径转成安全的目录名（与 Claude Code sanitizePath 逻辑对应）。
    例：/Users/maavis/my-project → -Users-maavis-my-project
    """
    # 把路径分隔符替换成连字符，去掉首尾的连字符
    sanitized = str(path).replace("/", "-").replace("\\", "-")
    return sanitized.strip("-")


# ── Frontmatter 解析 ──────────────────────────────────────────────────────────

def parse_frontmatter(content: str) -> dict:
    """
    解析 Markdown 文件的 YAML frontmatter。
    只处理简单的 key: value 格式，不引入 PyYAML 依赖（避免安装复杂度）。

    返回：{'name': ..., 'description': ..., 'type': ..., ...}
    找不到 frontmatter 时返回空 dict。
    """
    content = content.strip()
    if not content.startswith("---"):
        return {}

    # 找到 frontmatter 的结束标记
    end_match = re.search(r"\n---\s*\n", content[3:])
    if not end_match:
        return {}

    frontmatter_text = content[3: end_match.start() + 3]
    result = {}

    for line in frontmatter_text.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            result[key] = value

    return result


def _extract_body(content: str) -> str:
    """提取 frontmatter 之后的正文部分。"""
    content = content.strip()
    if not content.startswith("---"):
        return content

    end_match = re.search(r"\n---\s*\n", content[3:])
    if not end_match:
        return content

    body_start = end_match.start() + 3 + len(end_match.group())
    return content[body_start:].strip()


# ── 记忆文件扫描 ──────────────────────────────────────────────────────────────

def scan_memory_files(memory_dir: Optional[Path] = None) -> ScanResult:
    """
    扫描记忆目录，返回所有记忆文件的 header 列表。

    设计要点（与 Claude Code memoryScan.ts 一致）：
      - 只读前 30 行（frontmatter），不读全文，减少 I/O
      - 排除 MEMORY.md（索引文件，不是记忆本身）
      - 按 mtime 降序排列（最近修改的优先）
      - 上限 200 个文件，超出部分静默截断
      - 目录不存在时返回空结果，不报错
    """
    if memory_dir is None:
        memory_dir = get_memory_dir()

    warn_messages = []

    # 检查目录是否存在
    if not memory_dir.exists():
        return ScanResult(
            memory_dir=memory_dir,
            headers=[],
            index_health=IndexHealth(
                exists=False,
                line_count=0,
                byte_count=0,
                is_line_truncated=False,
                is_byte_truncated=False,
                warning="记忆目录不存在。你可能还没有 Claude Code 记忆，"
                        "或 Auto Memory 功能已被禁用（检查 CLAUDE_CODE_DISABLE_AUTO_MEMORY 环境变量）。",
            ),
            warnings=[f"记忆目录不存在：{memory_dir}"],
        )

    # 扫描所有 .md 文件（递归，排除 MEMORY.md）
    headers = []
    for md_file in sorted(memory_dir.rglob("*.md")):
        if md_file.name == MEMORY_INDEX_NAME:
            continue

        try:
            header = _read_memory_header(md_file, memory_dir)
            headers.append(header)
        except OSError as e:
            warn_messages.append(f"跳过无法读取的文件 {md_file.name}：{e}")
        except Exception as e:
            warn_messages.append(f"解析 {md_file.name} 时出错（已跳过）：{e}")

    # 按 mtime 降序排列，取前 200 个
    headers.sort(key=lambda h: h.mtime_ms, reverse=True)
    if len(headers) > MAX_MEMORY_FILES:
        warn_messages.append(
            f"记忆文件数量（{len(headers)}）超过上限 {MAX_MEMORY_FILES}，"
            f"已截断，{len(headers) - MAX_MEMORY_FILES} 个较旧的文件未被扫描。"
        )
        headers = headers[:MAX_MEMORY_FILES]

    # 检查索引文件健康状态
    index_health = check_memory_index_health(memory_dir)

    return ScanResult(
        memory_dir=memory_dir,
        headers=headers,
        index_health=index_health,
        project_name=get_project_name_from_memory_dir(memory_dir),
        warnings=warn_messages,
    )


def scan_all_projects(project_path: Optional[Path] = None) -> MultiProjectScanResult:
    """
    扫描所有项目的记忆目录，返回合并结果。

    这是 P0 Bug 的修复入口——不依赖 MCP Server 的 CWD，
    直接枚举用户所有项目，确保不会漏掉或找错记忆文件。

    Args:
        project_path: 可选的过滤路径。传入时只返回对应项目的记忆，
                      不传则返回所有项目的合并结果。
    """
    if project_path is not None:
        # 精确模式：用指定路径计算目标目录
        target_dir = get_memory_dir(cwd=project_path)
        scan = scan_memory_files(target_dir)
        return MultiProjectScanResult(
            projects=[scan],
            total_headers=scan.headers,
            total_count=len(scan.headers),
            project_count=1,
        )

    # 全局模式：枚举所有项目
    all_dirs = get_all_memory_dirs()

    if not all_dirs:
        return MultiProjectScanResult(
            projects=[],
            total_headers=[],
            total_count=0,
            project_count=0,
        )

    project_scans = []
    all_headers = []

    for mem_dir in all_dirs:
        scan = scan_memory_files(mem_dir)
        project_scans.append(scan)
        all_headers.extend(scan.headers)

    # 合并后按 mtime 降序重新排序
    all_headers.sort(key=lambda h: h.mtime_ms, reverse=True)

    return MultiProjectScanResult(
        projects=project_scans,
        total_headers=all_headers,
        total_count=len(all_headers),
        project_count=len(project_scans),
    )


def _read_memory_header(file_path: Path, memory_dir: Path) -> MemoryHeader:
    """
    读取单个记忆文件的 header（只读前 30 行）。
    """
    # 只读前 30 行，与源码 FRONTMATTER_MAX_LINES 一致
    lines = []
    with open(file_path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i >= FRONTMATTER_MAX_LINES:
                break
            lines.append(line)
    content = "".join(lines)

    # 获取文件修改时间
    stat = file_path.stat()
    mtime_ms = int(stat.st_mtime * 1000)

    # 解析 frontmatter
    fm = parse_frontmatter(content)

    # 验证 memory_type
    raw_type = fm.get("type", "").strip()
    memory_type = raw_type if raw_type in VALID_MEMORY_TYPES else None

    # 相对路径（相对于 memory 目录）
    try:
        filename = str(file_path.relative_to(memory_dir))
    except ValueError:
        filename = file_path.name

    return MemoryHeader(
        filename=filename,
        file_path=file_path,
        mtime_ms=mtime_ms,
        name=fm.get("name") or None,
        description=fm.get("description") or None,
        memory_type=memory_type,
    )


# ── 读取单条记忆完整内容 ──────────────────────────────────────────────────────

def read_memory_file(file_path: Path, memory_dir: Optional[Path] = None) -> MemoryFile:
    """
    读取单条记忆的完整内容。
    相比 scan 阶段，这里读取全文，用于 LLM 评分时的输入。
    """
    if memory_dir is None:
        memory_dir = get_memory_dir()

    with open(file_path, encoding="utf-8") as f:
        raw_content = f.read()

    stat = file_path.stat()
    mtime_ms = int(stat.st_mtime * 1000)
    fm = parse_frontmatter(raw_content)
    raw_type = fm.get("type", "").strip()
    memory_type = raw_type if raw_type in VALID_MEMORY_TYPES else None

    try:
        filename = str(file_path.relative_to(memory_dir))
    except ValueError:
        filename = file_path.name

    header = MemoryHeader(
        filename=filename,
        file_path=file_path,
        mtime_ms=mtime_ms,
        name=fm.get("name") or None,
        description=fm.get("description") or None,
        memory_type=memory_type,
    )

    body = _extract_body(raw_content)
    has_why = "**Why:**" in raw_content or "**why:**" in raw_content.lower()
    has_how_to_apply = (
        "**How to apply:**" in raw_content
        or "**how to apply:**" in raw_content.lower()
    )

    return MemoryFile(
        header=header,
        raw_content=raw_content,
        body=body,
        has_why=has_why,
        has_how_to_apply=has_how_to_apply,
    )


# ── MEMORY.md 索引健康检查 ────────────────────────────────────────────────────

def check_memory_index_health(memory_dir: Path) -> IndexHealth:
    """
    检查 MEMORY.md 索引文件的健康状态。
    上限：200 行 / 25KB（超出时 Claude Code 会截断，用户看不到完整索引）。
    """
    index_path = memory_dir / MEMORY_INDEX_NAME

    if not index_path.exists():
        return IndexHealth(
            exists=False,
            line_count=0,
            byte_count=0,
            is_line_truncated=False,
            is_byte_truncated=False,
            warning=None,
        )

    try:
        content = index_path.read_text(encoding="utf-8")
    except OSError as e:
        return IndexHealth(
            exists=True,
            line_count=0,
            byte_count=0,
            is_line_truncated=False,
            is_byte_truncated=False,
            warning=f"无法读取 MEMORY.md：{e}",
        )

    line_count = len(content.splitlines())
    byte_count = len(content.encode("utf-8"))
    is_line_truncated = line_count >= MAX_INDEX_LINES
    is_byte_truncated = byte_count >= MAX_INDEX_BYTES

    warning = None
    if is_line_truncated and is_byte_truncated:
        warning = (
            f"⚠️ MEMORY.md 已达到行数上限（{line_count} 行）且接近字节上限"
            f"（{byte_count:,} 字节）。Claude Code 正在截断索引，部分记忆可能不会被加载。"
            f"建议清理低质量记忆以缩减索引大小。"
        )
    elif is_line_truncated:
        warning = (
            f"⚠️ MEMORY.md 已达到 {line_count} 行（上限 {MAX_INDEX_LINES} 行）。"
            f"Claude Code 正在截断索引，建议清理低质量记忆。"
        )
    elif is_byte_truncated:
        warning = (
            f"⚠️ MEMORY.md 已达到 {byte_count:,} 字节（上限 {MAX_INDEX_BYTES:,} 字节）。"
            f"索引条目过长，建议精简描述。"
        )
    elif line_count >= MAX_INDEX_LINES * 0.8:
        # 接近上限时提前预警（80% 时）
        warning = (
            f"📊 MEMORY.md 当前 {line_count} 行，接近 {MAX_INDEX_LINES} 行上限"
            f"（已用 {line_count / MAX_INDEX_LINES:.0%}）。"
        )

    return IndexHealth(
        exists=True,
        line_count=line_count,
        byte_count=byte_count,
        is_line_truncated=is_line_truncated,
        is_byte_truncated=is_byte_truncated,
        warning=warning,
    )


# ── 辅助工具 ──────────────────────────────────────────────────────────────────

def memory_age_days(mtime_ms: int) -> int:
    """计算记忆距今的天数（向下取整，与 Claude Code memoryAge.ts 一致）。"""
    now_ms = int(datetime.now().timestamp() * 1000)
    return max(0, (now_ms - mtime_ms) // 86_400_000)


def format_age(mtime_ms: int, lang: str | None = None) -> str:
    """返回人类可读的记忆年龄（与 Claude Code memoryAge() 一致）。"""
    from src.config import detect_language
    resolved = lang if lang in ("en", "zh") else detect_language()
    days = memory_age_days(mtime_ms)
    if resolved == "zh":
        if days == 0: return "今天"
        if days == 1: return "昨天"
        return f"{days} 天前"
    else:
        if days == 0: return "today"
        if days == 1: return "yesterday"
        return f"{days}d ago"


def format_memory_manifest(headers: list[MemoryHeader]) -> str:
    """
    把 header 列表格式化为文本清单，供 LLM 读取。
    格式与 Claude Code formatMemoryManifest() 一致：
      - [type] filename (timestamp): description
    """
    lines = []
    for h in headers:
        tag = f"[{h.memory_type}] " if h.memory_type else ""
        ts = datetime.fromtimestamp(h.mtime_ms / 1000).isoformat()
        desc = f": {h.description}" if h.description else ""
        lines.append(f"- {tag}{h.filename} ({ts}){desc}")
    return "\n".join(lines)
