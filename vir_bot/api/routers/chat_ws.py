"""WebSocket 聊天端点"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
import tempfile
import time as _time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from vir_bot.core.pipeline import MessageType, Platform, PlatformMessage
from vir_bot.main import _get_app_state

logger = logging.getLogger(__name__)

router = APIRouter()

# 消息大小上限（100 KB）
MAX_MESSAGE_SIZE = 100_000


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
    """处理文本消息：优先流式输出，失败回退到同步模式。"""
    app_state = _get_app_state()
    if app_state.pipeline is None:
        await ws.send_json({"type": "error", "content": "Pipeline 未初始化"})
        return

    # 通知前端进入思考状态
    await ws.send_json({"type": "status", "state": "thinking"})

    full_content = ""
    stream = None
    try:
        system_prompt = app_state.pipeline._build_system_prompt()
        messages = [{"role": "user", "content": msg.content}]

        stream = app_state.pipeline.ai.chat_stream(
            messages=messages, system=system_prompt,
        )
        async for chunk in stream:
            if chunk.finish_reason == "stop":
                break
            if chunk.delta:
                full_content += chunk.delta
                await ws.send_json({"type": "text_delta", "content": chunk.delta})
    except Exception as e:
        logger.warning(f"[WS] 流式输出异常: {e}，回退到同步模式")
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
            full_content = response.content if response else ""
        except Exception as e2:
            logger.error(f"[WS] 同步模式也失败: {e2}")
    finally:
        if stream is not None:
            try:
                await stream.aclose()
            except Exception:
                pass

    await ws.send_json({"type": "status", "state": "idle"})
    content = full_content if full_content else "[无回复]"
    await ws.send_json({"type": "text_done", "content": content})
    await _synthesize_and_send(ws, content)


async def _synthesize_and_send(ws: WebSocket, text: str) -> None:
    """合成语音并发送音频 URL"""
    app_state = _get_app_state()
    if not app_state.pipeline or not app_state.pipeline.tts:
        return

    try:
        text_hash = hashlib.md5(text.encode()).hexdigest()[:8]
        output_path = f"./data/cache/voice_{text_hash}_{int(_time.time())}.wav"
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        result_path = await app_state.pipeline.tts.synthesize(text, output_path)
        if result_path:
            filename = Path(result_path).name
            await ws.send_json({
                "type": "voice_url",
                "url": f"/api/chat/ws/voice/{filename}",
            })
    except Exception as e:
        logger.error(f"[WS] TTS 合成失败: {e}")


async def _handle_interrupt(ws: WebSocket) -> None:
    """处理中断消息：记录日志，返回 idle 状态。"""
    logger.info("[WS] 用户发送中断信号")
    await ws.send_json({"type": "status", "state": "idle"})


async def _handle_voice(ws: WebSocket, msg: ChatMessage) -> None:
    """处理语音消息：base64 音频 → ASR 转文字 → 流式回复"""
    app_state = _get_app_state()
    if app_state.pipeline is None:
        await ws.send_json({"type": "error", "content": "Pipeline 未初始化"})
        return

    if not msg.audio:
        await ws.send_json({"type": "error", "content": "缺少音频数据"})
        return

    # 解码 base64 音频
    try:
        audio_bytes = base64.b64decode(msg.audio)
    except Exception as e:
        await ws.send_json({"type": "error", "content": f"音频解码失败: {e}"})
        return

    # 保存为临时文件
    suffix = f".{msg.format}" if msg.format else ".webm"
    cache_dir = Path("./data/cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False, dir=str(cache_dir))
    tmp.write(audio_bytes)
    tmp.close()
    audio_path = tmp.name

    await ws.send_json({"type": "status", "state": "thinking"})

    # ASR 转文字
    if not app_state.pipeline.asr:
        await ws.send_json({"type": "error", "content": "ASR 服务未配置"})
        Path(audio_path).unlink(missing_ok=True)
        return

    try:
        transcription = await app_state.pipeline.asr.recognize(audio_path)
        logger.info(f"[WS] ASR 转录: {transcription[:50]}")
    except Exception as e:
        logger.error(f"[WS] ASR 失败: {e}")
        await ws.send_json({"type": "error", "content": "语音识别失败"})
        return
    finally:
        Path(audio_path).unlink(missing_ok=True)

    if not transcription or not transcription.strip():
        await ws.send_json({"type": "text_done", "content": "抱歉，没有听清你说的话。"})
        return

    # 用转录文字调用流式输出
    text_msg = ChatMessage(type="text", content=transcription.strip())
    await _handle_text(ws, text_msg)


def _verify_ws_token(ws: WebSocket) -> bool:
    """从查询参数验证 WebSocket token。

    如果认证未启用则直接放行。返回 True 表示通过，False 表示拒绝。
    """
    from vir_bot.config import get_config

    config = get_config()

    if not config.web_console.auth.enabled:
        return True

    expected = config.web_console.auth.token
    if not expected:
        logger.warning("[WS] 认证已启用但 token 未配置，拒绝连接")
        return False

    token = ws.query_params.get("token")
    if not token:
        return False

    return hmac.compare_digest(token, expected)


@router.get("/voice/{filename}")
async def serve_voice(filename: str):
    """提供 TTS 合成的音频文件"""
    if not re.match(r'^voice_[a-f0-9]{8,}_\d+\.(wav|mp3|ogg)$', filename):
        return {"error": "无效文件名"}

    file_path = Path("./data/cache") / filename
    if not file_path.exists():
        return {"error": "文件不存在"}

    media_type = "audio/wav" if filename.endswith(".wav") else "audio/mpeg"
    return FileResponse(str(file_path), media_type=media_type)


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    """WebSocket 聊天端点。"""
    # 认证检查（在 accept 之前拒绝，减少资源消耗）
    if not _verify_ws_token(ws):
        await ws.close(code=4001, reason="认证失败")
        logger.warning("[WS] 认证失败，连接已拒绝")
        return

    await ws.accept()
    logger.info("[WS] 客户端已连接")

    try:
        while True:
            raw = await ws.receive_text()

            # 消息大小限制
            if len(raw) > MAX_MESSAGE_SIZE:
                await ws.send_json({
                    "type": "error",
                    "content": "消息过大，请控制在 100KB 以内",
                })
                continue

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
        try:
            await ws.close(code=1011, reason="服务器内部错误")
        except Exception:
            pass
