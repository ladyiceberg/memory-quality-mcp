"""
i18n.py · 多语言文本

所有面向用户的输出文字集中在此，server.py 通过 t() 获取。
新增语言只需在 STRINGS 中加一个新的语言 dict。

用法：
    from src.i18n import t
    t("audit.no_memories")           # 取当前语言文本
    t("audit.no_memories", lang="zh") # 强制指定语言
"""

from src.config import detect_language

# ── 文本库 ────────────────────────────────────────────────────────────────────

STRINGS: dict[str, dict[str, str]] = {

    # ── memory_audit ──────────────────────────────────────────────────────────
    "audit.no_memories": {
        "en": (
            "📭 No Claude Code memory files found{scope}.\n\n"
            "Possible reasons:\n"
            "- Claude Code version below v2.1.59 (Auto Memory not yet available)\n"
            "- Auto Memory disabled (check `CLAUDE_CODE_DISABLE_AUTO_MEMORY`)\n"
            "- Not enough conversations yet for Claude to decide what to remember\n"
            "- Memory directory is in a non-default location (check `~/.claude/settings.json`)"
        ),
        "zh": (
            "📭 未找到 Claude Code 记忆文件{scope}。\n\n"
            "可能原因：\n"
            "- Claude Code 版本低于 v2.1.59，Auto Memory 功能尚未开放\n"
            "- Auto Memory 被禁用（检查 `CLAUDE_CODE_DISABLE_AUTO_MEMORY` 环境变量）\n"
            "- 还没有积累足够多的对话让 Claude 决定写入记忆\n"
            "- 记忆目录在非默认位置（检查 `~/.claude/settings.json`）"
        ),
    },
    "audit.header": {
        "en": "## 🔍 Memory Store Health Check",
        "zh": "## 🔍 记忆库健康报告",
    },
    "audit.scope": {
        "en": "**Scope**: {scope}",
        "zh": "**扫描范围**：{scope}",
    },
    "audit.total": {
        "en": "**Total memories**: {total}",
        "zh": "**总记忆数**：{total} 条",
    },
    "audit.quick_check": {
        "en": "### Quick Diagnostics",
        "zh": "### 快速诊断",
    },
    "audit.table_header": {
        "en": "| Metric | Count |\n|--------|-------|",
        "zh": "| 指标 | 数量 |\n|------|------|",
    },
    "audit.stale_count": {
        "en": "| Possibly stale (past threshold) | {n} |",
        "zh": "| 可能过时（超过阈值天数）| {n} 条 |",
    },
    "audit.project_stale_count": {
        "en": "| Project memories past threshold | {n} |",
        "zh": "| 建议优先审查（project 类型过时）| {n} 条 |",
    },
    "audit.projects_header": {
        "en": "### Project Status",
        "zh": "### 各项目状态",
    },
    "audit.project_row": {
        "en": "- {status} **{name}**: {count} memories{index_info}",
        "zh": "- {status} **{name}**：{count} 条记忆{index_info}",
    },
    "audit.index_line_count": {
        "en": ", index {n} lines",
        "zh": "，索引 {n} 行",
    },
    "audit.index_missing": {
        "en": ", no index file",
        "zh": "，索引不存在",
    },
    "audit.memory_index_header": {
        "en": "### MEMORY.md Index",
        "zh": "### MEMORY.md 索引状态",
    },
    "audit.index_stats": {
        "en": "- Current: {lines} lines / {bytes} bytes\n- Limit: 200 lines / 25,000 bytes\n- Usage: {pct} (lines)",
        "zh": "- 当前：{lines} 行 / {bytes} 字节\n- 上限：200 行 / 25,000 字节\n- 使用率：{pct}（行）",
    },
    "audit.oldest_header": {
        "en": "### Oldest Memory",
        "zh": "### 最老的记忆",
    },
    "audit.oldest_row": {
        "en": "- `{filename}` — {age}\n  {desc}",
        "zh": "- `{filename}` — {age}\n  {desc}",
    },
    "audit.footer": {
        "en": "---\n▶ Run `memory_report()` for detailed quality scores and cleanup suggestions\n  (estimated ~{n} LLM calls)",
        "zh": "---\n▶ 运行 `memory_report()` 获取详细的质量评分和清理建议\n  （预计调用 LLM 约 {n} 次）",
    },
    "audit.scope_project": {
        "en": "project `{path}`",
        "zh": "项目 `{path}`",
    },
    "audit.scope_all": {
        "en": "all {n} projects",
        "zh": "全部 {n} 个项目",
    },
    "audit.no_memories_scope_suffix": {
        "en": " in project `{path}`",
        "zh": "（指定项目 `{path}` 下）",
    },
    "audit.no_memories_scope_all": {
        "en": "",
        "zh": "（所有项目下）",
    },

    # ── memory_report ─────────────────────────────────────────────────────────
    "report.no_memories": {
        "en": "📭 No memory files found, nothing to analyze.",
        "zh": "📭 未找到记忆文件，无需分析。",
    },
    "report.llm_error": {
        "en": (
            "❌ Cannot run LLM scoring: {error}\n\n"
            "Please set an API Key environment variable (OPENAI_API_KEY / KIMI_API_KEY / MINIMAX_API_KEY, etc.),\n"
            "or configure provider and api_key in `~/.memory-quality-mcp/config.yaml`."
        ),
        "zh": (
            "❌ 无法运行 LLM 评分：{error}\n\n"
            "请设置对应的 API Key 环境变量（OPENAI_API_KEY / KIMI_API_KEY / MINIMAX_API_KEY 等），\n"
            "或在 `~/.memory-quality-mcp/config.yaml` 中配置 provider 和 api_key。"
        ),
    },
    "report.header": {
        "en": "## 📊 Memory Quality Report",
        "zh": "## 📊 记忆质量详细报告",
    },
    "report.summary": {
        "en": "**Scope**: {scope}　**Total**: {total}  |  🗑 Delete {delete}  |  🔄 Review {review}  |  ✅ Keep {keep}",
        "zh": "**扫描范围**：{scope}　**总计**：{total} 条  |  🗑 删除 {delete} 条  |  🔄 复查 {review} 条  |  ✅ 保留 {keep} 条",
    },
    "report.conflicts_header": {
        "en": "### ⚡ {n} conflicting memory pair(s) found",
        "zh": "### ⚡ 发现 {n} 对冲突记忆",
    },
    "report.delete_header": {
        "en": "### 🗑 Suggested Deletions ({n})",
        "zh": "### 🗑 建议删除（{n} 条）",
    },
    "report.review_header": {
        "en": "### 🔄 Needs Review ({n})",
        "zh": "### 🔄 建议复查（{n} 条）",
    },
    "report.keep_header": {
        "en": "### ✅ Looks Good ({n})",
        "zh": "### ✅ 保留（{n} 条）",
    },
    "report.not_to_save_tag": {
        "en": " ⚠️ violates not-to-save rules",
        "zh": " ⚠️ 违反「不该存」规则",
    },
    "report.conflict_tag": {
        "en": " 🔀 has conflict",
        "zh": " 🔀 存在冲突",
    },
    "report.score_line": {
        "en": "  Score: {score:.1f} · {reason}",
        "zh": "  综合分：{score:.1f} · {reason}",
    },
    "report.keep_line": {
        "en": "- **{filename}** [{type}] · {age} · Score {score:.1f}",
        "zh": "- **{filename}** [{type}] · {age} · 综合分 {score:.1f}",
    },
    "report.read_errors_header": {
        "en": "### ⚠️ Read Errors",
        "zh": "### ⚠️ 读取错误",
    },
    "report.footer": {
        "en": (
            "---\n"
            "▶ To clean up: call `memory_cleanup(dry_run=True)` to preview, then `memory_cleanup(dry_run=False)` to execute\n"
            "  (this report is cached — cleanup won't re-analyze)\n\n"
            "💬 Score looks wrong? → https://github.com/ladyiceberg/memory-quality-mcp/issues/new?template=wrong_score.md"
        ),
        "zh": (
            "---\n"
            "▶ 确认清理请调用 `memory_cleanup(dry_run=True)` 预览，再调用 `memory_cleanup(dry_run=False)` 执行\n"
            "  （本次报告已缓存，cleanup 无需重新分析）\n\n"
            "💬 评分不准确？→ https://github.com/ladyiceberg/memory-quality-mcp/issues/new?template=wrong_score.md"
        ),
    },

    # ── memory_score ──────────────────────────────────────────────────────────
    "score.empty_content": {
        "en": "❌ Please provide memory content (content field cannot be empty).",
        "zh": "❌ 请提供要评分的记忆内容（content 字段不能为空）。",
    },
    "score.llm_error": {
        "en": "❌ Cannot run scoring: {error}\n\nPlease set an API Key environment variable (OPENAI_API_KEY / KIMI_API_KEY / MINIMAX_API_KEY, etc.).",
        "zh": "❌ 无法运行评分：{error}\n\n请设置 API Key 环境变量（OPENAI_API_KEY / KIMI_API_KEY / MINIMAX_API_KEY 等）。",
    },
    "score.header": {
        "en": "## 🔬 Memory Quality Score",
        "zh": "## 🔬 记忆质量评分",
    },
    "score.action": {
        "en": "**Recommended action**: {icon} {action}",
        "zh": "**建议操作**：{icon} {action}",
    },
    "score.composite": {
        "en": "**Composite score**: {score:.2f} / 5.00",
        "zh": "**综合分**：{score:.2f} / 5.00",
    },
    "score.not_to_save": {
        "en": "\n⚠️ **Violates not-to-save rules**: this type of content should not be stored as a memory.",
        "zh": "\n⚠️ **违反「不该存」规则**：此类内容不应存储为记忆。",
    },
    "score.dimensions_header": {
        "en": "### Dimension Scores\n| Dimension | Score | Description |\n|-----------|-------|-------------|",
        "zh": "### 四维评分\n| 维度 | 得分 | 说明 |\n|------|------|------|",
    },
    "score.dim_importance": {
        "en": "| Importance (×40%) | {v} / 5 | Usefulness for future conversations |",
        "zh": "| 重要性（×40%） | {v} / 5 | 对未来对话的帮助程度 |",
    },
    "score.dim_recency": {
        "en": "| Recency (×25%) | {v} / 5 | Is the information still accurate? |",
        "zh": "| 时效性（×25%） | {v} / 5 | 信息是否仍然准确 |",
    },
    "score.dim_credibility": {
        "en": "| Credibility (×15%) | {v} / 5 | Does it have a clear source? |",
        "zh": "| 可信度（×15%） | {v} / 5 | 是否有明确来源 |",
    },
    "score.dim_accuracy": {
        "en": "| Accuracy (×20%) | {v} | Was it recorded faithfully? |",
        "zh": "| 准确性（×20%） | {v} | 记录是否忠实于来源 |",
    },
    "score.accuracy_na": {
        "en": "N/A",
        "zh": "无法评估",
    },
    "score.reason_header": {
        "en": "### Rationale",
        "zh": "### 评分依据",
    },
    "score.scored_by_rules": {
        "en": "*Scored by: rule engine*",
        "zh": "*评分来源：规则引擎*",
    },
    "score.scored_by_llm": {
        "en": "*Scored by: LLM analysis*",
        "zh": "*评分来源：LLM 分析*",
    },

    # ── memory_cleanup ────────────────────────────────────────────────────────
    "cleanup.no_memories": {
        "en": "📭 No memory files found, nothing to clean up.",
        "zh": "📭 未找到记忆文件，无需清理。",
    },
    "cleanup.not_found": {
        "en": "❌ The following files were not found: {files}\n\nPlease run `memory_report()` first to get the correct filenames.",
        "zh": "❌ 以下文件未找到：{files}\n\n请先运行 `memory_report()` 获取正确的文件名。",
    },
    "cleanup.llm_error": {
        "en": "❌ Cannot run scoring engine: {error}\n\nPlease run `memory_report()` first to generate a cached analysis, or set an API Key environment variable.",
        "zh": "❌ 无法运行评分引擎：{error}\n\n请先运行 `memory_report()` 生成分析缓存，或设置 API Key 环境变量。",
    },
    "cleanup.nothing_to_clean": {
        "en": "✅ Nothing to clean up — memory store looks healthy.",
        "zh": "✅ 没有需要清理的记忆，记忆库状态良好。",
    },
    "cleanup.preview_header": {
        "en": "🔍 **Preview mode** (nothing deleted)\n{n} memories will be cleaned up{cache_note}\n",
        "zh": "🔍 **预览模式**（未执行任何删除）\n共 {n} 条记忆将被清理{cache_note}\n",
    },
    "cleanup.done_header": {
        "en": "✅ Cleaned up {n} memories (across {projects} projects){cache_note}\n",
        "zh": "✅ 已清理 {n} 条记忆（跨 {projects} 个项目）{cache_note}\n",
    },

    # ── memory_dashboard ──────────────────────────────────────────────────────
    "dashboard.demo_missing": {
        "en": (
            "❌ Demo data directory not found.\n"
            "Please run: python3 scripts/generate_memories.py --output examples/demo_memories"
        ),
        "zh": (
            "❌ 示例数据目录不存在。\n"
            "请运行：python3 scripts/generate_memories.py --output examples/demo_memories"
        ),
    },
    "dashboard.demo_llm_error": {
        "en": (
            "❌ Demo mode requires an API Key for scoring: {error}\n\n"
            "Please set an environment variable and retry, or view the sample report directly:\n"
            "python3 scripts/test_live.py --dir examples/demo_memories"
        ),
        "zh": (
            "❌ Demo 模式需要 API Key 运行评分：{error}\n\n"
            "请设置环境变量后重试，或直接查看示例报告：\n"
            "python3 scripts/test_live.py --dir examples/demo_memories"
        ),
    },
    "dashboard.demo_opened": {
        "en": (
            "✅ Demo Dashboard opened in browser\n\n"
            "Using built-in sample data — {total} simulated memories\n"
            "Overview: ✓ Keep {keep}  ! Review {review}  × Delete {delete}\n\n"
            "💡 To analyze your real memories, run `memory_report()` then open the Dashboard"
        ),
        "zh": (
            "✅ Demo Dashboard 已在浏览器中打开\n\n"
            "这是使用内置示例数据的演示，共 {total} 条模拟记忆\n"
            "概览：✓ 保留 {keep}  ！复查 {review}  × 删除 {delete}\n\n"
            "💡 想分析你自己的真实记忆？先运行 `memory_report()` 再打开 Dashboard"
        ),
    },
    "dashboard.demo_open_error": {
        "en": "❌ Failed to open Demo Dashboard: {error}",
        "zh": "❌ 打开 Demo Dashboard 失败：{error}",
    },
    "dashboard.no_cache": {
        "en": (
            "❌ Could not generate report cache. Please run `memory_report()` first, then open the Dashboard.\n\n"
            "💡 No memory files yet? Try demo mode: `memory_dashboard(demo=True)`"
        ),
        "zh": (
            "❌ 未能生成报告缓存。请先运行 `memory_report()` 再打开 Dashboard。\n\n"
            "💡 还没有记忆文件？可以先用演示模式：`memory_dashboard(demo=True)`"
        ),
    },
    "dashboard.opened": {
        "en": (
            "✅ Dashboard opened in browser\n\n"
            "Data source: analysis from {age} ({total} memories)\n"
            "File: {path}\n\n"
            "Overview: ✓ Keep {keep}  ! Review {review}  × Delete {delete}\n\n"
            "💬 Score looks wrong? → https://github.com/ladyiceberg/memory-quality-mcp/issues/new?template=wrong_score.md"
        ),
        "zh": (
            "✅ Dashboard 已在浏览器中打开\n\n"
            "数据来源：{age}的分析（{total} 条记忆）\n"
            "文件路径：{path}\n\n"
            "概览：✓ 保留 {keep}  ！复查 {review}  × 删除 {delete}\n\n"
            "💬 评分不准确？→ https://github.com/ladyiceberg/memory-quality-mcp/issues/new?template=wrong_score.md"
        ),
    },
    "dashboard.open_error": {
        "en": (
            "❌ Failed to open Dashboard: {error}\n\n"
            "Please check that a default browser is configured, or open manually:\n"
            "~/.memory-quality-mcp/dashboard.html"
        ),
        "zh": (
            "❌ 打开 Dashboard 失败：{error}\n\n"
            "请检查系统是否有默认浏览器，或手动打开：\n"
            "~/.memory-quality-mcp/dashboard.html"
        ),
    },

    # ── 工具 description（Claude 看的）────────────────────────────────────────
    "tool.audit.desc": {
        "en": (
            "Quick scan of all your Claude Code projects' memory store, returning a health summary. "
            "Scans all projects by default; pass project_path to scan a specific project. "
            "No LLM calls — fast, good for a quick overview."
        ),
        "zh": (
            "快速扫描你所有 Claude Code 项目的记忆库，返回健康摘要。"
            "默认扫描全部项目；传入 project_path 可只扫描指定项目。"
            "不调用 LLM，速度快，适合先做整体了解。"
        ),
    },
    "tool.report.desc": {
        "en": (
            "Detailed quality analysis of your memory store. Each memory gets a 4-dimension score "
            "(Importance / Recency / Credibility / Accuracy) with a recommended action (keep / review / delete). "
            "Scans all projects by default; pass project_path to analyze a specific project. "
            "Calls LLM — takes longer than memory_audit."
        ),
        "zh": (
            "对记忆库做详细的质量分析，每条记忆附带四维评分"
            "（重要性 / 时效性 / 可信度 / 准确性）和建议操作（保留 / 复查 / 删除）。"
            "默认扫描全部项目；传入 project_path 可只分析指定项目。"
            "会调用 LLM 进行分析，耗时比 memory_audit 长。"
        ),
    },
    "tool.cleanup.desc": {
        "en": (
            "Run memory cleanup. Defaults to preview mode (dry_run=true) — shows what would be removed without deleting. "
            "Set dry_run=false and confirm with the user before executing. "
            "All deletions are backed up to a .trash directory first."
        ),
        "zh": (
            "执行记忆清理。默认为预览模式（dry_run=true），只展示将要清理的内容，不实际删除。"
            "设置 dry_run=false 并经过用户明确确认后，才会执行删除。"
            "删除前会自动备份到 .trash 目录。"
        ),
    },
    "tool.score.desc": {
        "en": (
            "Score a single memory on 4 quality dimensions (Importance / Recency / Credibility / Accuracy). "
            "Mainly for debugging and validating the scoring model, "
            "or to check whether a new memory is worth saving."
        ),
        "zh": (
            "对单条记忆内容进行四维质量打分（重要性 / 时效性 / 可信度 / 准确性）。"
            "主要用于调试和验证评分模型，也可以用来评估一条新记忆是否值得保存。"
        ),
    },
    "tool.dashboard.desc": {
        "en": (
            "Generate a visual memory health report and open it in the system browser. "
            "Reuses the latest memory_report() cache — no extra LLM calls needed. "
            "If no cache exists, runs a full analysis first. "
            "Pass demo=true to use built-in sample data — no real memory files needed."
        ),
        "zh": (
            "生成记忆健康报告的可视化页面，用系统默认浏览器打开。"
            "优先复用上一次 memory_report() 的缓存结果，无需重新调用 LLM。"
            "如果没有缓存，会先运行一次完整分析再打开页面。"
            "传入 demo=true 可使用内置示例数据，无需真实记忆文件，适合首次体验。"
        ),
    },

    # ── 通用 ──────────────────────────────────────────────────────────────────
    "common.unknown_tool": {
        "en": "Unknown tool: {name}",
        "zh": "未知工具：{name}",
    },
}


# ── 获取文本 ──────────────────────────────────────────────────────────────────

def t(key: str, lang: str | None = None, **kwargs) -> str:
    """
    获取指定 key 的文本，自动 format 占位符。

    Args:
        key:    文本 key，格式为 "section.name"
        lang:   语言代码（en / zh）。不传则自动检测。
        **kwargs: 传给 str.format() 的占位符值

    Returns:
        格式化后的文本字符串
    """
    resolved_lang = lang if lang in ("en", "zh") else detect_language()

    entry = STRINGS.get(key, {})
    text = entry.get(resolved_lang) or entry.get("en") or f"[missing: {key}]"

    if kwargs:
        try:
            text = text.format(**kwargs)
        except KeyError:
            pass  # 占位符缺失时返回原文，不崩溃

    return text
