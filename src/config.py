"""
config.py · 统一的配置加载模块

解决 P1：config.yaml 在生产环境（uvx 安装后）找不到的问题。

配置读取优先级：
  1. 环境变量（最高优先级，方便 CI/CD 和 MCP 配置注入）
  2. ~/.memory-quality-mcp/config.yaml（用户配置文件，生产环境使用）
  3. 开发目录下的 config.yaml（仅开发时使用，Path(__file__)/../.. 的相对路径）

首次运行时，如果用户配置文件不存在，自动生成默认配置并打印提示。
"""

import os
from pathlib import Path
from typing import Any

import yaml


# ── 路径常量 ──────────────────────────────────────────────────────────────────

def get_user_config_dir() -> Path:
    """返回用户配置目录：~/.memory-quality-mcp/"""
    return Path.home() / ".memory-quality-mcp"


def get_user_config_path() -> Path:
    return get_user_config_dir() / "config.yaml"


def get_dev_config_path() -> Path:
    """开发时的 config.yaml（项目根目录下）"""
    return Path(__file__).parent.parent / "config.yaml"


# ── 默认配置模板 ──────────────────────────────────────────────────────────────

DEFAULT_CONFIG_TEMPLATE = """\
# Memory Quality MCP · 用户配置文件
# 位置：~/.memory-quality-mcp/config.yaml
#
# 修改说明：
#   1. 设置 provider 和对应的 API Key 环境变量
#   2. 其余参数保持默认即可
#
# 支持的模型提供商：
#   openai    → 设置环境变量 OPENAI_API_KEY
#   kimi      → 设置环境变量 KIMI_API_KEY      (api.moonshot.cn)
#   minimax   → 设置环境变量 MINIMAX_API_KEY   (api.minimax.chat)
#   anthropic → 设置环境变量 ANTHROPIC_API_KEY
#   custom    → 填写下方 base_url 和 api_key
#
# 不填 provider 时，自动检测已设置的环境变量。

provider: ""       # openai / kimi / minimax / anthropic / custom / 留空自动检测
model: ""          # 留空使用该 provider 的默认模型
# base_url: ""     # 仅 custom provider 需要
# api_key: ""      # 不推荐写在文件里，建议用环境变量

# ── 界面语言 ──────────────────────────────────────────────────────────────────

language: "auto"   # auto（跟随系统语言）/ en（英文）/ zh（中文）

# ── 评分参数（通常不需要修改）─────────────────────────────────────────────────

thresholds:
  delete: 2.5    # 综合分低于此值 → 建议删除
  review: 3.5    # 综合分低于此值 → 建议复查

weights:
  importance: 0.40
  recency: 0.25
  credibility: 0.15
  accuracy: 0.20

staleness_days:
  project_type: 90
  user_type: 180
  general: 90

batch_size: 6
trash_retention_days: 30
"""


# ── 环境变量覆盖 ──────────────────────────────────────────────────────────────

# 支持通过环境变量直接覆盖关键配置项，方便 MCP 客户端注入
ENV_OVERRIDES = {
    "MEMORY_QUALITY_PROVIDER":          ("provider", str),
    "MEMORY_QUALITY_MODEL":             ("model", str),
    "MEMORY_QUALITY_BASE_URL":          ("base_url", str),
    "MEMORY_QUALITY_API_KEY":           ("api_key", str),
    "MEMORY_QUALITY_DELETE_THRESHOLD":  ("thresholds.delete", float),
    "MEMORY_QUALITY_REVIEW_THRESHOLD":  ("thresholds.review", float),
    "MEMORY_QUALITY_BATCH_SIZE":        ("batch_size", int),
    "MEMORY_QUALITY_LANGUAGE":          ("language", str),
}


# ── 核心加载函数 ──────────────────────────────────────────────────────────────

_cached_config: dict | None = None


def load_config(force_reload: bool = False) -> dict:
    """
    加载配置，带缓存（避免每次调用都读文件）。

    优先级：
      1. 环境变量覆盖
      2. ~/.memory-quality-mcp/config.yaml（生产环境）
      3. 开发目录 config.yaml（仅本地开发）
      4. 内置默认值

    Args:
        force_reload: 强制重新读取文件，忽略缓存（测试用）
    """
    global _cached_config
    if _cached_config is not None and not force_reload:
        return _cached_config

    config = _load_from_file()
    config = _apply_env_overrides(config)
    _cached_config = config
    return config


def _load_from_file() -> dict:
    """按优先级读取配置文件。"""
    # 优先：用户配置目录
    user_path = get_user_config_path()
    if user_path.exists():
        try:
            with open(user_path, encoding="utf-8") as f:
                result = yaml.safe_load(f) or {}
            return result
        except Exception as e:
            print(f"[memory-quality-mcp] 警告：读取配置文件失败 ({user_path})：{e}")

    # 降级：开发目录（仅在开发环境有效）
    dev_path = get_dev_config_path()
    if dev_path.exists():
        try:
            with open(dev_path, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            pass

    # 两者都不存在：首次运行，生成默认配置
    _generate_default_config(user_path)
    return {}


def _generate_default_config(target_path: Path) -> None:
    """首次运行时自动生成默认配置文件。"""
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(DEFAULT_CONFIG_TEMPLATE, encoding="utf-8")
        print(
            f"\n[memory-quality-mcp] 已生成默认配置文件：{target_path}\n"
            "请编辑该文件设置你的模型提供商，或直接设置环境变量：\n"
            "  export OPENAI_API_KEY=sk-xxx       # 使用 OpenAI\n"
            "  export KIMI_API_KEY=sk-xxx          # 使用 Kimi\n"
            "  export MINIMAX_API_KEY=xxx          # 使用 MiniMax\n"
            "  export ANTHROPIC_API_KEY=sk-xxx     # 使用 Anthropic\n"
        )
    except OSError as e:
        print(f"[memory-quality-mcp] 警告：无法生成配置文件：{e}")


def _apply_env_overrides(config: dict) -> dict:
    """
    把环境变量覆盖写入配置 dict。
    支持点号路径（如 "thresholds.delete"）。
    """
    result = dict(config)
    for env_key, (config_path, converter) in ENV_OVERRIDES.items():
        env_val = os.environ.get(env_key)
        if not env_val:
            continue
        try:
            converted = converter(env_val)
        except (ValueError, TypeError):
            continue

        # 处理嵌套路径
        parts = config_path.split(".")
        if len(parts) == 1:
            result[parts[0]] = converted
        elif len(parts) == 2:
            if parts[0] not in result or not isinstance(result[parts[0]], dict):
                result[parts[0]] = {}
            result[parts[0]][parts[1]] = converted

    return result


def get_config_location() -> str:
    """返回当前实际使用的配置文件路径（用于调试显示）。"""
    if get_user_config_path().exists():
        return str(get_user_config_path())
    if get_dev_config_path().exists():
        return str(get_dev_config_path()) + " (开发模式)"
    return "（使用内置默认值）"


def detect_language() -> str:
    """
    检测应使用的界面语言。

    优先级：
      1. config.yaml 中的 language 字段（或环境变量 MEMORY_QUALITY_LANGUAGE）
      2. 系统 locale（LANG / LC_ALL / LANGUAGE 环境变量）
      3. 默认英文

    返回：
      "en" 或 "zh"
    """
    config = load_config()
    lang_setting = config.get("language", "auto").strip().lower()

    # 用户明确指定了语言
    if lang_setting in ("en", "zh"):
        return lang_setting

    # auto 模式：读系统 locale
    if lang_setting == "auto":
        for env_var in ("LANG", "LC_ALL", "LANGUAGE"):
            locale_val = os.environ.get(env_var, "")
            if locale_val.lower().startswith("zh"):
                return "zh"
        # locale 不是中文，或未设置 → 英文
        return "en"

    # 配置值无法识别 → 降级英文
    return "en"
