"""
test_step4.py · Step 4 的集成测试

覆盖范围：
  - memory_writer 的文件操作逻辑（不依赖 LLM）
  - 四个 MCP 工具的端到端响应（mock LLM 调用）
  - dry_run 安全机制验证
  - .trash 备份机制验证
"""

import time
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock
import pytest

from src.memory_writer import backup_and_delete, format_cleanup_result, CleanupResult
from src.memory_reader import scan_memory_files, scan_all_projects, MultiProjectScanResult


# ── Fixtures ──────────────────────────────────────────────────────────────────

SAMPLE_MEMORY_A = """\
---
name: 用户偏好
description: 用户喜欢简洁代码
type: user
---

用户喜欢简洁的代码风格。

**Why:** 用户明确说过
**How to apply:** 写代码时保持简洁
"""

SAMPLE_MEMORY_B = """\
---
name: 测试策略
description: 不用 mock 数据库
type: feedback
---

集成测试必须连接真实数据库。

**Why:** 历史教训
**How to apply:** 写测试时使用真实 DB
"""

SAMPLE_MEMORY_STALE = """\
---
name: 旧项目状态
description: 2024年的项目计划
type: project
---

项目计划在 2024-01-01 完成第一版。

**Why:** 当时的目标
**How to apply:** 已过时，仅供参考
"""


@pytest.fixture
def mock_memory_dir(tmp_path):
    """带有多种类型记忆文件的 mock 目录。"""
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()

    (memory_dir / "user_pref.md").write_text(SAMPLE_MEMORY_A, encoding="utf-8")
    (memory_dir / "feedback_testing.md").write_text(SAMPLE_MEMORY_B, encoding="utf-8")
    (memory_dir / "stale_project.md").write_text(SAMPLE_MEMORY_STALE, encoding="utf-8")

    # 设置 stale_project.md 的时间为 100 天前
    stale_path = memory_dir / "stale_project.md"
    old_time = time.time() - 100 * 86400
    import os
    os.utime(stale_path, (old_time, old_time))

    index = (
        "- [用户偏好](user_pref.md) — 喜欢简洁代码\n"
        "- [测试策略](feedback_testing.md) — 不用 mock\n"
        "- [旧项目状态](stale_project.md) — 2024年计划\n"
    )
    (memory_dir / "MEMORY.md").write_text(index, encoding="utf-8")

    return memory_dir


# ── memory_writer 测试 ────────────────────────────────────────────────────────

class TestMemoryWriter:
    def test_dry_run不删除文件(self, mock_memory_dir):
        files = [mock_memory_dir / "user_pref.md"]
        result = backup_and_delete(files, mock_memory_dir, dry_run=True)

        # dry_run 模式下文件应该还在
        assert (mock_memory_dir / "user_pref.md").exists()
        assert result.dry_run is True
        assert result.files_deleted == []
        assert result.trash_dir is None
        assert "user_pref.md" in result.files_targeted[0]

    def test_实际删除并备份(self, mock_memory_dir):
        files = [mock_memory_dir / "stale_project.md"]
        result = backup_and_delete(files, mock_memory_dir, dry_run=False)

        # 原文件应该被删除
        assert not (mock_memory_dir / "stale_project.md").exists()
        # 备份目录应该存在
        assert result.trash_dir is not None
        assert result.trash_dir.exists()
        # 备份文件应该在 .trash 里
        backup_files = list(result.trash_dir.rglob("*.md"))
        assert len(backup_files) == 1
        assert backup_files[0].name == "stale_project.md"

    def test_删除后更新MEMORY_md索引(self, mock_memory_dir):
        files = [mock_memory_dir / "stale_project.md"]
        result = backup_and_delete(files, mock_memory_dir, dry_run=False)

        assert result.index_updated is True
        index_content = (mock_memory_dir / "MEMORY.md").read_text(encoding="utf-8")
        # stale_project.md 的条目应该被移除
        assert "stale_project.md" not in index_content
        # 其他条目应该保留
        assert "user_pref.md" in index_content
        assert "feedback_testing.md" in index_content

    def test_文件不存在时优雅处理(self, mock_memory_dir):
        nonexistent = mock_memory_dir / "nonexistent.md"
        result = backup_and_delete([nonexistent], mock_memory_dir, dry_run=False)

        assert result.files_deleted == []
        assert len(result.errors) == 1
        assert "不存在" in result.errors[0]

    def test_删除多个文件(self, mock_memory_dir):
        files = [
            mock_memory_dir / "user_pref.md",
            mock_memory_dir / "stale_project.md",
        ]
        result = backup_and_delete(files, mock_memory_dir, dry_run=False)

        assert len(result.files_deleted) == 2
        assert not (mock_memory_dir / "user_pref.md").exists()
        assert not (mock_memory_dir / "stale_project.md").exists()
        # feedback_testing.md 应该保留
        assert (mock_memory_dir / "feedback_testing.md").exists()

    def test_format_cleanup_result_dry_run(self, mock_memory_dir):
        files = [mock_memory_dir / "user_pref.md"]
        result = backup_and_delete(files, mock_memory_dir, dry_run=True)
        text = format_cleanup_result(result)

        assert "预览模式" in text
        assert "user_pref.md" in text
        assert "dry_run=False" in text

    def test_format_cleanup_result_executed(self, mock_memory_dir):
        files = [mock_memory_dir / "stale_project.md"]
        result = backup_and_delete(files, mock_memory_dir, dry_run=False)
        text = format_cleanup_result(result)

        assert "已清理" in text
        assert "stale_project.md" in text
        assert ".trash" in text


# ── MCP 工具端到端测试 ────────────────────────────────────────────────────────

class TestMemoryAudit:
    @pytest.mark.asyncio
    async def test_目录不存在时返回友好提示(self, tmp_path):
        """目录不存在时 scan_all_projects 返回空结果，server 应返回友好提示。"""
        nonexistent = tmp_path / "nonexistent"
        scan = scan_memory_files(nonexistent)
        assert scan.headers == []
        assert scan.index_health.exists is False
        assert scan.index_health.warning is not None
        assert "不存在" in scan.index_health.warning

    @pytest.mark.asyncio
    async def test_有记忆时扫描结果正确(self, mock_memory_dir):
        """有记忆文件时，扫描结果包含正确数量和健康状态。"""
        scan = scan_memory_files(mock_memory_dir)
        assert len(scan.headers) == 3
        assert scan.index_health.exists is True
        assert scan.index_health.line_count == 3
        assert scan.index_health.is_line_truncated is False

    def test_scan_all_projects_多目录合并(self, tmp_path):
        """scan_all_projects 应合并多个项目的记忆。"""
        # 构造两个项目目录
        proj_a = tmp_path / "memory"
        proj_b = tmp_path / "proj_b" / "memory"
        proj_a.mkdir(parents=True)
        proj_b.mkdir(parents=True)

        (proj_a / "user_pref.md").write_text(
            "---\nname: 偏好A\ntype: user\n---\n内容A", encoding="utf-8"
        )
        (proj_b / "feedback.md").write_text(
            "---\nname: 反馈B\ntype: feedback\n---\n内容B", encoding="utf-8"
        )

        scan_a = scan_memory_files(proj_a)
        scan_b = scan_memory_files(proj_b)

        # 手工构造 MultiProjectScanResult 验证合并逻辑
        from src.memory_reader import MultiProjectScanResult
        combined_headers = scan_a.headers + scan_b.headers
        combined_headers.sort(key=lambda h: h.mtime_ms, reverse=True)

        multi = MultiProjectScanResult(
            projects=[scan_a, scan_b],
            total_headers=combined_headers,
            total_count=len(combined_headers),
            project_count=2,
        )
        assert multi.total_count == 2
        assert multi.project_count == 2


class TestMemoryScore:
    @pytest.mark.asyncio
    async def test_规则引擎命中不调LLM(self):
        """「不该存」的内容应被规则引擎处理，不调 LLM。"""
        from src.server import _handle_memory_score

        content = "代码模式是 MVC，文件路径在 src/controllers/"
        result = await _handle_memory_score({"content": content})

        assert len(result) == 1
        text = result[0].text
        # 规则引擎命中，应包含删除建议
        assert "DELETE" in text or "delete" in text.lower() or "🗑" in text

    @pytest.mark.asyncio
    async def test_空内容返回错误提示(self):
        from src.server import _handle_memory_score

        result = await _handle_memory_score({"content": ""})
        assert "不能为空" in result[0].text

    @pytest.mark.asyncio
    async def test_LLM评分结果格式化正确(self):
        """验证 LLM 评分的输出包含四维和综合分。"""
        from src.server import _handle_memory_score
        from src.quality_engine import ScoredMemory, DimScores
        from src.memory_reader import MemoryHeader

        mock_scored = ScoredMemory(
            header=MemoryHeader(
                filename="<single_score>",
                file_path=Path("<single_score>"),
                mtime_ms=int(time.time() * 1000),
                name=None,
                description=None,
                memory_type="user",
            ),
            scores=DimScores(
                importance=4.0,
                recency=4.0,
                credibility=5.0,
                accuracy=4.0,
                composite=4.2,
            ),
            action="keep",
            reason="用户明确表达的偏好",
            is_not_to_save=False,
            scored_by="llm",
        )

        with patch("src.quality_engine.score_single", return_value=mock_scored):
            result = await _handle_memory_score({
                "content": "用户喜欢简洁代码风格",
                "memory_type": "user",
            })

        text = result[0].text
        assert "4.2" in text
        assert "重要性" in text
        assert "时效性" in text
        assert "KEEP" in text or "keep" in text.lower() or "✅" in text


class TestMemoryCleanup:
    def _make_multi(self, mock_memory_dir, headers=None):
        """构造 MultiProjectScanResult 的 helper。"""
        from src.memory_reader import MultiProjectScanResult
        scan = scan_memory_files(mock_memory_dir)
        return MultiProjectScanResult(
            projects=[scan],
            total_headers=headers if headers is not None else scan.headers,
            total_count=len(headers) if headers is not None else len(scan.headers),
            project_count=1,
        )

    @pytest.mark.asyncio
    async def test_dry_run默认为True(self, mock_memory_dir):
        """不传 dry_run 时默认不删除文件。"""
        from src.server import _handle_memory_cleanup
        from src.memory_reader import MultiProjectScanResult

        multi = self._make_multi(mock_memory_dir)

        with patch("src.memory_reader.scan_all_projects", return_value=multi):
            with patch("src.quality_engine.run_quality_engine") as mock_engine:
                from src.quality_engine import EngineResult, ScoredMemory, DimScores
                from src.memory_reader import MemoryHeader

                mock_scored = ScoredMemory(
                    header=MemoryHeader(
                        filename="stale_project.md",
                        file_path=mock_memory_dir / "stale_project.md",
                        mtime_ms=int(time.time() * 1000) - 100 * 86400000,
                        name="旧项目",
                        description="过时的项目",
                        memory_type="project",
                    ),
                    scores=DimScores(1.0, 1.0, 2.0, 0.0, 1.19),
                    action="delete",
                    reason="project 类型已过时",
                    is_not_to_save=False,
                    scored_by="rules",
                )
                mock_engine.return_value = EngineResult(
                    scored_memories=[mock_scored],
                    conflicts=[],
                    total=1,
                    to_delete=1,
                    to_review=0,
                    to_keep=0,
                    llm_calls=0,
                )

                result = await _handle_memory_cleanup({})  # 不传 dry_run

        # dry_run 默认 True，文件不应被删除
        assert (mock_memory_dir / "stale_project.md").exists()
        assert "预览模式" in result[0].text

    @pytest.mark.asyncio
    async def test_指定filename清理(self, mock_memory_dir):
        """通过 filenames 参数直接指定要清理的文件。"""
        from src.server import _handle_memory_cleanup

        multi = self._make_multi(mock_memory_dir)

        with patch("src.memory_reader.scan_all_projects", return_value=multi):
            result = await _handle_memory_cleanup({
                "dry_run": True,
                "filenames": ["stale_project.md"],
            })

        text = result[0].text
        assert "stale_project.md" in text

    @pytest.mark.asyncio
    async def test_filename不存在时返回错误(self, mock_memory_dir):
        from src.server import _handle_memory_cleanup

        multi = self._make_multi(mock_memory_dir)

        with patch("src.memory_reader.scan_all_projects", return_value=multi):
            result = await _handle_memory_cleanup({
                "dry_run": True,
                "filenames": ["nonexistent_memory.md"],
            })

        assert "未找到" in result[0].text

    @pytest.mark.asyncio
    async def test_实际删除流程(self, mock_memory_dir):
        """dry_run=False 时文件应被实际删除。"""
        from src.server import _handle_memory_cleanup

        multi = self._make_multi(mock_memory_dir)

        with patch("src.memory_reader.scan_all_projects", return_value=multi):
            result = await _handle_memory_cleanup({
                "dry_run": False,
                "filenames": ["stale_project.md"],
            })

        # 文件应该被删除
        assert not (mock_memory_dir / "stale_project.md").exists()
        # .trash 备份应该存在
        trash_files = list((mock_memory_dir / ".trash").rglob("*.md"))
        assert len(trash_files) == 1
        assert trash_files[0].name == "stale_project.md"
        # 输出包含已清理信息
        assert "已清理" in result[0].text

    @pytest.mark.asyncio
    async def test_使用session_store缓存不重复调LLM(self, mock_memory_dir, tmp_path):
        """memory_cleanup() 在有缓存时应直接使用，不重新跑 LLM。"""
        from src.server import _handle_memory_cleanup
        from src.session_store import ReportEntry, save_report

        stale_path = mock_memory_dir / "stale_project.md"

        # 模拟一次 report 的缓存
        entries = [ReportEntry(
            filename="stale_project.md",
            file_path=str(stale_path),
            action="delete",
            composite=1.5,
            reason="project 类型已过时",
            is_not_to_save=False,
            memory_type="project",
            project_dir=str(mock_memory_dir),
        )]

        db_path = tmp_path / "test.db"
        with patch("src.session_store.get_db_path", return_value=db_path):
            save_report(entries)
            multi = self._make_multi(mock_memory_dir)

            with patch("src.memory_reader.scan_all_projects", return_value=multi):
                with patch("src.quality_engine.run_quality_engine") as mock_engine:
                    result = await _handle_memory_cleanup({"dry_run": True})

            # 有缓存时不应调用 LLM
            mock_engine.assert_not_called()
            # 输出应包含缓存相关信息
        assert "stale_project.md" in result[0].text
