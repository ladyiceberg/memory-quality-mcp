# Memory Quality — Command Reference

All commands are run via:
```bash
python ${CLAUDE_SKILL_DIR}/scripts/memory_quality.py <command> [options]
```

---

## `audit` — Quick overview (no API key needed)

Scans all memory files and prints a summary table. No LLM calls, instant.

```bash
python ${CLAUDE_SKILL_DIR}/scripts/memory_quality.py audit
python ${CLAUDE_SKILL_DIR}/scripts/memory_quality.py audit --project /path/to/project
```

**Output includes:**
- Total memory count per project
- File age (days since last modified)
- File size
- A quick flag for obviously stale entries (> 90 days old)

**Options:**
| Flag | Description |
|------|-------------|
| `--project <path>` | Limit to a single project directory |
| `--sort age\|size\|name` | Sort order (default: age) |

---

## `report` — Score all memories (requires API key)

Calls the LLM to score every memory on 4 dimensions and detect conflicts.
Results are cached in `~/.claude/memory_quality_cache.json`.

```bash
python ${CLAUDE_SKILL_DIR}/scripts/memory_quality.py report
python ${CLAUDE_SKILL_DIR}/scripts/memory_quality.py report --verbose
python ${CLAUDE_SKILL_DIR}/scripts/memory_quality.py report --project /path/to/project
```

**Output includes:**
- Per-file scores: importance / recency / credibility / accuracy / composite
- Recommended action: `keep` / `review` / `delete`
- Conflict pairs (memories that contradict each other)
- Summary: counts by action category

**Options:**
| Flag | Description |
|------|-------------|
| `--verbose` | Show full reason text for each memory |
| `--project <path>` | Limit to a single project |
| `--no-cache` | Force re-score even if cache exists |

**Scoring dimensions (1–5 each):**
- **Importance** (40%): How useful is this for future conversations?
- **Recency** (25%): Is this information still current?
- **Credibility** (15%): Does this have a clear user-stated source?
- **Accuracy** (20%): Is it faithfully recorded, not over-interpreted?

**Composite score → action:**
- > 3.5 → `keep`
- 2.5–3.5 → `review`
- < 2.5 → `delete`

---

## `cleanup` — Preview + execute deletions (requires prior `report`)

**Always two steps.** First run without `--execute` to preview, then confirm with the user before running with `--execute`.

```bash
# Step 1: preview
python ${CLAUDE_SKILL_DIR}/scripts/memory_quality.py cleanup

# Step 2: execute (only after user confirms)
python ${CLAUDE_SKILL_DIR}/scripts/memory_quality.py cleanup --execute
```

**Behavior:**
- Without `--execute`: prints the list of files that *would* be deleted. No changes made.
- With `--execute`: moves files to `~/.claude/memory_trash/` (not permanent deletion). A restore path is shown.
- Requires a cached `report` — run `report` first if you see "No cached report found".

**Options:**
| Flag | Description |
|------|-------------|
| `--execute` | Actually move files to trash (after preview confirmation) |
| `--project <path>` | Limit to a single project |
| `--min-score <n>` | Delete files with composite score below n (default: 2.5) |

---

## `score <text>` — Evaluate a single memory snippet

Scores one piece of text without touching any files. Useful for testing or checking before saving.

```bash
python ${CLAUDE_SKILL_DIR}/scripts/memory_quality.py score "User prefers dark mode"
python ${CLAUDE_SKILL_DIR}/scripts/memory_quality.py score "Always avoid phishing links" --type rule
```

**Output:** JSON with all 4 dimension scores, composite score, recommended action, and reason.

**Options:**
| Flag | Description |
|------|-------------|
| `--type preference\|rule\|context` | Hint for memory type (default: auto-detect) |

**Works without API key** for rule-based checks (e.g. "is this a task-type memory that should not be saved?"). Full LLM scoring requires an API key.

---

## `dashboard` — Visual HTML report in browser (requires prior `report`)

Opens an interactive HTML dashboard in your default browser.

```bash
python ${CLAUDE_SKILL_DIR}/scripts/memory_quality.py dashboard
```

**Shows:**
- Score distribution chart
- Filterable table: sort by score, filter by action or project
- Conflict pairs highlighted in red
- One-click copy of file paths for manual review

Requires a cached `report`. Run `report` first if you see "No cached report found".

---

## Environment variables

| Variable | Description |
|----------|-------------|
| `CLAUDE_PLUGIN_OPTION_api_key` | LLM API key (set via plugin config) |
| `CLAUDE_PLUGIN_OPTION_provider` | `openai` / `anthropic` / `minimax` / `kimi` |
| `CLAUDE_PLUGIN_OPTION_language` | `en` or `zh` (default: auto-detect from system locale) |
| `OPENAI_API_KEY` | Fallback if plugin option not set |
| `ANTHROPIC_API_KEY` | Fallback if plugin option not set |
| `MINIMAX_API_KEY` | Fallback if plugin option not set |
| `KIMI_API_KEY` | Fallback if plugin option not set |

---

## Example: full cleanup flow

```
1. audit          → see how many memories you have
2. report         → score all memories (uses API key)
3. cleanup        → preview what would be deleted
4. [user confirms]
5. cleanup --execute  → move low-quality files to trash
6. dashboard      → review results visually
```
