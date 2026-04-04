# Memory Quality MCP · 发布前问题清单

> 创建日期：2026-04-04
> 状态：待逐个解决

---

## 背景修正

**原误判已撤销**：之前担心「大多数用户没有记忆文件」是错误的。
Auto Memory 自 Claude Code v2.1.59 起已对所有用户默认开启。用户只要正常使用 Claude Code，就会在
`~/.claude/projects/<project>/memory/` 下自动积累记忆文件。
社区反馈（2026年2月底发布后）显示，「记忆越积越乱」确实是真实痛点，甚至有大量用户在搜索「怎么关掉 Auto Memory」。
这反而**验证了我们产品的核心假设**。

---

## 问题列表

---

### P0：路径检测 Bug

**严重程度**：🔴 高——会导致插件找不到或找错记忆文件

**问题描述**：

`get_memory_dir()` 使用 `os.getcwd()` 计算记忆路径。但 MCP Server 是一个独立进程，
启动时的 CWD 是 Claude Code 的工作目录，不一定是用户当前正在使用的项目目录。

实际路径计算：
```
记忆路径 = ~/.claude/projects/<sanitize(cwd)>/memory/
```

当 MCP Server 的 CWD 与用户工作项目不一致时，扫描的是错误项目的记忆，或完全找不到记忆。

**复现场景**：
- 用户在 `~/my-project` 下使用 Claude Code
- MCP Server 启动时 CWD 是 `~` 或其他目录
- `get_memory_dir()` 返回 `~/.claude/projects/-Users-maavis/memory/`（错误）
- 而不是 `~/.claude/projects/-Users-maavis-my-project/memory/`（正确）

**解决方向**：

选项 A：扫描所有项目的记忆目录（`~/.claude/projects/*/memory/`）
- 优点：不依赖 CWD，覆盖所有项目
- 缺点：记忆文件可能属于不同项目，混在一起评分语义不清晰

选项 B：`memory_audit/report` 接受可选的 `project_path` 参数，由 Claude 在调用时传入当前项目路径
- 优点：精确，语义清晰
- 缺点：依赖 Claude 正确传参

选项 C（推荐）：默认扫描用户级全局记忆（`~/.claude/projects/` 下所有项目）+ 支持 `project_path` 过滤
- 既能全局体检，又能精确定位单个项目

**待决策**：确定解决方案后实现

---

### P1：config.yaml 在生产环境找不到

**严重程度**：🟡 中——用户无法自定义配置

**问题描述**：

开发时 `config.yaml` 放在项目根目录，`Path(__file__).parent.parent / "config.yaml"` 能找到。
但用户通过 `uvx memory-quality-mcp` 安装后，包被解压到 uv 的缓存目录，
用户不知道 config.yaml 在哪里，也改不了。

**实际影响**：
- API Key 通过环境变量设置（合理，不受影响）
- 评分阈值、权重等参数用户无法调整
- Provider 切换（OpenAI/Kimi/MiniMax）用户无法配置

**解决方向**：

选项 A（推荐）：改为读取用户主目录下的配置文件
```
~/.memory-quality-mcp/config.yaml
```
首次运行时如果不存在，自动生成默认配置并提示用户位置。

选项 B：支持环境变量覆盖关键参数
```bash
MEMORY_QUALITY_PROVIDER=minimax
MEMORY_QUALITY_MODEL=MiniMax-M2.5
MEMORY_QUALITY_DELETE_THRESHOLD=2.5
```

两个选项都做，环境变量优先级高于配置文件。

**待决策**：确认配置文件路径后实现

---

### P2：cleanup 操作依赖会话状态

**严重程度**：🟡 中——操作不稳定，用户体验有缺陷

**问题描述**：

标准清理流程：
```
① memory_report() → Claude 展示要删哪些文件
② 用户说「确认清理」
③ Claude 调用 memory_cleanup(dry_run=False, filenames=[...])
```

第③步要求 Claude 从上下文里正确提取第①步的文件名列表。
在对话轮次多、或文件名复杂时，Claude 可能记错或遗漏。
更根本的问题：MCP 工具是无状态的，无法在工具调用之间保持「上次 report 的结果」。

**解决方向**：

SQLite 已在架构设计里（`data/history.db`），但目前没有实现。

选项 A（推荐）：`memory_report()` 执行后将结果写入本地 SQLite，
`memory_cleanup()` 不传 filenames 时，从 SQLite 读取最近一次 report 的「建议删除」列表。

```
memory_report() → 写入 SQLite（report_id, filename, action, scores）
memory_cleanup(dry_run=False) → 读取最近 report 的 delete 列表，执行清理
```

选项 B：在 memory_cleanup 里重新运行评分（双倍 API 消耗，不推荐）

**待决策**：确认方案后实现

---

### P3：README 为空

**严重程度**：🟡 中——用户无法上手

**问题描述**：

`README.md` 目前是空文件。用户在 mcp.so 或 PyPI 找到插件后，
打开 README 什么都没有，无法安装和使用。

**需要包含的内容**：
- 一句话介绍
- 前提条件（Claude Code v2.1.59+，有 Auto Memory 记忆文件）
- 安装方式（uvx / pip + Claude Code MCP 配置）
- 支持的模型提供商和配置方式（环境变量）
- 四个工具的使用示例
- 典型对话流程截图/示例

**待决策**：确认发布时机后编写

---

### P4：显示名称硬编码「Haiku」

**严重程度**：🟢 低——视觉细节，不影响功能

**问题描述**：

`test_live.py` 和 server.py 的输出里有：
```
正在调用 LLM 评分（Haiku）...
```

但现在实际使用的是 MiniMax M2.5，显示名称没有随配置更新。

**解决方向**：从 `CONFIG` 读取实际 model 名称替换硬编码字符串。

---

### P5：没有 memory_undo 工具

**严重程度**：🟢 低——功能完整性问题，v0.2 可做

**问题描述**：

`memory_cleanup()` 会把文件备份到 `.trash/<timestamp>/`，
但目前没有对应的 `memory_undo()` 工具让用户恢复误删的文件。
用户只能手动去 `.trash` 目录找文件。

**解决方向**：

`memory_undo()` 工具，列出最近的备份批次，支持恢复指定批次或单个文件。

**优先级**：v0.2，发布前不做。

---

### P6：两个工具定位有点尴尬

**严重程度**：🟢 低——产品体验问题

**问题描述**：

- `memory_audit()`：不调 LLM，速度快，但结果粗糙（只有规则引擎），
  用户看完不知道下一步该怎么做，价值感弱
- `memory_report()`：调 LLM，结果详细，但用户会担心 API 费用

潜在问题：用户先跑 audit 看到「发现 N 条可能问题」，然后跑 report 发现结果相差很大，
会觉得 audit 没用。

**解决方向**：
- `memory_audit()` 的输出末尾明确引导：「发现 X 条需要关注，运行 memory_report() 获取详细分析（约消耗 X 次 API 调用）」
- 在 audit 输出里加一行预估：「基于当前 N 条记忆，report 预计调用 LLM X 次」

**优先级**：小改动，发布前可顺手修。

---

## 优先级汇总

| 编号 | 问题 | 严重程度 | 发布前必须修？ |
|------|------|---------|--------------|
| P0 | 路径检测 Bug | 🔴 高 | ✅ 必须 |
| P1 | config.yaml 生产路径 | 🟡 中 | ✅ 必须 |
| P2 | cleanup 状态依赖 | 🟡 中 | ⚠️ 建议修，可简化方案 |
| P3 | README 为空 | 🟡 中 | ✅ 必须 |
| P4 | 显示名称硬编码 | 🟢 低 | ⚪ 顺手改 |
| P5 | 没有 undo 工具 | 🟢 低 | ❌ v0.2 |
| P6 | 两个工具定位尴尬 | 🟢 低 | ⚪ 顺手改 |

---

## 变更记录

| 日期 | 变更 |
|------|------|
| 2026-04-04 | 初始版本，整理发布前全部已知问题 |
