"""WebSocket 聊天端点"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from vir_bot.core.pipeline import MessageType, Platform, PlatformMessage
from vir_bot.main import _get_app_state

logger = logging.getLogger(__name__)

router = APIRouter()


@dataclass
class ChatMessage:
    """从 WebSocket 接收的 JSON 消息"""

    type: str
    content: str = ""
    audio: str = ""
    format: str = ""


def parse_message(raw: str) -> ChatMessage | None:
    """解析 WebSocket 文本帧为 ChatMessage。

    返回 None 表示无效消息（JSON 解析失败或缺少 type 字段）。
    """
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None

    if not isinstance(data, dict):
        return None

    msg_type = data.get("type")
    if not msg_type or not isinstance(msg_type, str):
        return None

    return ChatMessage(
        type=msg_type,
        content=data.get("content", ""),
        audio=data.get("audio", ""),
        format=data.get("format", ""),
    )


async def _handle_text(ws: WebSocket, msg: ChatMessage) -> None:
    """处理文本消息：调用 pipeline.process()，返回 text_done。"""
    app_state = _get_app_state()
    if app_state.pipeline is None:
        await ws.send_json({"type": "error", "content": "Pipeline 未初始化"})
        return

    # 通知前端进入思考状态
    await ws.send_json({"type": "status", "state": "thinking"})

    platform_msg = PlatformMessage(
        platform=Platform.API,
        msg_id=str(uuid.uuid4()),
        user_id="ws_user",
        user_name="WS用户",
        content=msg.content,
        msg_type=MessageType.TEXT,
    )

    try:
        response = await app_state.pipeline.process(platform_msg)
        content = response.content if response else "[无回复]"
    except Exception as e:
        logger.error(f"Pipeline 处理失败: {e}")
        content = "抱歉，处理消息时出现错误。"

    await ws.send_json({"type": "text_done", "content": content})


async def _handle_interrupt(ws: WebSocket) -> None:
    """处理中断消息：记录日志，返回 idle 状态。"""
    logger.info("[WS] 用户发送中断信号")
    await ws.send_json({"type": "status", "state": "idle"})


async def _handle_voice(ws: WebSocket, msg: ChatMessage) -> None:
    """处理语音消息（占位，后续实现）。"""
    await ws.send_json({
        "type": "error",
        "content": "语音消息暂不支持，敬请期待。",
    })


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    """WebSocket 聊天端点。"""
    await ws.accept()
    logger.info("[WS] 客户端已连接")

    try:
        while True:
            raw = await ws.receive_text()
            msg = parse_message(raw)
            if msg is None:
                await ws.send_json({"type": "error", "content": "无效的消息格式"})
                continue

            if msg.type == "text":
                await _handle_text(ws, msg)
            elif msg.type == "interrupt":
                await _handle_interrupt(ws)
            elif msg.type == "voice":
                await _handle_voice(ws, msg)
            else:
                await ws.send_json({
                    "type": "error",
                    "content": f"未知消息类型: {msg.type}",
                })
    except WebSocketDisconnect:
        logger.info("[WS] 客户端已断开")
    except Exception as e:
        logger.error(f"[WS] 连接异常: {e}")
