# Changelog

All notable changes to Memory Quality MCP will be documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [0.2.1] — 2026-04-05

### Fixed

- `age_display()` in session store now respects language setting — English users see "2h ago" instead of Chinese characters
- README_CN: add dashboard screenshots and language auto-detection note

---

## [0.2.0] — 2026-04-05

### Added

- **Internationalization (i18n)** — Dashboard and all tool output now support English and Chinese. Language is auto-detected from system locale (`LANG`/`LC_ALL`), or set explicitly via `config.yaml` (`language: en/zh/auto`) or the `MEMORY_QUALITY_LANGUAGE` environment variable.
- **Template-based Dashboard** — HTML dashboard extracted into `src/templates/dashboard_en.html` and `dashboard_zh.html`. Clean separation of data and presentation; adding a new language requires only a new HTML file.
- **`user`-type memory protection** — Memories of type `user` with a low composite score are now downgraded to `review` instead of `delete`, preventing accidental loss of high-value personal context.
- **Task-type detection in scoring prompt** — The LLM scorer now explicitly checks whether a memory records a one-off task context vs. a long-term user attribute before scoring, reducing false positives on temporary state memories.

### Changed

- All tool output strings centralized in `src/i18n.py` — tool descriptions, report headers, error messages, and status lines now render in the configured language.
- `memory_dashboard()` opens the English template by default; Chinese users on `zh_CN` locale get the Chinese template automatically.
- Scoring prompts (`BATCH_SCORING_SYSTEM`, `SINGLE_SCORE_SYSTEM`) now include a language instruction so the `reason` field matches the configured language.

---

## [0.1.0] — 2026-04-05

Initial release.

### Tools

- **`memory_audit()`** — Fast health check across all Claude Code projects (no LLM calls). Returns total memories, stale count, index usage, and estimated cost for a full report.
- **`memory_report()`** — Full 4-dimension quality scoring (Importance / Recency / Credibility / Accuracy) with conflict detection. Results cached in SQLite for reuse.
- **`memory_cleanup()`** — Safe cleanup with dry-run preview, `.trash/` backup, and MEMORY.md index sync. Reuses cached report — no extra LLM calls.
- **`memory_score()`** — Score a single memory string. Rule engine runs first; LLM called only if needed.
- **`memory_dashboard()`** — Generates a local HTML health report (Apple-inspired minimal design) and opens it in the default browser. Supports `demo=True` mode with built-in example data.

### Features

- **Multi-provider LLM support** — OpenAI, Kimi, MiniMax, Anthropic. Auto-detects from environment variables. Any OpenAI-compatible API supported via `MEMORY_QUALITY_BASE_URL`.
- **Rule engine** — Zero-cost pre-screening catches stale project memories and rule violations before calling the LLM.
- **Session store** — SQLite persistence at `~/.memory-quality-mcp/session.db`. Report results reused by cleanup and dashboard without re-analysis.
- **Multi-project scan** — Scans all `~/.claude/projects/*/memory/` directories. Supports `project_path` filter for single-project analysis.
- **Config file** — Auto-generated at `~/.memory-quality-mcp/config.yaml` on first run. Supports environment variable overrides (`MEMORY_QUALITY_PROVIDER`, `MEMORY_QUALITY_MODEL`, etc.).
- **Demo mode** — `memory_dashboard(demo=True)` loads built-in example memories so users can experience the full product without real memory files.
- **Safe deletion** — All deletions: preview first → explicit confirmation → auto-backup to `.trash/<timestamp>/`.

### Benchmark

- 11 initial labeled samples in `benchmark/dataset.json`, generated using Claude Code's own extraction prompt
- Covers all quality types: high-quality, stale, low-quality, conflicting, misrecorded
