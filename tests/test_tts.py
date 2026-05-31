"""MiMo TTS Provider 和语音决策机制测试"""
import base64

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from vir_bot.modules.voice import (
    MiMoTTSProvider,
    TTSFallbackProvider,
    _parse_voice_decision,
    _build_style_hint,
    convert_audio,
)


def _make_tts_config():
    """创建 TTS 配置的 MagicMock。"""
    config = MagicMock()
    config.mimo_model = "mimo-v2.5-tts"
    config.mimo_voice = "冰糖"
    config.speed = 1.0
    return config


def _mock_app_config():
    """创建应用配置的 MagicMock（提供 api_key / base_url）。"""
    app = MagicMock()
    app.ai.openai.api_key = "test-key"
    app.ai.openai.base_url = "https://api.example.com/"
    return app


def _fake_audio_response():
    """构造一个模拟的 TTS API 响应。"""
    fake_audio = base64.b64encode(b"RIFF-fake-wav-data").decode()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "choices": [{"message": {"audio": {"data": fake_audio}}}]
    }
    resp.raise_for_status = MagicMock()
    return resp


# ============================================================================
# MiMoTTSProvider
# ============================================================================


class TestMiMoTTSProvider:
    @patch("vir_bot.config.get_config", return_value=_mock_app_config())
    def test_init_defaults(self, _mock_gc):
        config = _make_tts_config()
        provider = MiMoTTSProvider(config)
        assert provider.model == "mimo-v2.5-tts"
        assert provider.voice == "冰糖"
        assert provider.speed == 1.0

    @patch("vir_bot.config.get_config", return_value=_mock_app_config())
    @pytest.mark.asyncio
    async def test_synthesize_success(self, _mock_gc):
        config = _make_tts_config()
        provider = MiMoTTSProvider(config)

        mock_resp = _fake_audio_response()

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            with patch("builtins.open", MagicMock()):
                result = await provider.synthesize("hello", "/tmp/test.wav")
                assert result == "/tmp/test.wav"

    @patch("vir_bot.config.get_config", return_value=_mock_app_config())
    @pytest.mark.asyncio
    async def test_synthesize_timeout_returns_none(self, _mock_gc):
        config = _make_tts_config()
        provider = MiMoTTSProvider(config)

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=Exception("timeout")):
            result = await provider.synthesize("hello", "/tmp/test.wav")
            assert result is None

    @patch("vir_bot.config.get_config", return_value=_mock_app_config())
    @pytest.mark.asyncio
    async def test_synthesize_with_style_hint(self, _mock_gc):
        config = _make_tts_config()
        provider = MiMoTTSProvider(config)

        mock_resp = _fake_audio_response()

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp) as mock_post:
            with patch("builtins.open", MagicMock()):
                await provider.synthesize("hello", "/tmp/test.wav", style_hint="用温柔的语调说话")
                call_args = mock_post.call_args
                messages = call_args.kwargs.get("json", {}).get("messages", [])
                assert any(m["role"] == "user" and "温柔" in m["content"] for m in messages)


# ============================================================================
# 语音决策解析
# ============================================================================


class TestVoiceDecision:
    def test_parse_voice_tag_present(self):
        content, use_voice = _parse_voice_decision("Hello world [VOICE]")
        assert use_voice is True
        assert content == "Hello world"

    def test_parse_voice_tag_absent(self):
        content, use_voice = _parse_voice_decision("Hello world")
        assert use_voice is False
        assert content == "Hello world"

    def test_parse_cleans_extra_newlines(self):
        content, _ = _parse_voice_decision("Hello\n\n\n\nWorld [VOICE]")
        assert "\n\n\n" not in content

    def test_parse_empty_string(self):
        content, use_voice = _parse_voice_decision("")
        assert use_voice is False
        assert content == ""


# ============================================================================
# 风格提示构建
# ============================================================================


class TestStyleHint:
    def test_manual_style_priority(self):
        voice_config = MagicMock()
        voice_config.tts.mimo_style = "用磁性的声音说话"
        result = _build_style_hint(MagicMock(), voice_config)
        assert result == "用磁性的声音说话"

    def test_auto_from_personality(self):
        voice_config = MagicMock()
        voice_config.tts.mimo_style = ""
        character = MagicMock()
        character.personality = "温柔活泼"
        result = _build_style_hint(character, voice_config)
        assert "温柔活泼" in result

    def test_default_when_no_personality(self):
        voice_config = MagicMock()
        voice_config.tts.mimo_style = ""
        character = MagicMock()
        character.personality = ""
        result = _build_style_hint(character, voice_config)
        assert "温柔" in result


# ============================================================================
# TTSFallbackProvider
# ============================================================================


class TestFallbackProvider:
    @pytest.mark.asyncio
    async def test_primary_success(self):
        primary = MagicMock()
        primary.synthesize = AsyncMock(return_value="/tmp/primary.wav")
        fallback = MagicMock()
        fallback.synthesize = AsyncMock(return_value="/tmp/fallback.wav")

        provider = TTSFallbackProvider(primary, fallback)
        result = await provider.synthesize("hello", "/tmp/out.wav")
        assert result == "/tmp/primary.wav"
        fallback.synthesize.assert_not_called()

    @pytest.mark.asyncio
    async def test_primary_fails_fallback_used(self):
        primary = MagicMock()
        primary.synthesize = AsyncMock(return_value=None)
        fallback = MagicMock()
        fallback.synthesize = AsyncMock(return_value="/tmp/fallback.wav")

        provider = TTSFallbackProvider(primary, fallback)
        result = await provider.synthesize("hello", "/tmp/out.wav")
        assert result == "/tmp/fallback.wav"
        fallback.synthesize.assert_called_once()
