#!/usr/bin/env python3
"""
test_live.py · 用真实 API Key 验证评分引擎

不需要 Claude Code，直接对种子数据跑完整评分流程，
验证 LLM 的判断是否符合预期。

用法：
  export ANTHROPIC_API_KEY=your_key_here
  .venv/bin/python scripts/test_live.py

  # 只跑规则引擎（不消耗 API）
  .venv/bin/python scripts/test_live.py --rules-only

  # 指定种子数据目录
  .venv/bin/python scripts/test_live.py --dir /tmp/test_memories
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.memory_reader import (
    format_age,
    get_memory_dir,
    read_memory_file,
    scan_memory_files,
)
from src.quality_engine import apply_rule_engine, run_quality_engine


# 每种类别的预期结果（用于验收）
EXPECTED = {
    "seed_user_role.md":            "keep",
    "seed_feedback_style.md":       "keep",
    "seed_feedback_no_summary.md":  "keep",
    "seed_project_old_deadline.md": "delete",   # project 类型 + 120 天
    "seed_project_old_status.md":   "delete",   # project 类型 + 95 天
    "seed_low_temp_note.md":        "delete",   # 低质量临时状态
    "seed_low_code_pattern.md":     "delete",   # 违反「不该存」规则（代码路径）
    "seed_conflict_a.md":           "review",   # 冲突记忆
    "seed_conflict_b.md":           "review",   # 冲突记忆
    "seed_accuracy_issue.md":       "review",   # 记偏了
}

ACTION_ICON = {"keep": "✅", "review": "🔄", "delete": "🗑 "}


def run(memory_dir: Path, rules_only: bool) -> None:
    print(f"\n{'='*60}")
    print(f"Memory Quality Engine — 真实验证")
    print(f"{'='*60}")
    print(f"数据目录：{memory_dir}")
    print(f"模式：{'仅规则引擎（不调 LLM）' if rules_only else '完整流程（规则 + LLM）'}\n")

    # 扫描文件
    scan = scan_memory_files(memory_dir)
    if not scan.headers:
        print("❌ 未找到记忆文件，请先运行：")
        print(f"   .venv/bin/python scripts/seed_memories.py --dir {memory_dir}")
        return

    print(f"找到 {len(scan.headers)} 条记忆文件\n")

    # 读取全文
    memory_files = []
    for h in scan.headers:
        try:
            memory_files.append(read_memory_file(h.file_path, memory_dir))
        except OSError as e:
            print(f"⚠️  无法读取 {h.filename}：{e}")

    if rules_only:
        # ── 只跑规则引擎 ─────────────────────────────────────────────────
        print("── 规则引擎结果 ──────────────────────────────────────")
        for mf in memory_files:
            result = apply_rule_engine(mf)
            if result:
                icon = ACTION_ICON[result.action]
                print(f"{icon} {mf.header.filename}")
                print(f"   → {result.action.upper()} [{result.scored_by}]")
                print(f"   原因：{result.reason[:80]}...")
            else:
                print(f"⚪  {mf.header.filename}")
                print(f"   → 规则无法判断，需要 LLM")
            print()
        return

    # ── 完整流程 ─────────────────────────────────────────────────────────
    from src.config import load_config
    cfg = load_config()
    model_name = cfg.get("model") or cfg.get("provider") or "自动检测"
    print(f"正在调用 LLM 评分（{model_name}）...\n")
    try:
        result = run_quality_engine(memory_files, run_conflict_detection=True)
    except ValueError as e:
        print(f"❌ {e}")
        print("\n请先设置 API Key：export ANTHROPIC_API_KEY=your_key_here")
        return

    # ── 打印评分结果 ──────────────────────────────────────────────────────
    print(f"── 评分结果（LLM 调用 {result.llm_calls} 次）───────────────────")
    print(f"总计：{result.total} 条  |  "
          f"删除 {result.to_delete}  |  复查 {result.to_review}  |  保留 {result.to_keep}\n")

    correct = 0
    wrong = 0

    for s in sorted(result.scored_memories, key=lambda x: x.header.filename):
        icon = ACTION_ICON[s.action]
        expected = EXPECTED.get(s.header.filename)
        age = format_age(s.header.mtime_ms)

        # 是否符合预期
        if expected:
            if s.action == expected:
                verdict = "✓"
                correct += 1
            else:
                verdict = f"✗ (预期 {expected})"
                wrong += 1
        else:
            verdict = "?"

        conflict_tag = " [冲突]" if s.conflicts_with else ""
        not_to_save_tag = " [违规]" if s.is_not_to_save else ""

        print(f"{icon} {s.header.filename:<40} {verdict}")
        print(f"   综合分 {s.scores.composite:.2f}  |  "
              f"重要性 {s.scores.importance:.1f}  时效性 {s.scores.recency:.1f}  "
              f"可信度 {s.scores.credibility:.1f}  "
              f"准确性 {'N/A' if s.scores.accuracy == 0 else f'{s.scores.accuracy:.1f}'}"
              f"{conflict_tag}{not_to_save_tag}")
        print(f"   {s.reason[:90]}")
        print()

    # ── 冲突汇总 ─────────────────────────────────────────────────────────
    if result.conflicts:
        print(f"── 冲突检测（{len(result.conflicts)} 对）──────────────────────────")
        for c in result.conflicts:
            sev = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(c.severity, "⚪")
            print(f"{sev} {c.filename_a}  ×  {c.filename_b}")
            print(f"   {c.description}")
        print()

    # ── 验收摘要 ─────────────────────────────────────────────────────────
    total_expected = correct + wrong
    if total_expected > 0:
        accuracy = correct / total_expected * 100
        print(f"── 验收结果 ────────────────────────────────────────────")
        print(f"预期符合率：{correct}/{total_expected} = {accuracy:.0f}%")
        if wrong > 0:
            print(f"⚠️  有 {wrong} 条不符合预期，建议检查 prompts.py 的评分标准")
        else:
            print(f"✅ 全部符合预期，评分引擎工作正常，可以进入打包发布")
    print()


def main():
    parser = argparse.ArgumentParser(description="用真实 API 验证评分引擎")
    parser.add_argument("--dir", type=Path, default=None)
    parser.add_argument("--rules-only", action="store_true")
    args = parser.parse_args()

    target_dir = args.dir or get_memory_dir()
    run(target_dir, rules_only=args.rules_only)


if __name__ == "__main__":
    main()
