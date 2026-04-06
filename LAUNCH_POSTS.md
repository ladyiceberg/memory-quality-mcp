# Memory Quality · Launch Posts

---

## Reddit — r/ClaudeAI

**Title:**
I built a Claude Code Skill that audits and cleans up your auto-saved memories (no MCP setup needed)

**Body:**

Claude Code v2.1.59+ automatically saves memories from your conversations. That's powerful — but after a few weeks, your memory store starts accumulating garbage:

- **Stale project context** — "working on X this week" from 3 months ago
- **Junk memories** — offhand remarks recorded as permanent facts
- **Conflicting memories** — "prefers detailed comments" AND "keep code minimal" both saved
- **Over-interpreted memories** — AI turned "I stayed up late last night" into "user is a night owl"

So I built **Memory Quality** — a Claude Code Skill that runs a 4-dimension quality audit (Importance / Recency / Credibility / Accuracy) on your memory store and gives you a visual dashboard with actionable cleanup recommendations.

**Why a Skill instead of MCP?**
No server to run, no config file to edit. Just install the plugin and talk to Claude naturally — "audit my memories", "show me what should be deleted", "open the memory dashboard".

**What it does:**
- `audit` — instant health check, no LLM cost, runs in seconds
- `report` — full 4-dimension scoring + conflict detection (~$0.01 for 50 memories)
- `cleanup` — safe cleanup with dry-run preview + auto-backup to `.trash/`
- `dashboard` — opens a local HTML dashboard in your browser
- `score "text"` — evaluate any single memory snippet on the spot

**Install (Claude Code Skill):**
```
# Step 1: add the marketplace (one-time)
/plugin marketplace add ladyiceberg/memory-quality-mcp

# Step 2: install
/plugin install memory-quality@ladyiceberg-memory-quality-mcp
```
Then just say: *"audit my memories"* or *"show me what should be deleted"*

**Also available as MCP** if you prefer that setup:
```json
"memory-quality": {
  "command": "uvx",
  "args": ["memory-quality-mcp"],
  "env": { "OPENAI_API_KEY": "your-key" }
}
```

Supports OpenAI, Anthropic, Kimi, MiniMax — any OpenAI-compatible API.

GitHub: https://github.com/ladyiceberg/memory-quality-mcp

Would love feedback — especially if you find the scoring consistently wrong. There's a "Score wrong? Tell us" link right in the dashboard.

---

## Claude Discord — #tools channel

🧠 **Memory Quality** — audit and clean up Claude Code's auto-saved memories

Claude Code's Auto Memory is great, but over time it collects stale project notes, junk memories, and conflicting preferences.

**Now available as a Claude Code Skill** — no MCP server, no config. Just install and ask Claude to check your memories.

**5 commands:**
- `audit` — quick scan, no LLM cost
- `report` — full 4-dimension scoring + conflict detection
- `cleanup` — safe cleanup with dry-run + `.trash/` backup
- `dashboard` — local visual HTML dashboard (screenshot below 👇)
- `score "text"` — evaluate any single memory snippet

**Install as Skill (recommended):**
```
# Step 1: add the marketplace (one-time)
/plugin marketplace add ladyiceberg/memory-quality-mcp

# Step 2: install
/plugin install memory-quality@ladyiceberg-memory-quality-mcp
```
Then say: *"audit my memories"* or *"open the memory dashboard"*

**Also works as MCP:**
```json
{ "command": "uvx", "args": ["memory-quality-mcp"], "env": { "OPENAI_API_KEY": "..." } }
```

Supports OpenAI / Anthropic / Kimi / MiniMax.

→ https://github.com/ladyiceberg/memory-quality-mcp

---

## agentskills.io Discord — #show-and-tell

🧠 **memory-quality** — a Claude Code Skill that audits your AI memory store

Built this to solve a real problem: Claude Code's auto-saved memories accumulate junk over time — stale context, over-interpreted remarks, conflicting preferences.

**What it does:**
- 4-dimension quality scoring (Importance / Recency / Credibility / Accuracy)
- Conflict detection — finds memories that contradict each other
- Safe cleanup with dry-run preview + `.trash/` backup
- Local HTML dashboard

Follows the agentskills.io standard, works with Claude Code and other supporting tools.

→ https://github.com/ladyiceberg/memory-quality-mcp

---

## 发图建议

- Reddit：图1（整体概览）作为第一张，图3或图4作为第二张
- Discord：直接贴图1
- agentskills Discord：贴 dashboard 截图即可
