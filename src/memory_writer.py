from __future__ import annotations
"""
memory_writer.py · 记忆文件写操作层

职责：
  - 备份待删除文件到 .trash 目录
  - 删除记忆文件
  - 同步更新 MEMORY.md 索引

安全原则：
  - 所有删除操作前必须先备份到 .trash/<timestamp>/
  - 绝不静默删除，调用方必须明确传入 dry_run=False
  - 删文件后同步更新 MEMORY.md，避免索引出现孤立条目
"""

import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.memory_reader import MEMORY_INDEX_NAME, MAX_INDEX_BYTES, MAX_INDEX_LINES


# ── 数据结构 ───────────────────────────────────────────────────────────────────

@dataclass
class CleanupResult:
    """memory_cleanup 操作的完整结果。"""
    dry_run: bool
    files_targeted: list[str]        # 计划删除的文件列表
    files_deleted: list[str]         # 实际已删除的文件（dry_run=True 时为空）
    trash_dir: Optional[Path]        # 备份目录（dry_run=True 时为 None）
    index_updated: bool              # MEMORY.md 是否已同步更新
    errors: list[str] = field(default_factory=list)


# ── 核心操作 ──────────────────────────────────────────────────────────────────

def backup_and_delete(
    files_to_delete: list[Path],
    memory_dir: Path,
    dry_run: bool = True,
) -> CleanupResult:
    """
    备份并删除指定的记忆文件，然后同步更新 MEMORY.md 索引。

    执行顺序（dry_run=False 时）：
      1. 创建 .trash/<timestamp>/ 备份目录
      2. 把每个待删文件 copy 到备份目录
      3. 删除原文件
      4. 更新 MEMORY.md，移除已删文件的索引条目

    Args:
        files_to_delete: 待删除的文件绝对路径列表
        memory_dir: 记忆目录根路径（用于定位 .trash 和 MEMORY.md）
        dry_run: True 时只预览，不执行任何文件操作

    Returns:
        CleanupResult 包含操作详情
    """
    targeted = [str(f.relative_to(memory_dir)) for f in files_to_delete if f.exists()]

    if dry_run:
        return CleanupResult(
            dry_run=True,
            files_targeted=targeted,
            files_deleted=[],
            trash_dir=None,
            index_updated=False,
        )

    # ── 创建 .trash 目录 ─────────────────────────────────────────────────────
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    trash_dir = memory_dir / ".trash" / timestamp
    trash_dir.mkdir(parents=True, exist_ok=True)

    deleted = []
    errors = []

    # ── 备份 + 删除 ──────────────────────────────────────────────────────────
    for f in files_to_delete:
        if not f.exists():
            errors.append(f"文件不存在，跳过：{f.name}")
            continue
        try:
            # 保持相对路径结构（子目录记忆也能正确备份）
            try:
                rel = f.relative_to(memory_dir)
            except ValueError:
                rel = Path(f.name)

            backup_path = trash_dir / rel
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, backup_path)   # copy2 保留 mtime
            f.unlink()
            deleted.append(str(rel))
        except OSError as e:
            errors.append(f"删除 {f.name} 失败：{e}")

    # ── 更新 MEMORY.md 索引 ──────────────────────────────────────────────────
    index_updated = False
    if deleted:
        index_updated = _update_memory_index(memory_dir, set(deleted))

    return CleanupResult(
        dry_run=False,
        files_targeted=targeted,
        files_deleted=deleted,
        trash_dir=trash_dir if deleted else None,
        index_updated=index_updated,
        errors=errors,
    )


def _update_memory_index(memory_dir: Path, deleted_filenames: set[str]) -> bool:
    """
    从 MEMORY.md 中移除已删除文件的索引条目。

    MEMORY.md 的每行格式为：
      - [标题](filename.md) — 描述

    对每行检查是否包含已删除的文件名，有则移除该行。

    Returns:
        True 表示索引更新成功，False 表示索引不存在或更新失败
    """
    index_path = memory_dir / MEMORY_INDEX_NAME
    if not index_path.exists():
        return False

    try:
        original = index_path.read_text(encoding="utf-8")
        lines = original.splitlines(keepends=True)
        kept_lines = []

        for line in lines:
            # 检查这行是否引用了被删除的文件
            # 格式：- [title](filename.md) 或直接包含文件名
            should_remove = False
            for deleted_rel in deleted_filenames:
                # 只取文件名部分做匹配（支持子目录记忆）
                filename = Path(deleted_rel).name
                if filename in line:
                    should_remove = True
                    break
            if not should_remove:
                kept_lines.append(line)

        updated = "".join(kept_lines)
        # 只在内容有变化时才写入，避免无意义的 mtime 更新
        if updated != original:
            index_path.write_text(updated, encoding="utf-8")

        return True

    except OSError:
        return False


# ── 格式化输出 ─────────────────────────────────────────────────────────────────

def format_cleanup_result(result: CleanupResult) -> str:
    """把 CleanupResult 格式化为用户友好的文本。"""
    lines = []

    if result.dry_run:
        lines.append(f"🔍 **预览模式**（未执行任何删除）")
        lines.append("")
        if not result.files_targeted:
            lines.append("✅ 没有需要清理的记忆。")
        else:
            lines.append(f"以下 {len(result.files_targeted)} 条记忆将被删除：")
            for f in result.files_targeted:
                lines.append(f"  - {f}")
            lines.append("")
            lines.append("▶ 确认清理请调用 `memory_cleanup(dry_run=False)`")
    else:
        if result.files_deleted:
            lines.append(f"✅ 已清理 {len(result.files_deleted)} 条记忆")
            if result.trash_dir:
                lines.append(f"   备份位置：{result.trash_dir}")
            if result.index_updated:
                lines.append(f"   MEMORY.md 索引已同步更新")
            lines.append("")
            lines.append("已删除：")
            for f in result.files_deleted:
                lines.append(f"  - {f}")
        else:
            lines.append("✅ 没有文件被删除。")

        if result.errors:
            lines.append("")
            lines.append("⚠️ 部分操作出错：")
            for e in result.errors:
                lines.append(f"  - {e}")

    return "\n".join(lines)
