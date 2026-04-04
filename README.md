# Memory Quality MCP

给 Claude Code 的记忆层加一个「体检」功能——告诉你现在记了什么、哪些该删、哪些冲突了、哪些记偏了。

## 为什么需要它

Claude Code v2.1.59 起，Auto Memory 默认开启：每次对话结束后 Claude 会自动把值得记住的内容写成 `.md` 文件。

随着时间推移，记忆库里会积累：
- **过时记忆**：「正在做 X 项目」「这周要完成 Y」——早就不准了
- **垃圾记忆**：随口一说被当成长期事实，低质量噪音
- **冲突记忆**：「喜欢简洁代码」和「要求注释详尽」同时存在
- **记偏的记忆**：AI 把一次临时状态过度解读成了固定偏好

这个插件对记忆库做四维质量评分（重要性 / 时效性 / 可信度 / 准确性），给出可执行的清理建议。

---

## 前提条件

- **Claude Code v2.1.59+**（`claude --version` 确认）
- **Python 3.10+**
- **LLM API Key**（OpenAI、Kimi、MiniMax、Anthropic 任选其一）

---

## 安装

### 方式一：uvx（推荐，无需手动安装）

在 Claude Code 的 MCP 配置文件里添加（`~/.claude/settings.json` 或项目下的 `.claude/settings.json`）：

```json
{
  "mcpServers": {
    "memory-quality": {
      "command": "uvx",
      "args": ["memory-quality-mcp"],
      "env": {
        "MINIMAX_API_KEY": "your-key-here"
      }
    }
  }
}
```

### 方式二：pip 安装

```bash
pip install memory-quality-mcp
```

然后在 MCP 配置里：

```json
{
  "mcpServers": {
    "memory-quality": {
      "command": "memory-quality-mcp",
      "env": {
        "OPENAI_API_KEY": "your-key-here"
      }
    }
  }
}
```

---

## 配置 API Key

插件支持多个模型提供商，通过环境变量配置 Key（推荐），或写入配置文件。

### 环境变量方式（推荐）

| 提供商 | 环境变量 | 默认模型 |
|--------|----------|---------|
| OpenAI | `OPENAI_API_KEY` | gpt-4o-mini |
| Kimi | `KIMI_API_KEY` | moonshot-v1-8k |
| MiniMax | `MINIMAX_API_KEY` | MiniMax-M2.5 |
| Anthropic | `ANTHROPIC_API_KEY` | claude-haiku-4-5 |

设置任意一个环境变量，插件会自动检测并使用对应的提供商。在 MCP 配置的 `env` 字段里传入即可（见上方安装示例），不需要设置系统环境变量。

### 配置文件方式

首次运行后，插件会在 `~/.memory-quality-mcp/config.yaml` 自动生成配置模板：

```yaml
provider: "minimax"   # openai / kimi / minimax / anthropic
model: ""             # 留空使用默认模型
```

---

## 使用方法

配置完成后，重启 Claude Code，在对话中直接调用：

### 1. 快速体检（不消耗 API）

```
帮我检查一下记忆库的健康状态
```

Claude 会调用 `memory_audit()`，返回：
- 所有项目的记忆总数
- 可能过时的数量
- 各项目索引使用率
- 预估详细分析需要的 API 调用次数

### 2. 详细质量分析

```
帮我详细分析一下记忆质量
```

Claude 会调用 `memory_report()`，对每条记忆进行四维评分，返回：
- 🗑 建议删除的条目（附原因）
- 🔄 建议复查的条目
- ⚡ 存在语义冲突的记忆对
- ✅ 质量良好的条目（verbose 模式）

> 费用参考：50 条记忆约调用 LLM 8-9 次，使用 gpt-4o-mini 约 $0.01。

### 3. 执行清理

```
帮我清理掉建议删除的那些记忆
```

Claude 会先调用 `memory_cleanup(dry_run=True)` 预览，确认后执行 `memory_cleanup(dry_run=False)`。

**安全机制**：
- 默认预览模式，不实际删除
- 删除前自动备份到 `.trash/<timestamp>/` 目录
- 绝不静默删除，每次都需要明确确认

### 4. 单条评分（调试用）

```
帮我评估这条记忆的质量：「用户喜欢在深夜写代码」
```

### 5. 只分析指定项目

```
帮我分析 ~/my-project 这个项目的记忆
```

---

## 四维评分说明

| 维度 | 权重 | 含义 |
|------|------|------|
| 重要性 | 40% | 这条记忆对未来对话有多大帮助 |
| 时效性 | 25% | 这条信息现在还准确吗 |
| 可信度 | 15% | 有没有明确的用户陈述作为来源 |
| 准确性 | 20% | AI 记录时有没有过度解读用户原意 |

综合分 > 3.5 → 保留 ｜ 2.5–3.5 → 建议复查 ｜ < 2.5 → 建议删除

---

## 典型对话示例

```
用户：帮我检查一下记忆质量

Claude：[调用 memory_audit()]
        你目前有 47 条记忆（跨 3 个项目）：
        - 可能过时：8 条
        - 建议优先审查（project 类型过时）：3 条
        - MEMORY.md 使用率：23%（46/200 行）

        预计详细分析需要调用 LLM 约 9 次。
        ▶ 运行 memory_report() 获取详细评分和清理建议

用户：帮我详细分析一下

Claude：[调用 memory_report()]
        ## 📊 记忆质量详细报告
        总计：47 条 | 🗑 删除 8 条 | 🔄 复查 5 条 | ✅ 保留 34 条

        ⚡ 发现 1 对冲突记忆
        - 🔴 feedback_code_style_a.md × feedback_code_style_b.md
          一条记「喜欢详细注释」，一条记「注释越少越好」，相互矛盾

        🗑 建议删除（8 条）
        - project_q1_plan.md [project] · 120 天前
          综合分：1.5 · project 类型已超过 90 天阈值，很可能已过时
        ...

        本次报告已缓存，cleanup 无需重新分析

用户：帮我清理掉建议删除的那些

Claude：[调用 memory_cleanup(dry_run=True)]
        🔍 预览模式（未执行任何删除）

        以下 8 条记忆将被删除：
          - project_q1_plan.md
          ...

        ▶ 确认清理请调用 memory_cleanup(dry_run=False)

用户：确认

Claude：[调用 memory_cleanup(dry_run=False)]
        ✅ 已清理 8 条
        备份位置：~/.claude/.../memory/.trash/20260404_143022/
        MEMORY.md 索引已同步更新
```

---

## 常见问题

**Q：提示「未找到记忆文件」**

需要 Claude Code v2.1.59+，且 Auto Memory 已开启。检查：
```bash
claude --version        # 确认版本 >= v2.1.59
ls ~/.claude/projects/  # 查看是否有项目记忆目录
```

如果版本足够新但还没有记忆文件，说明近期对话里 Claude 还没判断有值得记住的内容，属于正常情况，继续正常使用一段时间后会自动生成。

**Q：评分准确吗？**

评分仅供参考，最终决策权在你。所有删除操作都需要明确确认，且有备份。如果发现评分持续偏差，可以通过 `~/.memory-quality-mcp/config.yaml` 调整阈值。

**Q：支持哪些 LLM？**

支持所有 OpenAI 兼容接口的提供商。内置预设：OpenAI、Kimi、MiniMax、Anthropic。也可以通过 `base_url` 配置任意自定义提供商（`MEMORY_QUALITY_BASE_URL` 环境变量）。

**Q：会误删重要记忆吗？**

不会。所有删除操作：① 先预览 ② 需要明确确认 ③ 自动备份到 `.trash` 目录可手动恢复。

**Q：记忆文件在哪里？**

```bash
ls ~/.claude/projects/          # 列出所有项目
ls ~/.claude/projects/*/memory/ # 查看各项目记忆文件
```

也可以在 Claude Code 里直接输入 `/memory` 查看和编辑。

---

## 许可证

MIT
