"""主动消息管理 API"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from vir_bot.utils.logger import logger

router = APIRouter()


class ProactiveConfigUpdate(BaseModel):
    """更新主动消息配置"""
    enabled: bool | None = None
    check_interval_seconds: int | None = None
    min_cooldown_seconds: int | None = None
    max_daily_messages: int | None = None


class ProactiveResponse(BaseModel):
    """主动消息响应"""
    enabled: bool
    stats: dict | None = None
    message: str | None = None


@router.get("/api/proactive", tags=["主动消息"], response_model=ProactiveResponse)
async def get_proactive_status():
    """获取主动消息状态"""
    import sys
    from vir_bot.main import app_state

    if not app_state.proactive_service:
        return ProactiveResponse(enabled=False, message="主动消息服务未初始化")

    stats = app_state.proactive_service.get_stats()
    return ProactiveResponse(enabled=stats.get("enabled", False), stats=stats)


@router.post("/api/proactive/enable", tags=["主动消息"])
async def enable_proactive():
    """启用主动消息"""
    import sys
    from vir_bot.main import app_state

    if not app_state.proactive_service:
        raise HTTPException(status_code=400, detail="主动消息服务未初始化")

    app_state.proactive_service._enabled = True
    logger.info("主动消息已手动启用")
    return {"status": "enabled"}


@router.post("/api/proactive/disable", tags=["主动消息"])
async def disable_proactive():
    """禁用主动消息"""
    import sys
    from vir_bot.main import app_state

    if not app_state.proactive_service:
        raise HTTPException(status_code=400, detail="主动消息服务未初始化")

    app_state.proactive_service._enabled = False
    logger.info("主动消息已手动禁用")
    return {"status": "disabled"}


@router.post("/api/proactive/send", tags=["主动消息"])
async def trigger_proactive_send():
    """手动触发一次主动消息（测试用）"""
    import sys
    from vir_bot.main import app_state

    if not app_state.proactive_service:
        raise HTTPException(status_code=400, detail="主动消息服务未初始化")

    service = app_state.proactive_service
    if not service._enabled:
        raise HTTPException(status_code=400, detail="主动消息服务未启用")

    asyncio.get_event_loop().create_task(service._run_once())
    return {"status": "triggered"}


@router.get("/api/proactive/stats", tags=["主动消息"])
async def get_proactive_stats():
    """获取主动消息统计"""
    import sys
    from vir_bot.main import app_state

    if not app_state.proactive_service:
        return {"enabled": False}

    return app_state.proactive_service.get_stats()
