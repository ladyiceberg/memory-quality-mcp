"""
Memory Quality MCP Server
给 Claude Code 的记忆层加一个「体检」功能。

工具列表：
  - memory_audit()        快速体检，返回健康摘要（不调 LLM）
  - memory_report()       详细清单，每条附带四维质量评分（调 LLM）
  - memory_cleanup()      执行清理（默认 dry_run，先预览）
  - memory_score()        单条记忆质量打分（调试用）
"""

import asyncio
import os
from pathlib import Path

import yaml
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from src.config import load_config

# ── 加载配置 ──────────────────────────────────────────────────────────────────

CONFIG = load_config()

# ── MCP Server 初始化 ──────────────────────────────────────────────────────────

app = Server("memory-quality-mcp")


# ── 工具定义 ──────────────────────────────────────────────────────────────────

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="memory_audit",
            description=(
                "快速扫描你所有 Claude Code 项目的记忆库，返回健康摘要。"
                "默认扫描全部项目；传入 project_path 可只扫描指定项目。"
                "不调用 LLM，速度快，适合先做整体了解。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {
                        "type": "string",
                        "description": (
                            "可选。指定要扫描的项目路径（如 /Users/me/my-project）。"
                            "不传则扫描所有项目。"
                        ),
                    }
                },
                "required": [],
            },
        ),
        Tool(
            name="memory_report",
            description=(
                "对记忆库做详细的质量分析，每条记忆附带四维评分"
                "（重要性 / 时效性 / 可信度 / 准确性）和建议操作（保留 / 复查 / 删除）。"
                "默认扫描全部项目；传入 project_path 可只分析指定项目。"
                "会调用 LLM 进行分析，耗时比 memory_audit 长。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "verbose": {
                        "type": "boolean",
                        "description": "是否返回所有记忆。false（默认）只返回建议删除和建议复查的条目。",
                        "default": False,
                    },
                    "project_path": {
                        "type": "string",
                        "description": (
                            "可选。指定要分析的项目路径（如 /Users/me/my-project）。"
                            "不传则分析所有项目。"
                        ),
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="memory_cleanup",
            description=(
                "执行记忆清理。默认为预览模式（dry_run=true），只展示将要清理的内容，不实际删除。"
                "设置 dry_run=false 并经过用户明确确认后，才会执行删除。"
                "删除前会自动备份到 .trash 目录。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "dry_run": {
                        "type": "boolean",
                        "description": "true（默认）= 只预览，不执行。false = 真正删除（需用户确认）。",
                        "default": True,
                    },
                    "filenames": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "要清理的记忆文件名列表（来自 memory_report 的结果）。"
                            "不传则清理所有「建议删除」的条目。"
                        ),
                    },
                    "project_path": {
                        "type": "string",
                        "description": (
                            "可选。指定要清理的项目路径（如 /Users/me/my-project）。"
                            "不传则清理所有项目中建议删除的条目。"
                        ),
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="memory_score",
            description=(
                "对单条记忆内容进行四维质量打分（重要性 / 时效性 / 可信度 / 准确性）。"
                "主要用于调试和验证评分模型，也可以用来评估一条新记忆是否值得保存。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "要评分的记忆内容（纯文本或 Markdown 格式均可）。",
                    },
                    "memory_type": {
                        "type": "string",
                        "enum": ["user", "feedback", "project", "reference"],
                        "description": "记忆类型（可选，提供后评分更准确）。",
                    },
                },
                "required": ["content"],
            },
        ),
        Tool(
            name="memory_dashboard",
            description=(
                "生成记忆健康报告的可视化页面，用系统默认浏览器打开。"
                "优先复用上一次 memory_report() 的缓存结果，无需重新调用 LLM。"
                "如果没有缓存，会先运行一次完整分析再打开页面。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {
                        "type": "string",
                        "description": (
                            "可选。指定要分析的项目路径（如 /Users/me/my-project）。"
                            "不传则分析所有项目。"
                        ),
                    },
                },
                "required": [],
            },
        ),
    ]


# ── 工具实现 ──────────────────────────────────────────────────────────────────

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "memory_audit":
        return await _handle_memory_audit(arguments)
    elif name == "memory_report":
        return await _handle_memory_report(arguments)
    elif name == "memory_cleanup":
        return await _handle_memory_cleanup(arguments)
    elif name == "memory_score":
        return await _handle_memory_score(arguments)
    elif name == "memory_dashboard":
        return await _handle_memory_dashboard(arguments)
    else:
        return [TextContent(type="text", text=f"未知工具：{name}")]


# ── 4b：memory_audit ──────────────────────────────────────────────────────────

async def _handle_memory_audit(arguments: dict) -> list[TextContent]:
    """
    快速体检：纯文件扫描 + 规则引擎，不调 LLM。
    默认扫描所有项目，支持 project_path 精确过滤。
    """
    from src.memory_reader import (
        format_age,
        memory_age_days,
        scan_all_projects,
    )
    from src.quality_engine import STALENESS

    project_path_str = arguments.get("project_path")
    project_path = Path(project_path_str) if project_path_str else None

    multi = scan_all_projects(project_path)

    if multi.project_count == 0 or multi.total_count == 0:
        hint = (
            f"指定项目 `{project_path_str}` 下" if project_path_str
            else "所有项目下"
        )
        return [TextContent(type="text", text=(
            f"📭 未找到 Claude Code 记忆文件（{hint}）。\n\n"
            "可能原因：\n"
            "- Claude Code 版本低于 v2.1.59，Auto Memory 功能尚未开放\n"
            "- Auto Memory 被禁用（检查 `CLAUDE_CODE_DISABLE_AUTO_MEMORY` 环境变量）\n"
            "- 还没有积累足够多的对话让 Claude 决定写入记忆\n"
            "- 记忆目录在非默认位置（检查 `~/.claude/settings.json`）"
        ))]

    total = multi.total_count
    all_headers = multi.total_headers

    # 规则引擎快速统计
    stale_count = 0
    project_stale_count = 0
    oldest_header = None

    for h in all_headers:
        age = memory_age_days(h.mtime_ms)
        threshold = STALENESS.get(f"{h.memory_type}_type", STALENESS.get("general", 90))
        if age > threshold:
            stale_count += 1
        if h.memory_type == "project" and age > STALENESS.get("project_type", 90):
            project_stale_count += 1
        if oldest_header is None or h.mtime_ms < oldest_header.mtime_ms:
            oldest_header = h

    # 构建输出
    scope = f"项目 `{project_path_str}`" if project_path_str else f"全部 {multi.project_count} 个项目"
    lines = [
        f"## 🔍 记忆库健康报告",
        f"",
        f"**扫描范围**：{scope}",
        f"**总记忆数**：{total} 条",
        f"",
        f"### 快速诊断",
        f"| 指标 | 数量 |",
        f"|------|------|",
        f"| 可能过时（超过阈值天数）| {stale_count} 条 |",
        f"| 建议优先审查（project 类型过时）| {project_stale_count} 条 |",
        f"",
    ]

    # 多项目时按项目分列索引健康
    if multi.project_count > 1:
        lines.append("### 各项目状态")
        for scan in multi.projects:
            ih = scan.index_health
            status = "⚠️" if (ih.is_line_truncated or ih.is_byte_truncated) else "✅"
            lines.append(
                f"- {status} **{scan.project_name}**：{len(scan.headers)} 条记忆"
                + (f"，索引 {ih.line_count} 行" if ih.exists else "，索引不存在")
            )
        lines.append("")
    else:
        # 单项目展示索引健康详情
        scan = multi.projects[0]
        ih = scan.index_health
        if ih.exists:
            lines += [
                f"### MEMORY.md 索引状态",
                f"- 当前：{ih.line_count} 行 / {ih.byte_count:,} 字节",
                f"- 上限：200 行 / 25,000 字节",
                f"- 使用率：{ih.line_count / 200:.0%}（行）",
            ]
            if ih.warning:
                lines.append(f"- ⚠️ {ih.warning}")
            lines.append("")

    # 最老的记忆
    if oldest_header:
        lines += [
            f"### 最老的记忆",
            f"- `{oldest_header.filename}` — {format_age(oldest_header.mtime_ms)}",
            f"  {oldest_header.description or oldest_header.name or '无描述'}",
            f"",
        ]

    # 预估 LLM 调用次数（帮用户决定是否运行 report）
    batch_size = CONFIG.get("batch_size", 6)
    estimated_calls = (total + batch_size - 1) // batch_size + 1  # +1 冲突检测
    lines += [
        f"---",
        f"▶ 运行 `memory_report()` 获取详细的质量评分和清理建议",
        f"  （预计调用 LLM 约 {estimated_calls} 次）",
    ]

    return [TextContent(type="text", text="\n".join(lines))]


# ── 4c：memory_report ─────────────────────────────────────────────────────────

async def _handle_memory_report(arguments: dict) -> list[TextContent]:
    """
    详细质量报告：规则引擎 + LLM 四维评分 + 冲突检测。
    默认扫描所有项目，支持 project_path 精确过滤。
    """
    from src.memory_reader import (
        format_age,
        read_memory_file,
        scan_all_projects,
    )
    from src.quality_engine import run_quality_engine

    verbose = arguments.get("verbose", False)
    project_path_str = arguments.get("project_path")
    project_path = Path(project_path_str) if project_path_str else None

    multi = scan_all_projects(project_path)

    if multi.total_count == 0:
        return [TextContent(type="text", text="📭 未找到记忆文件，无需分析。")]

    # 读取全文（LLM 评分需要完整内容）
    memory_files = []
    read_errors = []
    for h in multi.total_headers:
        # 找到该 header 所属的项目 scan，以获取正确的 memory_dir
        owning_dir = h.file_path.parent
        while owning_dir.name != "memory" and owning_dir != owning_dir.parent:
            owning_dir = owning_dir.parent
        try:
            mf = read_memory_file(h.file_path, owning_dir)
            memory_files.append(mf)
        except OSError as e:
            read_errors.append(f"无法读取 {h.filename}：{e}")

    # 运行评分引擎
    try:
        result = run_quality_engine(memory_files, run_conflict_detection=True)
    except ValueError as e:
        return [TextContent(type="text", text=(
            f"❌ 无法运行 LLM 评分：{e}\n\n"
            "请设置对应的 API Key 环境变量（OPENAI_API_KEY / KIMI_API_KEY / MINIMAX_API_KEY 等），\n"
            "或在 `~/.memory-quality-mcp/config.yaml` 中配置 provider 和 api_key。"
        ))]

    # ── 把评分结果写入 session store（P2 修复）────────────────────────────────
    from src.session_store import save_report, ReportEntry
    store_entries = []
    for sm in result.scored_memories:
        # 找到该文件所属的 memory 目录
        project_dir = sm.header.file_path.parent
        while project_dir.name != "memory" and project_dir != project_dir.parent:
            project_dir = project_dir.parent
        store_entries.append(ReportEntry(
            filename=sm.header.filename,
            file_path=str(sm.header.file_path),
            action=sm.action,
            composite=sm.scores.composite,
            reason=sm.reason,
            is_not_to_save=sm.is_not_to_save,
            memory_type=sm.header.memory_type,
            project_dir=str(project_dir),
        ))
    report_id = save_report(store_entries)

    # ── 构建输出 ─────────────────────────────────────────────────────────────
    scope = f"项目 `{project_path_str}`" if project_path_str else f"全部 {multi.project_count} 个项目"
    lines = [
        f"## 📊 记忆质量详细报告",
        f"",
        f"**扫描范围**：{scope}　**总计**：{result.total} 条  |  "
        f"🗑 删除 {result.to_delete} 条  |  "
        f"🔄 复查 {result.to_review} 条  |  "
        f"✅ 保留 {result.to_keep} 条",
        f"",
    ]

    # 冲突
    if result.conflicts:
        lines.append(f"### ⚡ 发现 {len(result.conflicts)} 对冲突记忆")
        for c in result.conflicts:
            severity_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(c.severity, "⚪")
            lines.append(f"- {severity_icon} `{c.filename_a}` × `{c.filename_b}`")
            lines.append(f"  {c.description}")
        lines.append("")

    # 建议删除
    to_delete = [s for s in result.scored_memories if s.action == "delete"]
    if to_delete:
        lines.append(f"### 🗑 建议删除（{len(to_delete)} 条）")
        for s in to_delete:
            age = format_age(s.header.mtime_ms)
            type_tag = f"[{s.header.memory_type}]" if s.header.memory_type else "[?]"
            not_to_save_tag = " ⚠️ 违反「不该存」规则" if s.is_not_to_save else ""
            lines.append(
                f"- **{s.header.filename}** {type_tag} · {age}{not_to_save_tag}"
            )
            lines.append(f"  综合分：{s.scores.composite:.1f} · {s.reason}")
        lines.append("")

    # 建议复查
    to_review = [s for s in result.scored_memories if s.action == "review"]
    if to_review:
        lines.append(f"### 🔄 建议复查（{len(to_review)} 条）")
        for s in to_review:
            age = format_age(s.header.mtime_ms)
            type_tag = f"[{s.header.memory_type}]" if s.header.memory_type else "[?]"
            conflict_tag = " 🔀 存在冲突" if s.conflicts_with else ""
            lines.append(
                f"- **{s.header.filename}** {type_tag} · {age}{conflict_tag}"
            )
            lines.append(f"  综合分：{s.scores.composite:.1f} · {s.reason}")
        lines.append("")

    # verbose 模式：也显示保留的
    if verbose:
        to_keep = [s for s in result.scored_memories if s.action == "keep"]
        if to_keep:
            lines.append(f"### ✅ 保留（{len(to_keep)} 条）")
            for s in to_keep:
                age = format_age(s.header.mtime_ms)
                type_tag = f"[{s.header.memory_type}]" if s.header.memory_type else "[?]"
                lines.append(
                    f"- **{s.header.filename}** {type_tag} · {age} · 综合分 {s.scores.composite:.1f}"
                )
            lines.append("")

    # 读取错误
    if read_errors:
        lines.append("### ⚠️ 读取错误")
        for e in read_errors:
            lines.append(f"- {e}")
        lines.append("")

    lines += [
        f"---",
        f"▶ 确认清理请调用 `memory_cleanup(dry_run=True)` 预览，再调用 `memory_cleanup(dry_run=False)` 执行",
        f"  （本次报告已缓存，cleanup 无需重新分析）",
    ]

    return [TextContent(type="text", text="\n".join(lines))]


# ── 4a：memory_score ──────────────────────────────────────────────────────────

async def _handle_memory_score(arguments: dict) -> list[TextContent]:
    """单条记忆质量打分。"""
    from src.quality_engine import score_single

    content = arguments.get("content", "").strip()
    memory_type = arguments.get("memory_type")

    if not content:
        return [TextContent(type="text", text="❌ 请提供要评分的记忆内容（content 字段不能为空）。")]

    try:
        result = score_single(content, memory_type=memory_type)
    except ValueError as e:
        return [TextContent(type="text", text=(
            f"❌ 无法运行评分：{e}\n\n"
            "请设置 API Key 环境变量（OPENAI_API_KEY / KIMI_API_KEY / MINIMAX_API_KEY 等）。"
        ))]

    s = result.scores
    action_icon = {"keep": "✅", "review": "🔄", "delete": "🗑"}.get(result.action, "❓")
    not_to_save_line = "\n⚠️ **违反「不该存」规则**：此类内容不应存储为记忆。" if result.is_not_to_save else ""

    text = f"""## 🔬 记忆质量评分

**建议操作**：{action_icon} {result.action.upper()}
**综合分**：{s.composite:.2f} / 5.00{not_to_save_line}

### 四维评分
| 维度 | 得分 | 说明 |
|------|------|------|
| 重要性（×40%） | {s.importance:.1f} / 5 | 对未来对话的帮助程度 |
| 时效性（×25%） | {s.recency:.1f} / 5 | 信息是否仍然准确 |
| 可信度（×15%） | {s.credibility:.1f} / 5 | 是否有明确来源 |
| 准确性（×20%） | {"无法评估" if s.accuracy == 0 else f"{s.accuracy:.1f} / 5"} | 记录是否忠实于来源 |

### 评分依据
{result.reason}

*评分来源：{"规则引擎" if result.scored_by == "rules" else "LLM 分析"}*"""

    return [TextContent(type="text", text=text)]


# ── 4d：memory_cleanup ────────────────────────────────────────────────────────

async def _handle_memory_cleanup(arguments: dict) -> list[TextContent]:
    """
    执行记忆清理。
    - dry_run=True（默认）：只预览，不删除
    - dry_run=False：备份到 .trash 后删除，同步更新 MEMORY.md
    支持 project_path 过滤，不传则跨所有项目清理。
    """
    from src.memory_reader import (
        read_memory_file,
        scan_all_projects,
    )
    from src.quality_engine import run_quality_engine
    from src.memory_writer import backup_and_delete, format_cleanup_result

    dry_run = arguments.get("dry_run", True)
    target_filenames: list[str] | None = arguments.get("filenames")
    project_path_str = arguments.get("project_path")
    project_path = Path(project_path_str) if project_path_str else None

    multi = scan_all_projects(project_path)

    if multi.total_count == 0:
        return [TextContent(type="text", text="📭 未找到记忆文件，无需清理。")]

    all_headers = multi.total_headers

    # 确定要清理的文件列表
    if target_filenames:
        # 用户指定了具体文件名，跨所有项目搜索
        files_to_delete = []
        not_found = []
        for fname in target_filenames:
            matched = [h for h in all_headers if h.filename == fname or h.file_path.name == fname]
            if matched:
                files_to_delete.append(matched[0].file_path)
            else:
                not_found.append(fname)

        if not_found:
            return [TextContent(type="text", text=(
                f"❌ 以下文件未找到：{', '.join(not_found)}\n\n"
                f"请先运行 `memory_report()` 获取正确的文件名。"
            ))]
    else:
        # 未指定文件：优先读最近一次 report 的缓存（P2 修复）
        from src.session_store import load_latest_report
        cached = load_latest_report()

        if cached and cached.to_delete:
            # 用缓存，不重新跑 LLM
            age_str = cached.age_display()
            files_to_delete = [
                Path(e.file_path)
                for e in cached.to_delete
                if Path(e.file_path).exists()
            ]
            cache_note = f"（使用 {age_str} 的分析缓存，共 {len(cached.to_delete)} 条建议删除）"
        else:
            # 没有缓存：重新运行评分引擎
            cache_note = "（重新运行评分分析）"
            memory_files = []
            for h in all_headers:
                owning_dir = h.file_path.parent
                while owning_dir.name != "memory" and owning_dir != owning_dir.parent:
                    owning_dir = owning_dir.parent
                try:
                    memory_files.append(read_memory_file(h.file_path, owning_dir))
                except OSError:
                    pass

            try:
                engine_result = run_quality_engine(
                    memory_files,
                    run_conflict_detection=False,
                )
            except ValueError as e:
                return [TextContent(type="text", text=(
                    f"❌ 无法运行评分引擎：{e}\n\n"
                    "请先运行 `memory_report()` 生成分析缓存，或设置 API Key 环境变量。"
                ))]

            files_to_delete = [
                s.header.file_path
                for s in engine_result.scored_memories
                if s.action == "delete"
            ]

    if not files_to_delete:
        return [TextContent(type="text", text="✅ 没有需要清理的记忆，记忆库状态良好。")]

    # 按文件所属项目分组执行，保证每个项目的 MEMORY.md 分别更新
    from collections import defaultdict
    by_project: dict[Path, list[Path]] = defaultdict(list)
    for f in files_to_delete:
        mem_dir = f.parent
        while mem_dir.name != "memory" and mem_dir != mem_dir.parent:
            mem_dir = mem_dir.parent
        by_project[mem_dir].append(f)

    all_results = []
    for mem_dir, files in by_project.items():
        r = backup_and_delete(files, mem_dir, dry_run=dry_run)
        all_results.append(r)

    # 合并输出，附上 cache_note
    cache_line = f"\n*{cache_note}*" if not target_filenames else ""
    if len(all_results) == 1:
        output = format_cleanup_result(all_results[0]) + cache_line
    else:
        parts = []
        total_deleted = sum(len(r.files_deleted) for r in all_results)
        total_targeted = sum(len(r.files_targeted) for r in all_results)
        if dry_run:
            parts.append(f"🔍 **预览模式**（未执行任何删除）\n共 {total_targeted} 条记忆将被清理{cache_line}\n")
        else:
            parts.append(f"✅ 已清理 {total_deleted} 条记忆（跨 {len(all_results)} 个项目）{cache_line}\n")
        for r in all_results:
            parts.append(format_cleanup_result(r))
        output = "\n---\n".join(parts)

    return [TextContent(type="text", text=output)]


# ── memory_dashboard ──────────────────────────────────────────────────────────

async def _handle_memory_dashboard(arguments: dict) -> list[TextContent]:
    """
    生成可视化健康报告，打开浏览器展示。
    优先读 session_store 缓存，没有缓存时自动触发一次 report。
    """
    from src.session_store import load_latest_report
    from src.dashboard import open_dashboard

    project_path_str = arguments.get("project_path")

    # 尝试读缓存
    cached = load_latest_report()

    if not cached:
        # 没有缓存：自动触发一次 report，把结果写入缓存
        report_result = await _handle_memory_report(arguments)
        # report 完成后缓存已写入，再次读取
        cached = load_latest_report()

        if not cached:
            return [TextContent(type="text", text=(
                "❌ 未能生成报告缓存。请先运行 `memory_report()` 再打开 Dashboard。"
            ))]

    # 生成 HTML 并打开浏览器
    try:
        html_path = open_dashboard(cached)
        age_str = cached.age_display()
        total = len(cached.entries)
        to_delete = len(cached.to_delete)
        to_review = len(cached.to_review)
        to_keep = total - to_delete - to_review

        return [TextContent(type="text", text=(
            f"✅ Dashboard 已在浏览器中打开\n\n"
            f"数据来源：{age_str}的分析（{total} 条记忆）\n"
            f"文件路径：{html_path}\n\n"
            f"概览：✓ 保留 {to_keep}  ！复查 {to_review}  × 删除 {to_delete}"
        ))]
    except Exception as e:
        return [TextContent(type="text", text=(
            f"❌ 打开 Dashboard 失败：{e}\n\n"
            f"请检查系统是否有默认浏览器，或手动打开：\n"
            f"~/.memory-quality-mcp/dashboard.html"
        ))]


# ── 启动入口 ──────────────────────────────────────────────────────────────────

async def serve():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


def main():
    asyncio.run(serve())


if __name__ == "__main__":
    main()
