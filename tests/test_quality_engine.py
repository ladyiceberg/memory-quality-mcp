"""
test_quality_engine.py · 质量评分引擎的测试

分两层：
  - TestRuleEngine：纯规则，零 API 成本，直接运行
  - TestLLMScore：mock Anthropic client，验证逻辑正确性
  - TestCompositeScore：数学计算，直接验证
"""

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.memory_reader import MemoryFile, MemoryHeader
from src.quality_engine import (
    ConflictPair,
    DimScores,
    EngineResult,
    ScoredMemory,
    _action_from_composite,
    _compute_composite,
    _fallback_scored,
    apply_rule_engine,
    detect_conflicts,
    llm_score_batch,
    run_quality_engine,
    score_single,
)
from src.llm_client import LLMClient, LLMResponse


# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_header(
    filename="test.md",
    memory_type="user",
    age_days=0,
    name="测试记忆",
    description="测试描述",
) -> MemoryHeader:
    """构造测试用的 MemoryHeader。"""
    mtime_ms = int(time.time() * 1000) - age_days * 86_400_000
    return MemoryHeader(
        filename=filename,
        file_path=Path(filename),
        mtime_ms=mtime_ms,
        name=name,
        description=description,
        memory_type=memory_type,
    )


def make_memory_file(
    content: str,
    filename="test.md",
    memory_type="user",
    age_days=0,
    has_why=True,
    has_how=True,
) -> MemoryFile:
    """构造测试用的 MemoryFile。"""
    header = make_header(filename, memory_type, age_days)
    return MemoryFile(
        header=header,
        raw_content=content,
        body=content,
        has_why=has_why,
        has_how_to_apply=has_how,
    )


def make_mock_client(scored_memories: list[dict]) -> MagicMock:
    """
    构造 mock LLMClient，complete() 返回预设的评分结果。
    scored_memories 是 LLM 返回的 memories 数组。
    """
    mock_client = MagicMock(spec=LLMClient)
    mock_client.complete.return_value = LLMResponse(
        content="",
        parsed={"memories": scored_memories},
    )
    return mock_client


# ── 综合分计算测试 ────────────────────────────────────────────────────────────

class TestCompositeScore:
    def test_标准四维计算(self):
        # 4×0.4 + 4×0.25 + 4×0.15 + 4×0.2 = 4.0
        result = _compute_composite(4.0, 4.0, 4.0, 4.0)
        assert result == pytest.approx(4.0, abs=0.01)

    def test_accuracy为0时权重重新分配(self):
        # accuracy=0，其权重(0.2)分摊给其余三维
        # importance=5, recency=5, credibility=5 → 应该是 5.0
        result = _compute_composite(5.0, 5.0, 5.0, 0.0)
        assert result == pytest.approx(5.0, abs=0.01)

    def test_accuracy为0时低分不被拉高(self):
        # importance=2, recency=2, credibility=2, accuracy=0
        result_with_acc = _compute_composite(2.0, 2.0, 2.0, 2.0)
        result_no_acc = _compute_composite(2.0, 2.0, 2.0, 0.0)
        # 两者都应该是 2.0（因为所有维度相同）
        assert result_with_acc == pytest.approx(2.0, abs=0.01)
        assert result_no_acc == pytest.approx(2.0, abs=0.01)

    def test_混合分数计算(self):
        # 高重要性但低时效性
        result = _compute_composite(5.0, 1.0, 4.0, 4.0)
        # 5×0.4 + 1×0.25 + 4×0.15 + 4×0.2 = 2.0+0.25+0.6+0.8 = 3.65
        assert result == pytest.approx(3.65, abs=0.01)


class TestActionFromComposite:
    def test_高分保留(self):
        assert _action_from_composite(4.0, False) == "keep"
        assert _action_from_composite(3.6, False) == "keep"

    def test_中分复查(self):
        assert _action_from_composite(3.0, False) == "review"
        assert _action_from_composite(2.5, False) == "review"

    def test_低分删除(self):
        assert _action_from_composite(2.0, False) == "delete"
        assert _action_from_composite(1.0, False) == "delete"

    def test_is_not_to_save强制删除(self):
        # 即使综合分高，违反「不该存」规则的也要删
        assert _action_from_composite(4.5, True) == "delete"

    def test_边界值(self):
        # 恰好等于阈值时的行为
        assert _action_from_composite(2.5, False) == "review"   # >= delete 阈值
        assert _action_from_composite(3.5, False) == "keep"     # >= review 阈值


# ── 规则引擎测试 ──────────────────────────────────────────────────────────────

class TestRuleEngine:
    def test_正常高质量记忆返回None(self):
        """正常记忆不应被规则引擎截断，应返回 None 交给 LLM。"""
        mf = make_memory_file(
            content="---\nname: 用户偏好\ndescription: 用户喜欢简洁风格\ntype: user\n---\n"
                    "用户偏好简洁的代码风格。\n\n**Why:** 用户明确表达\n**How to apply:** 写代码时保持简洁",
        )
        result = apply_rule_engine(mf)
        assert result is None

    def test_不该存的内容被标记删除(self):
        """包含「不该存」规则关键词的记忆应被直接标记删除。"""
        mf = make_memory_file(
            content="---\nname: 代码模式\ntype: user\n---\n项目的代码模式是 MVC 架构",
        )
        result = apply_rule_engine(mf)
        assert result is not None
        assert result.action == "delete"
        assert result.is_not_to_save is True
        assert result.scored_by == "rules"

    def test_git相关内容被标记删除(self):
        mf = make_memory_file(
            content="---\nname: 提交记录\ntype: project\n---\n最近的 git log 显示有 3 个 commit",
        )
        result = apply_rule_engine(mf)
        assert result is not None
        assert result.action == "delete"
        assert result.is_not_to_save is True

    def test_project类型超过90天被标记删除(self):
        mf = make_memory_file(
            content="---\nname: 项目截止日期\ntype: project\n---\n"
                    "memory-quality-mcp 目标在 2025-10-01 前发布到 PyPI。\n\n"
                    "**Why:** 验证窗口期有限\n**How to apply:** 控制 scope",
            memory_type="project",
            age_days=100,  # 超过 90 天阈值
        )
        result = apply_rule_engine(mf)
        assert result is not None
        assert result.action == "delete"
        assert result.is_not_to_save is False  # 不是「不该存」，是过时了
        assert result.scored_by == "rules"
        assert "90" in result.reason  # 原因里包含阈值

    def test_project类型未超时返回None(self):
        mf = make_memory_file(
            content="---\nname: 项目状态\ntype: project\n---\n项目目标是 6 周内发布",
            memory_type="project",
            age_days=30,  # 未超过 90 天
        )
        result = apply_rule_engine(mf)
        assert result is None

    def test_user类型超过180天返回None给LLM判断(self):
        """user 类型阈值 180 天，超时也交给 LLM（user 记忆更稳定）。
        注意：当前规则引擎对 user 类型没有直接删除，只对 project 有。"""
        mf = make_memory_file(
            content="---\nname: 用户背景\ntype: user\n---\n用户是数据科学家",
            memory_type="user",
            age_days=200,
        )
        # user 类型即使超时，规则引擎也返回 None，交给 LLM
        result = apply_rule_engine(mf)
        assert result is None

    def test_无结构短内容被标记复查(self):
        mf = make_memory_file(
            content="随便记的一句话",
            has_why=False,
            has_how=False,
        )
        # 设置 header 没有 name 和 description
        mf.header.name = None
        mf.header.description = None
        result = apply_rule_engine(mf)
        assert result is not None
        assert result.action == "review"

    def test_有name的短内容返回None(self):
        """有 name 字段的记忆，即使正文短，也交给 LLM 判断。"""
        mf = make_memory_file(
            content="用户喜欢简洁",
            has_why=False,
            has_how=False,
        )
        # header 有 name
        mf.header.name = "用户偏好"
        result = apply_rule_engine(mf)
        assert result is None


# ── LLM 评分测试（使用 mock）────────────────────────────────────────────────

class TestLLMScoreBatch:
    def test_基本评分流程(self):
        """验证 LLM 返回结果能被正确解析。"""
        mf = make_memory_file(
            content="---\nname: 用户偏好\ntype: user\n---\n用户喜欢简洁代码",
            filename="user_pref.md",
        )

        mock_client = make_mock_client([{
            "filename": "user_pref.md",
            "importance": 4.0,
            "recency": 4.0,
            "credibility": 5.0,
            "accuracy": 4.0,
            "composite": 4.2,
            "action": "keep",
            "reason": "用户明确表达的偏好，对未来对话有持续帮助",
            "is_not_to_save": False,
        }])

        results = llm_score_batch([mf], client=mock_client)

        assert len(results) == 1
        assert results[0].action == "keep"
        assert results[0].scored_by == "llm"
        assert results[0].scores.importance == 4.0
        assert results[0].scores.credibility == 5.0

    def test_综合分由代码重新计算不信任LLM返回值(self):
        """综合分必须由代码计算，不能直接用 LLM 返回的 composite 值。"""
        mf = make_memory_file(
            content="---\nname: 测试\ntype: user\n---\n内容",
            filename="test.md",
        )
        mock_client = make_mock_client([{
            "filename": "test.md",
            "importance": 2.0,
            "recency": 2.0,
            "credibility": 2.0,
            "accuracy": 2.0,
            "composite": 99.0,  # LLM 返回了错误的综合分
            "action": "keep",
            "reason": "测试",
            "is_not_to_save": False,
        }])

        results = llm_score_batch([mf], client=mock_client)
        # 代码重新计算：2×0.4+2×0.25+2×0.15+2×0.2 = 2.0
        assert results[0].scores.composite == pytest.approx(2.0, abs=0.1)
        # 综合分 2.0 < 2.5，应该是 delete
        assert results[0].action == "delete"

    def test_批次分割正确(self):
        """7 条记忆用 batch_size=6 应该分成 2 批。"""
        memories = [
            make_memory_file(
                content=f"---\nname: 记忆{i}\ntype: user\n---\n内容{i}",
                filename=f"mem_{i}.md",
            )
            for i in range(7)
        ]

        mock_client = MagicMock(spec=LLMClient)
        mock_client.complete.side_effect = [
            LLMResponse(content="", parsed={"memories": [
                {"filename": f"mem_{i}.md", "importance": 3.0, "recency": 3.0,
                 "credibility": 3.0, "accuracy": 3.0, "composite": 3.0,
                 "action": "review", "reason": "测试", "is_not_to_save": False}
                for i in range(6)
            ]}),
            LLMResponse(content="", parsed={"memories": [
                {"filename": "mem_6.md", "importance": 4.0, "recency": 4.0,
                 "credibility": 4.0, "accuracy": 4.0, "composite": 4.0,
                 "action": "keep", "reason": "测试", "is_not_to_save": False}
            ]}),
        ]

        results = llm_score_batch(memories, client=mock_client)

        assert len(results) == 7
        assert mock_client.complete.call_count == 2  # 确认调用了 2 次

    def test_LLM无响应时降级处理(self):
        """LLM 返回 None parsed 时，结果应该是 review 而不是报错。"""
        mf = make_memory_file(content="内容", filename="test.md")

        mock_client = MagicMock(spec=LLMClient)
        mock_client.complete.return_value = LLMResponse(content="", parsed=None)

        results = llm_score_batch([mf], client=mock_client)

        assert len(results) == 1
        assert results[0].action == "review"
        assert results[0].scored_by == "llm_fallback"

    def test_is_not_to_save强制删除覆盖LLM建议(self):
        """即使 LLM 建议 keep，is_not_to_save=True 也应强制 delete。"""
        mf = make_memory_file(content="内容", filename="test.md")
        mock_client = make_mock_client([{
            "filename": "test.md",
            "importance": 5.0,
            "recency": 5.0,
            "credibility": 5.0,
            "accuracy": 5.0,
            "composite": 5.0,
            "action": "keep",
            "reason": "很重要",
            "is_not_to_save": True,  # 违反规则，强制删除
        }])

        results = llm_score_batch([mf], client=mock_client)
        assert results[0].action == "delete"


# ── 冲突检测测试 ──────────────────────────────────────────────────────────────

class TestConflictDetection:
    def test_检测到冲突(self):
        memories = [
            make_memory_file("用户喜欢早起", filename="early_bird.md"),
            make_memory_file("用户习惯深夜工作", filename="night_owl.md"),
        ]

        mock_client = MagicMock(spec=LLMClient)
        mock_client.complete.return_value = LLMResponse(
            content="",
            parsed={"conflicts": [{
                "filename_a": "early_bird.md",
                "filename_b": "night_owl.md",
                "description": "早起习惯与深夜工作习惯相互矛盾",
                "severity": "high",
            }]},
        )

        conflicts = detect_conflicts(memories, client=mock_client)

        assert len(conflicts) == 1
        assert conflicts[0].filename_a == "early_bird.md"
        assert conflicts[0].severity == "high"

    def test_无冲突返回空列表(self):
        memories = [
            make_memory_file("用户是数据科学家", filename="role.md"),
            make_memory_file("用户喜欢 Python", filename="lang.md"),
        ]

        mock_client = MagicMock(spec=LLMClient)
        mock_client.complete.return_value = LLMResponse(
            content="",
            parsed={"conflicts": []},
        )

        conflicts = detect_conflicts(memories, client=mock_client)
        assert conflicts == []

    def test_少于2条记忆不调用LLM(self):
        mock_client = MagicMock()
        conflicts = detect_conflicts([make_memory_file("内容")], client=mock_client)
        assert conflicts == []
        mock_client.messages.create.assert_not_called()


# ── 完整流程测试 ──────────────────────────────────────────────────────────────

class TestRunQualityEngine:
    def test_空输入返回空结果(self):
        result = run_quality_engine([], run_conflict_detection=False)
        assert result.total == 0
        assert result.to_delete == 0
        assert result.llm_calls == 0

    def test_规则引擎截断无需LLM(self):
        """「不该存」的记忆被规则引擎处理，不触发 LLM 调用。"""
        mf = make_memory_file(
            content="---\nname: git历史\ntype: project\n---\ngit log 显示最近 3 次提交",
        )
        # 不传 client，依赖规则引擎
        result = run_quality_engine([mf], run_conflict_detection=False, client=None)

        assert result.total == 1
        assert result.to_delete == 1
        assert result.llm_calls == 0

    def test_规则引擎与LLM混合流程(self):
        """部分记忆被规则引擎处理，部分交给 LLM。"""
        rule_mf = make_memory_file(
            content="---\nname: git记录\ntype: project\n---\n代码模式是 MVC",
        )
        llm_mf = make_memory_file(
            content="---\nname: 用户偏好\ntype: user\n---\n用户喜欢简洁代码",
            filename="pref.md",
        )

        mock_client = MagicMock(spec=LLMClient)
        # 第一次 complete：LLM 评分
        # 第二次 complete：冲突检测（只有 pref.md 一条 keep，不会触发冲突检测）
        mock_client.complete.return_value = LLMResponse(
            content="",
            parsed={"memories": [{
                "filename": "pref.md",
                "importance": 4.0,
                "recency": 4.0,
                "credibility": 4.0,
                "accuracy": 4.0,
                "composite": 4.0,
                "action": "keep",
                "reason": "有价值的用户偏好",
                "is_not_to_save": False,
            }]},
        )

        result = run_quality_engine([rule_mf, llm_mf], client=mock_client)

        assert result.total == 2
        assert result.to_delete == 1   # rule_mf 被规则引擎删
        assert result.to_keep == 1     # llm_mf 被 LLM 评为 keep

    def test_统计数量正确(self):
        """验证 to_delete / to_review / to_keep 统计。"""
        memories = []
        expected_actions = []

        # 3 个会被规则引擎删的
        for i in range(3):
            memories.append(make_memory_file(
                content=f"---\nname: 代码{i}\ntype: project\n---\n代码模式{i}",
                filename=f"code_{i}.md",
                age_days=100,
                memory_type="project",
            ))

        result = run_quality_engine(memories, run_conflict_detection=False, client=None)
        assert result.total == 3
        assert result.to_delete == 3
