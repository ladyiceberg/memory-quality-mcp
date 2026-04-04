# Benchmark 数据集构建指南

> 目的：说明如何构建和扩充 memory-quality-mcp 的评分校准数据集
> 当前状态：11 条初始样本（自动生成），待人工标注和真实数据扩充

---

## 一、数据集定位

这个 Benchmark 有两个用途：

**内部用途（当前阶段）**：衡量评分引擎的准确率——模型给出的分数与人工标注分数的相关性是核心指标，目标 > 0.7。

**外部定位（后续）**：这是目前开源社区里唯一专注「记忆质量判断」的标注数据集（现有 Benchmark 全部测的是召回准确率，不是质量判断）。发布后有先发优势，可以建立标准制定者地位。

---

## 二、数据集结构

### dataset.json 字段说明

```json
{
  "id": "唯一标识符",
  "source": "generated_from_claude_code_prompt | from_real_data | manual",
  "scenario_id": "对应的场景名（自动生成时有）",
  "quality_label": "高质量 | 过时 | 低质量（临时状态）| 冲突 | 记偏了",
  "expected_action": "keep | review | delete",
  "memory_type": "user | feedback | project | reference",
  "age_days": 0,
  "content": "完整的记忆文件内容（frontmatter + 正文）",
  "human_scores": {
    "importance": null,    // 1-5，待标注
    "recency": null,       // 1-5，待标注
    "credibility": null,   // 1-5，待标注
    "accuracy": null       // 0-5，待标注（0=无法评估）
  },
  "notes": "标注备注"
}
```

### 当前数据分布

| 质量类型 | 数量 | 预期动作 |
|---------|------|---------|
| 高质量（稳定偏好/背景）| 5 条 | keep |
| 过时（project 类型超时）| 3 条 | delete |
| 记偏了（过度解读）| 1 条 | review |
| 冲突（相反偏好）| 1 条 | review |
| 日常生活场景 | 2 条 | keep/delete 各 1 |

---

## 三、数据来源

### 来源 A：自动生成（已有）

**工具**：`scripts/generate_memories.py`

**核心设计**：复用 Claude Code 官方的记忆提取 Prompt（`buildExtractAutoOnlyPrompt()`），让 LLM 以「记忆提取 Agent」身份运行，输出格式与真实 Auto Memory 完全一致。

```bash
# 使用内置场景（12 个覆盖各质量类型的对话）
python3 scripts/generate_memories.py --benchmark

# 传入自定义对话数据
python3 scripts/generate_memories.py \
  --conversations /path/to/chats.json \
  --benchmark

# 预览不调 LLM
python3 scripts/generate_memories.py --dry-run
```

**自定义对话数据格式**（`--conversations` 参数）：

```json
[
  {
    "scenario_id": "my_scenario_001",
    "quality_label": "高质量",
    "expected_action": "keep",
    "age_days": 5,
    "messages": [
      {"role": "user", "content": "..."},
      {"role": "assistant", "content": "..."}
    ]
  }
]
```

**适用场景**：
- Auto Memory 功能未开放，无法获取真实记忆文件时
- 需要覆盖特定质量类型，补充数据集的薄弱环节
- 日常生活场景对话也适用，不限于工程场景

**注意**：自动生成的数据需要人工审核 `expected_action` 是否合理，再填写 `human_scores`。

---

### 来源 B：真实用户 Chatbot 数据（待处理）

**背景**：已有一批来自真实 Chatbot 产品的脱敏用户对话数据，是与来源 A 相比最大的差异化资产——合成数据造不出来的细腻模式（随口一说、被误解的偏好、时效性失效的旧记忆）在这里天然存在。

**处理流程**（数据准备好后执行）：

```
步骤一：抽取样本
  从真实对话里找两类信号：
  - 路径 B（正例）：用户明确确认的偏好（「对，就这样」「记住这个」）
  - 路径 C（负例）：随口一说的临时状态，不应被固化为长期记忆

步骤二：格式化为对话片段
  每个样本包装成 generate_memories.py 支持的 JSON 格式
  {scenario_id, quality_label, expected_action, age_days, messages}

步骤三：运行提取脚本
  python3 scripts/generate_memories.py \
    --conversations /path/to/real_data_samples.json \
    --benchmark

步骤四：人工审核 + 标注
  检查生成的记忆是否符合预期
  填写 human_scores 四维评分
```

**预期产出**：补充 30-50 条真实数据条目，重点覆盖「随口一说被固化」和「单次表述被过度解读」这两类 AI 记录错误。

---

### 来源 C：手工编写（边界情况）

对于规则引擎的边界情况，直接手写极端样本：

```json
{
  "id": "manual_extreme_001",
  "source": "manual",
  "quality_label": "规则引擎边界",
  "expected_action": "delete",
  "memory_type": "user",
  "content": "---\nname: 测试\ntype: user\n---\n包含 architecture 词语但不是关于代码架构的记忆",
  "human_scores": {"importance": 4, "recency": 4, "credibility": 5, "accuracy": 5},
  "notes": "验证规则引擎是否误判含 architecture 词语的非代码记忆"
}
```

---

## 四、人工标注规范

拿到数据集条目后，填写 `human_scores` 四个维度（1-5 分）：

| 维度 | 1 分 | 3 分 | 5 分 |
|------|------|------|------|
| **重要性** | 临时状态，未来几乎用不到 | 有一定参考价值 | 稳定偏好/事实，未来对话会反复引用 |
| **时效性** | 明确时间词（「今年」「最近」）或高度可变状态 | 可能有变化，但尚未过时 | 描述稳定偏好或事实，不太可能改变 |
| **可信度** | 纯 AI 推测，无用户表述支撑 | 来自对话推断，推断合理 | 用户明确陈述（「我喜欢X」「我是做Y的」）|
| **准确性** | AI 将一次性表述固化为长期习惯，严重过度解读 | 基本准确，有轻微概括 | 完整准确地记录了用户表述，无过度解读 |

**准确性为 0 的情况**：可信度 < 3（来源本身不清晰），无从比对，标 0 表示「无法评估」。

**标注原则**：
- 两个标注人独立打分，分歧 > 1 分的条目进入复议
- 重点标注「边界样本」（综合分在 2.3-2.7 之间的），这里是模型最容易出错的地方

---

## 五、已知问题

### 规则引擎 false positive（待优化）

测试中发现 `user_background.md` 被误判为「违规：包含 architecture」，原因是记忆内容中「model interpretability」的上下文触发了「architecture」关键词匹配，但这条记忆实际上是合理的用户背景信息。

根因：规则词表用的是子串匹配，过宽。

修复方向：改为完整词边界匹配（`\barchitecture\b`）+ 增加上下文判断（是否与代码/软件相关）。

暂时记录在此，等 Benchmark 数据足够后用数据驱动地调整规则。

---

## 六、目标规模和时间线

| 阶段 | 目标条数 | 来源 | 时间 |
|------|---------|------|------|
| 当前（v0.1）| 11 条 | 自动生成 | 已完成 |
| 短期 | 30-50 条 | 真实 Chatbot 数据 | 数据准备好后 |
| 发布前 | 100 条 | 三种来源混合 + 人工标注 | 发布时 |

100 条标注完成后，运行 `eval.py`（待写）验证模型分与人工分的相关性，目标 > 0.7。

---

## 七、相关文件

| 文件 | 说明 |
|------|------|
| `benchmark/dataset.json` | 数据集本体 |
| `scripts/generate_memories.py` | 自动生成脚本 |
| `benchmark/eval.py` | 评估脚本（待写）|
| `src/quality_engine.py` | 评分引擎实现 |
| `CLAUDE_CODE_INTERNALS.md` | Claude Code 记忆格式参考 |
