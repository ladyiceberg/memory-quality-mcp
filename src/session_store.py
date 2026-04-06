from __future__ import annotations
"""
session_store.py · 本地会话状态持久化

解决 P2：memory_report() 和 memory_cleanup() 之间的状态依赖问题。

设计：
  - memory_report() 执行后把评分结果写入 SQLite
  - memory_cleanup() 不传 filenames 时，直接读最近一次 report 的「建议删除」列表
  - 不依赖 Claude 在对话上下文里记住文件名，操作更可靠

存储位置：~/.memory-quality-mcp/session.db
保留策略：只保留最近 10 次 report，自动清理旧记录
"""

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# ── 常量 ──────────────────────────────────────────────────────────────────────

MAX_REPORTS_KEPT = 10  # 最多保留最近 N 次 report


def get_db_path() -> Path:
    """数据库文件路径：~/.memory-quality-mcp/session.db"""
    db_dir = Path.home() / ".memory-quality-mcp"
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / "session.db"


# ── 数据结构 ───────────────────────────────────────────────────────────────────

@dataclass
class ReportEntry:
    """单条记忆的评分结果，持久化到 SQLite。"""
    filename: str
    file_path: str
    action: str          # keep / review / delete
    composite: float
    reason: str
    is_not_to_save: bool
    memory_type: Optional[str]
    project_dir: str     # 所属 memory 目录的绝对路径


@dataclass
class StoredReport:
    """一次完整的 report 结果。"""
    report_id: int
    created_at: float    # Unix 时间戳
    entries: list[ReportEntry]

    @property
    def to_delete(self) -> list[ReportEntry]:
        return [e for e in self.entries if e.action == "delete"]

    @property
    def to_review(self) -> list[ReportEntry]:
        return [e for e in self.entries if e.action == "review"]

    def age_seconds(self) -> float:
        return time.time() - self.created_at

    def age_display(self) -> str:
        from src.config import detect_language
        secs = self.age_seconds()
        lang = detect_language()
        if lang == "zh":
            if secs < 60:    return "刚刚"
            if secs < 3600:  return f"{int(secs / 60)} 分钟前"
            if secs < 86400: return f"{int(secs / 3600)} 小时前"
            return f"{int(secs / 86400)} 天前"
        else:
            if secs < 60:    return "just now"
            if secs < 3600:  return f"{int(secs / 60)}m ago"
            if secs < 86400: return f"{int(secs / 3600)}h ago"
            return f"{int(secs / 86400)}d ago"


# ── 数据库初始化 ───────────────────────────────────────────────────────────────

def _get_connection() -> sqlite3.Connection:
    """获取数据库连接，自动创建表结构。"""
    conn = sqlite3.connect(str(get_db_path()))
    conn.row_factory = sqlite3.Row
    _ensure_tables(conn)
    return conn


def _ensure_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS reports (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS report_entries (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id     INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
            filename      TEXT NOT NULL,
            file_path     TEXT NOT NULL,
            action        TEXT NOT NULL,
            composite     REAL NOT NULL,
            reason        TEXT NOT NULL,
            is_not_to_save INTEGER NOT NULL DEFAULT 0,
            memory_type   TEXT,
            project_dir   TEXT NOT NULL
        );
    """)
    conn.commit()


# ── 写入 ──────────────────────────────────────────────────────────────────────

def save_report(entries: list[ReportEntry]) -> int:
    """
    保存一次 report 结果，返回 report_id。
    自动清理超过 MAX_REPORTS_KEPT 的旧记录。
    """
    if not entries:
        return -1

    conn = _get_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO reports (created_at) VALUES (?)",
            (time.time(),),
        )
        report_id = cursor.lastrowid

        conn.executemany(
            """INSERT INTO report_entries
               (report_id, filename, file_path, action, composite, reason,
                is_not_to_save, memory_type, project_dir)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    report_id,
                    e.filename,
                    e.file_path,
                    e.action,
                    e.composite,
                    e.reason,
                    1 if e.is_not_to_save else 0,
                    e.memory_type,
                    e.project_dir,
                )
                for e in entries
            ],
        )
        conn.commit()

        # 清理旧记录（保留最近 N 次）
        conn.execute(
            """DELETE FROM reports WHERE id NOT IN (
                SELECT id FROM reports ORDER BY created_at DESC LIMIT ?
            )""",
            (MAX_REPORTS_KEPT,),
        )
        conn.commit()

        return report_id
    finally:
        conn.close()


# ── 读取 ──────────────────────────────────────────────────────────────────────

def load_latest_report() -> Optional[StoredReport]:
    """读取最近一次 report，如果没有记录则返回 None。"""
    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT id, created_at FROM reports ORDER BY created_at DESC LIMIT 1"
        ).fetchone()

        if not row:
            return None

        report_id = row["id"]
        created_at = row["created_at"]

        entry_rows = conn.execute(
            """SELECT filename, file_path, action, composite, reason,
                      is_not_to_save, memory_type, project_dir
               FROM report_entries
               WHERE report_id = ?""",
            (report_id,),
        ).fetchall()

        entries = [
            ReportEntry(
                filename=r["filename"],
                file_path=r["file_path"],
                action=r["action"],
                composite=r["composite"],
                reason=r["reason"],
                is_not_to_save=bool(r["is_not_to_save"]),
                memory_type=r["memory_type"],
                project_dir=r["project_dir"],
            )
            for r in entry_rows
        ]

        return StoredReport(
            report_id=report_id,
            created_at=created_at,
            entries=entries,
        )
    finally:
        conn.close()


def load_report_by_id(report_id: int) -> Optional[StoredReport]:
    """按 ID 读取指定 report。"""
    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT id, created_at FROM reports WHERE id = ?",
            (report_id,),
        ).fetchone()

        if not row:
            return None

        entry_rows = conn.execute(
            """SELECT filename, file_path, action, composite, reason,
                      is_not_to_save, memory_type, project_dir
               FROM report_entries WHERE report_id = ?""",
            (report_id,),
        ).fetchall()

        return StoredReport(
            report_id=row["id"],
            created_at=row["created_at"],
            entries=[
                ReportEntry(
                    filename=r["filename"],
                    file_path=r["file_path"],
                    action=r["action"],
                    composite=r["composite"],
                    reason=r["reason"],
                    is_not_to_save=bool(r["is_not_to_save"]),
                    memory_type=r["memory_type"],
                    project_dir=r["project_dir"],
                )
                for r in entry_rows
            ],
        )
    finally:
        conn.close()
