#!/usr/bin/env python3
"""
seed_memories.py · 在本机创建一批测试用记忆文件

用途：
  1. 在 Auto Memory 功能未开放时，手动生成测试数据
  2. 覆盖各种质量类型（高质量、过时、低质量、冲突、违规），验证评分引擎
  3. 可指定目标目录，不影响真实记忆

用法：
  # 写入默认记忆目录（~/.claude/projects/<当前目录>/memory/）
  python3 scripts/seed_memories.py

  # 写入指定目录
  python3 scripts/seed_memories.py --dir /tmp/test_memories

  # 预览将要创建的文件（不实际写入）
  python3 scripts/seed_memories.py --dry-run

  # 清理已创建的种子文件
  python3 scripts/seed_memories.py --clean
"""

import argparse
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# 把项目根目录加入 sys.path，方便直接运行
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.memory_reader import get_memory_dir, MEMORY_INDEX_NAME


# ── 种子记忆数据（覆盖所有质量类型）────────────────────────────────────────────

SEED_MEMORIES = [
    # ── 高质量记忆（应该被保留）────────────────────────────────────────────
    {
        "filename": "seed_user_role.md",
        "age_days": 5,
        "content": """\
---
name: 用户角色与背景
description: 用户是 AI 产品创业者，关注 C 端和小 B 端机会
type: user
---

用户是在做 AI 领域机会挖掘的创业者，技术背景较弱但有较强的产品和市场判断力。

**Why:** 用户自己介绍的背景
**How to apply:** 解释技术细节时多用类比，避免过多代码；产品方向建议优先 C 端和小 B 端
""",
        "category": "高质量",
    },
    {
        "filename": "seed_feedback_style.md",
        "age_days": 10,
        "content": """\
---
name: 输出风格偏好
description: 用户希望回答先给白话结论，再展开细节
type: feedback
---

用户希望每段技术内容前先给「白话」说明，再展开源码和细节。

**Why:** 用户明确提出，说「带着读，而不是堆着扔」
**How to apply:** 每次给出技术解释时，先用一两句话说清楚「这在干什么」，再给细节
""",
        "category": "高质量",
    },
    {
        "filename": "seed_feedback_no_summary.md",
        "age_days": 3,
        "content": """\
---
name: 不要在回答末尾总结
description: 用户不喜欢回答末尾重复总结已说过的内容
type: feedback
---

不要在每次回答末尾加「总结：……」或「综上所述……」之类的段落，用户觉得多余。

**Why:** 用户明确说过「我能读懂，不需要重复」
**How to apply:** 回答直接结束，不加尾部总结
""",
        "category": "高质量",
    },

    # ── 过时记忆（project 类型，超过 90 天）─────────────────────────────────
    {
        "filename": "seed_project_old_deadline.md",
        "age_days": 120,
        "content": """\
---
name: Q1 产品发布计划
description: memory-quality-mcp 计划在 2025-03-31 前发布 beta
type: project
---

memory-quality-mcp 的 beta 版本计划在 2025-03-31 前发布到 PyPI。

**Why:** 需要在 Q1 窗口期内验证需求
**How to apply:** 所有功能讨论围绕 6 周交付目标
""",
        "category": "过时",
    },
    {
        "filename": "seed_project_old_status.md",
        "age_days": 95,
        "content": """\
---
name: 当前开发重点
description: 正在开发 Step 2（记忆读取层），预计本周完成
type: project
---

当前开发重点是 Step 2 的 memory_reader.py，预计本周完成并开始 Step 3。

**Why:** 追踪项目进展
**How to apply:** 提问时可以假设 Step 1-2 已完成
""",
        "category": "过时",
    },

    # ── 低质量记忆（建议删除）────────────────────────────────────────────────
    {
        "filename": "seed_low_temp_note.md",
        "age_days": 30,
        "content": """\
---
name: 今天的想法
description: 随手记的一个临时想法
type: user
---

今天想到可以在产品里加一个「一键体检」按钮，感觉挺好的。
""",
        "category": "低质量",
    },
    {
        "filename": "seed_low_code_pattern.md",
        "age_days": 15,
        "content": """\
---
name: 代码架构记录
description: memory-quality-mcp 使用分层架构
type: reference
---

项目架构：memory_reader.py 负责读取，quality_engine.py 负责评分，server.py 是 MCP 入口。
文件路径在 /Users/maavis/opportunity_mining/memory-quality-mcp/src/。

**Why:** 记录架构方便后续参考
**How to apply:** 讨论代码时先看这里
""",
        "category": "低质量（违规：代码结构/文件路径）",
    },

    # ── 冲突记忆（语义矛盾）─────────────────────────────────────────────────
    {
        "filename": "seed_conflict_a.md",
        "age_days": 20,
        "content": """\
---
name: 代码注释偏好 A
description: 用户喜欢代码注释详尽
type: feedback
---

用户希望代码注释尽量详尽，每一行都要有注释说明在做什么。

**Why:** 用户技术背景较弱，需要详细注释帮助理解
**How to apply:** 写代码时每行加中文注释
""",
        "category": "冲突",
    },
    {
        "filename": "seed_conflict_b.md",
        "age_days": 8,
        "content": """\
---
name: 代码注释偏好 B
description: 用户偏好简洁代码，注释越少越好
type: feedback
---

用户反馈代码注释太多反而干扰阅读，希望保持代码简洁，只在关键逻辑处加注释。

**Why:** 用户说「注释太多像教科书，不想看」
**How to apply:** 只在非直觉的逻辑处加注释，常见操作不注释
""",
        "category": "冲突",
    },

    # ── 「记偏了」记忆（准确性问题）─────────────────────────────────────────
    {
        "filename": "seed_accuracy_issue.md",
        "age_days": 7,
        "content": """\
---
name: 用户工作时间偏好
description: 用户是夜猫子，习惯深夜工作
type: user
---

用户习惯在深夜（22:00-02:00）工作，思维最清晰。偏好在这个时间段处理复杂任务。

**Why:** 用户曾经说过「昨晚很晚才睡完成了这个功能」
**How to apply:** 深夜发消息时不需要担心打扰用户
""",
        "category": "记偏了（单次随口一说被固化为习惯）",
    },
]

# MEMORY.md 索引模板
def build_index(filenames_and_names: list[tuple[str, str, str]]) -> str:
    lines = []
    for filename, name, category in filenames_and_names:
        lines.append(f"- [{name}]({filename}) — {category}")
    return "\n".join(lines) + "\n"


# ── 核心逻辑 ──────────────────────────────────────────────────────────────────

def seed(target_dir: Path, dry_run: bool = False) -> None:
    """在 target_dir 创建种子记忆文件。"""
    target_dir = target_dir.resolve()

    print(f"\n{'[DRY RUN] ' if dry_run else ''}目标目录：{target_dir}")
    print(f"将创建 {len(SEED_MEMORIES)} 条种子记忆\n")

    if not dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)

    index_entries = []

    for mem in SEED_MEMORIES:
        filename = mem["filename"]
        file_path = target_dir / filename
        age_days = mem["age_days"]
        category = mem["category"]
        content = mem["content"]

        # 解析 name 用于显示和索引
        name = filename  # 默认用文件名
        for line in content.splitlines():
            if line.startswith("name:"):
                name = line.split(":", 1)[1].strip()
                break

        print(f"  {'(跳过) ' if dry_run else '写入  '} {filename:<40} [{category}]  ({age_days}天前)")

        if not dry_run:
            file_path.write_text(content, encoding="utf-8")
            # 设置文件修改时间为 age_days 天前
            old_time = time.time() - age_days * 86400
            os.utime(file_path, (old_time, old_time))

        index_entries.append((filename, name, category))

    # 写 MEMORY.md 索引
    index_path = target_dir / MEMORY_INDEX_NAME
    index_content = build_index(index_entries)
    print(f"\n  {'(跳过) ' if dry_run else '写入  '} MEMORY.md  ({len(index_entries)} 条索引)")

    if not dry_run:
        index_path.write_text(index_content, encoding="utf-8")
        print(f"\n✅ 种子数据已写入：{target_dir}")
        print(f"\n现在可以运行以下命令测试：")
        print(f"  export ANTHROPIC_API_KEY=your_key_here")
        print(f"  # 在 Claude Code 的 MCP 配置里添加 memory-quality-mcp")
        print(f"  # 然后在 Claude Code 中运行 memory_audit()")
    else:
        print(f"\n（dry-run 模式，未实际写入任何文件）")


def clean(target_dir: Path) -> None:
    """清理 target_dir 中的种子文件。"""
    target_dir = target_dir.resolve()
    print(f"\n清理目录：{target_dir}")

    seed_filenames = {m["filename"] for m in SEED_MEMORIES}
    seed_filenames.add(MEMORY_INDEX_NAME)

    removed = []
    for filename in seed_filenames:
        file_path = target_dir / filename
        if file_path.exists():
            file_path.unlink()
            removed.append(filename)
            print(f"  删除  {filename}")

    if removed:
        print(f"\n✅ 已清理 {len(removed)} 个文件")
    else:
        print("未找到种子文件")


# ── CLI 入口 ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="为 memory-quality-mcp 创建测试用记忆文件"
    )
    parser.add_argument(
        "--dir",
        type=Path,
        default=None,
        help="目标目录（默认：当前项目的 Claude Code 记忆目录）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只预览，不实际写入",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="清理已创建的种子文件",
    )

    args = parser.parse_args()

    # 确定目标目录
    if args.dir:
        target_dir = args.dir
    else:
        target_dir = get_memory_dir()
        print(f"使用默认记忆目录：{target_dir}")

    if args.clean:
        clean(target_dir)
    else:
        seed(target_dir, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
