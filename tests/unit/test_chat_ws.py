"""chat_ws 模块单元测试"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vir_bot.api.routers.chat_ws import (
    ChatMessage,
    _handle_text,
    _handle_voice,
    _synthesize_and_send,
    parse_message,
    serve_voice,
)
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
    pipeline.tts = None

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
    pipeline.tts = None

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
    pipeline.tts = None

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
    pipeline.tts = None

    app_state = MagicMock()
    app_state.pipeline = pipeline

    msg = ChatMessage(type="text", content="hello")

    with patch("vir_bot.api.routers.chat_ws._get_app_state", return_value=app_state):
        await _handle_text(ws, msg)

    sent = [call.args[0] for call in ws.send_json.call_args_list]
    assert sent[-1] == {"type": "text_done", "content": "[无回复]"}


# ---------------------------------------------------------------------------
# _handle_voice 测试
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_voice_pipeline_not_initialized():
    """Pipeline 未初始化时返回错误消息。"""
    ws = AsyncMock()
    app_state = MagicMock()
    app_state.pipeline = None

    msg = ChatMessage(type="voice", audio="base64data", format="wav")

    with patch("vir_bot.api.routers.chat_ws._get_app_state", return_value=app_state):
        await _handle_voice(ws, msg)

    ws.send_json.assert_awaited_once_with(
        {"type": "error", "content": "Pipeline 未初始化"},
    )


@pytest.mark.asyncio
async def test_handle_voice_missing_audio():
    """缺少音频数据时返回错误消息。"""
    ws = AsyncMock()
    app_state = MagicMock()
    app_state.pipeline = MagicMock()

    msg = ChatMessage(type="voice", audio="", format="wav")

    with patch("vir_bot.api.routers.chat_ws._get_app_state", return_value=app_state):
        await _handle_voice(ws, msg)

    ws.send_json.assert_awaited_once_with(
        {"type": "error", "content": "缺少音频数据"},
    )


@pytest.mark.asyncio
async def test_handle_voice_invalid_base64():
    """无效 base64 数据时返回错误消息。"""
    ws = AsyncMock()
    app_state = MagicMock()
    app_state.pipeline = MagicMock()

    msg = ChatMessage(type="voice", audio="!!!invalid!!!", format="wav")

    with patch("vir_bot.api.routers.chat_ws._get_app_state", return_value=app_state):
        await _handle_voice(ws, msg)

    sent = [call.args[0] for call in ws.send_json.call_args_list]
    assert sent[0]["type"] == "error"
    assert "音频解码失败" in sent[0]["content"]


@pytest.mark.asyncio
async def test_handle_voice_asr_not_configured():
    """ASR 未配置时返回错误消息。"""
    ws = AsyncMock()
    pipeline = MagicMock()
    pipeline.asr = None
    app_state = MagicMock()
    app_state.pipeline = pipeline

    import base64 as b64

    msg = ChatMessage(type="voice", audio=b64.b64encode(b"audio").decode(), format="wav")

    with patch("vir_bot.api.routers.chat_ws._get_app_state", return_value=app_state):
        with patch("vir_bot.api.routers.chat_ws.tempfile") as mock_tempfile:
            mock_tmp = MagicMock()
            mock_tmp.name = "/tmp/test.wav"
            mock_tempfile.NamedTemporaryFile.return_value = mock_tmp
            await _handle_voice(ws, msg)

    sent = [call.args[0] for call in ws.send_json.call_args_list]
    assert any(s == {"type": "error", "content": "ASR 服务未配置"} for s in sent)


@pytest.mark.asyncio
async def test_handle_voice_asr_failure():
    """ASR 识别失败时返回错误消息。"""
    ws = AsyncMock()
    pipeline = MagicMock()
    pipeline.asr = AsyncMock()
    pipeline.asr.recognize.side_effect = RuntimeError("ASR crashed")
    app_state = MagicMock()
    app_state.pipeline = pipeline

    import base64 as b64

    msg = ChatMessage(type="voice", audio=b64.b64encode(b"audio").decode(), format="wav")

    with patch("vir_bot.api.routers.chat_ws._get_app_state", return_value=app_state):
        with patch("vir_bot.api.routers.chat_ws.tempfile") as mock_tempfile:
            mock_tmp = MagicMock()
            mock_tmp.name = "/tmp/test.wav"
            mock_tempfile.NamedTemporaryFile.return_value = mock_tmp
            await _handle_voice(ws, msg)

    sent = [call.args[0] for call in ws.send_json.call_args_list]
    assert any(s == {"type": "error", "content": "语音识别失败"} for s in sent)


@pytest.mark.asyncio
async def test_handle_voice_empty_transcription():
    """ASR 返回空文字时发送提示消息。"""
    ws = AsyncMock()
    pipeline = MagicMock()
    pipeline.asr = AsyncMock()
    pipeline.asr.recognize.return_value = "   "
    pipeline.tts = None
    app_state = MagicMock()
    app_state.pipeline = pipeline

    import base64 as b64

    msg = ChatMessage(type="voice", audio=b64.b64encode(b"audio").decode(), format="wav")

    with patch("vir_bot.api.routers.chat_ws._get_app_state", return_value=app_state):
        with patch("vir_bot.api.routers.chat_ws.tempfile") as mock_tempfile:
            mock_tmp = MagicMock()
            mock_tmp.name = "/tmp/test.wav"
            mock_tempfile.NamedTemporaryFile.return_value = mock_tmp
            await _handle_voice(ws, msg)

    sent = [call.args[0] for call in ws.send_json.call_args_list]
    assert any(
        s == {"type": "text_done", "content": "抱歉，没有听清你说的话。"}
        for s in sent
    )


@pytest.mark.asyncio
async def test_handle_voice_success_delegates_to_handle_text():
    """ASR 成功转录后委托给 _handle_text 处理。"""
    ws = AsyncMock()
    pipeline = MagicMock()
    pipeline.asr = AsyncMock()
    pipeline.asr.recognize.return_value = "你好世界"
    pipeline._build_system_prompt.return_value = "system"
    pipeline.tts = None

    async def fake_stream(messages, system=None, **kw):
        yield AIStreamChunk(delta="回复")
        yield AIStreamChunk(delta="", finish_reason="stop")

    pipeline.ai.chat_stream = fake_stream
    app_state = MagicMock()
    app_state.pipeline = pipeline

    import base64 as b64

    msg = ChatMessage(type="voice", audio=b64.b64encode(b"audio").decode(), format="wav")

    with patch("vir_bot.api.routers.chat_ws._get_app_state", return_value=app_state):
        with patch("vir_bot.api.routers.chat_ws.tempfile") as mock_tempfile:
            mock_tmp = MagicMock()
            mock_tmp.name = "/tmp/test.wav"
            mock_tempfile.NamedTemporaryFile.return_value = mock_tmp
            await _handle_voice(ws, msg)

    sent = [call.args[0] for call in ws.send_json.call_args_list]
    assert any(s.get("type") == "text_delta" for s in sent)
    assert any(s.get("type") == "text_done" and s.get("content") == "回复" for s in sent)


# ---------------------------------------------------------------------------
# _synthesize_and_send 测试
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synthesize_and_send_no_pipeline():
    """Pipeline 为 None 时直接返回。"""
    ws = AsyncMock()
    app_state = MagicMock()
    app_state.pipeline = None

    with patch("vir_bot.api.routers.chat_ws._get_app_state", return_value=app_state):
        await _synthesize_and_send(ws, "hello")

    ws.send_json.assert_not_awaited()


@pytest.mark.asyncio
async def test_synthesize_and_send_no_tts():
    """TTS 为 None 时直接返回。"""
    ws = AsyncMock()
    pipeline = MagicMock()
    pipeline.tts = None
    app_state = MagicMock()
    app_state.pipeline = pipeline

    with patch("vir_bot.api.routers.chat_ws._get_app_state", return_value=app_state):
        await _synthesize_and_send(ws, "hello")

    ws.send_json.assert_not_awaited()


@pytest.mark.asyncio
async def test_synthesize_and_send_success():
    """TTS 合成成功后发送 voice_url。"""
    ws = AsyncMock()
    pipeline = MagicMock()
    pipeline.tts = AsyncMock()
    pipeline.tts.synthesize.return_value = "./data/cache/voice_abc12345_1234567890.wav"
    app_state = MagicMock()
    app_state.pipeline = pipeline

    with patch("vir_bot.api.routers.chat_ws._get_app_state", return_value=app_state):
        await _synthesize_and_send(ws, "你好")

    ws.send_json.assert_awaited_once_with({
        "type": "voice_url",
        "url": "/api/chat/ws/voice/voice_abc12345_1234567890.wav",
    })


@pytest.mark.asyncio
async def test_synthesize_and_send_synthesize_returns_none():
    """TTS 合成返回 None 时不发送消息。"""
    ws = AsyncMock()
    pipeline = MagicMock()
    pipeline.tts = AsyncMock()
    pipeline.tts.synthesize.return_value = None
    app_state = MagicMock()
    app_state.pipeline = pipeline

    with patch("vir_bot.api.routers.chat_ws._get_app_state", return_value=app_state):
        await _synthesize_and_send(ws, "你好")

    ws.send_json.assert_not_awaited()


@pytest.mark.asyncio
async def test_synthesize_and_send_exception():
    """TTS 合成异常时静默处理。"""
    ws = AsyncMock()
    pipeline = MagicMock()
    pipeline.tts = AsyncMock()
    pipeline.tts.synthesize.side_effect = RuntimeError("TTS failed")
    app_state = MagicMock()
    app_state.pipeline = pipeline

    with patch("vir_bot.api.routers.chat_ws._get_app_state", return_value=app_state):
        await _synthesize_and_send(ws, "你好")

    ws.send_json.assert_not_awaited()


# ---------------------------------------------------------------------------
# serve_voice 测试
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_serve_voice_invalid_filename():
    """无效文件名返回错误。"""
    result = await serve_voice("../../etc/passwd")
    assert result == {"error": "无效文件名"}


@pytest.mark.asyncio
async def test_serve_voice_invalid_extension():
    """无效扩展名返回错误。"""
    result = await serve_voice("voice_abc12345_123.txt")
    assert result == {"error": "无效文件名"}


@pytest.mark.asyncio
async def test_serve_voice_file_not_found():
    """文件不存在返回错误。"""
    result = await serve_voice("voice_abc12345_1234567890.wav")
    assert result == {"error": "文件不存在"}


@pytest.mark.asyncio
async def test_serve_voice_valid_wav():
    """有效 wav 文件返回 FileResponse。"""
    with patch("vir_bot.api.routers.chat_ws.Path") as mock_path_cls:
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_path.__truediv__ = lambda self, x: mock_path
        mock_path_cls.return_value = mock_path

        with patch("vir_bot.api.routers.chat_ws.FileResponse") as mock_fr:
            mock_fr.return_value = "response"
            result = await serve_voice("voice_abc12345_1234567890.wav")

    assert result != {"error": "无效文件名"}
    assert result != {"error": "文件不存在"}
