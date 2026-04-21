"""配置管理 API"""
from __future__ import annotations

import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from vir_bot.config import get_config, load_config

router = APIRouter()


class AIStatusResponse(BaseModel):
    provider: str
    model: str
    healthy: bool


class ConfigUpdateRequest(BaseModel):
    key: str  # 例如 "ai.provider", "platforms.discord.enabled"
    value: str


@router.get("/")
async def get_config_values():
    """获取当前配置（敏感字段脱敏）"""
    config = get_config()
    return {
        "app": {"name": config.app.name, "version": config.app.version, "debug": config.app.debug},
        "ai": {
            "provider": config.ai.provider,
            "model": _get_current_model(config),
        },
        "platforms": {
            "qq": {"enabled": config.platforms.qq.enabled},
            "wechat": {"enabled": config.platforms.wechat.enabled},
            "discord": {"enabled": config.platforms.discord.enabled},
        },
        "web_console": {
            "host": config.web_console.host,
            "port": config.web_console.port,
        },
        "mcp": {"enabled": config.mcp.enabled, "tool_count": 0},
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
    config = get_config()
    if provider not in ["ollama", "openai", "local_model"]:
        raise HTTPException(status_code=400, detail=f"未知 Provider: {provider}")
    config.ai.provider = provider
    await AIProviderFactory.create(config.ai).health_check()  # 简单验证
    return {"status": "ok", "provider": provider}


def _get_current_model(config) -> str:
    p = config.ai.provider
    if p == "ollama":
        return config.ai.ollama.model
    elif p == "openai":
        return config.ai.openai.model
    else:
        return config.ai.local_model.model