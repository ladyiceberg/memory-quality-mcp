#!/usr/bin/env python3
"""
filter_type_a.py · 对 A 类数据做规则过滤

过滤规则：
  1. 纯遗忘：ai_mistake 以「遗忘/忘记/遗漏/重复询问」等开头，没有描述 AI 会主动输出的错误内容
  2. 小说/创作场景：涉及角色设定、世界观、剧情、OOC 等
  3. 游戏场景：王者荣耀、修仙、法宝等

用法：
  python3 benchmark/filter_type_a.py
"""

import csv, json, re
from pathlib import Path

csv.field_size_limit(10_000_000)

INPUT_FILE  = Path(__file__).parent / "精筛后数据.csv"
OUTPUT_FILE = Path(__file__).parent / "精筛后数据_A类过滤.csv"

# ── 过滤规则 ──────────────────────────────────────────────────────────────────

# 规则1：纯遗忘 — ai_mistake 只描述「遗忘后重复询问/无法匹配」，缺乏具体错误行为
# 判断逻辑：开头是遗忘类词语，且没有「推荐了X」「输出了X」「给出了X」等主动错误行为
FORGET_STARTS = re.compile(r'^(AI会遗忘|AI会忘记|AI会遗漏|AI遗忘|AI遗漏|后续.*重复询问|AI未记住|AI若未|AI如果遗漏|AI如果记错)')
ACTIVE_MISTAKE = re.compile(r'推荐|给出|输出|生成|发送|告诉|认为|判断|称呼|使用|提供|建议|写出|说出|表述|忽略.*导致')

def is_pure_forget(mistake: str) -> bool:
    if not FORGET_STARTS.search(mistake):
        return False
    # 有主动错误行为描述 → 不是纯遗忘，保留
    if ACTIVE_MISTAKE.search(mistake):
        return False
    return True

# 规则2：小说/创作场景
FICTION_KEYWORDS = re.compile(
    r'角色设定|世界观|剧情|OOC|梦境|小说创作|人物设定|连载|章节|设定.*矛盾|混淆.*设定|记错.*设定|'
    r'写错.*角色|遗忘.*设定|忘记.*设定|创作.*偏离|违背.*设定|核心设定|基础设定|后续创作'
)

# 规则3：游戏场景
GAME_KEYWORDS = re.compile(
    r'王者荣耀|三角洲行动|修仙|法宝|灵气|游戏.*段位|掌机|SteamDeck|烽火地带|畅玩服'
)

def should_filter_a(item: dict) -> tuple[bool, str]:
    reason  = item.get('reason', '')
    mistake = item.get('ai_mistake', '')
    combined = reason + mistake

    if is_pure_forget(mistake):
        return True, '纯遗忘：未描述主动错误行为'
    if FICTION_KEYWORDS.search(combined):
        return True, '小说/创作场景'
    if GAME_KEYWORDS.search(combined):
        return True, '游戏场景'
    return False, ''


# ── 主流程 ────────────────────────────────────────────────────────────────────

def main():
    with open(INPUT_FILE, newline='', encoding='utf-8-sig') as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames
        rows = list(reader)

    total_a = 0
    filtered_a = 0
    filter_stats = {}
    output_rows = []

    for row in rows:
        raw_v2     = re.sub(r'```json\s*|```\s*', '', row.get('记忆质量选择V2', '')).strip()
        raw_final  = row.get('记忆质量筛选final', '').strip()

        try:
            items    = json.loads(raw_v2)
            verdicts = json.loads(raw_final)
        except:
            output_rows.append(row)
            continue

        new_items    = []
        new_verdicts = []
        row_changed  = False

        for item, v in zip(items, verdicts):
            if item.get('type') == 'A' and v.get('verdict') == 'keep':
                total_a += 1
                drop, reason = should_filter_a(item)
                if drop:
                    filtered_a += 1
                    filter_stats[reason] = filter_stats.get(reason, 0) + 1
                    new_items.append(item)
                    new_verdicts.append({'verdict': 'drop', 'drop_reason': f'规则过滤：{reason}'})
                    row_changed = True
                    continue
            new_items.append(item)
            new_verdicts.append(v)

        if row_changed:
            row = dict(row)
            row['记忆质量筛选final'] = json.dumps(new_verdicts, ensure_ascii=False)

        output_rows.append(row)

    # 写出
    with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8-sig') as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)

    # 统计
    print(f'A 类 keep 总计：{total_a} 条')
    print(f'本次过滤：{filtered_a} 条')
    print(f'过滤后剩余：{total_a - filtered_a} 条\n')
    print('过滤原因分布：')
    for r, c in sorted(filter_stats.items(), key=lambda x: -x[1]):
        print(f'  [{c:3d}] {r}')
    print(f'\n✅ 已保存：{OUTPUT_FILE}')


if __name__ == '__main__':
    main()
