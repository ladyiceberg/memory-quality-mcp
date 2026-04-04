"""
llm_client.py · 统一的 LLM 调用层

支持所有 OpenAI 兼容接口的模型提供商：
  - OpenAI（gpt-4o-mini 等）
  - Anthropic（通过 openai 兼容接口 / 原生 SDK）
  - Kimi（api.moonshot.cn）
  - MiniMax（api.minimax.chat）
  - 其他任何 OpenAI 兼容提供商（配置 base_url 即可）

设计原则：
  - quality_engine.py 不感知具体厂商，只调用 LLMClient
  - 新增提供商只需要在 config.yaml 里改配置，不改代码
  - tool_use（结构化输出）用 JSON mode 实现，所有提供商统一
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml


# ── 预设提供商配置 ─────────────────────────────────────────────────────────────

PROVIDER_PRESETS = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY",
        "default_model": "gpt-4o-mini",
    },
    "anthropic": {
        # Anthropic 也提供 OpenAI 兼容接口
        "base_url": "https://api.anthropic.com/v1",
        "api_key_env": "ANTHROPIC_API_KEY",
        "default_model": "claude-haiku-4-5",
    },
    "kimi": {
        "base_url": "https://api.moonshot.cn/v1",
        "api_key_env": "KIMI_API_KEY",
        "default_model": "moonshot-v1-8k",
    },
    "minimax": {
        "base_url": "https://api.minimax.chat/v1",
        "api_key_env": "MINIMAX_API_KEY",
        "default_model": "MiniMax-M2.5",
    },
}


# ── 数据结构 ───────────────────────────────────────────────────────────────────

@dataclass
class LLMResponse:
    """统一的 LLM 响应格式，隐藏各厂商的差异。"""
    content: str          # 模型返回的文本内容
    parsed: Any           # 如果是 JSON 输出，解析后的对象；否则为 None


# ── 客户端 ─────────────────────────────────────────────────────────────────────

class LLMClient:
    """
    统一的 LLM 客户端，基于 openai SDK 的兼容层。

    所有 OpenAI 兼容的提供商（Kimi、MiniMax 等）都可以通过
    设置不同的 base_url 和 api_key 来使用。
    """

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str,
    ):
        from openai import OpenAI
        self.model = model
        self._client = OpenAI(api_key=api_key, base_url=base_url)

    def complete(
        self,
        system: str,
        user: str,
        json_schema: Optional[dict] = None,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        """
        发送一次对话请求。

        如果提供了 json_schema，使用 JSON mode 要求模型输出符合 schema 的 JSON。
        这是替代 Anthropic tool_use 的跨平台方案。

        Args:
            system: system prompt
            user: user message
            json_schema: 期望的 JSON 输出结构（用于结构化输出）
            max_tokens: 最大输出 token 数
        """
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        if json_schema:
            # 把 schema 注入 system prompt，兼容所有提供商
            # 不使用 response_format 参数（部分提供商不支持）
            schema_hint = (
                f"\n\n请严格按照以下 JSON schema 格式输出，不要输出任何其他文字：\n"
                f"```json\n{json.dumps(json_schema, ensure_ascii=False, indent=2)}\n```"
            )
            messages[0]["content"] = system + schema_hint

            response = self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=max_tokens,
            )
        else:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=max_tokens,
            )

        raw_content = response.choices[0].message.content or ""

        # 尝试解析 JSON
        parsed = None
        if json_schema:
            try:
                content = raw_content.strip()
                # 去掉思考模型的 <think>...</think> 推理过程（MiniMax、DeepSeek-R1 等）
                import re
                content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
                # 去掉 markdown 代码块包裹
                if content.startswith("```"):
                    lines = content.splitlines()
                    content = "\n".join(
                        l for l in lines
                        if not l.strip().startswith("```")
                    ).strip()
                parsed = json.loads(content)
            except (json.JSONDecodeError, ValueError):
                parsed = None

        return LLMResponse(content=raw_content, parsed=parsed)


# ── 工厂函数 ───────────────────────────────────────────────────────────────────


def create_client(config: Optional[dict] = None) -> LLMClient:
    """
    根据配置创建 LLMClient。

    配置读取优先级：
      1. 传入的 config 参数
      2. ~/.memory-quality-mcp/config.yaml（通过 src.config.load_config() 加载）
      3. 环境变量（OPENAI_API_KEY / KIMI_API_KEY / MINIMAX_API_KEY / ANTHROPIC_API_KEY）

    config.yaml 最简配置示例：

      # 使用 OpenAI
      provider: openai
      model: gpt-4o-mini

      # 使用 Kimi
      provider: kimi
      model: moonshot-v1-8k

      # 使用 MiniMax
      provider: minimax
      model: abab6.5s-chat

      # 自定义提供商（任何 OpenAI 兼容接口）
      provider: custom
      model: your-model-name
      base_url: https://your-api.com/v1
      api_key: your-key
    """
    if config is None:
        from src.config import load_config
        config = load_config()

    provider = config.get("provider", "").lower()
    model = config.get("model", "")
    base_url = config.get("base_url", "")
    api_key = config.get("api_key", "")

    # ── 从预设提供商解析配置 ──────────────────────────────────────────────────
    if provider in PROVIDER_PRESETS:
        preset = PROVIDER_PRESETS[provider]

        if not base_url:
            base_url = preset["base_url"]
        if not model:
            model = preset["default_model"]
        if not api_key:
            # 优先从环境变量读取
            api_key = os.environ.get(preset["api_key_env"], "")

    # ── 自动检测：没有配置 provider 时，按环境变量猜测 ────────────────────────
    if not provider or not api_key:
        api_key, base_url, model = _auto_detect(api_key, base_url, model)

    # ── 最终校验 ─────────────────────────────────────────────────────────────
    if not api_key:
        available_envs = [
            f"  {p.upper()}_API_KEY" if p != "anthropic" else "  ANTHROPIC_API_KEY"
            for p in PROVIDER_PRESETS
        ]
        raise ValueError(
            "未找到可用的 API Key。\n"
            "请在 config.yaml 中配置 provider 和 api_key，\n"
            "或设置以下任一环境变量：\n"
            + "\n".join(available_envs)
        )

    if not base_url:
        raise ValueError(
            f"未知的提供商：{provider}。\n"
            "请在 config.yaml 中设置 base_url，或使用预设提供商：\n"
            f"  {', '.join(PROVIDER_PRESETS.keys())}"
        )

    if not model:
        raise ValueError("未配置模型名称，请在 config.yaml 中设置 model 字段。")

    return LLMClient(model=model, api_key=api_key, base_url=base_url)


def _auto_detect(
    api_key: str,
    base_url: str,
    model: str,
) -> tuple[str, str, str]:
    """
    没有明确配置 provider 时，按环境变量自动检测可用的提供商。
    优先顺序：OpenAI → Kimi → MiniMax → Anthropic
    """
    for provider_name, preset in PROVIDER_PRESETS.items():
        env_key = os.environ.get(preset["api_key_env"], "")
        if env_key:
            return (
                env_key,
                base_url or preset["base_url"],
                model or preset["default_model"],
            )

    return api_key, base_url, model
