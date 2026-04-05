# Changelog

All notable changes to Memory Quality MCP will be documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

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
