# Memory Quality MCP · 项目状态文档

> 最后更新：2026-04-06
> 当前版本：v0.2.2（已发布到 PyPI）

---

## 一、这个项目是什么

**Memory Quality** 是一个工具，帮助用户审计和清理 Claude Code 自动保存的记忆文件。

Claude Code v2.1.59+ 会自动从对话中提取记忆（存在 `~/.claude/projects/*/memory/` 下），久了之后会积累垃圾：过时的项目状态、被过度解读的随口一说、互相矛盾的偏好记录等。这个工具用四个维度（重要性 / 时效性 / 可信度 / 准确性）对每条记忆评分，检测冲突，提供可视化看板，并安全地清理低质量条目。

**两种使用方式：**
- **MCP Server**：`uvx memory-quality-mcp`，给 Claude Code 添加 5 个工具函数
- **Claude Code Skills Plugin**：通过 `/plugin marketplace add` 安装，无需运行服务器

---

## 二、仓库结构

```
memory-quality-mcp/
├── src/                        # 核心逻辑（MCP 和 Skills 共用）
│   ├── server.py               # MCP Server 入口，5 个工具定义
│   ├── quality_engine.py       # 评分引擎（规则 + LLM）+ 冲突检测
│   ├── memory_reader.py        # 扫描 ~/.claude/projects/*/memory/ 目录
│   ├── memory_writer.py        # 删除 + 备份到 .trash/ + 更新 MEMORY.md
│   ├── session_store.py        # SQLite 缓存（report 结果复用）
│   ├── llm_client.py           # 统一 LLM 客户端（OpenAI-compatible）
│   ├── dashboard.py            # 生成 HTML 报告并打开浏览器
│   ├── config.py               # 配置加载（env > ~/.memory-quality-mcp/config.yaml）
│   ├── i18n.py                 # 所有面向用户的文本（EN/ZH）
│   ├── prompts.py              # 所有 LLM prompt 模板
│   └── templates/              # dashboard_en.html / dashboard_zh.html
│
├── skills/                     # Claude Code Skills Plugin
│   ├── .claude-plugin/
│   │   ├── plugin.json         # 插件元数据 + userConfig（API key 等）
│   │   └── marketplace.json    # /plugin marketplace add 的入口文件
│   ├── hooks/hooks.json        # SessionStart 自动安装 Python 依赖
│   ├── requirements.txt        # openai + pyyaml
│   └── skills/memory-quality/
│       ├── SKILL.md            # Skill 入口（237 字符 description）
│       ├── scripts/memory_quality.py  # CLI 脚本（直接 import src/）
│       └── references/commands.md    # 详细命令文档
│
├── benchmark/                  # 评分质量 Benchmark
│   ├── dataset.json            # 833 条 memory，已跑 LLM 评分
│   ├── scenarios.json          # 1658 条 scenario（原始对话转换）
│   ├── EVALUATION_REPORT.md    # 完整评估报告
│   ├── STATUS.md               # Benchmark 现状与 TODO（重要！）
│   └── run_benchmark_scores.py # 批量跑评分脚本（断点续跑）
│
├── examples/demo_memories/     # 内置演示数据（demo 模式用）
├── scripts/
│   ├── seed_memories.py        # 生成测试记忆文件到本地
│   └── test_live.py            # 用真实 API 验证评分引擎
│
├── pyproject.toml              # 包配置（版本号在这里改）
├── CHANGELOG.md                # 版本历史
├── LAUNCH_POSTS.md             # 各平台发帖文案（已更新到 v0.2.2）
└── config.yaml                 # 本地配置（.gitignore 忽略，不提交）
```

---

## 三、关键技术决策

### 3.1 评分引擎两层设计

```
输入 memory 文件
    ↓
Layer 1：规则引擎（零 API 成本）
  - 检测「不该存」类型（代码模式、临时任务、AI 建议等）
  - 检测 project 类型超时（> 90 天）
  ↓ 无法判断的继续往下
Layer 2：LLM 评分（单条独立调用）
  - 使用 SINGLE_SCORE_SCHEMA（单对象，结构简单，解析稳定）
  - 失败 → action="error"，scores=-1，不混入统计
    ↓
冲突检测（批量，必须多条一起看）
  - 找出语义互相矛盾的记忆对
```

**为什么 Layer 2 改成单条而不是批量：**
批量评分（6条一批）的 JSON schema 要求 LLM 输出包含 6 个对象的数组，实测 MiniMax 解析失败率高达 55%。一条失败整批废掉。改成单条后每条独立，失败只影响该条。冲突检测必须多条一起看，不受影响。

### 3.2 MCP vs Skills 架构关系

Skills 的 `memory_quality.py` 直接通过 `sys.path` 动态 import `src/` 模块，**两者共用一套核心逻辑**，不存在代码重复。

路径关系：`skills/skills/memory-quality/scripts/` 向上 4 级 = 项目根目录

### 3.3 Git 双仓库推送

- 本地工作目录：`/Users/maavis/opportunity_mining/`（私有 monorepo）
- 公开仓：`ladyiceberg/memory-quality-mcp`（对外产品）
- **推送规则**：改了 memory-quality-mcp 下的内容，必须推两次：
  ```bash
  git push origin main                                     # 推私有仓
  git subtree split --prefix=memory-quality-mcp -b _pub
  git push public _pub:main --force
  git branch -D _pub
  ```
- 改了其他目录（follow-builders 等），只推私有仓

---

## 四、已发布渠道

| 渠道 | 状态 | 说明 |
|------|------|------|
| PyPI | ✅ v0.2.2 | `uvx memory-quality-mcp` |
| mcp.so | ✅ 已提交 | MCP 目录 |
| Glama | ✅ 已提交 | MCP 目录 |
| awesome-mcp-servers | ✅ PR 已提交 | 等待合并 |
| GitHub topic 标签 | ✅ 已打 | `agent-skill`, `claude-code`, `claude-skill` 等 6 个 |
| SkillsMP.com | ✅ 自动索引 | 通过 GitHub topic 自动收录 |
| Reddit r/ClaudeAI | ⬜ 待发 | 文案在 LAUNCH_POSTS.md |
| Anthropic Discord | ⬜ 待发 | 文案在 LAUNCH_POSTS.md |
| agentskills.io Discord | ⬜ 待发 | 文案在 LAUNCH_POSTS.md |
| anthropics/skills PR | ⬜ 待考虑 | 官方仓库不接受社区 PR，可提 Issue 申请进 Partner Skills |

---

## 五、Benchmark 现状

详见 `benchmark/STATUS.md`，这里只列关键数字：

- **833 条 memory 已全部跑完评分**，结果持久化在 `dataset.json`
- **LLM 解析失败率 55%**（461/833）：这是当前最大问题，根治方向见下方 TODO
- **整体准确率 32.3%**（仅统计非 error 条目）：低的主要原因是 LLM 失败太多
- **keep 识别最差（18.2%）**，大量 keep 被打成 review

---

## 六、踩过的坑（避免重复踩）

### 坑 1：CLAUDE_CONFIG_DIR 环境变量冲突
Claude Code 开发环境下 `CLAUDE_CONFIG_DIR` 被设为 `~/.claude-internal`，导致 `get_all_memory_dirs()` 扫错目录，找不到记忆文件。
**解决**：本地测试时用 `env -u CLAUDE_CONFIG_DIR python3 ...`，正常用户没有这个变量。

### 坑 2：批量评分解析失败率极高
初始设计每批 6 条一起发给 LLM，MiniMax 输出经常截断，整批失败。
**解决**：改成单条独立调用，详见 3.1。

### 坑 3：解析失败时强制打 3.0/review 污染统计
旧逻辑：`_fallback_scored()` 在失败时伪造 3.0 的分数标记为 review，混入统计，让人以为评了但其实是假的。
**解决**：失败时 scores=-1，action="error"，在报告摘要里单独显示"❓ 失败 N 条"。

### 坑 4：Python 版本差异（MCP vs Skills）
MCP 通过 `uvx` 运行，Python 是 3.11+。Skills 调系统 `python3`，macOS 是 3.9。
`str | None` 是 Python 3.10+ 语法，Skills 下会报错。
**解决**：所有 `src/` 模块加 `from __future__ import annotations`（第一行，在 docstring 之前）。

### 坑 5：Git 双仓库路径结构不同
私有仓文件路径是 `memory-quality-mcp/src/config.py`，公开仓是 `src/config.py`。不能直接 `git push public main`——会把整个 monorepo 推过去。
**解决**：`git subtree split --prefix=memory-quality-mcp -b _pub` 提取，再 force push。

### 坑 6：`from __future__` 重复行
用 Python 脚本批量插入时，部分文件被插入了两行。表面上不报错（Python 允许重复），但不干净，而且当时的 commit 没有把修复记录进去，导致后续 subtree push 时又带着旧版本。
**教训**：用脚本批量改文件后，一定要 `git diff` 确认，立即 commit，不要留 unstaged 的修复。

### 坑 7：Skills 安装命令写错
发帖文案里写的 `/plugin install https://...` 是错的，`/plugin install` 不支持直接传 URL。
**正确方式**：
```
/plugin marketplace add ladyiceberg/memory-quality-mcp
/plugin install memory-quality@ladyiceberg-memory-quality-mcp
```

### 坑 8：API Key 丢失
每次新 session 都要重新找 API key。
**解决**：存在 `~/.env.local`，使用前 `source ~/.env.local`。文件内容：
```
MINIMAX_API_KEY=...
PYPI_TOKEN=...
```

---

## 七、接下来的 TODO

### 优先级高（有用户反馈时做）

**A. 修复 LLM 解析失败率（55%）**
当前根因：单条评分的 `max_tokens=512` 可能不够，某些长记忆被截断。
方案：
1. `max_tokens` 从 512 改到 1024
2. 失败后自动重试一次
3. 修完后重跑 `benchmark/run_benchmark_scores.py` 验证改善效果

**B. 发帖推广**
文案已经写好在 `LAUNCH_POSTS.md`，三个渠道：
- Reddit r/ClaudeAI
- Anthropic Discord
- agentskills.io Discord

### 优先级中（有时间时做）

**C. 改进评分准确率**
当前整体准确率 32.3%，目标 60%+。
主要方向：加强 prompt 里对"临时性内容"的识别，加 few-shot 示例。
需配合 Benchmark 重跑验证。

**D. human_scores 标注**
833 条 memory 的 `human_scores` 全为 null，有了它才能做"LLM 评分 vs 人工评分"对比。
建议抽 100-200 条，优先标注 delete/keep 分歧最大的。

### 优先级低（视情况）

**E. anthropics/skills 收录**
官方仓库不接受社区 PR，可以提 Issue 申请加入 README 的 Partner Skills 章节。目前只有 Notion 一家。

**F. claude-plugins.dev 提交**
手动提交仓库 URL，比较小的目录站。

---

## 八、本地开发环境

```bash
# 进入项目
cd /Users/maavis/opportunity_mining/memory-quality-mcp

# 加载 API keys
source ~/.env.local

# 运行评分引擎测试（种子数据）
env -u CLAUDE_CONFIG_DIR .venv/bin/python scripts/test_live.py --dir /tmp/test_memories

# 运行 Skills CLI 测试
env -u CLAUDE_CONFIG_DIR MINIMAX_API_KEY="$MINIMAX_API_KEY" \
  python3 skills/skills/memory-quality/scripts/memory_quality.py audit

# 发布到 PyPI
python3 -m build
TWINE_USERNAME=__token__ TWINE_PASSWORD="$PYPI_TOKEN" \
  python3 -m twine upload dist/memory_quality_mcp-<version>*

# 推公开仓
git subtree split --prefix=memory-quality-mcp -b _pub
git push public _pub:main --force
git branch -D _pub
```

---

## 九、版本历史摘要

| 版本 | 日期 | 主要内容 |
|------|------|---------|
| v0.1.0 | 2026-04-05 | 初始发布，5个 MCP 工具，多 provider 支持 |
| v0.2.0 | 2026-04-05 | i18n（EN/ZH），模板化 Dashboard，user 类型保护 |
| v0.2.1 | 2026-04-05 | 修复 age_display 语言问题 |
| v0.2.2 | 2026-04-06 | 单条评分、error 标记、Python 3.9 兼容、Skills Plugin |
