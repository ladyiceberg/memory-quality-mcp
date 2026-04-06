#!/usr/bin/env python3
"""
memory_quality.py · Memory Quality CLI — Claude Code Skills 版本

把 memory-quality-mcp 的核心功能封装成命令行脚本，
供 Claude Code Skills Plugin 直接调用，无需安装 MCP Server。

用法（由 SKILL.md 指挥 Claude 执行）：
  python memory_quality.py audit                    # 快速体检
  python memory_quality.py report                   # 详细评分（需要 LLM API Key）
  python memory_quality.py cleanup                  # 预览清理列表
  python memory_quality.py cleanup --execute        # 确认执行清理
  python memory_quality.py score "记忆文本内容"     # 单条评分
  python memory_quality.py dashboard                # 打开可视化看板

依赖安装（由 hooks/hooks.json SessionStart hook 自动完成）：
  pip install openai pyyaml

配置（通过 plugin.json 的 userConfig 传入，自动导出为环境变量）：
  CLAUDE_PLUGIN_OPTION_api_key      → LLM API Key
  CLAUDE_PLUGIN_OPTION_provider     → openai / anthropic / minimax / kimi
  CLAUDE_PLUGIN_OPTION_language     → en / zh（不填则自动检测系统 locale）

设计原则：
  - 直接 import src/ 里已有且经过测试的所有逻辑，不重写
  - 本脚本只做：解析参数 → 调用函数 → 打印结果
  - 依赖安装路径通过 CLAUDE_PLUGIN_DATA 或 fallback 处理
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path


# ── 依赖路径处理 ───────────────────────────────────────────────────────────────
# hooks.json 把依赖安装到 ${CLAUDE_PLUGIN_DATA}/lib，需要加到 sys.path

def _setup_deps_path() -> None:
    """
    把 Plugin 的依赖目录加入 sys.path。
    hooks.json 在 SessionStart 时把 openai/pyyaml 安装到
    ${CLAUDE_PLUGIN_DATA}/lib，这里确保 Python 能找到它们。
    """
    plugin_data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if plugin_data:
        lib_dir = Path(plugin_data) / "lib"
        if lib_dir.exists() and str(lib_dir) not in sys.path:
            sys.path.insert(0, str(lib_dir))

_setup_deps_path()


# ── src/ 路径处理 ──────────────────────────────────────────────────────────────
# 脚本在 skills/skills/memory-quality/scripts/ 里，
# src/ 在项目根目录，需要把根目录加入 sys.path

def _setup_src_path() -> None:
    """
    把 memory-quality-mcp 的 src/ 根目录加入 sys.path。
    脚本路径：skills/skills/memory-quality/scripts/memory_quality.py
    根目录路径：向上 4 级
    """
    script_dir = Path(__file__).resolve().parent          # scripts/
    skill_dir  = script_dir.parent                        # memory-quality/
    skills_dir = skill_dir.parent                         # skills/（子目录）
    plugin_dir = skills_dir.parent                        # skills/（根）
    project_root = plugin_dir.parent                      # memory-quality-mcp/

    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

_setup_src_path()


# ── 导入 src/ 模块 ─────────────────────────────────────────────────────────────

try:
    from src.memory_reader import (
        scan_all_projects,
        read_memory_file,
        format_age,
        memory_age_days,
    )
    from src.memory_writer import backup_and_delete, format_cleanup_result
    from src.quality_engine import run_quality_engine, score_single, STALENESS
    from src.session_store import (
        save_report, load_latest_report,
        ReportEntry, StoredReport,
    )
    from src.dashboard import open_dashboard
    from src.config import load_config, detect_language
    from src.llm_client import create_client
    from src.i18n import t
except ImportError as e:
    print(f"ERROR: Cannot import memory-quality-mcp modules: {e}")
    print("Make sure this script is inside the memory-quality-mcp/skills/ directory.")
    sys.exit(1)


# ── 配置：从 Plugin userConfig 环境变量读取 ────────────────────────────────────

def _build_config_from_env() -> dict:
    """
    从 Plugin userConfig 注入的环境变量构建配置 dict。
    变量名规则：CLAUDE_PLUGIN_OPTION_<field_name>（全大写）。
    """
    config = load_config()

    # Plugin userConfig → 覆盖 config.yaml 里的值
    api_key  = os.environ.get("CLAUDE_PLUGIN_OPTION_api_key", "")
    provider = os.environ.get("CLAUDE_PLUGIN_OPTION_provider", "")
    language = os.environ.get("CLAUDE_PLUGIN_OPTION_language", "")

    if api_key:
        config["api_key"] = api_key
    if provider:
        config["provider"] = provider
    if language:
        config["language"] = language

    return config


# ── 公共工具 ───────────────────────────────────────────────────────────────────

def _get_lang() -> str:
    return detect_language()


def _print_header(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def _print_section(title: str) -> None:
    print(f"\n── {title} {'─'*(54 - len(title))}")


# ── CMD: audit ────────────────────────────────────────────────────────────────

def cmd_audit(project_path: str | None) -> int:
    """
    快速体检：扫描所有记忆文件，返回健康摘要。不调用 LLM。
    """
    lang = _get_lang()
    path = Path(project_path) if project_path else None
    multi = scan_all_projects(path)

    if multi.project_count == 0 or multi.total_count == 0:
        scope_hint = f" in project '{project_path}'" if project_path else ""
        print(t("audit.no_memories", lang=lang,
                scope=scope_hint or t("audit.no_memories_scope_all", lang=lang)))
        return 0

    total = multi.total_count
    all_headers = multi.total_headers
    config = load_config()
    batch_size = config.get("batch_size", 6)

    # 规则统计（不调 LLM）
    stale_count = 0
    project_stale_count = 0
    oldest = None

    for h in all_headers:
        age = memory_age_days(h.mtime_ms)
        threshold = STALENESS.get(f"{h.memory_type}_type", STALENESS.get("general", 90))
        if age > threshold:
            stale_count += 1
        if h.memory_type == "project" and age > STALENESS.get("project_type", 90):
            project_stale_count += 1
        if oldest is None or h.mtime_ms < oldest.mtime_ms:
            oldest = h

    scope = (
        t("audit.scope_project", lang=lang, path=project_path)
        if project_path
        else t("audit.scope_all", lang=lang, n=multi.project_count)
    )

    _print_header(t("audit.header", lang=lang).lstrip("# ").strip())
    print(t("audit.scope", lang=lang, scope=scope))
    print(t("audit.total", lang=lang, total=total))

    _print_section(t("audit.quick_check", lang=lang).lstrip("# ").strip())
    print(t("audit.table_header", lang=lang))
    print(t("audit.stale_count", lang=lang, n=stale_count))
    print(t("audit.project_stale_count", lang=lang, n=project_stale_count))

    # 多项目时按项目列出
    if multi.project_count > 1:
        _print_section(t("audit.projects_header", lang=lang).lstrip("# ").strip())
        for scan in multi.projects:
            ih = scan.index_health
            status = "⚠️" if (ih.is_line_truncated or ih.is_byte_truncated) else "✅"
            index_info = (
                t("audit.index_line_count", lang=lang, n=ih.line_count)
                if ih.exists
                else t("audit.index_missing", lang=lang)
            )
            print(t("audit.project_row", lang=lang,
                    status=status, name=scan.project_name,
                    count=len(scan.headers), index_info=index_info))
    else:
        scan = multi.projects[0]
        ih = scan.index_health
        if ih.exists:
            _print_section(t("audit.memory_index_header", lang=lang).lstrip("# ").strip())
            print(t("audit.index_stats", lang=lang,
                    lines=ih.line_count,
                    bytes=f"{ih.byte_count:,}",
                    pct=f"{ih.line_count / 200:.0%}"))
            if ih.warning:
                print(f"⚠️  {ih.warning}")

    if oldest:
        _print_section(t("audit.oldest_header", lang=lang).lstrip("# ").strip())
        desc = oldest.description or oldest.name or ""
        print(t("audit.oldest_row", lang=lang,
                filename=oldest.filename,
                age=format_age(oldest.mtime_ms),
                desc=desc))

    estimated_calls = (total + batch_size - 1) // batch_size + 1
    print()
    print(t("audit.footer", lang=lang, n=estimated_calls))
    return 0


# ── CMD: report ───────────────────────────────────────────────────────────────

def cmd_report(project_path: str | None, verbose: bool) -> int:
    """
    详细质量报告：LLM 四维评分 + 冲突检测。结果缓存到 SQLite。
    """
    lang = _get_lang()
    path = Path(project_path) if project_path else None
    multi = scan_all_projects(path)

    if multi.total_count == 0:
        print(t("report.no_memories", lang=lang))
        return 0

    # 读取全文（评分需要完整内容）
    memory_files = []
    read_errors = []
    for h in multi.total_headers:
        owning_dir = h.file_path.parent
        while owning_dir.name != "memory" and owning_dir != owning_dir.parent:
            owning_dir = owning_dir.parent
        try:
            mf = read_memory_file(h.file_path, owning_dir)
            memory_files.append(mf)
        except OSError as e:
            read_errors.append(f"Cannot read {h.filename}: {e}")

    # 运行评分引擎
    config = _build_config_from_env()
    try:
        client = create_client(config)
        result = run_quality_engine(memory_files, run_conflict_detection=True,
                                    client=client)
    except ValueError as e:
        print(t("report.llm_error", lang=lang, error=e))
        return 1

    # 缓存到 session store
    store_entries = []
    for sm in result.scored_memories:
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
    save_report(store_entries)

    # 输出
    scope = (
        t("audit.scope_project", lang=lang, path=project_path)
        if project_path
        else t("audit.scope_all", lang=lang, n=multi.project_count)
    )
    _print_header(t("report.header", lang=lang).lstrip("# ").strip())
    print(t("report.summary", lang=lang,
            scope=scope, total=result.total,
            delete=result.to_delete, review=result.to_review, keep=result.to_keep))

    # 冲突
    if result.conflicts:
        _print_section(f"Conflicts ({len(result.conflicts)})")
        for c in result.conflicts:
            severity_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(c.severity, "⚪")
            print(f"{severity_icon} {c.filename_a}  ×  {c.filename_b}")
            print(f"   {c.description}")

    # 建议删除
    to_delete = [s for s in result.scored_memories if s.action == "delete"]
    if to_delete:
        _print_section(t("report.delete_header", lang=lang,
                         n=len(to_delete)).lstrip("# ").strip())
        for s in to_delete:
            age = format_age(s.header.mtime_ms)
            type_tag = f"[{s.header.memory_type}]" if s.header.memory_type else "[?]"
            not_to_save = t("report.not_to_save_tag", lang=lang) if s.is_not_to_save else ""
            print(f"  {s.header.filename} {type_tag} · {age}{not_to_save}")
            print(t("report.score_line", lang=lang,
                    score=s.scores.composite, reason=s.reason))

    # 建议复查
    to_review = [s for s in result.scored_memories if s.action == "review"]
    if to_review:
        _print_section(t("report.review_header", lang=lang,
                         n=len(to_review)).lstrip("# ").strip())
        for s in to_review:
            age = format_age(s.header.mtime_ms)
            type_tag = f"[{s.header.memory_type}]" if s.header.memory_type else "[?]"
            conflict = t("report.conflict_tag", lang=lang) if s.conflicts_with else ""
            print(f"  {s.header.filename} {type_tag} · {age}{conflict}")
            print(t("report.score_line", lang=lang,
                    score=s.scores.composite, reason=s.reason))

    # verbose 模式：显示保留
    if verbose:
        to_keep = [s for s in result.scored_memories if s.action == "keep"]
        if to_keep:
            _print_section(t("report.keep_header", lang=lang,
                             n=len(to_keep)).lstrip("# ").strip())
            for s in to_keep:
                age = format_age(s.header.mtime_ms)
                type_tag = f"[{s.header.memory_type}]" if s.header.memory_type else "[?]"
                print(t("report.keep_line", lang=lang,
                        filename=s.header.filename,
                        type=type_tag, age=age,
                        score=s.scores.composite))

    if read_errors:
        _print_section("Read Errors")
        for e in read_errors:
            print(f"  {e}")

    print()
    print(t("report.footer", lang=lang))
    return 0


# ── CMD: cleanup ──────────────────────────────────────────────────────────────

def cmd_cleanup(project_path: str | None, execute: bool) -> int:
    """
    清理建议删除的记忆文件。
    默认预览（dry_run）；传入 --execute 才真正删除。
    """
    lang = _get_lang()
    path = Path(project_path) if project_path else None
    multi = scan_all_projects(path)

    if multi.total_count == 0:
        print(t("cleanup.no_memories", lang=lang))
        return 0

    all_headers = multi.total_headers

    # 读取 session store 缓存
    cached = load_latest_report()
    if cached and cached.to_delete:
        age_str = cached.age_display()
        files_to_delete = [
            Path(e.file_path)
            for e in cached.to_delete
            if Path(e.file_path).exists()
        ]
        cache_note = f" (using cached report from {age_str})"
    else:
        # 没有缓存：提示先运行 report
        print("No cached report found. Please run 'report' first to analyze memories.")
        print("  python memory_quality.py report")
        return 1

    if not files_to_delete:
        print(t("cleanup.nothing_to_clean", lang=lang))
        return 0

    # 按项目分组执行
    from collections import defaultdict
    by_project: dict[Path, list[Path]] = defaultdict(list)
    for f in files_to_delete:
        mem_dir = f.parent
        while mem_dir.name != "memory" and mem_dir != mem_dir.parent:
            mem_dir = mem_dir.parent
        by_project[mem_dir].append(f)

    dry_run = not execute
    all_results = []
    for mem_dir, files in by_project.items():
        r = backup_and_delete(files, mem_dir, dry_run=dry_run)
        all_results.append(r)

    # 输出
    if len(all_results) == 1:
        print(format_cleanup_result(all_results[0]))
        if dry_run:
            print()
            print("To execute the cleanup, run:")
            print("  python memory_quality.py cleanup --execute")
    else:
        total_targeted = sum(len(r.files_targeted) for r in all_results)
        total_deleted  = sum(len(r.files_deleted)  for r in all_results)
        if dry_run:
            print(t("cleanup.preview_header", lang=lang,
                    n=total_targeted, cache_note=cache_note))
        else:
            print(t("cleanup.done_header", lang=lang,
                    n=total_deleted, projects=len(all_results), cache_note=cache_note))
        for r in all_results:
            print()
            print(format_cleanup_result(r))
        if dry_run:
            print()
            print("To execute the cleanup, run:")
            print("  python memory_quality.py cleanup --execute")

    return 0


# ── CMD: score ────────────────────────────────────────────────────────────────

def cmd_score(content: str, memory_type: str | None) -> int:
    """
    对单条记忆内容进行四维质量评分。
    """
    lang = _get_lang()

    if not content.strip():
        print(t("score.empty_content", lang=lang))
        return 1

    config = _build_config_from_env()
    try:
        # score_single 内部先走规则引擎（零 API 成本），
        # 只有规则引擎无法判断时才用 client 调 LLM。
        # 先尝试不传 client（规则引擎可以处理的情况），
        # 如果需要 LLM 再创建 client。
        try:
            client = create_client(config)
        except ValueError:
            client = None  # 没有 API Key，只能走规则引擎

        result = score_single(content, memory_type=memory_type, client=client)
    except ValueError as e:
        print(t("score.llm_error", lang=lang, error=e))
        return 1

    s = result.scores
    action_icon = {"keep": "✅", "review": "🔄", "delete": "🗑"}.get(result.action, "❓")
    not_to_save = t("score.not_to_save", lang=lang) if result.is_not_to_save else ""

    _print_header(t("score.header", lang=lang).lstrip("# ").strip())
    print(t("score.action", lang=lang, icon=action_icon, action=result.action.upper()))
    print(t("score.composite", lang=lang, score=s.composite) + not_to_save)
    print()
    print(t("score.dimensions_header", lang=lang))
    acc_val = t("score.accuracy_na", lang=lang) if s.accuracy == 0 else f"{s.accuracy:.1f} / 5"
    print(t("score.dim_importance", lang=lang,  v=f"{s.importance:.1f}"))
    print(t("score.dim_recency",    lang=lang,  v=f"{s.recency:.1f}"))
    print(t("score.dim_credibility",lang=lang,  v=f"{s.credibility:.1f}"))
    print(t("score.dim_accuracy",   lang=lang,  v=acc_val))
    print()
    print(t("score.reason_header", lang=lang))
    print(result.reason)
    print()
    scored_by = (
        t("score.scored_by_rules", lang=lang)
        if result.scored_by == "rules"
        else t("score.scored_by_llm", lang=lang)
    )
    print(scored_by)
    return 0


# ── CMD: dashboard ────────────────────────────────────────────────────────────

def cmd_dashboard() -> int:
    """
    生成可视化 HTML 报告并用系统浏览器打开。
    优先复用 session store 里最近一次 report 的缓存。
    """
    lang = _get_lang()
    cached = load_latest_report()

    if not cached:
        print(t("dashboard.no_cache", lang=lang))
        return 1

    try:
        html_path = open_dashboard(cached, lang=lang)
        total    = len(cached.entries)
        to_delete = len(cached.to_delete)
        to_review = len(cached.to_review)
        to_keep   = total - to_delete - to_review
        age_str   = cached.age_display()

        print(t("dashboard.opened", lang=lang,
                age=age_str, total=total, path=html_path,
                keep=to_keep, review=to_review, delete=to_delete))
    except Exception as e:
        print(t("dashboard.open_error", lang=lang, error=e))
        return 1

    return 0


# ── CLI 入口 ───────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="memory_quality",
        description="Audit and clean up Claude Code's auto-saved memories.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # audit
    p_audit = sub.add_parser("audit", help="Quick health check — no LLM cost")
    p_audit.add_argument("--project", help="Scan a specific project path only")

    # report
    p_report = sub.add_parser("report", help="Full quality analysis with LLM scoring")
    p_report.add_argument("--project", help="Analyze a specific project path only")
    p_report.add_argument("--verbose", action="store_true",
                          help="Also show memories marked for keeping")

    # cleanup
    p_cleanup = sub.add_parser("cleanup",
                                help="Preview or execute cleanup of low-quality memories")
    p_cleanup.add_argument("--project", help="Clean a specific project path only")
    p_cleanup.add_argument("--execute", action="store_true",
                           help="Actually delete files (default is preview only)")

    # score
    p_score = sub.add_parser("score", help="Score a single memory string")
    p_score.add_argument("content", help="Memory text to score")
    p_score.add_argument("--type", dest="memory_type",
                         choices=["user", "feedback", "project", "reference"],
                         help="Memory type (improves scoring accuracy)")

    # dashboard
    sub.add_parser("dashboard",
                   help="Open the visual health dashboard in your browser")

    args = parser.parse_args()

    if args.command == "audit":
        return cmd_audit(args.project)
    elif args.command == "report":
        return cmd_report(args.project, args.verbose)
    elif args.command == "cleanup":
        return cmd_cleanup(args.project, args.execute)
    elif args.command == "score":
        return cmd_score(args.content, args.memory_type)
    elif args.command == "dashboard":
        return cmd_dashboard()
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
