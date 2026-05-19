"""配置管理 API — 支持分节读写、敏感字段脱敏、YAML 持久化"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from vir_bot.config import get_config, get_config_path, load_config

router = APIRouter()

# =============================================================================
# 敏感字段定义：字段路径 → 环境变量名（None 表示无对应 env var）
# =============================================================================

SENSITIVE_FIELDS: dict[str, str | None] = {
    "ai.openai.api_key": "VIRBOT_OPENAI_KEY",
    "platforms.qq.access_token": "VIRBOT_QQ_TOKEN",
    "platforms.qq_official.app_secret": None,
    "platforms.wechat.wechat_work.corp_secret": None,
    "platforms.wechat.wechat_work.token": None,
    "platforms.wechat.wechat_work.encoding_aes_key": None,
    "platforms.discord.bot_token": "VIRBOT_DISCORD_TOKEN",
    "platforms.telegram.bot_token": None,
    "mcp.hardware.mqtt.password": None,
    "web_console.auth.token": "VIRBOT_CONSOLE_TOKEN",
    "voice.asr.api_key": None,
}

# 配置节名称 → YAML 中的 key 映射
SECTION_KEYS = {
    "app": "app",
    "ai": "ai",
    "character": "character",
    "expression": "expression",
    "memory": "memory",
    "platforms": "platforms",
    "pipeline": "pipeline",
    "mcp": "mcp",
    "voice": "voice",
    "visual": "visual",
    "web_console": "web_console",
    "security": "security",
    "proactive": "proactive",
}

MASK_SET = "***已设置***"
MASK_UNSET = "***未设置***"


# =============================================================================
# 工具函数
# =============================================================================


def _get_nested(data: dict, dotted_key: str) -> Any:
    """通过点分路径获取嵌套字典的值"""
    keys = dotted_key.split(".")
    current = data
    for k in keys:
        if not isinstance(current, dict) or k not in current:
            return None
        current = current[k]
    return current


def _set_nested(data: dict, dotted_key: str, value: Any) -> None:
    """通过点分路径设置嵌套字典的值"""
    keys = dotted_key.split(".")
    current = data
    for k in keys[:-1]:
        if k not in current or not isinstance(current[k], dict):
            current[k] = {}
        current = current[k]
    current[keys[-1]] = value


def _mask_sensitive(data: dict, prefix: str = "") -> dict:
    """递归脱敏：将敏感字段的值替换为掩码"""
    result = {}
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            result[key] = _mask_sensitive(value, path)
        elif path in SENSITIVE_FIELDS:
            result[key] = MASK_SET if value else MASK_UNSET
        else:
            result[key] = value
    return result


def _strip_sensitive_from_update(data: dict, prefix: str = "") -> dict:
    """从更新数据中移除敏感字段（不允许通过 API 写入）"""
    result = {}
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        if path in SENSITIVE_FIELDS:
            continue  # 跳过敏感字段
        if isinstance(value, dict):
            cleaned = _strip_sensitive_from_update(value, path)
            if cleaned:  # 只保留非空子字典
                result[key] = cleaned
        else:
            result[key] = value
    return result


def _read_yaml() -> dict:
    """读取当前 config.yaml 原始内容"""
    config_path = get_config_path()
    if not config_path.exists():
        return {}
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _write_yaml(data: dict) -> None:
    """写入 config.yaml（写前备份）"""
    config_path = get_config_path()
    if config_path.exists():
        shutil.copy2(config_path, config_path.with_suffix(".yaml.bak"))
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


# =============================================================================
# Response Models
# =============================================================================


class AIStatusResponse(BaseModel):
    provider: str
    model: str
    healthy: bool


# =============================================================================
# 原有端点（保持兼容）
# =============================================================================


@router.get("/")
async def get_config_values():
    """获取当前配置摘要（敏感字段脱敏）"""
    config = get_config()
    return {
        "app": {"name": config.app.name, "version": config.app.version, "debug": config.app.debug},
        "ai": {
            "provider": config.ai.provider,
            "model": _get_current_model(config),
        },
        "platforms": {
            "qq": {"enabled": config.platforms.qq.enabled},
            "qq_official": {"enabled": config.platforms.qq_official.enabled},
            "wechat": {"enabled": config.platforms.wechat.enabled},
            "discord": {"enabled": config.platforms.discord.enabled},
            "telegram": {"enabled": config.platforms.telegram.enabled},
        },
        "web_console": {
            "host": config.web_console.host,
            "port": config.web_console.port,
        },
        "mcp": {"enabled": config.mcp.enabled},
        "voice": {"enabled": config.voice.enabled},
        "visual": {"enabled": config.visual.enabled},
    }


@router.get("/ai/status", response_model=AIStatusResponse)
async def get_ai_status():
    from vir_bot.core.ai_provider import AIProviderFactory

    config = get_config()
    provider = AIProviderFactory.create(config.ai)
    healthy = await provider.health_check()
    return AIStatusResponse(
        provider=config.ai.provider,
        model=provider.model_name,
        healthy=healthy,
    )


@router.post("/ai/switch")
async def switch_ai_provider(provider: str):
    """切换 AI Provider（临时，不持久化）"""
    from vir_bot.core.ai_provider import AIProviderFactory

    config = get_config()
    if provider not in ["ollama", "openai", "local_model"]:
        raise HTTPException(status_code=400, detail=f"未知 Provider: {provider}")
    config.ai.provider = provider
    await AIProviderFactory.create(config.ai).health_check()
    return {"status": "ok", "provider": provider}


# =============================================================================
# 新端点：分节配置读写
# =============================================================================


@router.get("/sections")
async def get_all_sections():
    """获取所有配置节（敏感字段脱敏）"""
    raw = _read_yaml()
    masked = _mask_sensitive(raw)
    return {"sections": masked}


@router.get("/sections/{section}")
async def get_section(section: str):
    """获取单个配置节（敏感字段脱敏）"""
    if section not in SECTION_KEYS:
        raise HTTPException(status_code=404, detail=f"未知配置节: {section}")

    yaml_key = SECTION_KEYS[section]
    raw = _read_yaml()
    section_data = raw.get(yaml_key)
    if section_data is None:
        raise HTTPException(status_code=404, detail=f"配置节 '{section}' 不存在")

    if isinstance(section_data, dict):
        return {"section": section, "data": _mask_sensitive(section_data, yaml_key)}
    return {"section": section, "data": section_data}


@router.put("/sections/{section}")
async def update_section(section: str, body: dict[str, Any]):
    """更新单个配置节（写回 config.yaml，敏感字段自动过滤）"""
    if section not in SECTION_KEYS:
        raise HTTPException(status_code=404, detail=f"未知配置节: {section}")

    yaml_key = SECTION_KEYS[section]
    raw = _read_yaml()

    # 过滤掉敏感字段
    cleaned = _strip_sensitive_from_update(body, yaml_key)
    if not cleaned:
        return {"status": "skipped", "message": "没有可更新的非敏感字段"}

    # 深度合并：只更新传入的字段，保留其他字段
    if yaml_key not in raw or not isinstance(raw[yaml_key], dict):
        raw[yaml_key] = cleaned
    else:
        _deep_merge(raw[yaml_key], cleaned)

    _write_yaml(raw)

    # 重新加载配置到内存
    load_config(get_config_path())

    return {"status": "ok", "updated_fields": list(cleaned.keys())}


@router.get("/sensitive-fields")
async def get_sensitive_fields():
    """返回所有敏感字段路径列表"""
    return {"fields": list(SENSITIVE_FIELDS.keys())}


@router.get("/env-hints")
async def get_env_hints():
    """返回敏感字段 → 环境变量名的映射"""
    return {
        "hints": {
            path: env_var
            for path, env_var in SENSITIVE_FIELDS.items()
            if env_var is not None
        }
    }


# =============================================================================
# 辅助函数
# =============================================================================


def _deep_merge(base: dict, override: dict) -> None:
    """深度合并 override 到 base（就地修改 base）"""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def _get_current_model(config) -> str:
    p = config.ai.provider
    if p == "ollama":
        return config.ai.ollama.model
    elif p == "openai":
        return config.ai.openai.model
    elif p == "lora":
        return config.ai.lora.base_model
    else:
        return config.ai.local_model.model
