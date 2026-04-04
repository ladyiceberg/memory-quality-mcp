# Claude Code 记忆系统内部机制

> 目的：为 memory-quality-mcp 开发提供足够的内部机制参考，避免反复查阅源码。
> 来源：对 claude-code-main 源码的直接阅读与分析（2026-04-04）。
> 覆盖范围：Auto Memory 子系统（我们的直接操作对象），附带其他子系统的关键说明。

---

## 一、整体架构速览

Claude Code 的记忆系统由 5 个子系统组成，我们只需关注 **Auto Memory**：

```
┌─────────────────────────────────────────────────────┐
│  Auto Memory   ← 我们的操作对象（持久跨会话）         │
│  Session Memory ← 只在当前会话内有效，不需要操作      │
│  Agent Memory   ← 专用 Agent 的独立记忆，不需要操作   │
│  memdir 核心层  ← Auto Memory 的底层基础设施          │
│  Team Memory    ← 需要 feature flag，暂不考虑         │
└─────────────────────────────────────────────────────┘
```

---

## 二、文件系统结构（最重要）

### 2.1 Auto Memory 的完整目录布局

```
~/.claude/projects/<sanitized-git-root>/memory/
    ├── MEMORY.md              ← 索引文件（只是目录，不包含记忆内容本身）
    ├── user_role.md           ← 一条记忆 = 一个独立 .md 文件
    ├── feedback_testing.md    ← 一条记忆
    ├── project_deadline.md    ← 一条记忆
    └── team/                  ← Team Memory 子目录（需 TEAMMEM flag，忽略）
```

**关键设计**：单文件单记忆。MEMORY.md 是纯索引，记忆内容全在独立 `.md` 文件里。

### 2.2 路径解析逻辑（`paths.ts`）

```
getAutoMemPath() 的解析顺序：
  1. CLAUDE_COWORK_MEMORY_PATH_OVERRIDE 环境变量（全路径覆盖）
  2. settings.json 的 autoMemoryDirectory 字段（支持 ~/ 展开）
  3. 默认：{memoryBaseDir}/projects/{sanitizePath(git-root)}/memory/

memoryBaseDir 的解析：
  1. CLAUDE_CODE_REMOTE_MEMORY_DIR 环境变量
  2. 默认：~/.claude/
```

**对我们的影响**：扫描记忆前必须调用 `getAutoMemPath()` 的等价逻辑（不能硬编码 `~/.claude/`），因为用户可能通过 settings.json 自定义了记忆目录。

### 2.3 Auto Memory 的启用状态检测

以下任一条件会禁用 Auto Memory：
- 环境变量 `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`
- 环境变量 `CLAUDE_CODE_SIMPLE=1`（bare 模式）
- 远程模式（`CLAUDE_CODE_REMOTE=1`）且未设置 `CLAUDE_CODE_REMOTE_MEMORY_DIR`
- `settings.json` 里 `autoMemoryEnabled: false`

我们的 MCP 工具在启动时应检测记忆目录是否存在，若不存在则提示用户可能已禁用 Auto Memory。

---

## 三、单条记忆的文件格式

### 3.1 标准 Frontmatter 格式

每条记忆文件的结构：

```markdown
---
name: 用户角色描述
description: 用户是数据科学家，关注可观测性
type: user
---

正文内容（具体的记忆详情）

**Why:** 这条记忆的来源原因（用户自己说的，或某次纠正）
**How to apply:** 在什么情况下应用这条记忆
```

**扫描时只读前 30 行**（`FRONTMATTER_MAX_LINES = 30`）即可获取所有结构化字段，不需要读全文。

### 3.2 四种记忆类型（type 字段）

源码定义（`memoryTypes.ts`），完整语义如下：

| 类型 | 默认 Scope | 核心用途 | 典型保存时机 |
|------|-----------|---------|------------|
| `user` | 始终 private | 用户身份、目标、背景知识、偏好 | 了解用户角色/习惯时 |
| `feedback` | 默认 private | AI 行为纠正或确认（避免重复犯同样的错） | 被纠正「别这样」或被确认「对，就这样」时 |
| `project` | 建议 team | 项目进展、决策、背景、截止日期 | 了解谁在做什么、为什么、何时完成时 |
| `reference` | 通常 team | 外部系统指针（URL、Linear、Slack 等） | 了解外部资源位置及用途时 |

**重要**：`type` 字段缺失时 `parseMemoryType()` 返回 `undefined`，系统降级处理（不报错）。历史遗留文件可能没有 `type` 字段。

### 3.3 「不该存的记忆」—— 官方明确列出（可直接用于我们的 prompt）

以下类型的内容**不该出现在记忆里**（来自源码 `WHAT_NOT_TO_SAVE_SECTION`）：

- 代码模式、架构、文件路径、项目结构（可以从代码推断）
- git 历史、近期变更（`git log`/`git blame` 才是权威）
- 调试方案、bug 修复记录（fix 在代码里，commit message 有上下文）
- CLAUDE.md 里已有的内容（重复存储）
- 临时任务状态、当前对话的进行中工作

**设计洞察**：这些规则可以直接复用到我们的「低质量记忆识别」prompt，等于 Anthropic 官方背书的质量标准。

---

## 四、MEMORY.md 索引文件的限制

### 4.1 硬上限（`memdir.ts`）

```
MAX_ENTRYPOINT_LINES = 200 行
MAX_ENTRYPOINT_BYTES = 25,000 字节（约 25KB）
截断规则：先按行截断（自然边界），再按字节截断（防止长行绕过行限制）
```

超出时，系统会追加警告并截断，用户看不到被截断的记忆索引。

**对我们的影响**：
- 这是一个可以检测的健康指标——MEMORY.md 接近或超过上限说明记忆库需要清理
- `memory_audit()` 应该检测 MEMORY.md 的当前行数和大小，并在接近上限时警告

### 4.2 MEMORY.md 的内容格式

MEMORY.md 是纯索引，每条记忆一行，格式为：

```
- [Title](filename.md) — 一行摘要（建议 < 150 字符）
```

不包含 frontmatter，不包含记忆详情。修改记忆时，需要同步更新这里的索引条目。

---

## 五、扫描机制（`memoryScan.ts`）

### 5.1 `scanMemoryFiles()` 的完整行为

```python
# 等价的 Python 伪代码，描述扫描逻辑：

def scan_memory_files(memory_dir):
    entries = readdir(memory_dir, recursive=True)
    md_files = [f for f in entries if f.endswith('.md') and basename(f) != 'MEMORY.md']

    headers = []
    for f in md_files:
        content, mtime = read_file_first_30_lines(f)
        frontmatter = parse_frontmatter(content)
        headers.append({
            'filename': f,           # 相对路径
            'filePath': absolute(f), # 绝对路径
            'mtimeMs': mtime,        # 修改时间（毫秒时间戳）
            'description': frontmatter.get('description'),
            'type': frontmatter.get('type'),  # 可能为 None
        })

    headers.sort(key=lambda x: x['mtimeMs'], reverse=True)  # 最新优先
    return headers[:200]  # 硬上限 200 个文件
```

**关键点**：
- 递归扫描（包含子目录）
- 只读前 30 行（含 frontmatter），省 I/O
- 按 mtime 降序排列（最近修改的优先）
- 最多返回 200 个文件，超出部分静默截断

### 5.2 `formatMemoryManifest()` 的输出格式

扫描结果格式化后的样子（用于 LLM 输入）：

```
- [user] user_role.md (2026-04-03T10:00:00.000Z): 用户是数据科学家，关注可观测性
- [feedback] feedback_testing.md (2026-04-02T08:30:00.000Z): 用户不喜欢 mock 数据库
- project_deadline.md (2026-03-15T12:00:00.000Z)    ← type 为 None 时省略标签
```

---

## 六、新鲜度系统（`memoryAge.ts`）

### 6.1 内置的时效性警告

Claude Code 自己有一套时效性警告，会在每次使用记忆时注入到 system prompt：

```python
def get_freshness_warning(mtime_ms):
    days = (now() - mtime_ms) / 86_400_000
    if days <= 1:
        return ""   # 当天或昨天：不警告
    return f"This memory is {days} days old. " \
           f"Memories are point-in-time observations, not live state — " \
           f"claims about code behavior or file:line citations may be outdated. " \
           f"Verify against current code before asserting as fact."
```

**设计洞察**：Anthropic 自己承认时效性是问题，但他们的解法是「每次使用时提醒」而非「主动清理」。我们做的是他们没做的那一半。

### 6.2 时效性阈值建议

基于 Anthropic 的设计，我们的时效性评分可以参考：

| 年龄 | Claude Code 的处理 | 我们的评分建议 |
|------|-------------------|--------------|
| ≤ 1 天 | 无警告 | 时效性 5/5 |
| 2-7 天 | 轻量警告 | 时效性 4/5 |
| 7-30 天 | 警告 | 时效性 3/5（视内容类型） |
| 30-90 天 | 警告 | 时效性 2/5（project 类型降权更快）|
| > 90 天 | 警告 | 时效性 1/5，强烈建议复查 |

特别注意：`project` 类型记忆衰减最快（项目状态变化快），`user` 类型相对稳定。

---

## 七、记忆提取机制（`extractMemories.ts`）

### 7.1 触发时机

每轮对话结束（模型产生最终响应、无 tool call）后，由 `handleStopHooks()` 触发，fire-and-forget（不阻塞用户看到响应）。

### 7.2 提取流程关键细节

```
每轮对话结束
  → 检查：是子 Agent？→ 跳过（防递归）
  → 检查：功能关闭？→ 跳过
  → 检查：已有提取在跑？→ stash，trailing run
  → 检查：主 Agent 本轮已手动写过记忆？→ 跳过
  → 启动 Forked Agent（沙箱权限，最多 5 轮）
      ├── 只能读任意文件
      └── 只能写 auto memory 目录内的文件
  → 最多等 60 秒（drainPendingExtraction）
```

### 7.3 提取的「不保存」规则（对我们识别低质量记忆有直接价值）

源码 `WHAT_NOT_TO_SAVE_SECTION` 明确列出，即使用户明确要求保存，也不该存：
- PR 列表、活动摘要（提示用户说「哪个是非显而易见的发现」，那才值得记）
- 临时状态（当前会话中的进行中工作）
- 能从代码/git 推断的内容

---

## 八、对 memory-quality-mcp 的直接影响（设计决策依据）

### 8.1 「一条记忆」的定义（问题一的答案）

**不需要 NLP 切分**。每个 `.md` 文件 = 一条记忆，`name` 字段是摘要，`type` 字段可直接用。我们的 `memory_report()` 直接遍历 `.md` 文件即可。

### 8.2 扫描范围（问题二的答案）

**只扫描 Auto Memory 目录**（`~/.claude/projects/<hash>/memory/`），排除 MEMORY.md。

**不扫描**：
- `CLAUDE.md`——用户手写指令，不是 Claude 自动提取的记忆，语义不同
- `session_memory/session_notes.md`——会话内临时摘要，会话结束即过时
- `agent-memory/`——专用 Agent 的独立记忆，与主对话记忆分开

### 8.3 评分调用方式（问题三的答案）

参考 Claude Code 自己的「先扫 frontmatter，再做轻量 LLM 调用」模式：

```
第一步：扫描所有 .md 文件，只读 frontmatter（纯文件 I/O，零 API 成本）
  → 直接识别低质量信号：
    · type=project + mtime > 90天 → 大概率过时，标记待审
    · 无 Why/How to apply 结构 → 可信度信号弱
    · 符合「不该存」规则（代码模式、git 历史等）→ 直接标记

第二步：每批 5-8 条发给 LLM 做四维质量评分（Haiku）
  → 一次 API 调用处理一批（批内有上下文，冲突检测在这里做）
  → 50 条记忆 ≈ 7-10 次 API 调用
```

### 8.4 Cleanup 的安全机制（问题四的答案）

删除一条记忆 = 删除对应 `.md` 文件 + 更新 MEMORY.md 中的索引条目（两步都要做）。

安全策略：
```
执行前：把要删除的文件移入 memory/.trash/<timestamp>/
执行中：删除原文件 → 更新 MEMORY.md 索引
执行后：告知用户「已备份到 .trash，可手动恢复」
```

不能只删文件不更新 MEMORY.md：索引文件有 200 行上限，孤立条目会占用索引空间。

### 8.5 可以直接复用的 Anthropic 官方规则

以下内容可以直接搬进我们的 LLM prompt，不需要自己设计：

1. **四种类型定义**（`memoryTypes.ts` 的 `TYPES_SECTION_INDIVIDUAL`）
2. **「不该存」规则**（`WHAT_NOT_TO_SAVE_SECTION`）——用于识别低质量记忆
3. **时效性警告文本模板**（`memoryFreshnessText()`）——用于告知用户哪些记忆可能过时
4. **「Before recommending from memory」section**（`TRUSTING_RECALL_SECTION`）——可用于我们的「记偏了」检测 prompt

---

## 九、关键常量速查

| 常量 | 值 | 来源文件 | 用途 |
|------|-----|---------|------|
| `MAX_MEMORY_FILES` | 200 | `memoryScan.ts` | 扫描上限，超出静默截断 |
| `FRONTMATTER_MAX_LINES` | 30 | `memoryScan.ts` | 只读前 30 行获取 frontmatter |
| `MAX_ENTRYPOINT_LINES` | 200 | `memdir.ts` | MEMORY.md 行数上限 |
| `MAX_ENTRYPOINT_BYTES` | 25,000 | `memdir.ts` | MEMORY.md 字节上限（≈25KB）|
| `AUTO_MEM_DIRNAME` | `'memory'` | `paths.ts` | 记忆目录名 |
| `AUTO_MEM_ENTRYPOINT_NAME` | `'MEMORY.md'` | `paths.ts` | 索引文件名 |
| Forked Agent 最大轮数 | 5 | `extractMemories.ts` | 提取 Agent 的执行上限 |
| `drainPendingExtraction` 超时 | 60 秒 | `extractMemories.ts` | 等待提取完成的最大时间 |

---

## 十、需要注意的边界情况

### 10.1 记忆目录不存在

用户可能刚安装 Claude Code 还没有任何记忆，或 Auto Memory 被禁用。我们的工具需要优雅处理目录不存在的情况（返回空结果，给出提示，而不是报错退出）。

### 10.2 没有 type 字段的历史文件

`parseMemoryType()` 对未知或缺失的 type 返回 `undefined`，我们的代码也需要处理这种情况（不能假设 type 一定存在）。

### 10.3 MEMORY.md 已截断

如果 MEMORY.md 已经达到 200 行上限，索引是不完整的。但实际的记忆文件仍然完整存在——我们直接扫描 `.md` 文件，不依赖 MEMORY.md 做枚举，所以这个问题对我们不影响扫描完整性，但会影响我们更新索引时的准确性（需要先读全量再写回）。

### 10.4 并发写入竞争

Claude Code 的提取是异步后台运行的。如果用户正在使用 Claude Code 同时我们的工具在运行清理，可能出现同时写 MEMORY.md 的竞争。

处理方式：cleanup 操作建议加文件锁，或在文档中明确提示「清理时请关闭 Claude Code 会话」。

### 10.5 git worktree 的记忆共享

`getAutoMemBase()` 使用 `findCanonicalGitRoot()`，同一 git repo 的所有 worktree 共享同一个记忆目录。这是预期行为，我们扫描时无需区分 worktree。

---

## 附录：相关源文件索引

| 文件 | 关键内容 |
|------|---------|
| `src/memdir/paths.ts` | `getAutoMemPath()`、`isAutoMemoryEnabled()`、路径解析完整逻辑 |
| `src/memdir/memoryTypes.ts` | 四种类型定义、「不该存」规则、frontmatter 格式示例 |
| `src/memdir/memoryScan.ts` | `scanMemoryFiles()`、`formatMemoryManifest()`、扫描逻辑 |
| `src/memdir/memoryAge.ts` | `memoryAgeDays()`、`memoryFreshnessText()`、时效性警告 |
| `src/memdir/memdir.ts` | `truncateEntrypointContent()`、MEMORY.md 截断规则、`buildMemoryLines()` |
| `src/memdir/findRelevantMemories.ts` | `scanMemoryFiles()` + Sonnet selector 完整流程 |
| `src/services/extractMemories/extractMemories.ts` | Auto Memory 提取状态机（Forked Agent 编排）|
| `claude_memory_system_analysis.md` | 系统整体架构分析（人工梳理文档）|
| `claude_auto_memory_extraction_deep_dive.md` | 提取流程深度拆解（人工梳理文档）|
