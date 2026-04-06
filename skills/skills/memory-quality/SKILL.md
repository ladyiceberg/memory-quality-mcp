---
name: memory-quality
description: >
  Audits and cleans up Claude Code auto-saved memory files. Scores on 4
  dimensions, detects conflicts, opens a visual dashboard. Trigger on:
  memories, memory quality, memory cleanup, memory health, memory dashboard,
  检查记忆, 清理记忆, 记忆质量, 记忆看板.
allowed-tools: Bash(python *)
argument-hint: "[audit|report|cleanup|score <text>|dashboard]"
---

# Memory Quality

Helps users understand and clean up the memory files that Claude Code saves
automatically. Files live in `~/.claude/projects/*/memory/`.

Memory files on this machine:
```!
find ~/.claude/projects -name "*.md" -path "*/memory/*" 2>/dev/null \
  | grep -v "MEMORY\.md" | wc -l | tr -d ' '
```
If the count above is 0, tell the user they don't have memory files yet and
suggest they keep using Claude Code normally — files appear after a few
sessions.

## Choosing what to run

- **Quick overview, no cost** → `audit`
- **See what should be deleted** → `report` (calls LLM, results cached)
- **Delete low-quality memories** → `cleanup` then `cleanup --execute` (two steps, see below)
- **Open visual report in browser** → `dashboard` (needs cached `report` first)
- **Evaluate a single memory** → `score "<text>"`

For detailed command options and example output, see
[references/commands.md](references/commands.md).

## Running a command

```bash
python ${CLAUDE_SKILL_DIR}/scripts/memory_quality.py <command> [options]
```

## Cleanup is always two steps

1. Run `cleanup` — shows a preview of what would be deleted.
2. Show the user the list and ask for confirmation.
3. Only after confirmation, run `cleanup --execute`.

Never skip the preview step. Even though a `.trash/` backup is created
automatically, users don't expect silent deletions.

## When there's no cached report

`cleanup` and `dashboard` both require a prior `report` to be run. If the
script says "No cached report found", run `report` first, then retry.

## API Key

`audit` and `dashboard` (with cache) need no API key. `report` and `score`
need one. If missing, ask the user to set `OPENAI_API_KEY`,
`ANTHROPIC_API_KEY`, `MINIMAX_API_KEY`, or `KIMI_API_KEY` in their
environment, or configure it via plugin settings.
