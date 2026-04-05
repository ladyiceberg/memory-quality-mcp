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
from src.i18n import t

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
            description=t("tool.audit.desc"),
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
            description=t("tool.report.desc"),
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
            description=t("tool.cleanup.desc"),
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
            description=t("tool.score.desc"),
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
            description=t("tool.dashboard.desc"),
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
                    "demo": {
                        "type": "boolean",
                        "description": (
                            "可选。true = 使用内置示例数据打开演示页面，"
                            "适合还没有真实记忆文件的用户体验产品功能。"
                        ),
                        "default": False,
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
        return [TextContent(type="text", text=t("common.unknown_tool", name=name))]


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
        scope = (
            t("audit.no_memories_scope_suffix", path=project_path_str)
            if project_path_str
            else t("audit.no_memories_scope_all")
        )
        return [TextContent(type="text", text=t("audit.no_memories", scope=scope))]

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
    scope = t("audit.scope_project", path=project_path_str) if project_path_str else t("audit.scope_all", n=multi.project_count)
    lines = [
        t("audit.header"),
        "",
        t("audit.scope", scope=scope),
        t("audit.total", total=total),
        "",
        t("audit.quick_check"),
        t("audit.table_header"),
        t("audit.stale_count", n=stale_count),
        t("audit.project_stale_count", n=project_stale_count),
        "",
    ]

    # 多项目时按项目分列索引健康
    if multi.project_count > 1:
        lines.append(t("audit.projects_header"))
        for scan in multi.projects:
            ih = scan.index_health
            status = "⚠️" if (ih.is_line_truncated or ih.is_byte_truncated) else "✅"
            index_info = t("audit.index_line_count", n=ih.line_count) if ih.exists else t("audit.index_missing")
            lines.append(t("audit.project_row", status=status, name=scan.project_name, count=len(scan.headers), index_info=index_info))
        lines.append("")
    else:
        # 单项目展示索引健康详情
        scan = multi.projects[0]
        ih = scan.index_health
        if ih.exists:
            lines += [t("audit.memory_index_header")]
            lines += [t("audit.index_stats", lines=ih.line_count, bytes=f"{ih.byte_count:,}", pct=f"{ih.line_count / 200:.0%}")]
            if ih.warning:
                lines.append(f"- ⚠️ {ih.warning}")
            lines.append("")

    # 最老的记忆
    if oldest_header:
        lines += [
            t("audit.oldest_header"),
            t("audit.oldest_row", filename=oldest_header.filename, age=format_age(oldest_header.mtime_ms), desc=oldest_header.description or oldest_header.name or ''),
            "",
        ]

    # 预估 LLM 调用次数（帮用户决定是否运行 report）
    batch_size = CONFIG.get("batch_size", 6)
    estimated_calls = (total + batch_size - 1) // batch_size + 1  # +1 冲突检测
    lines += [t("audit.footer", n=estimated_calls)]

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
        return [TextContent(type="text", text=t("report.no_memories"))]

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
        return [TextContent(type="text", text=t("report.llm_error", error=e))]

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
    scope = t("audit.scope_project", path=project_path_str) if project_path_str else t("audit.scope_all", n=multi.project_count)
    lines = [
        t("report.header"),
        "",
        t("report.summary", scope=scope, total=result.total, delete=result.to_delete, review=result.to_review, keep=result.to_keep),
        "",
    ]

    # 冲突
    if result.conflicts:
        lines.append(t("report.conflicts_header", n=len(result.conflicts)))
        for c in result.conflicts:
            severity_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(c.severity, "⚪")
            lines.append(f"- {severity_icon} `{c.filename_a}` × `{c.filename_b}`")
            lines.append(f"  {c.description}")
        lines.append("")

    # 建议删除
    to_delete = [s for s in result.scored_memories if s.action == "delete"]
    if to_delete:
        lines.append(t("report.delete_header", n=len(to_delete)))
        for s in to_delete:
            age = format_age(s.header.mtime_ms)
            type_tag = f"[{s.header.memory_type}]" if s.header.memory_type else "[?]"
            not_to_save_tag = t("report.not_to_save_tag") if s.is_not_to_save else ""
            lines.append(
                f"- **{s.header.filename}** {type_tag} · {age}{not_to_save_tag}"
            )
            lines.append(t("report.score_line", score=s.scores.composite, reason=s.reason))
        lines.append("")

    # 建议复查
    to_review = [s for s in result.scored_memories if s.action == "review"]
    if to_review:
        lines.append(t("report.review_header", n=len(to_review)))
        for s in to_review:
            age = format_age(s.header.mtime_ms)
            type_tag = f"[{s.header.memory_type}]" if s.header.memory_type else "[?]"
            conflict_tag = t("report.conflict_tag") if s.conflicts_with else ""
            lines.append(
                f"- **{s.header.filename}** {type_tag} · {age}{conflict_tag}"
            )
            lines.append(t("report.score_line", score=s.scores.composite, reason=s.reason))
        lines.append("")

    # verbose 模式：也显示保留的
    if verbose:
        to_keep = [s for s in result.scored_memories if s.action == "keep"]
        if to_keep:
            lines.append(t("report.keep_header", n=len(to_keep)))
            for s in to_keep:
                age = format_age(s.header.mtime_ms)
                type_tag_val = s.header.memory_type or "?"
                lines.append(t("report.keep_line", filename=s.header.filename, type=type_tag_val, age=age, score=s.scores.composite))
            lines.append("")

    # 读取错误
    if read_errors:
        lines.append(t("report.read_errors_header"))
        for e in read_errors:
            lines.append(f"- {e}")
        lines.append("")

    lines += [t("report.footer")]

    return [TextContent(type="text", text="\n".join(lines))]


# ── 4a：memory_score ──────────────────────────────────────────────────────────

async def _handle_memory_score(arguments: dict) -> list[TextContent]:
    """单条记忆质量打分。"""
    from src.quality_engine import score_single

    content = arguments.get("content", "").strip()
    memory_type = arguments.get("memory_type")

    if not content:
        return [TextContent(type="text", text=t("score.empty_content"))]

    try:
        result = score_single(content, memory_type=memory_type)
    except ValueError as e:
        return [TextContent(type="text", text=t("score.llm_error", error=e))]

    s = result.scores
    action_icon = {"keep": "✅", "review": "🔄", "delete": "🗑"}.get(result.action, "❓")
    not_to_save_line = t("score.not_to_save") if result.is_not_to_save else ""
    accuracy_val = t("score.accuracy_na") if s.accuracy == 0 else f"{s.accuracy:.1f} / 5"
    scored_by = t("score.scored_by_rules") if result.scored_by == "rules" else t("score.scored_by_llm")

    text = "\n".join([
        t("score.header"),
        "",
        t("score.action", icon=action_icon, action=result.action.upper()),
        t("score.composite", score=s.composite) + not_to_save_line,
        "",
        t("score.dimensions_header"),
        t("score.dim_importance", v=f"{s.importance:.1f}"),
        t("score.dim_recency", v=f"{s.recency:.1f}"),
        t("score.dim_credibility", v=f"{s.credibility:.1f}"),
        t("score.dim_accuracy", v=accuracy_val),
        "",
        t("score.reason_header"),
        result.reason,
        "",
        scored_by,
    ])

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
        return [TextContent(type="text", text=t("cleanup.no_memories"))]

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
            return [TextContent(type="text", text=t("cleanup.not_found", files=', '.join(not_found)))]
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
                return [TextContent(type="text", text=t("cleanup.llm_error", error=e))]

            files_to_delete = [
                s.header.file_path
                for s in engine_result.scored_memories
                if s.action == "delete"
            ]

    if not files_to_delete:
        return [TextContent(type="text", text=t("cleanup.nothing_to_clean"))]

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
            parts.append(t("cleanup.preview_header", n=total_targeted, cache_note=cache_line))
        else:
            parts.append(t("cleanup.done_header", n=total_deleted, projects=len(all_results), cache_note=cache_line))
        for r in all_results:
            parts.append(format_cleanup_result(r))
        output = "\n---\n".join(parts)

    return [TextContent(type="text", text=output)]


# ── memory_dashboard ──────────────────────────────────────────────────────────

async def _handle_memory_dashboard(arguments: dict) -> list[TextContent]:
    """
    生成可视化健康报告，打开浏览器展示。
    优先读 session_store 缓存，没有缓存时自动触发一次 report。
    demo=True 时使用内置示例数据，无需真实记忆文件。
    """
    from src.session_store import load_latest_report, save_report, ReportEntry
    from src.dashboard import open_dashboard

    demo = arguments.get("demo", False)
    project_path_str = arguments.get("project_path")

    # ── Demo 模式：加载预生成的示例数据 ───────────────────────────────────────
    if demo:
        import time
        from src.memory_reader import scan_memory_files, read_memory_file
        from src.quality_engine import run_quality_engine
        from src.session_store import StoredReport

        demo_dir = Path(__file__).parent.parent / "examples" / "demo_memories"
        if not demo_dir.exists():
            return [TextContent(type="text", text=t("dashboard.demo_missing"))]

        scan = scan_memory_files(demo_dir)
        memory_files = []
        for h in scan.headers:
            try:
                memory_files.append(read_memory_file(h.file_path, demo_dir))
            except OSError:
                pass

        try:
            engine_result = run_quality_engine(memory_files, run_conflict_detection=True)
        except ValueError as e:
            return [TextContent(type="text", text=t("dashboard.demo_llm_error", error=e))]

        # 构造临时 report 对象（不写入 session_store，避免污染用户的真实缓存）
        entries = []
        for sm in engine_result.scored_memories:
            entries.append(ReportEntry(
                filename=sm.header.filename,
                file_path=str(sm.header.file_path),
                action=sm.action,
                composite=sm.scores.composite,
                reason=sm.reason,
                is_not_to_save=sm.is_not_to_save,
                memory_type=sm.header.memory_type,
                project_dir=str(demo_dir),
            ))

        demo_report = StoredReport(
            report_id=-1,
            created_at=time.time(),
            entries=entries,
        )

        try:
            html_path = open_dashboard(demo_report, is_demo=True)
            total = len(entries)
            to_delete = len([e for e in entries if e.action == "delete"])
            to_review = len([e for e in entries if e.action == "review"])
            to_keep = total - to_delete - to_review
            return [TextContent(type="text", text=t("dashboard.demo_opened", total=total, keep=to_keep, review=to_review, delete=to_delete))]
        except Exception as e:
            return [TextContent(type="text", text=t("dashboard.demo_open_error", error=e))]

    # ── 正常模式 ──────────────────────────────────────────────────────────────
    cached = load_latest_report()

    if not cached:
        # 没有缓存：自动触发一次 report
        report_result = await _handle_memory_report(arguments)
        cached = load_latest_report()

        if not cached:
            return [TextContent(type="text", text=t("dashboard.no_cache"))]

    # 生成 HTML 并打开浏览器
    try:
        html_path = open_dashboard(cached)
        age_str = cached.age_display()
        total = len(cached.entries)
        to_delete = len(cached.to_delete)
        to_review = len(cached.to_review)
        to_keep = total - to_delete - to_review

        return [TextContent(type="text", text=t("dashboard.opened", age=age_str, total=total, path=html_path, keep=to_keep, review=to_review, delete=to_delete))]
    except Exception as e:
        return [TextContent(type="text", text=t("dashboard.open_error", error=e))]


# ── 启动入口 ──────────────────────────────────────────────────────────────────

async def serve():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


def main():
    asyncio.run(serve())


if __name__ == "__main__":
    main()
