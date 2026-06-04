"""chat_ws 模块单元测试"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vir_bot.api.routers.chat_ws import ChatMessage, _handle_text, parse_message
from vir_bot.core.ai_provider import AIStreamChunk


# ---------------------------------------------------------------------------
# parse_message 测试
# ---------------------------------------------------------------------------


def test_parse_text_message():
    """解析正常的文本消息"""
    raw = json.dumps({"type": "text", "content": "你好"})
    msg = parse_message(raw)
    assert msg is not None
    assert msg.type == "text"
    assert msg.content == "你好"
    assert msg.audio == ""
    assert msg.format == ""


def test_parse_interrupt_message():
    """解析中断消息"""
    raw = json.dumps({"type": "interrupt"})
    msg = parse_message(raw)
    assert msg is not None
    assert msg.type == "interrupt"
    assert msg.content == ""


def test_parse_invalid_json():
    """无效 JSON 返回 None"""
    assert parse_message("not json") is None
    assert parse_message("") is None
    assert parse_message("{broken") is None


def test_parse_missing_type():
    """缺少 type 字段返回 None"""
    assert parse_message(json.dumps({"content": "你好"})) is None
    assert parse_message(json.dumps({})) is None


def test_parse_voice_message():
    """解析语音消息（含 audio 和 format 字段）"""
    raw = json.dumps({"type": "voice", "audio": "base64data", "format": "wav"})
    msg = parse_message(raw)
    assert msg is not None
    assert msg.type == "voice"
    assert msg.audio == "base64data"
    assert msg.format == "wav"


def test_parse_type_not_string():
    """type 字段非字符串返回 None"""
    assert parse_message(json.dumps({"type": 123})) is None
    assert parse_message(json.dumps({"type": None})) is None


def test_parse_non_dict():
    """非字典 JSON 返回 None"""
    assert parse_message(json.dumps([1, 2, 3])) is None
    assert parse_message(json.dumps("just a string")) is None


# ---------------------------------------------------------------------------
# _handle_text 流式输出测试
# ---------------------------------------------------------------------------


async def _make_stream(*deltas: str) -> list[AIStreamChunk]:
    """构造 AIStreamChunk 列表用于模拟流式返回。"""
    chunks = [AIStreamChunk(delta=d) for d in deltas]
    chunks.append(AIStreamChunk(delta="", finish_reason="stop"))
    return chunks


@pytest.mark.asyncio
async def test_handle_text_streaming_success():
    """流式输出正常：逐块发送 text_delta，最后发送 text_done。"""
    ws = AsyncMock()
    ws.send_json = AsyncMock()

    chunks = [
        AIStreamChunk(delta="你"),
        AIStreamChunk(delta="好"),
        AIStreamChunk(delta="呀"),
        AIStreamChunk(delta="", finish_reason="stop"),
    ]

    async def fake_stream(messages, system=None, **kw):
        for c in chunks:
            yield c

    pipeline = MagicMock()
    pipeline._build_system_prompt.return_value = "system prompt"
    pipeline.ai.chat_stream = fake_stream

    app_state = MagicMock()
    app_state.pipeline = pipeline

    msg = ChatMessage(type="text", content="hello")

    with patch("vir_bot.api.routers.chat_ws._get_app_state", return_value=app_state):
        await _handle_text(ws, msg)

    sent = [call.args[0] for call in ws.send_json.call_args_list]
    assert sent[0] == {"type": "status", "state": "thinking"}
    assert sent[1] == {"type": "text_delta", "content": "你"}
    assert sent[2] == {"type": "text_delta", "content": "好"}
    assert sent[3] == {"type": "text_delta", "content": "呀"}
    assert sent[4] == {"type": "status", "state": "idle"}
    assert sent[5] == {"type": "text_done", "content": "你好呀"}


@pytest.mark.asyncio
async def test_handle_text_stream_fallback_to_sync():
    """流式异常时回退到同步 pipeline.process()。"""
    ws = AsyncMock()
    ws.send_json = AsyncMock()

    async def failing_stream(messages, system=None, **kw):
        raise RuntimeError("stream broke")
        yield  # pragma: no cover  (make it an async generator)

    pipeline = MagicMock()
    pipeline._build_system_prompt.return_value = "system"
    pipeline.ai.chat_stream = failing_stream

    sync_response = MagicMock()
    sync_response.content = "同步回复"
    pipeline.process = AsyncMock(return_value=sync_response)

    app_state = MagicMock()
    app_state.pipeline = pipeline

    msg = ChatMessage(type="text", content="hello")

    with patch("vir_bot.api.routers.chat_ws._get_app_state", return_value=app_state):
        await _handle_text(ws, msg)

    pipeline.process.assert_awaited_once()
    sent = [call.args[0] for call in ws.send_json.call_args_list]
    assert sent[0] == {"type": "status", "state": "thinking"}
    assert sent[-2] == {"type": "status", "state": "idle"}
    assert sent[-1] == {"type": "text_done", "content": "同步回复"}


@pytest.mark.asyncio
async def test_handle_text_both_fail():
    """流式和同步都失败时返回默认提示。"""
    ws = AsyncMock()
    ws.send_json = AsyncMock()

    async def failing_stream(messages, system=None, **kw):
        raise RuntimeError("stream broke")
        yield  # pragma: no cover

    pipeline = MagicMock()
    pipeline._build_system_prompt.return_value = "system"
    pipeline.ai.chat_stream = failing_stream
    pipeline.process = AsyncMock(side_effect=RuntimeError("sync broke"))

    app_state = MagicMock()
    app_state.pipeline = pipeline

    msg = ChatMessage(type="text", content="hello")

    with patch("vir_bot.api.routers.chat_ws._get_app_state", return_value=app_state):
        await _handle_text(ws, msg)

    sent = [call.args[0] for call in ws.send_json.call_args_list]
    assert sent[-1] == {"type": "text_done", "content": "[无回复]"}


@pytest.mark.asyncio
async def test_handle_text_pipeline_not_initialized():
    """Pipeline 未初始化时返回错误消息。"""
    ws = AsyncMock()
    ws.send_json = AsyncMock()

    app_state = MagicMock()
    app_state.pipeline = None

    msg = ChatMessage(type="text", content="hello")

    with patch("vir_bot.api.routers.chat_ws._get_app_state", return_value=app_state):
        await _handle_text(ws, msg)

    ws.send_json.assert_awaited_once_with(
        {"type": "error", "content": "Pipeline 未初始化"},
    )


@pytest.mark.asyncio
async def test_handle_text_empty_stream():
    """流式返回无 delta 内容时，text_done 为 [无回复]。"""
    ws = AsyncMock()
    ws.send_json = AsyncMock()

    async def empty_stream(messages, system=None, **kw):
        yield AIStreamChunk(delta="", finish_reason="stop")

    pipeline = MagicMock()
    pipeline._build_system_prompt.return_value = "system"
    pipeline.ai.chat_stream = empty_stream

    app_state = MagicMock()
    app_state.pipeline = pipeline

    msg = ChatMessage(type="text", content="hello")

    with patch("vir_bot.api.routers.chat_ws._get_app_state", return_value=app_state):
        await _handle_text(ws, msg)

    sent = [call.args[0] for call in ws.send_json.call_args_list]
    assert sent[-1] == {"type": "text_done", "content": "[无回复]"}
