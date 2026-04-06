from __future__ import annotations
from __future__ import annotations
"""
quality_engine.py · 记忆质量评分引擎

两层设计：
  Layer 1 - 规则引擎：零 API 成本的快速初筛，直接从 frontmatter 识别明显低质量信号
  Layer 2 - LLM 评分：对规则引擎未能直接判断的记忆，批量发给配置的 LLM 做四维评分

数据流：
  MemoryFile → rule_engine() → 明显低质量直接标记，其余进入 LLM
             → llm_score_batch() → 四维分 + 冲突检测
             → ScoredMemory（最终结果）
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from src.llm_client import LLMClient, create_client
from src.memory_reader import MemoryFile, MemoryHeader, memory_age_days, read_memory_file
from src.config import load_config, detect_language
from src.prompts import (
    BATCH_SCORING_SCHEMA,
    BATCH_SCORING_USER_TEMPLATE,
    CONFLICT_DETECTION_SCHEMA,
    CONFLICT_DETECTION_SYSTEM,
    CONFLICT_DETECTION_USER_TEMPLATE,
    SINGLE_SCORE_SCHEMA,
    get_batch_scoring_system,
    get_single_score_system,
)


# ── 数据结构 ───────────────────────────────────────────────────────────────────

@dataclass
class DimScores:
    """四维评分。"""
    importance: float       # 重要性 1-5
    recency: float          # 时效性 1-5
    credibility: float      # 可信度 1-5
    accuracy: float         # 准确性 0-5（0 表示无法评估）
    composite: float        # 综合分 0-5


@dataclass
class ConflictPair:
    """一对存在语义冲突的记忆。"""
    filename_a: str
    filename_b: str
    description: str
    severity: str           # high / medium / low


@dataclass
class ScoredMemory:
    """单条记忆的完整评分结果。"""
    header: MemoryHeader
    scores: DimScores
    action: str             # keep / review / delete
    reason: str             # 人类可读的原因
    is_not_to_save: bool    # 是否违反「不该存」规则
    scored_by: str          # "rules" 或 "llm"
    conflicts_with: list[str] = field(default_factory=list)  # 与之冲突的文件名


@dataclass
class EngineResult:
    """quality_engine 的完整输出。"""
    scored_memories: list[ScoredMemory]
    conflicts: list[ConflictPair]
    total: int
    to_delete: int
    to_review: int
    to_keep: int
    llm_calls: int          # 实际消耗的 LLM API 调用次数


# ── 配置加载 ──────────────────────────────────────────────────────────────────

_CONFIG = load_config()

THRESHOLDS = _CONFIG.get("thresholds", {"delete": 2.5, "review": 3.5})
WEIGHTS = _CONFIG.get("weights", {
    "importance": 0.40,
    "recency": 0.25,
    "credibility": 0.15,
    "accuracy": 0.20,
})
STALENESS = _CONFIG.get("staleness_days", {
    "project_type": 90,
    "user_type": 180,
    "general": 90,
})
BATCH_SIZE = _CONFIG.get("batch_size", 6)
MODEL = _CONFIG.get("model", "claude-haiku-4-5")


# ── 规则引擎（Layer 1，零 API 成本）──────────────────────────────────────────

# 「不该存」的关键词模式（来自 Claude Code 官方规则）
_NOT_TO_SAVE_PATTERNS = [
    # 代码模式 / 架构相关
    "代码模式", "架构", "文件路径", "项目结构",
    "code pattern", "architecture", "file path",
    # git 相关
    "git log", "git blame", "git history", "commit",
    "谁改了", "最近改动",
    # 调试 / 修复相关
    "调试方案", "bug fix", "修复方法", "debug",
    # 临时状态
    "待办", "todo", "进行中", "当前任务", "本次会话",
]

# 高度时效性的词（含有这些词的记忆可信度下降）
_STALE_INDICATORS = [
    "今年", "最近", "现在", "目前", "这周", "这个月",
    "this year", "recently", "currently", "right now",
    "正在做", "在做", "即将",
]


def apply_rule_engine(memory_file: MemoryFile) -> Optional[ScoredMemory]:
    """
    规则引擎：对单条记忆做快速初筛。

    返回：
      - ScoredMemory：如果规则能直接得出明确结论（「不该存」或明显过时）
      - None：规则无法判断，需要交给 LLM 处理
    """
    h = memory_file.header
    content_lower = memory_file.raw_content.lower()

    # ── 规则 1：符合「不该存」规则 → 直接标记删除 ──────────────────────────
    for pattern in _NOT_TO_SAVE_PATTERNS:
        if pattern.lower() in content_lower:
            return _make_rule_scored(
                header=h,
                action="delete",
                reason=f"内容属于「不该存的记忆」类型（包含模式：{pattern}）。"
                       f"代码模式、git 历史、临时任务状态等不应存储为记忆。",
                is_not_to_save=True,
                importance=1.0,
                recency=1.0,
                credibility=2.0,
                accuracy=0.0,
            )

    # ── 规则 2：project 类型 + 超过 90 天 → 明确过时 ───────────────────────
    age_days = memory_age_days(h.mtime_ms)
    staleness_threshold = _get_staleness_threshold(h.memory_type)

    if h.memory_type == "project" and age_days > staleness_threshold:
        return _make_rule_scored(
            header=h,
            action="delete",
            reason=f"project 类型记忆已有 {age_days} 天（阈值 {staleness_threshold} 天）。"
                   f"项目状态变化快，这条记忆很可能已经过时。",
            is_not_to_save=False,
            importance=2.0,
            recency=1.0,
            credibility=3.0,
            accuracy=3.0,
        )

    # ── 规则 3：无 Why 且无 How to apply 结构 + 无 frontmatter → 低质量 ────
    # 只对没有任何结构的记忆做判断，有 frontmatter 的交给 LLM
    if (not memory_file.has_why
            and not memory_file.has_how_to_apply
            and not memory_file.header.name
            and not memory_file.header.description):
        body_len = len(memory_file.body.strip())
        if body_len < 50:  # 内容太短且无结构
            return _make_rule_scored(
                header=h,
                action="review",
                reason="记忆内容过短（< 50 字符），且缺乏 name、description 和 Why/How to apply 结构。"
                       "建议人工确认这条记忆是否有保留价值。",
                is_not_to_save=False,
                importance=1.5,
                recency=3.0,
                credibility=1.5,
                accuracy=0.0,
            )

    # 规则无法判断 → 交给 LLM
    return None


def _get_staleness_threshold(memory_type: Optional[str]) -> int:
    """根据记忆类型返回时效性阈值（天）。"""
    if memory_type == "project":
        return STALENESS.get("project_type", 90)
    if memory_type == "user":
        return STALENESS.get("user_type", 180)
    return STALENESS.get("general", 90)


def _compute_composite(
    importance: float,
    recency: float,
    credibility: float,
    accuracy: float,
) -> float:
    """
    计算综合分。
    accuracy=0 表示无法评估，此时将其权重分摊给其余三维（比例不变）。
    """
    w = WEIGHTS
    if accuracy == 0:
        # 重新归一化：把 accuracy 权重按比例分摊
        total_other = w["importance"] + w["recency"] + w["credibility"]
        wi = w["importance"] / total_other
        wr = w["recency"] / total_other
        wc = w["credibility"] / total_other
        return round(importance * wi + recency * wr + credibility * wc, 2)
    return round(
        importance * w["importance"]
        + recency * w["recency"]
        + credibility * w["credibility"]
        + accuracy * w["accuracy"],
        2,
    )


def _action_from_composite(
    composite: float,
    is_not_to_save: bool,
    memory_type: Optional[str] = None,
) -> str:
    """根据综合分和「不该存」标志返回建议操作。

    user 类型保护：综合分低于删除阈值时，user 类型不直接删除，降级为 review。
    原因：user 类型记录用户的个人属性/背景，误删代价远高于误留，保守处理更安全。
    """
    if is_not_to_save:
        return "delete"
    if composite < THRESHOLDS["delete"]:
        if memory_type == "user":
            return "review"
        return "delete"
    if composite < THRESHOLDS["review"]:
        return "review"
    return "keep"


def _make_rule_scored(
    header: MemoryHeader,
    action: str,
    reason: str,
    is_not_to_save: bool,
    importance: float,
    recency: float,
    credibility: float,
    accuracy: float,
) -> ScoredMemory:
    """规则引擎直接产出 ScoredMemory 的工厂函数。"""
    composite = _compute_composite(importance, recency, credibility, accuracy)
    return ScoredMemory(
        header=header,
        scores=DimScores(
            importance=importance,
            recency=recency,
            credibility=credibility,
            accuracy=accuracy,
            composite=composite,
        ),
        action=action,
        reason=reason,
        is_not_to_save=is_not_to_save,
        scored_by="rules",
    )


# ── LLM 评分（Layer 2）────────────────────────────────────────────────────────

def _get_client() -> LLMClient:
    """根据 config.yaml 或环境变量创建 LLM 客户端。"""
    return create_client(_CONFIG)


def _format_memory_for_prompt(memory_file: MemoryFile, index: int) -> str:
    """把单条记忆格式化为 prompt 输入文本。"""
    h = memory_file.header
    age_days = memory_age_days(h.mtime_ms)
    type_tag = h.memory_type or "未知类型"

    lines = [
        f"### 记忆 {index + 1}：{h.filename}",
        f"类型：{type_tag} | 距今：{age_days} 天 | 名称：{h.name or '无'}",
        f"描述：{h.description or '无'}",
        "",
        memory_file.raw_content.strip(),
        "",
    ]
    return "\n".join(lines)


def llm_score_batch(
    memory_files: list[MemoryFile],
    client: Optional[LLMClient] = None,
) -> list[ScoredMemory]:
    """
    批量 LLM 评分。

    每批最多 BATCH_SIZE 条（默认 6），发一次 API 请求。
    50 条记忆 ≈ 8-9 次 API 调用。
    """
    if not memory_files:
        return []

    if client is None:
        client = _get_client()

    all_results: list[ScoredMemory] = []

    # 分批处理
    for batch_start in range(0, len(memory_files), BATCH_SIZE):
        batch = memory_files[batch_start: batch_start + BATCH_SIZE]
        batch_results = _score_single_batch(batch, client)
        all_results.extend(batch_results)

    return all_results


def _score_single_batch(
    batch: list[MemoryFile],
    client: LLMClient,
) -> list[ScoredMemory]:
    """对单批记忆调用一次 LLM，返回评分结果。"""
    memories_text = "\n".join(
        _format_memory_for_prompt(mf, i) for i, mf in enumerate(batch)
    )
    user_msg = BATCH_SCORING_USER_TEMPLATE.format(
        count=len(batch),
        memories_text=memories_text,
    )

    response = client.complete(
        system=get_batch_scoring_system(detect_language()),
        user=user_msg,
        json_schema=BATCH_SCORING_SCHEMA,
        max_tokens=2048,
    )

    # 解析 JSON 结果
    parsed = response.parsed
    if not parsed:
        return [_fallback_scored(mf.header) for mf in batch]

    raw_results: list[dict] = parsed.get("memories", [])

    # 把 LLM 输出映射回 ScoredMemory
    scored = []
    for i, mf in enumerate(batch):
        if i < len(raw_results):
            raw = raw_results[i]
            accuracy = float(raw.get("accuracy", 0))
            importance = float(raw.get("importance", 3))
            recency = float(raw.get("recency", 3))
            credibility = float(raw.get("credibility", 3))
            composite = _compute_composite(importance, recency, credibility, accuracy)
            is_not_to_save = bool(raw.get("is_not_to_save", False))
            action = _action_from_composite(composite, is_not_to_save, mf.header.memory_type)

            scored.append(ScoredMemory(
                header=mf.header,
                scores=DimScores(
                    importance=importance,
                    recency=recency,
                    credibility=credibility,
                    accuracy=accuracy,
                    composite=composite,
                ),
                action=action,
                reason=raw.get("reason", "LLM 评分，无详细原因"),
                is_not_to_save=is_not_to_save,
                scored_by="llm",
            ))
        else:
            scored.append(_fallback_scored(mf.header))

    return scored


def _fallback_scored(header: MemoryHeader) -> ScoredMemory:
    """LLM 调用失败时的降级处理：标记为 review。"""
    return ScoredMemory(
        header=header,
        scores=DimScores(
            importance=3.0,
            recency=3.0,
            credibility=3.0,
            accuracy=3.0,
            composite=3.0,
        ),
        action="review",
        reason="评分失败（LLM 返回异常），建议人工复查。",
        is_not_to_save=False,
        scored_by="llm_fallback",
    )


# ── 冲突检测 ──────────────────────────────────────────────────────────────────

def detect_conflicts(
    memory_files: list[MemoryFile],
    client: Optional[LLMClient] = None,
) -> list[ConflictPair]:
    """
    对一批记忆做冲突检测。
    只检测保留价值较高的记忆（避免对垃圾记忆之间的矛盾浪费 token）。
    """
    if len(memory_files) < 2:
        return []

    if client is None:
        client = _get_client()

    memories_text = "\n".join(
        _format_memory_for_prompt(mf, i) for i, mf in enumerate(memory_files)
    )
    user_msg = CONFLICT_DETECTION_USER_TEMPLATE.format(
        memories_text=memories_text,
    )

    response = client.complete(
        system=CONFLICT_DETECTION_SYSTEM,
        user=user_msg,
        json_schema=CONFLICT_DETECTION_SCHEMA,
        max_tokens=1024,
    )

    parsed = response.parsed
    if not parsed:
        return []

    raw_conflicts: list[dict] = parsed.get("conflicts", [])
    return [
        ConflictPair(
            filename_a=c["filename_a"],
            filename_b=c["filename_b"],
            description=c["description"],
            severity=c.get("severity", "medium"),
        )
        for c in raw_conflicts
    ]


# ── 单条评分（memory_score 工具用）───────────────────────────────────────────

def score_single(
    content: str,
    memory_type: Optional[str] = None,
    client: Optional[LLMClient] = None,
) -> ScoredMemory:
    """
    对单条记忆内容评分（memory_score 工具的底层实现）。
    接受纯文本内容，构造临时 header 后评分。
    """
    from src.memory_reader import MemoryHeader, MemoryFile
    import time

    # 构造临时 header
    tmp_header = MemoryHeader(
        filename="<single_score>",
        file_path=Path("<single_score>"),
        mtime_ms=int(time.time() * 1000),
        name=None,
        description=None,
        memory_type=memory_type,
    )
    tmp_file = MemoryFile(
        header=tmp_header,
        raw_content=content,
        body=content,
        has_why="**Why:**" in content,
        has_how_to_apply="**How to apply:**" in content,
    )

    # 先过规则引擎（不需要 client）
    rule_result = apply_rule_engine(tmp_file)
    if rule_result:
        return rule_result

    # 规则引擎无法判断，走 LLM
    if client is None:
        client = _get_client()

    response = client.complete(
        system=get_single_score_system(detect_language()),
        user=f"请评分以下记忆内容：\n\n{content}",
        json_schema=SINGLE_SCORE_SCHEMA,
        max_tokens=512,
    )

    parsed = response.parsed
    if not parsed:
        return _fallback_scored(tmp_header)

    raw = parsed
    accuracy = float(raw.get("accuracy", 0))
    importance = float(raw.get("importance", 3))
    recency = float(raw.get("recency", 3))
    credibility = float(raw.get("credibility", 3))
    composite = _compute_composite(importance, recency, credibility, accuracy)
    is_not_to_save = bool(raw.get("is_not_to_save", False))
    action = _action_from_composite(composite, is_not_to_save, memory_type)

    return ScoredMemory(
        header=tmp_header,
        scores=DimScores(
            importance=importance,
            recency=recency,
            credibility=credibility,
            accuracy=accuracy,
            composite=composite,
        ),
        action=action,
        reason=raw.get("reason", ""),
        is_not_to_save=is_not_to_save,
        scored_by="llm",
    )


# ── 主入口：完整评分流程 ──────────────────────────────────────────────────────

def run_quality_engine(
    memory_files: list[MemoryFile],
    run_conflict_detection: bool = True,
    client: Optional[LLMClient] = None,
) -> EngineResult:
    """
    完整的质量评分流程入口。

    流程：
      1. 规则引擎快速初筛（零 API 成本）
      2. 剩余记忆批量发给 LLM 评分
      3. 对「保留」和「复查」的记忆做冲突检测
      4. 汇总结果
    """
    if not memory_files:
        return EngineResult(
            scored_memories=[],
            conflicts=[],
            total=0,
            to_delete=0,
            to_review=0,
            to_keep=0,
            llm_calls=0,
        )

    if client is None:
        try:
            client = _get_client()
        except ValueError:
            pass  # 没有配置 API Key，规则引擎结果仍然返回

    # Step 1：规则引擎初筛
    rule_scored: list[ScoredMemory] = []
    needs_llm: list[MemoryFile] = []

    for mf in memory_files:
        result = apply_rule_engine(mf)
        if result is not None:
            rule_scored.append(result)
        else:
            needs_llm.append(mf)

    # Step 2：LLM 批量评分
    llm_scored: list[ScoredMemory] = []
    llm_calls = 0

    if needs_llm and client:
        llm_scored = llm_score_batch(needs_llm, client)
        llm_calls = (len(needs_llm) + BATCH_SIZE - 1) // BATCH_SIZE

    # Step 3：冲突检测（只对非删除的记忆做）
    all_scored = rule_scored + llm_scored
    conflicts: list[ConflictPair] = []

    if run_conflict_detection and client:
        non_delete_files = [
            mf for mf, sc in zip(memory_files, all_scored)
            if sc.action != "delete"
        ]
        if len(non_delete_files) >= 2:
            conflicts = detect_conflicts(non_delete_files, client)
            llm_calls += 1

            # 把冲突信息注入到对应的 ScoredMemory
            conflict_map: dict[str, list[str]] = {}
            for c in conflicts:
                conflict_map.setdefault(c.filename_a, []).append(c.filename_b)
                conflict_map.setdefault(c.filename_b, []).append(c.filename_a)

            for sm in all_scored:
                if sm.header.filename in conflict_map:
                    sm.conflicts_with = conflict_map[sm.header.filename]

    # Step 4：统计汇总
    to_delete = sum(1 for s in all_scored if s.action == "delete")
    to_review = sum(1 for s in all_scored if s.action == "review")
    to_keep = sum(1 for s in all_scored if s.action == "keep")

    return EngineResult(
        scored_memories=all_scored,
        conflicts=conflicts,
        total=len(all_scored),
        to_delete=to_delete,
        to_review=to_review,
        to_keep=to_keep,
        llm_calls=llm_calls,
    )
