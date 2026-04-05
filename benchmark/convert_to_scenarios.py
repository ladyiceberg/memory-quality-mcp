#!/usr/bin/env python3
"""
convert_to_scenarios.py · 把精筛后数据转换成 generate_memories.py 能处理的格式

逻辑：
  1. 跳过任何含「模型回复解析失败」轮次的 session
  2. 从「记忆质量选择V2」提取 turns（关键轮次），截取对应的对话片段
  3. 从 type 映射 expected_action 和 quality_label
  4. 输出为 generate_memories.py 的 --conversations 格式

用法：
  python3 benchmark/convert_to_scenarios.py
  python3 benchmark/convert_to_scenarios.py --input benchmark/精筛后数据_A类过滤.csv
"""

import csv
import json
import re
import argparse
from pathlib import Path

csv.field_size_limit(10_000_000)

INPUT_FILE  = Path(__file__).parent / "精筛后数据_A类过滤.csv"
OUTPUT_FILE = Path(__file__).parent / "scenarios.json"

# type → expected_action / quality_label 映射
TYPE_META = {
    "A": {"expected_action": "keep",   "quality_label": "高质量（明确偏好/背景）"},
    "B": {"expected_action": "delete", "quality_label": "低质量（临时状态）"},
    "C": {"expected_action": "keep",   "quality_label": "高质量（AI纠错）"},
    "D": {"expected_action": "review", "quality_label": "时效性（项目背景）"},
    "E": {"expected_action": "delete", "quality_label": "低质量（过度解读风险）"},
    "F": {"expected_action": "review", "quality_label": "冲突（前后矛盾）"},
}

# 提取窗口：关键轮次前后各保留 N 轮，控制 messages 长度
CONTEXT_WINDOW = 2


def parse_dialog(raw: str) -> dict[int, dict]:
    """解析完整对话，返回 {turn_num: {user, assistant}} 字典。"""
    try:
        data = json.loads(raw)
        turns_raw = data["session_info"]["turns"]
    except Exception:
        return {}

    turns = {}
    for t in turns_raw:
        num = t.get("turn")
        user = t.get("用户提问", "").strip()
        asst = t.get("模型回复", "")

        # 跳过解析失败的
        if "解析失败" in str(asst):
            return None  # 整个 session 废弃

        if isinstance(asst, list):
            # 有些回复是列表结构，拼成文本
            asst = " ".join(str(x) for x in asst).strip()
        else:
            asst = str(asst).strip()

        if num is not None:
            turns[num] = {"user": user, "assistant": asst}

    return turns


def extract_messages(turns: dict[int, dict], key_turns: list[int]) -> list[dict]:
    """
    围绕关键轮次提取 messages，前后加上下文窗口。
    返回 [{"role": "user"/"assistant", "content": "..."}] 格式。
    """
    if not key_turns or not turns:
        return []

    all_nums = sorted(turns.keys())
    # 计算需要包含的轮次范围
    min_turn = max(min(all_nums), min(key_turns) - CONTEXT_WINDOW)
    max_turn = min(max(all_nums), max(key_turns) + CONTEXT_WINDOW)

    messages = []
    for num in all_nums:
        if num < min_turn or num > max_turn:
            continue
        t = turns[num]
        if t["user"]:
            messages.append({"role": "user", "content": t["user"]})
        if t["assistant"]:
            messages.append({"role": "assistant", "content": t["assistant"]})

    return messages


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",  type=Path, default=INPUT_FILE)
    parser.add_argument("--output", type=Path, default=OUTPUT_FILE)
    args = parser.parse_args()

    with open(args.input, newline='', encoding='utf-8-sig') as fh:
        rows = list(csv.DictReader(fh))

    scenarios = []
    stats = {
        "total_sessions": len(rows),
        "skipped_parse_fail": 0,
        "skipped_no_items": 0,
        "skipped_empty_messages": 0,
        "converted": 0,
        "by_type": {},
    }

    for row in rows:
        session_id = row.get("session_id", "")

        # 解析完整对话
        turns = parse_dialog(row.get("完整对话", ""))
        if turns is None:
            stats["skipped_parse_fail"] += 1
            continue

        # 解析筛选结果
        raw_v2    = re.sub(r'```json\s*|```\s*', '', row.get("记忆质量选择V2", "")).strip()
        raw_final = row.get("记忆质量筛选final", "").strip()
        try:
            items    = json.loads(raw_v2)
            verdicts = json.loads(raw_final)
        except Exception:
            stats["skipped_no_items"] += 1
            continue

        # 逐条处理 keep 的条目
        for item, verdict in zip(items, verdicts):
            if verdict.get("verdict") != "keep":
                continue

            t = item.get("type", "")
            meta = TYPE_META.get(t, {"expected_action": "review", "quality_label": "未知"})

            # 关键轮次
            key_turns = item.get("turns") or []
            if isinstance(key_turns, int):
                key_turns = [key_turns]

            messages = extract_messages(turns, key_turns)
            if not messages:
                stats["skipped_empty_messages"] += 1
                continue

            scenario_id = f"{session_id[:8]}_{t}_{len(scenarios)}"

            scenarios.append({
                "scenario_id":    scenario_id,
                "session_id":     session_id,
                "quality_label":  meta["quality_label"],
                "expected_action": meta["expected_action"],
                "scenario_type":  t,
                "key_signal":     item.get("reason", ""),
                "ai_mistake":     item.get("ai_mistake", ""),
                "age_days":       0,   # 无时间信息，默认0
                "messages":       messages,
            })

            stats["converted"] += 1
            stats["by_type"][t] = stats["by_type"].get(t, 0) + 1

    args.output.write_text(
        json.dumps(scenarios, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"{'='*50}")
    print(f"转换完成")
    print(f"{'='*50}")
    print(f"总 session：{stats['total_sessions']}")
    print(f"跳过（含解析失败）：{stats['skipped_parse_fail']}")
    print(f"跳过（无筛选条目）：{stats['skipped_no_items']}")
    print(f"跳过（messages为空）：{stats['skipped_empty_messages']}")
    print(f"转换成功：{stats['converted']} 条 scenario")
    print(f"类型分布：{dict(sorted(stats['by_type'].items()))}")
    print(f"\n✅ 已保存：{args.output}")


if __name__ == "__main__":
    main()
