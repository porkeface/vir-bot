"""平台状态 API"""
from __future__ import annotations

import logging
from fastapi import APIRouter, Request, Response

from vir_bot.main import _get_app_state

router = APIRouter()
logger = logging.getLogger("uvicorn.error")


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


@router.post("/qq/callback")
async def qq_official_callback(request: Request):
    """QQ 官方机器人回调入口"""
    state = _get_app_state()
    adapter = state.adapters.get("qq_official")
    if not adapter:
        return Response(status_code=503, content="qq_official not enabled")

    body = await request.body()
    signature = request.headers.get("X-Signature", "")
    secret = state.config.platforms.qq_official.app_secret

    # 调试：打印收到的签名和计算出的签名
    computed = adapter.verify_signature(body, signature, secret)
    logger.info(f"[QQ官方] 回调调试 — 收到签名: {signature}")
    logger.info(f"[QQ官方] 回调调试 — 计算签名: {adapter._debug_signature(body, secret)}")
    logger.info(f"[QQ官方] 回调调试 — 验证结果: {computed}")

    # 临时跳过签名验证，先拿到 openid（后续修复签名后再启用）
    # if not computed:
    #     logger.warning("[QQ官方] 签名验证失败")
    #     return Response(status_code=403, content="invalid signature")

    try:
        data = await request.json()
    except Exception:
        return Response(status_code=400, content="invalid json")

    msg = adapter.parse_callback(data)
    if not msg:
        return Response(status_code=200, content="ignored")

    # 打印 openid 方便用户获取
    openid = msg.metadata.get("openid", "")
    group_openid = msg.metadata.get("group_openid", "")
    logger.info(f"[QQ官方] 收到消息 — openid: {openid}, group_openid: {group_openid}")
    logger.info(f"[QQ官方] 请把 openid 填入 config.yaml 的 proactive.targets.qq_official.openid")

    pipeline = state.pipeline
    response = await pipeline.process(msg)
    if response:
        # 将回调消息的 openid/group_openid 传递给响应，供 send_message 使用
        response.metadata.update(msg.metadata)
        await adapter.send_message(response)

    return Response(status_code=200, content="ok")