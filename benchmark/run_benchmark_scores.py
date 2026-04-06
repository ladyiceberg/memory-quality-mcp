#!/usr/bin/env python3
"""
run_benchmark_scores.py · 对 dataset.json 里所有 memory 跑 LLM 评分，结果回写文件

用法：
  cd memory-quality-mcp/
  source ~/.env.local            # 加载 MINIMAX_API_KEY
  .venv/bin/python benchmark/run_benchmark_scores.py

断点续跑：
  已有 llm_scores 的条目自动跳过，直接从未跑的继续。

输出：
  - 实时更新 benchmark/dataset.json（每批写入一次）
  - 完成后打印准确率统计
"""

import json
import sys
import time
from pathlib import Path

# 项目根目录加入 path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import load_config
from src.llm_client import create_client
from src.quality_engine import score_single

DATASET_PATH = ROOT / "benchmark" / "dataset.json"
BATCH_SIZE = 6        # 每批评分后写入一次文件
RETRY_DELAY = 5       # 失败后等待秒数
MAX_RETRIES = 2       # 最多重试次数


def load_dataset():
    with open(DATASET_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_dataset(data):
    with open(DATASET_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def run():
    # 初始化
    config = load_config()
    try:
        client = create_client(config)
    except ValueError as e:
        print(f"❌ 无法创建 LLM 客户端：{e}")
        print("请先设置 API Key：export MINIMAX_API_KEY=xxx 或 source ~/.env.local")
        sys.exit(1)

    data = load_dataset()
    total = len(data)

    # 找出还没跑的条目
    pending = [i for i, d in enumerate(data) if not d.get("llm_scores")]
    already_done = total - len(pending)

    print(f"dataset.json 总计：{total} 条")
    print(f"已完成：{already_done} 条，待跑：{len(pending)} 条")
    if not pending:
        print("✅ 全部已完成，无需重跑")
        return

    batches = (len(pending) + BATCH_SIZE - 1) // BATCH_SIZE
    print(f"批次大小：{BATCH_SIZE}，预计批次数：{batches}\n")

    done = 0
    failed = 0

    for batch_start in range(0, len(pending), BATCH_SIZE):
        batch_indices = pending[batch_start: batch_start + BATCH_SIZE]
        batch_num = batch_start // BATCH_SIZE + 1

        for idx in batch_indices:
            entry = data[idx]
            content = entry.get("content", "")
            memory_type = entry.get("memory_type")

            # 重试循环
            result = None
            for attempt in range(MAX_RETRIES + 1):
                try:
                    result = score_single(content, memory_type=memory_type, client=client)
                    break
                except Exception as e:
                    if attempt < MAX_RETRIES:
                        print(f"  ⚠️  [{idx}] 第 {attempt+1} 次失败，{RETRY_DELAY}s 后重试：{e}")
                        time.sleep(RETRY_DELAY)
                    else:
                        print(f"  ❌ [{idx}] 最终失败，跳过：{e}")
                        failed += 1

            if result is None:
                # 记录失败，标记为 uncertain
                data[idx]["llm_scores"] = {
                    "importance": None,
                    "recency": None,
                    "credibility": None,
                    "accuracy": None,
                    "composite": None,
                }
                data[idx]["llm_action"] = "uncertain"
                data[idx]["llm_reason"] = "评分失败"
                data[idx]["llm_is_not_to_save"] = None
                data[idx]["scored_by"] = "failed"
            else:
                s = result.scores
                data[idx]["llm_scores"] = {
                    "importance": s.importance,
                    "recency": s.recency,
                    "credibility": s.credibility,
                    "accuracy": s.accuracy,
                    "composite": s.composite,
                }
                data[idx]["llm_action"] = result.action
                data[idx]["llm_reason"] = result.reason
                data[idx]["llm_is_not_to_save"] = result.is_not_to_save
                data[idx]["scored_by"] = result.scored_by
                done += 1

        # 每批写入一次文件
        save_dataset(data)
        completed = already_done + batch_start + len(batch_indices)
        print(f"批次 {batch_num}/{batches} 完成 — 已写入 {completed}/{total} 条"
              f"（本批失败 {failed} 条）")
        failed = 0  # 重置本批计数

    # 最终统计
    print(f"\n{'='*60}")
    print(f"评分完成！共处理 {done} 条")

    # 准确率统计
    correct = sum(
        1 for d in data
        if d.get("llm_action") and d.get("expected_action")
        and d["llm_action"] == d["expected_action"]
        and d["llm_action"] != "uncertain"
    )
    scoreable = sum(
        1 for d in data
        if d.get("llm_action") and d["llm_action"] != "uncertain"
        and d.get("expected_action")
    )
    uncertain = sum(1 for d in data if d.get("llm_action") == "uncertain")

    print(f"评分失败（uncertain）：{uncertain} 条")
    if scoreable > 0:
        print(f"准确率（llm_action == expected_action）：{correct}/{scoreable} = {correct/scoreable*100:.1f}%")

    # 按 expected_action 分类准确率
    from collections import defaultdict
    by_expected: dict = defaultdict(lambda: {"correct": 0, "total": 0})
    for d in data:
        if d.get("llm_action") and d["llm_action"] != "uncertain" and d.get("expected_action"):
            ea = d["expected_action"]
            by_expected[ea]["total"] += 1
            if d["llm_action"] == ea:
                by_expected[ea]["correct"] += 1

    print("\n按 expected_action 分类准确率：")
    for action in ["keep", "review", "delete"]:
        stat = by_expected.get(action)
        if stat and stat["total"] > 0:
            pct = stat["correct"] / stat["total"] * 100
            print(f"  {action:8s}: {stat['correct']:3d}/{stat['total']:3d} = {pct:.1f}%")

    print(f"\n结果已写入：{DATASET_PATH}")


if __name__ == "__main__":
    run()
