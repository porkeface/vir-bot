"""语音模块（TTS / ASR / 唤醒词 — 预留接口）"""
from __future__ import annotations

from abc import ABC, abstractmethod

from vir_bot.utils.logger import logger


class TTSProvider(ABC):
    """TTS 抽象接口"""

    @abstractmethod
    async def synthesize(self, text: str, output_path: str) -> str:
        """将文字转为语音，返回音频文件路径"""
        ...


class EdgeTTSProvider(TTSProvider):
    """微软 Edge TTS（高质量，免费）"""

    def __init__(self, voice_id: str = "zh-CN-XiaoxiaoNeural", speed: float = 1.0):
        self.voice_id = voice_id
        self.speed = speed

    async def synthesize(self, text: str, output_path: str) -> str:
        try:
            import edge_tts
        except ImportError:
            logger.warning("edge-tts not installed, TTS disabled")
            return ""

        communicate = edge_tts.Communicate(text, self.voice_id)
        rate = f"{'+' if self.speed >= 1 else '-'}{int(abs(self.speed - 1) * 50)}%"
        await communicate.save(output_path)
        return output_path


class ASRProvider(ABC):
    """ASR 抽象接口"""

    @abstractmethod
    async def recognize(self, audio_path: str) -> str:
        """将语音文件转为文字"""
        ...


class WhisperASRProvider(ASRProvider):
    """OpenAI Whisper ASR（本地）"""

    def __init__(self, model: str = "base", language: str = "zh"):
        self.model_name = model
        self.language = language
        self._model = None

    def _get_model(self):
        if self._model is None:
            import whisper
            self._model = whisper.load_model(self.model_name)
        return self._model

    async def recognize(self, audio_path: str) -> str:
        try:
            import whisper
        except ImportError:
            logger.warning("whisper not installed, ASR disabled")
            return ""
        model = self._get_model()
        result = model.transcribe(audio_path, language=self.language)
        return result["text"]


class WakeWordProvider(ABC):
    """离线唤醒词检测"""

    @abstractmethod
    async def listen(self) -> str:
        """监听音频流，返回检测到的唤醒词"""
        ...


class PorcupineWakeWordProvider(WakeWordProvider):
    """Porcupine 离线唤醒词"""

    def __init__(self, keywords: list[str] | None = None):
        self.keywords = keywords or ["hey-vir"]

    async def listen(self) -> str:
        logger.info("Wake word detection started (placeholder)")
        return ""


# ============================================================================
# 工具函数
# ============================================================================


def create_tts(config) -> TTSProvider | None:
    if not config.enabled:
        return None
    if config.tts.provider == "edge":
        return EdgeTTSProvider(config.tts.voice_id, config.tts.speed)
    return None


def create_asr(config) -> ASRProvider | None:
    if not config.enabled:
        return None
    if config.asr.provider == "whisper":
        return WhisperASRProvider(config.asr.model, config.asr.language)
    return None


def create_wake_word(config) -> WakeWordProvider | None:
    if not config.enabled:
        return None
    if config.wake_word.provider == "porcupine":
        return PorcupineWakeWordProvider(config.wake_word.keywords)
    return None