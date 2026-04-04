#!/usr/bin/env python3
"""
generate_memories.py · 用 Claude Code 原版提取 Prompt 生成真实格式的记忆文件

用途：
  1. 在 Auto Memory 功能未开放时，生成格式完全正确的记忆文件用于测试
  2. 覆盖所有质量类型（高质量/过时/低质量/冲突/记偏了），验证评分引擎
  3. 可传入自己的真实对话数据，同时产出 Benchmark 数据集条目

核心设计：
  - 复用 Claude Code 原版的记忆提取 Prompt 结构（不是我们自己设计的）
  - LLM 以「记忆提取 Agent」身份运行，输出格式与真实 Auto Memory 完全一致
  - 每 12 条消息一批（与 Claude Code 源码 ~12 messages 保持一致）

用法：
  # 使用内置场景数据，生成到默认目录
  python3 scripts/generate_memories.py

  # 指定输出目录
  python3 scripts/generate_memories.py --output /tmp/test_memories

  # 传入自己的对话数据（JSON 格式）
  python3 scripts/generate_memories.py --conversations /path/to/chats.json

  # 同时生成 Benchmark 数据集
  python3 scripts/generate_memories.py --benchmark

  # 只预览，不调 LLM（查看会处理哪些对话）
  python3 scripts/generate_memories.py --dry-run
"""

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.llm_client import create_client
from src.config import load_config


# ── 内置场景对话数据集 ─────────────────────────────────────────────────────────
# 精心设计，覆盖评分引擎需要识别的所有质量类型
# 场景设定：用户在用 Claude Code 做项目，但也会聊日常

BUILTIN_SCENARIOS = [

    # ── 高质量：稳定的用户偏好和背景 ──────────────────────────────────────────
    {
        "scenario_id": "user_background",
        "quality_label": "高质量",
        "expected_action": "keep",
        "age_days": 3,
        "messages": [
            {"role": "user", "content": "帮我解释一下这段 Python 代码"},
            {"role": "assistant", "content": "我来解释一下这段代码的逻辑..."},
            {"role": "user", "content": "我用 Python 已经七八年了，不用解释太基础的东西，直接说设计思路就行"},
            {"role": "assistant", "content": "了解，你有丰富的 Python 经验，我直接说重点..."},
            {"role": "user", "content": "对，这样更好。另外我现在在做机器学习方向的研究，主要关注模型可解释性"},
            {"role": "assistant", "content": "好的，我会记住你的背景，后续解释会结合可解释性角度..."},
        ],
    },
    {
        "scenario_id": "feedback_response_style",
        "quality_label": "高质量",
        "expected_action": "keep",
        "age_days": 5,
        "messages": [
            {"role": "user", "content": "帮我写一个总结"},
            {"role": "assistant", "content": "好的，以下是总结：...\n\n总结来说，主要有三点：第一点..."},
            {"role": "user", "content": "不要在结尾再重复总结一遍，我刚看完正文，不需要再来一遍"},
            {"role": "assistant", "content": "明白了，以后不在结尾加总结段落"},
            {"role": "user", "content": "对，直接结束就好"},
            {"role": "assistant", "content": "收到"},
        ],
    },
    {
        "scenario_id": "feedback_communication_preference",
        "quality_label": "高质量",
        "expected_action": "keep",
        "age_days": 7,
        "messages": [
            {"role": "user", "content": "你能不能每次回答之前先给我一个结论，再展开解释？"},
            {"role": "assistant", "content": "当然可以，我会先说结论，再展开细节"},
            {"role": "user", "content": "对，就是「先结论后解释」这个顺序，我习惯这样读"},
            {"role": "assistant", "content": "好的，我记住了"},
            {"role": "user", "content": "之前你帮我的那几个问题回答得很好，就是这个风格"},
            {"role": "assistant", "content": "明白，这个沟通方式确实更高效"},
        ],
    },

    # ── 过时：project 类型，设置为 100 天前 ──────────────────────────────────
    {
        "scenario_id": "stale_project_deadline",
        "quality_label": "过时",
        "expected_action": "delete",
        "age_days": 100,
        "messages": [
            {"role": "user", "content": "我现在在做一个电商数据分析项目，要在三月底前交付"},
            {"role": "assistant", "content": "了解，三月底有截止日期，我会在建议中考虑这个时间约束"},
            {"role": "user", "content": "对，客户是一家零售连锁，主要分析他们的库存周转率"},
            {"role": "assistant", "content": "好的，零售行业的库存周转分析，三月底交付"},
            {"role": "user", "content": "我现在在用 Pandas 处理数据，量大概是两年的销售记录"},
            {"role": "assistant", "content": "两年销售数据用 Pandas 处理，我会考虑性能优化方向"},
        ],
    },
    {
        "scenario_id": "stale_project_status",
        "quality_label": "过时",
        "expected_action": "delete",
        "age_days": 95,
        "messages": [
            {"role": "user", "content": "我这周在做 Step 2 的开发，就是记忆文件读取那部分"},
            {"role": "assistant", "content": "了解，你在开发记忆文件读取模块"},
            {"role": "user", "content": "预计这周能完成，下周开始做评分引擎"},
            {"role": "assistant", "content": "好的，记忆读取本周完成，下周评分引擎"},
            {"role": "user", "content": "主要挑战是处理 frontmatter 格式的边界情况"},
            {"role": "assistant", "content": "frontmatter 解析的边界情况确实需要仔细处理"},
        ],
    },

    # ── 低质量：临时状态，随口一说 ────────────────────────────────────────────
    {
        "scenario_id": "low_quality_temp_state",
        "quality_label": "低质量（临时状态）",
        "expected_action": "delete",
        "age_days": 20,
        "messages": [
            {"role": "user", "content": "今天我状态不好，头疼，能不能给简单点的解释"},
            {"role": "assistant", "content": "当然，我用最简单的方式说..."},
            {"role": "user", "content": "嗯好多了，谢谢"},
            {"role": "assistant", "content": "不客气，有什么需要继续问"},
            {"role": "user", "content": "就这些了，我去休息一下"},
            {"role": "assistant", "content": "好的，保重"},
        ],
    },
    {
        "scenario_id": "low_quality_random_thought",
        "quality_label": "低质量（随口想法）",
        "expected_action": "delete",
        "age_days": 15,
        "messages": [
            {"role": "user", "content": "突然想到一个功能，可以加个「一键体检」按钮"},
            {"role": "assistant", "content": "这个想法不错，可以作为功能点考虑"},
            {"role": "user", "content": "就是随便想想，不一定做"},
            {"role": "assistant", "content": "了解，先记下来以后看情况"},
            {"role": "user", "content": "嗯，先把现在的做完再说"},
            {"role": "assistant", "content": "明白，当前任务优先"},
        ],
    },

    # ── 冲突：两段对话描述相反的偏好 ─────────────────────────────────────────
    {
        "scenario_id": "conflict_a_detailed",
        "quality_label": "冲突（详细派）",
        "expected_action": "review",
        "age_days": 20,
        "messages": [
            {"role": "user", "content": "你能不能代码注释写详细一点，我想方便以后回顾"},
            {"role": "assistant", "content": "好的，我会给每段逻辑加详细注释"},
            {"role": "user", "content": "对，每一行最好都说明一下在做什么"},
            {"role": "assistant", "content": "明白，行级注释可以帮助理解"},
            {"role": "user", "content": "特别是一些非直觉的操作，一定要说明原因"},
            {"role": "assistant", "content": "了解，重点注释非直觉的逻辑和原因"},
        ],
    },
    {
        "scenario_id": "conflict_b_concise",
        "quality_label": "冲突（简洁派）",
        "expected_action": "review",
        "age_days": 8,
        "messages": [
            {"role": "user", "content": "注释太多了，代码看起来很乱，能不能少写一点"},
            {"role": "assistant", "content": "好的，我减少注释量，保持代码简洁"},
            {"role": "user", "content": "对，只在真正复杂的地方加注释就好，其他地方代码自己说话"},
            {"role": "assistant", "content": "明白，注释要有价值，不解释显而易见的逻辑"},
            {"role": "user", "content": "之前那种每行一个注释的风格我真的很难看"},
            {"role": "assistant", "content": "了解，以后只在关键逻辑处加注释"},
        ],
    },

    # ── 记偏了：AI 过度解读单次表述 ──────────────────────────────────────────
    {
        "scenario_id": "accuracy_issue_night_owl",
        "quality_label": "记偏了（过度解读）",
        "expected_action": "review",
        "age_days": 6,
        "messages": [
            {"role": "user", "content": "昨晚写代码写到两点才睡，今天有点累"},
            {"role": "assistant", "content": "理解，熬夜写代码确实消耗大"},
            {"role": "user", "content": "有时候灵感来了就停不下来"},
            {"role": "assistant", "content": "创作状态好的时候确实容易忘记时间"},
            {"role": "user", "content": "好，继续问你问题"},
            {"role": "assistant", "content": "好的，随时"},
        ],
    },

    # ── 日常生活场景（来自 Chatbot 典型场景）─────────────────────────────────
    {
        "scenario_id": "daily_life_food_preference",
        "quality_label": "高质量（日常偏好）",
        "expected_action": "keep",
        "age_days": 10,
        "messages": [
            {"role": "user", "content": "帮我推荐一些食谱"},
            {"role": "assistant", "content": "你有什么饮食偏好或限制吗？"},
            {"role": "user", "content": "我不吃辣，对香菜过敏，平时比较喜欢清淡的"},
            {"role": "assistant", "content": "了解，推荐清淡、不辣、无香菜的食谱..."},
            {"role": "user", "content": "对，就是这类型，另外我在减脂，低热量优先"},
            {"role": "assistant", "content": "好的，清淡低热量，不辣不含香菜"},
        ],
    },
    {
        "scenario_id": "daily_life_ephemeral",
        "quality_label": "低质量（日常临时）",
        "expected_action": "delete",
        "age_days": 30,
        "messages": [
            {"role": "user", "content": "今天下午有个重要会议，帮我想想要注意什么"},
            {"role": "assistant", "content": "会议前要做好准备..."},
            {"role": "user", "content": "好的谢谢，就这些了"},
            {"role": "assistant", "content": "会议顺利"},
            {"role": "user", "content": "嗯，回头再说"},
            {"role": "assistant", "content": "好的"},
        ],
    },
]


# ── 提取 Prompt 模板（复用 Claude Code 原版结构）─────────────────────────────

EXTRACTION_SYSTEM_PROMPT = """You are now acting as the memory extraction subagent. Analyze the conversation messages provided and extract information worth saving as persistent memories.

You MUST only use content from the provided messages. Do not invent or infer beyond what is explicitly stated.

## Types of memory

There are several discrete types of memory that you can store in your memory system:

<types>
<type>
    <name>user</name>
    <description>Contain information about the user's role, goals, responsibilities, and knowledge. Great user memories help you tailor your future behavior to the user's preferences and perspective.</description>
    <when_to_save>When you learn any details about the user's role, preferences, responsibilities, or knowledge</when_to_save>
</type>
<type>
    <name>feedback</name>
    <description>Guidance the user has given about how to approach work — both what to avoid and what to keep doing.</description>
    <when_to_save>Any time the user corrects your approach OR confirms a non-obvious approach worked.</when_to_save>
    <body_structure>Lead with the rule itself, then a **Why:** line and a **How to apply:** line.</body_structure>
</type>
<type>
    <name>project</name>
    <description>Information about ongoing work, goals, initiatives, or deadlines not derivable from other sources.</description>
    <when_to_save>When you learn who is doing what, why, or by when.</when_to_save>
    <body_structure>Lead with the fact or decision, then a **Why:** line and a **How to apply:** line.</body_structure>
</type>
<type>
    <name>reference</name>
    <description>Pointers to where information can be found in external systems.</description>
    <when_to_save>When you learn about resources in external systems and their purpose.</when_to_save>
</type>
</types>

## What NOT to save in memory

- Code patterns, conventions, architecture, file paths, or project structure
- Git history, recent changes, or who-changed-what
- Debugging solutions or fix recipes
- Ephemeral task details: in-progress work, temporary state, current conversation context
- One-time events that won't recur (today's meeting, current headache, etc.)

## Output format

Output a JSON array. Each element represents one memory file to create:

```json
[
  {
    "filename": "user_background.md",
    "frontmatter": {
      "name": "User background and expertise",
      "description": "One-line description used to decide relevance",
      "type": "user"
    },
    "body": "Full memory content here.\\n\\n**Why:** reason\\n**How to apply:** guidance"
  }
]
```

Rules:
- filename must be snake_case.md
- description must be specific and under 150 characters
- body for feedback/project types MUST include **Why:** and **How to apply:** lines
- If nothing is worth saving, return an empty array []
- Do NOT include ephemeral or temporary information
"""

EXTRACTION_USER_TEMPLATE = """Here are the conversation messages to analyze:

{messages_text}

Extract any information worth saving as persistent memories. Output JSON only, no other text."""


# ── 数据结构 ───────────────────────────────────────────────────────────────────

@dataclass
class GeneratedMemory:
    """一条生成的记忆文件。"""
    filename: str
    frontmatter: dict
    body: str
    scenario_id: str
    quality_label: str
    expected_action: str
    age_days: int


@dataclass
class GenerationResult:
    """generate_memories() 的完整返回值。"""
    memories: list[GeneratedMemory]
    benchmark_entries: list[dict]
    skipped_scenarios: list[str]    # 未提取到任何记忆的场景
    api_calls: int


# ── 核心生成逻辑 ──────────────────────────────────────────────────────────────

def format_messages_for_prompt(messages: list[dict]) -> str:
    """把消息列表格式化为 prompt 输入文本。"""
    lines = []
    for i, msg in enumerate(messages):
        role = "User" if msg["role"] == "user" else "Assistant"
        lines.append(f"[{i+1}] {role}: {msg['content']}")
    return "\n".join(lines)


def extract_memories_from_conversation(
    scenario: dict,
    client,
    dry_run: bool = False,
) -> list[GeneratedMemory]:
    """
    对单个场景对话运行提取 Prompt，返回生成的记忆列表。
    """
    scenario_id = scenario["scenario_id"]
    quality_label = scenario["quality_label"]
    expected_action = scenario["expected_action"]
    age_days = scenario.get("age_days", 0)
    messages = scenario["messages"]

    if dry_run:
        print(f"  [DRY RUN] 跳过 API 调用：{scenario_id}")
        return []

    messages_text = format_messages_for_prompt(messages)
    user_msg = EXTRACTION_USER_TEMPLATE.format(messages_text=messages_text)

    response = client.complete(
        system=EXTRACTION_SYSTEM_PROMPT,
        user=user_msg,
        max_tokens=2048,
    )

    # 解析 JSON 输出
    raw = response.content.strip()
    # 去掉 <think> 标签（思考模型）
    raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
    # 去掉 markdown 代码块
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(l for l in lines if not l.strip().startswith("```")).strip()

    try:
        memory_list = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"  ⚠️  {scenario_id}: JSON 解析失败 ({e})")
        print(f"     原始输出前 200 字符：{raw[:200]}")
        return []

    if not isinstance(memory_list, list):
        print(f"  ⚠️  {scenario_id}: 返回值不是列表")
        return []

    results = []
    for item in memory_list:
        if not isinstance(item, dict):
            continue
        filename = item.get("filename", f"{scenario_id}.md")
        fm = item.get("frontmatter", {})
        body = item.get("body", "")

        if not fm.get("name") or not fm.get("type"):
            print(f"  ⚠️  {scenario_id}: 记忆缺少必要字段，跳过")
            continue

        results.append(GeneratedMemory(
            filename=filename,
            frontmatter=fm,
            body=body,
            scenario_id=scenario_id,
            quality_label=quality_label,
            expected_action=expected_action,
            age_days=age_days,
        ))

    return results


# ── 文件写入 ──────────────────────────────────────────────────────────────────

def write_memory_file(memory: GeneratedMemory, output_dir: Path) -> Path:
    """把一条记忆写成 .md 文件，设置正确的 mtime。"""
    output_dir.mkdir(parents=True, exist_ok=True)

    # 构建 frontmatter + 正文
    fm = memory.frontmatter
    lines = [
        "---",
        f"name: {fm.get('name', '')}",
        f"description: {fm.get('description', '')}",
        f"type: {fm.get('type', 'user')}",
        "---",
        "",
        memory.body.strip(),
        "",
    ]
    content = "\n".join(lines)

    file_path = output_dir / memory.filename
    file_path.write_text(content, encoding="utf-8")

    # 设置文件修改时间为 age_days 天前
    old_time = time.time() - memory.age_days * 86400
    os.utime(file_path, (old_time, old_time))

    return file_path


def write_memory_index(memories: list[GeneratedMemory], output_dir: Path) -> None:
    """生成 MEMORY.md 索引文件。"""
    lines = []
    for m in memories:
        name = m.frontmatter.get("name", m.filename)
        desc = m.frontmatter.get("description", "")
        hook = desc[:100] if desc else f"[{m.quality_label}]"
        lines.append(f"- [{name}]({m.filename}) — {hook}")

    index_path = output_dir / "MEMORY.md"
    index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── Benchmark 输出 ────────────────────────────────────────────────────────────

def build_benchmark_entry(memory: GeneratedMemory) -> dict:
    """把生成的记忆转成 Benchmark 数据集条目。"""
    fm = memory.frontmatter
    body = memory.body

    # 重组完整记忆内容（frontmatter + body）
    full_content = (
        f"---\nname: {fm.get('name','')}\n"
        f"description: {fm.get('description','')}\n"
        f"type: {fm.get('type','user')}\n---\n\n"
        f"{body}"
    )

    return {
        "id": f"gen_{memory.scenario_id}_{memory.filename.replace('.md','')}",
        "source": "generated_from_claude_code_prompt",
        "scenario_id": memory.scenario_id,
        "quality_label": memory.quality_label,
        "expected_action": memory.expected_action,
        "memory_type": fm.get("type"),
        "age_days": memory.age_days,
        "content": full_content,
        "human_scores": {
            "importance": None,   # 待人工标注
            "recency": None,
            "credibility": None,
            "accuracy": None,
        },
        "notes": f"自动生成，场景：{memory.quality_label}，预期动作：{memory.expected_action}",
    }


# ── 主入口 ─────────────────────────────────────────────────────────────────────

def generate_memories(
    scenarios: list[dict],
    output_dir: Path,
    benchmark_path: Optional[Path] = None,
    dry_run: bool = False,
) -> GenerationResult:
    """
    对所有场景运行提取，生成记忆文件和 Benchmark 条目。
    """
    if not dry_run:
        client = create_client(load_config())
    else:
        client = None

    all_memories: list[GeneratedMemory] = []
    benchmark_entries: list[dict] = []
    skipped: list[str] = []
    api_calls = 0

    total = len(scenarios)
    for i, scenario in enumerate(scenarios):
        sid = scenario["scenario_id"]
        label = scenario["quality_label"]
        print(f"\n[{i+1}/{total}] 处理场景：{sid} ({label})")

        memories = extract_memories_from_conversation(scenario, client, dry_run)

        if not memories:
            if not dry_run:
                print(f"  ℹ️  未提取到记忆（LLM 判断无值得保存的内容）")
                skipped.append(sid)
            api_calls += 1
            continue

        api_calls += 1
        for m in memories:
            print(f"  ✅ 生成：{m.filename} [{m.frontmatter.get('type')}]")

            if not dry_run:
                write_memory_file(m, output_dir)
                all_memories.append(m)
                benchmark_entries.append(build_benchmark_entry(m))

    # 写 MEMORY.md 索引
    if all_memories:
        write_memory_index(all_memories, output_dir)
        print(f"\n✅ 已生成 MEMORY.md 索引（{len(all_memories)} 条）")

    # 写 Benchmark 文件
    if benchmark_path and benchmark_entries:
        benchmark_path.parent.mkdir(parents=True, exist_ok=True)
        # 合并已有条目（如果存在）
        existing = []
        if benchmark_path.exists():
            try:
                existing = json.loads(benchmark_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        existing_ids = {e["id"] for e in existing}
        new_entries = [e for e in benchmark_entries if e["id"] not in existing_ids]
        merged = existing + new_entries

        benchmark_path.write_text(
            json.dumps(merged, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"✅ Benchmark 数据集：新增 {len(new_entries)} 条（总计 {len(merged)} 条）")
        print(f"   路径：{benchmark_path}")

    return GenerationResult(
        memories=all_memories,
        benchmark_entries=benchmark_entries,
        skipped_scenarios=skipped,
        api_calls=api_calls,
    )


# ── CLI 入口 ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="用 Claude Code 原版提取 Prompt 生成真实格式的记忆文件"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("/tmp/generated_memories"),
        help="记忆文件输出目录（默认：/tmp/generated_memories）",
    )
    parser.add_argument(
        "--conversations",
        type=Path,
        default=None,
        help=(
            "自定义对话数据文件（JSON 格式）。\n"
            "格式：[{\"scenario_id\":\"...\", \"quality_label\":\"...\", "
            "\"expected_action\":\"keep/review/delete\", \"age_days\":0, "
            "\"messages\":[{\"role\":\"user\",\"content\":\"...\"},...]}]"
        ),
    )
    parser.add_argument(
        "--benchmark",
        action="store_true",
        help="同时生成 Benchmark 数据集条目（写入 benchmark/dataset.json）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只预览要处理的场景，不调 LLM，不写文件",
    )
    parser.add_argument(
        "--list-scenarios",
        action="store_true",
        help="列出所有内置场景，不执行生成",
    )

    args = parser.parse_args()

    # 列出内置场景
    if args.list_scenarios:
        print(f"\n内置场景列表（共 {len(BUILTIN_SCENARIOS)} 个）：\n")
        for s in BUILTIN_SCENARIOS:
            print(f"  {s['scenario_id']:<40} [{s['quality_label']}]  预期：{s['expected_action']}")
        return

    # 加载对话数据
    if args.conversations:
        try:
            scenarios = json.loads(args.conversations.read_text(encoding="utf-8"))
            print(f"✅ 从 {args.conversations} 加载了 {len(scenarios)} 个场景")
        except Exception as e:
            print(f"❌ 读取对话文件失败：{e}")
            sys.exit(1)
    else:
        scenarios = BUILTIN_SCENARIOS
        print(f"使用内置场景数据（{len(scenarios)} 个场景）")

    # Benchmark 输出路径
    benchmark_path = None
    if args.benchmark:
        benchmark_path = Path(__file__).parent.parent / "benchmark" / "dataset.json"

    # 打印运行信息
    print(f"\n{'='*60}")
    print(f"Memory Generator — 记忆文件生成器")
    print(f"{'='*60}")
    print(f"模式：{'DRY RUN（不调 LLM）' if args.dry_run else '完整生成'}")
    print(f"输出目录：{args.output}")
    print(f"场景数量：{len(scenarios)}")
    if args.benchmark:
        print(f"Benchmark：{benchmark_path}")
    print()

    # 执行生成
    result = generate_memories(
        scenarios=scenarios,
        output_dir=args.output,
        benchmark_path=benchmark_path,
        dry_run=args.dry_run,
    )

    # 打印摘要
    print(f"\n{'='*60}")
    print(f"生成摘要")
    print(f"{'='*60}")
    if not args.dry_run:
        print(f"生成记忆文件：{len(result.memories)} 条")
        print(f"API 调用次数：{result.api_calls} 次")

        if result.skipped_scenarios:
            print(f"未提取到记忆：{len(result.skipped_scenarios)} 个场景")
            for s in result.skipped_scenarios:
                print(f"  - {s}")

        # 按质量分类统计
        by_expected = {}
        for m in result.memories:
            by_expected.setdefault(m.expected_action, []).append(m.filename)
        for action, files in sorted(by_expected.items()):
            icon = {"keep": "✅", "review": "🔄", "delete": "🗑 "}.get(action, "❓")
            print(f"\n{icon} 预期 {action.upper()}（{len(files)} 条）：")
            for f in files:
                print(f"  - {f}")

        print(f"\n✅ 记忆文件已写入：{args.output}")
        print(f"\n下一步：用这些文件测试 MCP 插件")
        print(f"  export MINIMAX_API_KEY=your_key")
        print(f"  .venv/bin/python scripts/test_live.py --dir {args.output}")
    else:
        print(f"DRY RUN 完成，共 {len(scenarios)} 个场景待处理")
        print(f"去掉 --dry-run 参数即可实际生成")


if __name__ == "__main__":
    main()
