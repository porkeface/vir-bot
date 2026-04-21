"""平台状态 API"""
from __future__ import annotations

from fastapi import APIRouter

from vir_bot.main import _get_app_state

router = APIRouter()


@router.get("/")
async def list_platforms():
    state = _get_app_state()
    result = []
    for name, adapter in state.adapters.items():
        result.append({
            "name": name,
            "running": getattr(adapter, "_running", False),
            "platform": adapter.platform.value if hasattr(adapter, "platform") else name,
        })
    return result


@router.post("/{name}/start")
async def start_platform(name: str):
    state = _get_app_state()
    if name not in state.adapters:
        return {"status": "error", "message": f"未知平台: {name}"}
    await state.adapters[name].start()
    return {"status": "ok", "message": f"{name} 已启动"}


@router.post("/{name}/stop")
async def stop_platform(name: str):
    state = _get_app_state()
    if name not in state.adapters:
        return {"status": "error", "message": f"未知平台: {name}"}
    await state.adapters[name].stop()
    return {"status": "ok", "message": f"{name} 已停止"}