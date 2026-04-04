"""
test_memory_reader.py · memory_reader 模块的验收测试

用 mock 数据验证核心逻辑，不依赖本机真实记忆文件。
"""

import json
import time
from pathlib import Path

import pytest

from src.memory_reader import (
    IndexHealth,
    MemoryFile,
    MemoryHeader,
    ScanResult,
    check_memory_index_health,
    format_age,
    format_memory_manifest,
    get_memory_dir,
    memory_age_days,
    parse_frontmatter,
    read_memory_file,
    scan_memory_files,
    _sanitize_path,
    _extract_body,
    MAX_INDEX_LINES,
    MAX_INDEX_BYTES,
)


# ── Fixtures：创建 mock 记忆目录 ─────────────────────────────────────────────

SAMPLE_USER_MEMORY = """\
---
name: 用户角色
description: 用户是数据科学家，关注可观测性
type: user
---

用户是数据科学家，目前在调查日志系统。

**Why:** 用户自己说的
**How to apply:** 解释代码时侧重 logging 逻辑
"""

SAMPLE_FEEDBACK_MEMORY = """\
---
name: 测试风格偏好
description: 用户不喜欢 mock 数据库
type: feedback
---

集成测试必须连接真实数据库，不能用 mock。

**Why:** 上个季度 mock 测试通过但生产迁移失败
**How to apply:** 写测试时始终使用真实数据库
"""

SAMPLE_PROJECT_MEMORY = """\
---
name: 项目截止日期
description: memory-quality-mcp 项目，6 周内发布
type: project
---

memory-quality-mcp 目标 6 周内发布到 PyPI。

**Why:** 验证窗口期 12-18 个月，需要快速占位
**How to apply:** 控制 scope，不做过度设计
"""

SAMPLE_NO_TYPE_MEMORY = """\
---
name: 旧格式记忆
description: 没有 type 字段的旧记忆
---

这是一条没有 type 字段的历史遗留记忆。
"""

SAMPLE_NO_FRONTMATTER = """\
这是一条完全没有 frontmatter 的记忆，直接是正文内容。
"""


@pytest.fixture
def mock_memory_dir(tmp_path):
    """创建一个标准的 mock 记忆目录，包含各类样本文件。"""
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()

    # 写入样本记忆文件
    (memory_dir / "user_role.md").write_text(SAMPLE_USER_MEMORY, encoding="utf-8")
    (memory_dir / "feedback_testing.md").write_text(SAMPLE_FEEDBACK_MEMORY, encoding="utf-8")
    (memory_dir / "project_deadline.md").write_text(SAMPLE_PROJECT_MEMORY, encoding="utf-8")
    (memory_dir / "legacy_no_type.md").write_text(SAMPLE_NO_TYPE_MEMORY, encoding="utf-8")
    (memory_dir / "no_frontmatter.md").write_text(SAMPLE_NO_FRONTMATTER, encoding="utf-8")

    # 写入 MEMORY.md 索引
    index_content = """\
- [用户角色](user_role.md) — 用户是数据科学家
- [测试风格偏好](feedback_testing.md) — 不喜欢 mock 数据库
- [项目截止日期](project_deadline.md) — 6 周内发布
- [旧格式记忆](legacy_no_type.md) — 历史遗留
"""
    (memory_dir / "MEMORY.md").write_text(index_content, encoding="utf-8")

    return memory_dir


# ── parse_frontmatter 测试 ────────────────────────────────────────────────────

class TestParseFrontmatter:
    def test_标准格式解析正确(self):
        fm = parse_frontmatter(SAMPLE_USER_MEMORY)
        assert fm["name"] == "用户角色"
        assert fm["description"] == "用户是数据科学家，关注可观测性"
        assert fm["type"] == "user"

    def test_没有frontmatter返回空dict(self):
        fm = parse_frontmatter(SAMPLE_NO_FRONTMATTER)
        assert fm == {}

    def test_type字段缺失时不报错(self):
        fm = parse_frontmatter(SAMPLE_NO_TYPE_MEMORY)
        assert fm["name"] == "旧格式记忆"
        assert "type" not in fm or fm.get("type") == ""

    def test_空内容返回空dict(self):
        assert parse_frontmatter("") == {}
        assert parse_frontmatter("   ") == {}

    def test_只有开头分隔符没有结束返回空dict(self):
        assert parse_frontmatter("---\nname: test\n") == {}


# ── _sanitize_path 测试 ───────────────────────────────────────────────────────

class TestSanitizePath:
    def test_标准路径转换(self):
        result = _sanitize_path(Path("/Users/maavis/my-project"))
        assert result == "Users-maavis-my-project"

    def test_连字符首尾被去除(self):
        result = _sanitize_path(Path("/Users/maavis"))
        assert not result.startswith("-")
        assert not result.endswith("-")


# ── scan_memory_files 测试 ────────────────────────────────────────────────────

class TestScanMemoryFiles:
    def test_正常扫描返回正确数量(self, mock_memory_dir):
        result = scan_memory_files(mock_memory_dir)
        # 5 个 .md 文件，排除 MEMORY.md，剩 4 个有 frontmatter 的 + 1 个没有
        assert isinstance(result, ScanResult)
        assert len(result.headers) == 5

    def test_MEMORY_md被排除(self, mock_memory_dir):
        result = scan_memory_files(mock_memory_dir)
        filenames = [h.filename for h in result.headers]
        assert "MEMORY.md" not in filenames

    def test_memory_type正确解析(self, mock_memory_dir):
        result = scan_memory_files(mock_memory_dir)
        by_file = {h.filename: h for h in result.headers}

        assert by_file["user_role.md"].memory_type == "user"
        assert by_file["feedback_testing.md"].memory_type == "feedback"
        assert by_file["project_deadline.md"].memory_type == "project"

    def test_无效type返回None不报错(self, mock_memory_dir):
        result = scan_memory_files(mock_memory_dir)
        by_file = {h.filename: h for h in result.headers}
        # legacy_no_type.md 没有 type 字段，应该是 None
        assert by_file["legacy_no_type.md"].memory_type is None

    def test_无frontmatter文件被正常处理(self, mock_memory_dir):
        result = scan_memory_files(mock_memory_dir)
        by_file = {h.filename: h for h in result.headers}
        h = by_file["no_frontmatter.md"]
        assert h.memory_type is None
        assert h.name is None

    def test_目录不存在时优雅返回(self, tmp_path):
        nonexistent = tmp_path / "nonexistent" / "memory"
        result = scan_memory_files(nonexistent)
        assert len(result.headers) == 0
        assert result.index_health.exists is False
        assert result.index_health.warning is not None

    def test_按mtime降序排列(self, mock_memory_dir):
        # 修改文件的 mtime，让 project_deadline.md 变成最新
        project_file = mock_memory_dir / "project_deadline.md"
        new_time = time.time() + 1000  # 比其他文件晚
        import os
        os.utime(project_file, (new_time, new_time))

        result = scan_memory_files(mock_memory_dir)
        assert result.headers[0].filename == "project_deadline.md"

    def test_mtime_ms是毫秒时间戳(self, mock_memory_dir):
        result = scan_memory_files(mock_memory_dir)
        now_ms = int(time.time() * 1000)
        for h in result.headers:
            # mtime 应该在合理范围内（1970年之后，现在之前）
            assert h.mtime_ms > 0
            assert h.mtime_ms <= now_ms + 2000  # 允许 2 秒误差


# ── read_memory_file 测试 ─────────────────────────────────────────────────────

class TestReadMemoryFile:
    def test_读取完整内容(self, mock_memory_dir):
        file_path = mock_memory_dir / "user_role.md"
        result = read_memory_file(file_path, mock_memory_dir)

        assert isinstance(result, MemoryFile)
        assert result.header.memory_type == "user"
        assert "数据科学家" in result.raw_content

    def test_正文提取正确(self, mock_memory_dir):
        file_path = mock_memory_dir / "user_role.md"
        result = read_memory_file(file_path, mock_memory_dir)
        # 正文不应该包含 frontmatter
        assert "---" not in result.body
        assert "数据科学家" in result.body

    def test_has_why检测(self, mock_memory_dir):
        # user_role.md 有 **Why:**
        file_with_why = mock_memory_dir / "user_role.md"
        result = read_memory_file(file_with_why, mock_memory_dir)
        assert result.has_why is True

        # no_frontmatter.md 没有 **Why:**
        file_without_why = mock_memory_dir / "no_frontmatter.md"
        result = read_memory_file(file_without_why, mock_memory_dir)
        assert result.has_why is False

    def test_has_how_to_apply检测(self, mock_memory_dir):
        file_path = mock_memory_dir / "feedback_testing.md"
        result = read_memory_file(file_path, mock_memory_dir)
        assert result.has_how_to_apply is True


# ── check_memory_index_health 测试 ───────────────────────────────────────────

class TestCheckMemoryIndexHealth:
    def test_正常状态无警告(self, mock_memory_dir):
        health = check_memory_index_health(mock_memory_dir)
        assert health.exists is True
        assert health.line_count > 0
        assert health.is_line_truncated is False
        assert health.is_byte_truncated is False

    def test_MEMORY_md不存在时(self, tmp_path):
        empty_dir = tmp_path / "memory"
        empty_dir.mkdir()
        health = check_memory_index_health(empty_dir)
        assert health.exists is False
        assert health.warning is None

    def test_超过行数上限时报警告(self, tmp_path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        # 写入超过 200 行的 MEMORY.md
        lines = [f"- [记忆{i}](memory_{i}.md) — 测试记忆\n" for i in range(210)]
        (memory_dir / "MEMORY.md").write_text("".join(lines), encoding="utf-8")

        health = check_memory_index_health(memory_dir)
        assert health.is_line_truncated is True
        assert health.warning is not None
        assert "上限" in health.warning

    def test_接近上限时有预警(self, tmp_path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        # 写入 165 行（> 200 * 0.8 = 160）
        lines = [f"- [记忆{i}](memory_{i}.md) — 测试记忆\n" for i in range(165)]
        (memory_dir / "MEMORY.md").write_text("".join(lines), encoding="utf-8")

        health = check_memory_index_health(memory_dir)
        assert health.is_line_truncated is False
        assert health.warning is not None  # 应该有预警


# ── 辅助函数测试 ──────────────────────────────────────────────────────────────

class TestHelpers:
    def test_memory_age_days_今天(self):
        now_ms = int(time.time() * 1000)
        assert memory_age_days(now_ms) == 0

    def test_memory_age_days_昨天(self):
        yesterday_ms = int(time.time() * 1000) - 86_400_000
        assert memory_age_days(yesterday_ms) == 1

    def test_memory_age_days_负值不会出现(self):
        future_ms = int(time.time() * 1000) + 86_400_000
        assert memory_age_days(future_ms) == 0

    def test_format_age_今天(self):
        now_ms = int(time.time() * 1000)
        assert format_age(now_ms) == "今天"

    def test_format_age_昨天(self):
        yesterday_ms = int(time.time() * 1000) - 86_400_000
        assert format_age(yesterday_ms) == "昨天"

    def test_format_age_多天前(self):
        old_ms = int(time.time() * 1000) - 10 * 86_400_000
        assert format_age(old_ms) == "10 天前"

    def test_format_memory_manifest格式正确(self, mock_memory_dir):
        result = scan_memory_files(mock_memory_dir)
        manifest = format_memory_manifest(result.headers)
        assert "[user]" in manifest
        assert "[feedback]" in manifest
        assert "user_role.md" in manifest


# ── 集成测试：扫描真实记忆目录（如果存在）────────────────────────────────────

class TestRealMemoryDir:
    def test_真实记忆目录扫描不报错(self):
        """
        如果本机有真实的 Claude Code 记忆目录，扫描它并打印结果。
        没有也不失败（graceful degradation）。
        """
        real_dir = get_memory_dir()
        result = scan_memory_files(real_dir)

        if not result.index_health.exists:
            print(f"\n📭 本机暂无记忆文件（{real_dir}），跳过真实数据验证。")
            return

        print(f"\n✅ 找到真实记忆目录：{real_dir}")
        print(f"   记忆数量：{len(result.headers)}")
        print(f"   MEMORY.md：{result.index_health.line_count} 行 / {result.index_health.byte_count:,} 字节")

        if result.index_health.warning:
            print(f"   ⚠️ {result.index_health.warning}")

        for h in result.headers[:5]:  # 只打印前 5 条
            age = format_age(h.mtime_ms)
            type_tag = f"[{h.memory_type}]" if h.memory_type else "[无类型]"
            print(f"   {type_tag} {h.filename} ({age}): {h.description or h.name or '无描述'}")

        # 基本断言：有记忆时这些字段应该是合理的
        for h in result.headers:
            assert h.file_path.exists()
            assert h.mtime_ms > 0
