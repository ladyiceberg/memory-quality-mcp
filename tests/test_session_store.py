"""
test_session_store.py · session_store 模块测试
"""

import time
from pathlib import Path
from unittest.mock import patch

import pytest

from src.session_store import (
    ReportEntry,
    StoredReport,
    load_latest_report,
    load_report_by_id,
    save_report,
    MAX_REPORTS_KEPT,
)


@pytest.fixture(autouse=True)
def use_temp_db(tmp_path):
    """每个测试用独立的临时数据库，避免互相污染。"""
    db_path = tmp_path / "test_session.db"
    with patch("src.session_store.get_db_path", return_value=db_path):
        yield db_path


def make_entry(filename: str, action: str = "delete", project_dir: str = "/tmp/memory") -> ReportEntry:
    return ReportEntry(
        filename=filename,
        file_path=f"{project_dir}/{filename}",
        action=action,
        composite=2.0 if action == "delete" else 4.0,
        reason="测试原因",
        is_not_to_save=False,
        memory_type="user",
        project_dir=project_dir,
    )


class TestSaveAndLoad:
    def test_保存并读取最新report(self):
        entries = [
            make_entry("old_project.md", "delete"),
            make_entry("good_memory.md", "keep"),
        ]
        report_id = save_report(entries)
        assert report_id > 0

        stored = load_latest_report()
        assert stored is not None
        assert stored.report_id == report_id
        assert len(stored.entries) == 2

    def test_to_delete过滤正确(self):
        entries = [
            make_entry("del_a.md", "delete"),
            make_entry("keep_b.md", "keep"),
            make_entry("del_c.md", "delete"),
            make_entry("review_d.md", "review"),
        ]
        save_report(entries)
        stored = load_latest_report()

        assert len(stored.to_delete) == 2
        assert len(stored.to_review) == 1
        assert {e.filename for e in stored.to_delete} == {"del_a.md", "del_c.md"}

    def test_空列表不保存(self):
        result = save_report([])
        assert result == -1
        assert load_latest_report() is None

    def test_按id读取(self):
        id1 = save_report([make_entry("a.md")])
        id2 = save_report([make_entry("b.md"), make_entry("c.md")])

        r1 = load_report_by_id(id1)
        r2 = load_report_by_id(id2)

        assert r1 is not None and len(r1.entries) == 1
        assert r2 is not None and len(r2.entries) == 2

    def test_id不存在返回None(self):
        assert load_report_by_id(99999) is None

    def test_没有记录时返回None(self):
        assert load_latest_report() is None


class TestRetentionPolicy:
    def test_超过上限时旧记录被清理(self):
        # 保存 MAX_REPORTS_KEPT + 2 次
        for i in range(MAX_REPORTS_KEPT + 2):
            save_report([make_entry(f"mem_{i}.md")])

        # 只应保留最近 MAX_REPORTS_KEPT 次
        import sqlite3
        from src.session_store import get_db_path
        conn = sqlite3.connect(str(get_db_path()))
        count = conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
        conn.close()
        assert count == MAX_REPORTS_KEPT

    def test_最新report始终可读(self):
        for i in range(MAX_REPORTS_KEPT + 3):
            last_id = save_report([make_entry(f"mem_{i}.md")])

        latest = load_latest_report()
        assert latest is not None
        assert latest.report_id == last_id


class TestStoredReportHelpers:
    def test_age_display_刚刚(self):
        report = StoredReport(
            report_id=1,
            created_at=time.time() - 10,
            entries=[],
        )
        assert report.age_display() == "刚刚"

    def test_age_display_分钟(self):
        report = StoredReport(
            report_id=1,
            created_at=time.time() - 300,  # 5分钟前
            entries=[],
        )
        assert "分钟前" in report.age_display()

    def test_age_display_小时(self):
        report = StoredReport(
            report_id=1,
            created_at=time.time() - 7200,  # 2小时前
            entries=[],
        )
        assert "小时前" in report.age_display()
