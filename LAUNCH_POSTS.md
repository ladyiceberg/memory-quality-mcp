# Memory Quality MCP · 发帖文案

---

## Reddit — r/ClaudeAI

**标题：**
I built a MCP plugin that audits and cleans up Claude Code's auto-saved memories

**正文：**

Claude Code v2.1.59+ automatically saves memories from your conversations. That's powerful — but after a few weeks, your memory store starts accumulating garbage:

- **Stale project context** — "working on X this week" from 3 months ago
- **Junk memories** — offhand remarks recorded as permanent facts
- **Conflicting memories** — "prefers detailed comments" AND "keep code minimal" both saved
- **Over-interpreted memories** — AI turned "I stayed up late last night" into "user is a night owl"

So I built **Memory Quality MCP** — a plugin that runs a 4-dimension quality audit (Importance / Recency / Credibility / Accuracy) on your memory store and gives you a visual dashboard with actionable cleanup recommendations.

**What it does:**
- `memory_audit()` — instant health check, no LLM cost
- `memory_report()` — full scoring with conflict detection (~$0.01 for 50 memories)
- `memory_cleanup()` — safe cleanup with dry-run preview + auto-backup to `.trash/`
- `memory_dashboard()` — opens a local HTML dashboard in your browser

Try the demo first (no real memory files needed):
```
Open the memory dashboard in demo mode
```

**Install:**
```json
"memory-quality": {
  "command": "uvx",
  "args": ["memory-quality-mcp"],
  "env": { "OPENAI_API_KEY": "your-key" }
}
```

Supports OpenAI, Anthropic, Kimi, MiniMax — any OpenAI-compatible API.

GitHub: https://github.com/ladyiceberg/memory-quality-mcp

Would love feedback, especially if you find the scoring consistently wrong — there's a "Score wrong? Tell us" link right in the dashboard.

---

## Claude Discord — #tools 频道

🧠 **Memory Quality MCP** — audit and clean up Claude Code's auto-saved memories

Claude Code's Auto Memory is great, but over time it collects stale project notes, junk memories, and conflicting preferences. This plugin gives your memory store a health check.

**4 tools:**
- `memory_audit()` — quick scan, no LLM cost
- `memory_report()` — full 4-dimension scoring + conflict detection
- `memory_cleanup()` — safe cleanup with dry-run + `.trash/` backup
- `memory_dashboard()` — local visual dashboard (screenshot below 👇)

**Install in 1 line** (uvx, no manual setup):
```json
{ "command": "uvx", "args": ["memory-quality-mcp"], "env": { "OPENAI_API_KEY": "..." } }
```

Supports OpenAI / Anthropic / Kimi / MiniMax.
Demo mode works without any real memory files — just say "open the memory dashboard in demo mode".

→ https://github.com/ladyiceberg/memory-quality-mcp

---

## 发图建议

- Reddit：图1（整体概览）作为第一张，图3或图4作为第二张
- Discord：直接贴图1
