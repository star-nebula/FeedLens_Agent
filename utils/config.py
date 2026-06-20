"""FeedLens 集中式配置加载模块。

加载 config/config.yaml，支持 ${ENV_VAR} 环境变量插值，带缓存。
所有模块统一通过此模块读取配置，消除 _load_config() 重复定义。

Usage:
    from utils.config import load_config
    config = load_config()
    api_key = config.get("llm", {}).get("deepseek", {}).get("api_key", "")
"""

import os
import re
import yaml
from typing import Any, Dict

from dotenv import load_dotenv

# 加载项目根目录的 .env 文件（幂等：仅在首次 import 时执行一次）
_env_loaded = False


def _ensure_dotenv():
    global _env_loaded
    if _env_loaded:
        return
    env_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        ".env",
    )
    if os.path.exists(env_path):
        load_dotenv(env_path)
    _env_loaded = True


_CONFIG_CACHE: Dict[str, Any] = {}

_ENV_VAR_PATTERN = re.compile(r'\$\{(\w+)\}')


def _expand_env_vars(value: Any) -> Any:
    """递归展开值中的 ${ENV_VAR} 引用。"""
    if isinstance(value, str):
        def _replacer(match):
            var_name = match.group(1)
            return os.environ.get(var_name, "")
        return _ENV_VAR_PATTERN.sub(_replacer, value)
    if isinstance(value, dict):
        return {k: _expand_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env_vars(item) for item in value]
    return value


def load_config() -> Dict[str, Any]:
    """加载 config/config.yaml，展开环境变量，带缓存。"""
    _ensure_dotenv()
    if "config" in _CONFIG_CACHE:
        return _CONFIG_CACHE["config"]

    config_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config",
    )
    config_path = os.path.join(config_dir, "config.yaml")

    if not os.path.exists(config_path):
        _CONFIG_CACHE["config"] = {}
        return {}

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    config = _expand_env_vars(config)
    _CONFIG_CACHE["config"] = config
    return config


def clear_cache():
    """清空配置缓存（测试用）。"""
    _CONFIG_CACHE.clear()
