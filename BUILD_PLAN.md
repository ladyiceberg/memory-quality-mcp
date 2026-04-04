# Memory Quality MCP · 构建计划

> 目标：跑通 Step 1-4（脚手架 → 文件读取 → 评分引擎 → 四个 MCP 工具）
> Step 5（Benchmark）之后单独启动
> 最后更新：2026-04-04

---

## 依赖关系图

```
Step 1：脚手架
    └── Step 2：记忆文件读取层
            ├── Step 3：质量评分引擎
            │       └── Step 4a：memory_score()      ← 最简单，先做
            │       └── Step 4b：memory_audit()
            │       └── Step 4c：memory_report()
            │       └── Step 4d：memory_cleanup()    ← 最后做，涉及写操作
            └── Step 6：集成测试 + 打包（Step 4 完成后）
```

**串行依赖**：1 → 2 → 3 → 4a → 4b → 4c → 4d
**没有可并行的部分**：每一步都依赖上一步的输出。

---

## Step 1：项目脚手架

**目标**：`uvx memory-quality-mcp` 能启动，Claude Code 能识别到这个 MCP server。

**产出文件**：
```
memory-quality-mcp/
├── pyproject.toml       ← 依赖声明（mcp SDK、anthropic、pyyaml）
├── config.yaml          ← 评分阈值、API key 占位
└── src/
    ├── __init__.py
    └── server.py        ← MCP server 入口，注册工具名（逻辑先留空）
```

**验收标准**：
- `uv run python -m src.server` 能启动不报错
- Claude Code 的 MCP 配置里加入后，能看到 4 个工具名

---

## Step 2：记忆文件读取层

**目标**：能正确扫描本机真实记忆目录，返回结构化数据。

**产出文件**：
```
src/memory_reader.py
```

**实现内容**：
- `get_memory_dir()` ——解析实际路径，优先级：
  1. `CLAUDE_CODE_REMOTE_MEMORY_DIR` 环境变量
  2. `~/.claude/settings.json` 的 `autoMemoryDirectory` 字段
  3. 默认：`~/.claude/projects/<sanitized-git-root>/memory/`
- `scan_memory_files()` ——遍历目录，只读前 30 行（frontmatter），返回 header 列表
  - 排除 MEMORY.md
  - 按 mtime 降序排列
  - 上限 200 个文件
- `read_memory_file(path)` ——读取单条记忆的完整内容
- `parse_frontmatter(content)` ——解析 name / description / type / mtime
- `check_memory_index_health()` ——检测 MEMORY.md 是否接近 200 行 / 25KB 上限

**边界情况**：
- 目录不存在 → 返回空列表 + 提示，不报错
- type 字段缺失 → 降级处理（type=None），不崩溃
- frontmatter 格式损坏 → 跳过该文件，记录 warning

**验收标准**：
- 对本机真实记忆目录跑一遍，打印所有记忆的 name / type / mtime，结果正确

---

## Step 3：质量评分引擎

**目标**：对一批记忆做四维质量评分，输出结构化结果。

**产出文件**：
```
src/quality_engine.py
src/prompts.py          ← 所有 LLM prompt 模板，集中管理
```

**实现顺序**（先规则，后 LLM）：

### 3a. 规则引擎（零 API 成本的初筛）

直接从 frontmatter 识别明显信号，不调 LLM：

| 规则 | 信号 | 处理方式 |
|------|------|---------|
| `type=project` + mtime > 90天 | 时效性极低 | 时效性预打分 1/5，标记待 LLM 确认 |
| 无 `**Why:**` 结构 | 可信度存疑 | 可信度预打分降权 |
| 内容符合「不该存」规则 | 低质量 | 直接标记为「建议删除」，跳过 LLM |
| `type=user` + mtime > 180天 | 可能过时 | 时效性预打分 2/5 |

「不该存」规则（来自 Anthropic 官方 `WHAT_NOT_TO_SAVE_SECTION`）：
- 描述代码模式 / 架构 / 文件路径
- 描述 git 历史 / 近期变更
- 临时任务状态、当前会话进行中的工作
- CLAUDE.md 里已有的内容

### 3b. LLM 评分（Haiku，批量 5-8 条）

对规则引擎未能直接判断的记忆，发给 LLM 做四维评分：

```
输入：一批记忆（5-8 条），每条包含完整内容
输出：每条的四维评分 + 建议操作 + 原因
```

**四维定义**（详见 DESIGN.md 第五节）：
- 重要性（40%）：对未来对话的帮助程度
- 时效性（25%）：信息是否仍然准确
- 可信度（15%）：是否有明确来源
- 准确性（20%）：记录是否忠实于来源（可信度 < 3 时标为「无法评估」）

**综合分**：
```
< 2.5  → 建议删除
2.5-3.5 → 建议复查
> 3.5  → 保留
```

### 3c. 冲突检测

在同批次内，检测两两语义矛盾：
```
例：「用户喜欢简洁代码」vs「用户要求注释详尽」→ 潜在冲突
```

**验收标准**：
- 对 10 条样本记忆跑评分，结果符合直觉
- 批量调用：50 条记忆 ≤ 10 次 API 调用

---

## Step 4：四个 MCP 工具

**目标**：在 server.py 里实现四个工具，能跑完整对话流程。

**实现顺序**（按依赖和复杂度）：

### 4a. `memory_score(content: str)`
- 最简单，单条评分
- 直接调用 quality_engine 的 LLM 评分
- 用于调试和验证评分模型

### 4b. `memory_audit()`
- 调用 scan_memory_files() + 规则引擎
- 返回健康摘要：总数、各类异常数
- 检测 MEMORY.md 是否接近上限
- **不调 LLM**（audit 是快速体检，不做深度分析）

### 4c. `memory_report(verbose=False)`
- 调用完整评分流程（规则引擎 + LLM）
- 返回详细清单，每条附四维评分 + 建议操作 + 原因
- verbose=False 时只返回「建议删除」和「建议复查」的条目

### 4d. `memory_cleanup(dry_run=True)`
- **最后做，涉及文件写操作**
- 执行顺序：
  1. 读取要清理的记忆列表（来自 memory_report 的结果）
  2. 备份：把待删文件移入 `memory/.trash/<timestamp>/`
  3. 删除原文件
  4. 同步更新 MEMORY.md 索引（删除对应条目）
  5. 返回操作摘要
- `dry_run=True` 时只预览，不执行任何写操作
- 永远不静默删除（即使 dry_run=False 也要先确认）

**验收标准**：
- 跑完整对话流程：`audit` → `report` → 确认 → `cleanup(dry_run=True)` → 确认 → `cleanup(dry_run=False)`
- dry_run 模式下文件系统零变化
- .trash 备份正常工作，MEMORY.md 索引同步更新

---

## Step 5（之后单独启动）：Benchmark 小数据集

```
benchmark/
  annotation_guide.md    ← 四维评分标注规范
  dataset.json           ← 100 条标注样本
  eval.py                ← 评估脚本
```

需要 Mavis 参与：从真实 Chatbot 数据抽取样本，人工标注。

---

## 文件结构（完成后）

```
memory-quality-mcp/
├── DESIGN.md                    ← 产品设计方案
├── BUILD_PLAN.md                ← 本文件：构建计划
├── CLAUDE_CODE_INTERNALS.md     ← Claude Code 源码分析
├── README.md                    ← 用户安装文档（Step 4 完成后写）
├── pyproject.toml
├── config.yaml
├── src/
│   ├── __init__.py
│   ├── server.py                ← MCP server 主入口
│   ├── memory_reader.py         ← 文件读取层
│   ├── quality_engine.py        ← 四维评分引擎
│   └── prompts.py               ← LLM prompt 模板
├── benchmark/
│   ├── annotation_guide.md
│   ├── dataset.json
│   └── eval.py
└── tests/
    └── test_quality.py
```
