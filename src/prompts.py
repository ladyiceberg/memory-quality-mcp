"""
prompts.py · 所有 LLM prompt 模板

设计原则：
  - 所有 prompt 集中在这里，方便迭代和 A/B 测试
  - 直接复用 Claude Code 官方的记忆质量规则（WHAT_NOT_TO_SAVE_SECTION）
  - 使用结构化 JSON 输出，避免解析歧义
"""

# ── 「不该存的记忆」规则（来自 Claude Code 官方源码，直接复用）───────────────
# 源文件：src/memdir/memoryTypes.ts → WHAT_NOT_TO_SAVE_SECTION

WHAT_NOT_TO_SAVE_RULES = """
以下类型的内容不该出现在记忆里（即使用户要求保存也不应该存）：
- 代码模式、架构、文件路径、项目结构（这些可以从代码推断）
- git 历史、近期变更、谁改了什么（git log/blame 才是权威）
- 调试方案、bug 修复记录（修复在代码里，commit message 有上下文）
- CLAUDE.md 里已有的内容（重复存储）
- 临时任务状态、当前会话进行中的工作、短期计划
"""

# ── 四维评分定义 ──────────────────────────────────────────────────────────────

SCORING_DIMENSIONS = """
四个维度的评分标准（每个维度 1-5 分）：

【重要性】这条记忆对未来对话有多大帮助？
  5分：包含明确的用户偏好/决策/背景，未来对话会反复用到
  3分：有一定参考价值，但不是关键信息
  1分：临时状态、随口一说、对未来几乎没有帮助

【时效性】这条信息现在还准确吗？
  5分：描述稳定的偏好或事实，不太可能改变
  3分：可能有变化，但尚未过时
  1分：包含明确时间词（"现在"、"最近"、"今年"）或高度可变的状态

【可信度】这条记忆有没有明确来源？
  5分：用户明确陈述（"我喜欢X"、"我是做Y的"）
  3分：来自对话推断，但推断合理
  1分：纯粹是 AI 的推测，没有任何用户表述支撑

【准确性】（仅在可信度 >= 3 时评估）记录内容是否忠实于来源？
  5分：完整准确地记录了用户的表述，没有过度解读
  3分：基本准确，但有轻微的概括或引申
  1分：AI 将一次性/情绪化表述固化为长期事实，或严重过度解读
  0分：可信度 < 3，无法评估（来源本身不清晰，无从比对）
"""

# ── 主评分 prompt ─────────────────────────────────────────────────────────────

BATCH_SCORING_SYSTEM = f"""你是一个 AI 记忆质量审查专家。你的任务是评估 Claude Code 的自动记忆条目的质量。

{WHAT_NOT_TO_SAVE_RULES}

{SCORING_DIMENSIONS}

【综合分计算】
综合分 = 重要性×0.40 + 时效性×0.25 + 可信度×0.15 + 准确性×0.20
（准确性为 0 时，其权重分摊给其余三维，比例不变：重要性×0.50 + 时效性×0.31 + 可信度×0.19）

【建议操作】
- 综合分 > 3.5 → "keep"（保留）
- 综合分 2.5-3.5 → "review"（建议复查）
- 综合分 < 2.5 → "delete"（建议删除）
- 符合「不该存」规则 → 直接 "delete"，不计算评分

请严格按照 JSON schema 输出，不要输出任何解释文字。
"""

BATCH_SCORING_USER_TEMPLATE = """请对以下 {count} 条记忆逐一评分。

{memories_text}

---
请按 JSON schema 输出每条记忆的评分结果。
memories 数组的顺序和长度必须与输入完全一致。
"""

BATCH_SCORING_SCHEMA = {
    "type": "object",
    "properties": {
        "memories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string"},
                    "importance": {"type": "number", "minimum": 1, "maximum": 5},
                    "recency": {"type": "number", "minimum": 1, "maximum": 5},
                    "credibility": {"type": "number", "minimum": 1, "maximum": 5},
                    "accuracy": {"type": "number", "minimum": 0, "maximum": 5},
                    "composite": {"type": "number", "minimum": 0, "maximum": 5},
                    "action": {"type": "string", "enum": ["keep", "review", "delete"]},
                    "reason": {"type": "string"},
                    "is_not_to_save": {"type": "boolean"},
                },
                "required": [
                    "filename", "importance", "recency",
                    "credibility", "accuracy", "composite", "action", "reason",
                    "is_not_to_save",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["memories"],
    "additionalProperties": False,
}

# ── 冲突检测 prompt ───────────────────────────────────────────────────────────

CONFLICT_DETECTION_SYSTEM = """你是一个 AI 记忆冲突检测专家。你的任务是找出记忆列表中存在语义矛盾的条目对。

冲突的定义：两条记忆描述同一个主题，但内容相互矛盾或不一致。
例如：
  ✅ 冲突：「用户喜欢简洁代码」 vs 「用户要求代码注释详尽」
  ✅ 冲突：「用户早睡习惯」 vs 「用户习惯熬夜写代码」
  ❌ 不是冲突：两条记忆描述不同主题，只是都提到了同一个词

只报告你确定存在矛盾的记忆对，不确定的不要报告。
请严格按照 JSON schema 输出。
"""

CONFLICT_DETECTION_USER_TEMPLATE = """请检查以下记忆列表中是否存在语义冲突：

{memories_text}

---
找出所有存在语义矛盾的记忆对，按 JSON schema 输出。
没有冲突时返回空数组。
"""

CONFLICT_DETECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "conflicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "filename_a": {"type": "string"},
                    "filename_b": {"type": "string"},
                    "description": {"type": "string"},
                    "severity": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                    },
                },
                "required": ["filename_a", "filename_b", "description", "severity"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["conflicts"],
    "additionalProperties": False,
}

# ── 单条评分 prompt（memory_score 工具用）────────────────────────────────────

SINGLE_SCORE_SYSTEM = f"""你是一个 AI 记忆质量审查专家。请对提供的单条记忆内容进行四维质量评分。

{WHAT_NOT_TO_SAVE_RULES}

{SCORING_DIMENSIONS}

请严格按照 JSON schema 输出。
"""

SINGLE_SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "importance": {"type": "number", "minimum": 1, "maximum": 5},
        "recency": {"type": "number", "minimum": 1, "maximum": 5},
        "credibility": {"type": "number", "minimum": 1, "maximum": 5},
        "accuracy": {"type": "number", "minimum": 0, "maximum": 5},
        "composite": {"type": "number", "minimum": 0, "maximum": 5},
        "action": {"type": "string", "enum": ["keep", "review", "delete"]},
        "reason": {"type": "string"},
        "is_not_to_save": {"type": "boolean"},
    },
    "required": [
        "importance", "recency", "credibility", "accuracy",
        "composite", "action", "reason", "is_not_to_save",
    ],
    "additionalProperties": False,
}
