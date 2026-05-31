"""语音模块（TTS / ASR）

架构：
  ASR: SenseVoice (主) → OpenAI Whisper API (备) → Vosk (离线备)
  TTS: MiMo-V2.5-TTS (主，云端 API) → edge-tts (备) → Piper (离线备)
"""
from __future__ import annotations

import asyncio
import base64
import os
import sys
from abc import ABC, abstractmethod
from pathlib import Path

import re

import httpx

from vir_bot.utils.logger import logger


# ============================================================================
# TTS 抽象接口
# ============================================================================


class TTSProvider(ABC):
    """TTS 抽象接口"""

    @abstractmethod
    async def synthesize(self, text: str, output_path: str, **kwargs) -> str:
        """将文字转为语音，返回音频文件路径"""
        ...


# ============================================================================
# ASR 抽象接口
# ============================================================================


class ASRProvider(ABC):
    """ASR 抽象接口"""

    @abstractmethod
    async def recognize(self, audio_path: str) -> str:
        """将语音文件转为文字"""
        ...

    async def recognize_with_emotion(self, audio_path: str) -> dict:
        """将语音文件转为文字，同时返回情绪信息。
        返回 {"text": str, "emotion": str, "language": str}
        子类可覆盖以提供情绪检测。"""
        text = await self.recognize(audio_path)
        return {"text": text, "emotion": "neutral", "language": "zh"}


# ============================================================================
# SenseVoice ASR（主方案 — funasr，含情绪检测）
# ============================================================================


class SenseVoiceASRProvider(ASRProvider):
    """阿里 SenseVoice ASR（本地推理，支持情绪检测）

    模型 ~450MB，首次加载自动从 modelscope 下载。
    支持中英日粤韩五语，中文准确率 97%+。
    """

    # SenseVoice 情绪标签到中文映射
    _EMOTION_MAP = {
        "HAPPY": "happy",
        "SAD": "sad",
        "ANGRY": "angry",
        "NEUTRAL": "neutral",
        "FEARFUL": "fear",
        "DISGUST": "disgust",
        "SURPRISED": "surprise",
        "<|HAPPY|>": "happy",
        "<|SAD|>": "sad",
        "<|ANGRY|>": "angry",
        "<|NEUTRAL|>": "neutral",
        "<|FEARFUL|>": "fear",
        "<|DISGUST|>": "disgust",
        "<|SURPRISED|>": "surprise",
    }

    def __init__(self, model: str = "iic/SenseVoiceSmall", language: str = "auto", device: str = "cuda:0"):
        self.model_name = model
        self.language = language
        self.device = device
        self._model = None

    def _get_model(self):
        if self._model is None:
            from funasr import AutoModel

            logger.info(f"[SenseVoice] 加载模型: {self.model_name} (device={self.device})")
            self._model = AutoModel(
                model=self.model_name,
                vad_model="fsmn-vad",
                vad_kwargs={"max_single_segment_time": 30000},
                trust_remote_code=True,
                device=self.device,
            )
            logger.info("[SenseVoice] 模型加载完成")
        return self._model

    async def recognize(self, audio_path: str) -> str:
        result = await self.recognize_with_emotion(audio_path)
        return result["text"]

    async def recognize_with_emotion(self, audio_path: str) -> dict:
        try:
            model = self._get_model()
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: model.generate(
                    input=audio_path,
                    cache={},
                    language=self.language,
                    use_itn=True,
                    batch_size_s=60,
                ),
            )

            if not result:
                return {"text": "", "emotion": "neutral", "language": "zh"}

            raw_text = result[0].get("text", "") if isinstance(result[0], dict) else str(result[0])

            # 解析 SenseVoice 输出中的情绪和语言标签
            # 格式: <|zh|><|NEUTRAL|><|Speech|><|woitn|>你好
            emotion = "neutral"
            language = "zh"
            text = raw_text

            for tag, emo in self._EMOTION_MAP.items():
                if tag in raw_text:
                    emotion = emo
                    text = text.replace(tag, "")
                    break

            # 提取语言标签
            for lang_tag in ["<|zh|>", "<|en|>", "<|ja|>", "<|yue|>", "<|ko|>"]:
                if lang_tag in raw_text:
                    language = lang_tag.strip("<|>")
                    text = text.replace(lang_tag, "")
                    break

            # 清理所有 <|...|> 标签
            import re
            text = re.sub(r"<\|[^|]*\|>", "", text).strip()

            logger.info(f"[SenseVoice] 识别: {text[:50]} (emotion={emotion}, lang={language})")
            return {"text": text, "emotion": emotion, "language": language}

        except Exception as e:
            logger.error(f"[SenseVoice] 识别失败: {e}")
            return {"text": "", "emotion": "neutral", "language": "zh"}


# ============================================================================
# CosyVoice 2 TTS（主方案 — 本地推理，支持声音克隆）
# ============================================================================


class CosyVoice2TTSProvider(TTSProvider):
    """阿里 CosyVoice 2 TTS（本地推理，零样本声音克隆）

    CosyVoice2-0.5B 是零样本声音克隆模型，所有合成模式都需要参考音频。
    - 有 voice_sample_path → zero-shot 声音克隆
    - 无 voice_sample_path → 使用 instruct2 模式（描述音色风格）
    """

    def __init__(
        self,
        model_dir: str = "pretrained_models/CosyVoice2-0.5B",
        speed: float = 1.0,
        voice_sample_path: str = "",
        voice_sample_text: str = "",
        instruct_text: str = "用温柔甜美的女声说话",
    ):
        self.model_dir = model_dir
        self.speed = speed
        self.voice_sample_path = voice_sample_path
        self.voice_sample_text = voice_sample_text
        self.instruct_text = instruct_text
        self._model = None
        self._prompt_speech = None
        self._ready = False

    def _ensure_paths(self):
        """确保 CosyVoice 和 Matcha-TTS 在 sys.path 中"""
        cosyvoice_root = str(Path(__file__).resolve().parents[3] / "third_party" / "CosyVoice")
        matcha_root = str(Path(__file__).resolve().parents[3] / "third_party" / "CosyVoice" / "third_party" / "Matcha-TTS")
        for p in [cosyvoice_root, matcha_root]:
            if p not in sys.path:
                sys.path.insert(0, p)

    def _get_model(self):
        if self._model is None:
            self._ensure_paths()
            from cosyvoice.cli.cosyvoice import CosyVoice2

            model_path = self.model_dir
            if not os.path.isabs(model_path):
                project_root = Path(__file__).resolve().parents[3]
                model_path = str(project_root / model_path)

            logger.info(f"[CosyVoice2] 加载模型: {model_path}")
            self._model = CosyVoice2(model_path, fp16=True)
            logger.info(f"[CosyVoice2] 模型加载完成，sample_rate={self._model.sample_rate}")

            # 加载参考音频用于 zero-shot
            if self.voice_sample_path:
                self._load_prompt_speech()

            self._ready = True

        return self._model

    def _load_prompt_speech(self):
        """加载参考音频（用于 zero-shot 声音克隆）"""
        try:
            import torchaudio

            sample_path = self.voice_sample_path
            if not os.path.isabs(sample_path):
                project_root = Path(__file__).resolve().parents[3]
                sample_path = str(project_root / sample_path)

            if not Path(sample_path).exists():
                logger.warning(f"[CosyVoice2] 声音样本不存在: {sample_path}")
                return

            logger.info(f"[CosyVoice2] 加载声音样本: {sample_path}")
            speech, sr = torchaudio.load(sample_path, backend="soundfile")

            # 重采样到 22050Hz（CosyVoice 要求）
            if sr != 22050:
                speech = torchaudio.transforms.Resample(orig_freq=sr, new_freq=22050)(speech)

            # 取前 10 秒
            max_samples = 22050 * 10
            if speech.shape[1] > max_samples:
                speech = speech[:, :max_samples]

            self._prompt_speech = speech
            logger.info(f"[CosyVoice2] 声音样本就绪 (shape={speech.shape})")
        except Exception as e:
            logger.error(f"[CosyVoice2] 加载声音样本失败: {e}")
            self._prompt_speech = None

    async def _ensure_reference_wav(self) -> str:
        """确保 instruct2 模式的参考音频存在。
        用 edge-tts 生成真实语音参考，因为静音会导致特征提取失败。"""
        cache_dir = Path(__file__).resolve().parents[3] / "data" / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        ref_wav = cache_dir / "_ref_voice.wav"

        if ref_wav.exists():
            return str(ref_wav)

        try:
            import edge_tts
            ref_mp3 = cache_dir / "_ref_voice.mp3"
            logger.info("[CosyVoice2] 生成 edge-tts 参考音频...")
            communicate = edge_tts.Communicate(
                "你好，我是暖树，很高兴认识你。希望每天都能陪伴你。",
                "zh-CN-XiaoxiaoNeural",
            )
            await communicate.save(str(ref_mp3))

            # MP3 → WAV（22050Hz，单声道）
            import torch
            import torchaudio
            speech, sr = torchaudio.load(str(ref_mp3), backend="soundfile")
            if sr != 22050:
                speech = torchaudio.transforms.Resample(orig_freq=sr, new_freq=22050)(speech)
            max_samples = 22050 * 10
            if speech.shape[1] > max_samples:
                speech = speech[:, :max_samples]
            torchaudio.save(str(ref_wav), speech, 22050)
            ref_mp3.unlink(missing_ok=True)
            logger.info(f"[CosyVoice2] 参考音频就绪: {ref_wav}")
        except Exception as e:
            logger.warning(f"[CosyVoice2] 生成参考音频失败: {e}，使用静音")
            import torch
            import torchaudio
            silence = torch.zeros(1, 22050 * 3)
            torchaudio.save(str(ref_wav), silence, 22050)

        return str(ref_wav)

    async def synthesize(self, text: str, output_path: str, **kwargs) -> str:
        try:
            model = self._get_model()
            loop = asyncio.get_event_loop()

            mode = "zero-shot" if self._prompt_speech is not None else "instruct2"
            logger.info(f"[CosyVoice2] 开始合成 ({mode}), 文本长度: {len(text)}")

            # instruct2 模式需要真实语音参考，提前生成
            ref_path = None
            if self._prompt_speech is None:
                ref_path = await self._ensure_reference_wav()

            def _generate():
                import torch
                import torchaudio

                all_speech = []

                if self._prompt_speech is not None:
                    # zero-shot 声音克隆模式（prompt_wav 是 tensor）
                    prompt_text = self.voice_sample_text or "你好，我是暖树，很高兴认识你。"
                    for output in model.inference_zero_shot(
                        tts_text=text,
                        prompt_text=prompt_text,
                        prompt_wav=self._prompt_speech,
                        speed=self.speed,
                    ):
                        all_speech.append(output["tts_speech"])
                else:
                    # instruct2 模式：通过文字描述音色风格（prompt_wav 需要真实语音文件）
                    for output in model.inference_instruct2(
                        tts_text=text,
                        instruct_text=self.instruct_text,
                        prompt_wav=ref_path,
                        speed=self.speed,
                    ):
                        all_speech.append(output["tts_speech"])

                if not all_speech:
                    logger.warning("[CosyVoice2] 推理返回空结果")
                    return ""

                speech = torch.cat(all_speech, dim=1)
                sample_rate = model.sample_rate
                duration = speech.shape[1] / sample_rate

                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                torchaudio.save(output_path, speech, sample_rate)
                logger.info(f"[CosyVoice2] 音频保存完成: {duration:.1f}s, {output_path}")
                return output_path

            result = await loop.run_in_executor(None, _generate)
            if result:
                logger.info(f"[CosyVoice2] 合成完成: {result}")
            else:
                logger.warning("[CosyVoice2] 合成返回空路径")
            return result

        except Exception as e:
            logger.error(f"[CosyVoice2] 合成失败: {e}")
            return ""


# ============================================================================
# MiMo TTS（云端 API）
# ============================================================================


class MiMoTTSProvider(TTSProvider):
    """MiMo-V2.5-TTS API Provider（通过 tp-api.com 调用）"""

    def __init__(self, config):
        from vir_bot.config import get_config

        app_config = get_config()
        self.api_key = app_config.ai.openai.api_key
        self.base_url = app_config.ai.openai.base_url.rstrip("/")
        self.model = config.mimo_model or "mimo-v2.5-tts"
        self.voice = config.mimo_voice or "冰糖"
        self.speed = config.speed
        self.timeout = 10

    async def synthesize(self, text: str, output_path: str, **kwargs) -> str | None:
        """合成语音，返回输出文件路径"""
        style_hint = kwargs.get("style_hint", "")
        messages = []
        if style_hint:
            messages.append({"role": "user", "content": style_hint})
        messages.append({"role": "assistant", "content": text})

        payload = {
            "model": self.model,
            "messages": messages,
            "audio": {"format": "wav", "voice": self.voice},
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"api-key": self.api_key},
                    json=payload,
                )
                resp.raise_for_status()

            data = resp.json()
            audio_b64 = data["choices"][0]["message"]["audio"]["data"]
            audio_bytes = base64.b64decode(audio_b64)

            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(audio_bytes)

            logger.info(f"MiMo TTS synthesized: {output_path} ({len(audio_bytes)} bytes)")
            return output_path

        except httpx.TimeoutException:
            logger.warning("MiMo TTS timeout")
            return None
        except httpx.HTTPStatusError as e:
            logger.warning(f"MiMo TTS HTTP error: {e.response.status_code}")
            return None
        except Exception as e:
            logger.warning(f"MiMo TTS error: {e}")
            return None


# ============================================================================
# TTS Fallback 链
# ============================================================================


class TTSFallbackProvider(TTSProvider):
    """带 Fallback 的 TTS Provider。主 Provider 失败时自动切换到备选。"""

    def __init__(self, primary: TTSProvider, fallback: TTSProvider):
        self.primary = primary
        self.fallback = fallback

    async def synthesize(self, text: str, output_path: str, **kwargs) -> str | None:
        result = await self.primary.synthesize(text, output_path, **kwargs)
        if result:
            return result
        logger.warning("Primary TTS failed, falling back to backup provider")
        return await self.fallback.synthesize(text, output_path, **kwargs)


# ============================================================================
# Edge TTS（轻量备选）
# ============================================================================


class EdgeTTSProvider(TTSProvider):
    """微软 Edge TTS（在线，免费，轻量）"""

    def __init__(self, voice_id: str = "zh-CN-XiaoxiaoNeural", speed: float = 1.0):
        self.voice_id = voice_id
        self.speed = speed

    async def synthesize(self, text: str, output_path: str, **kwargs) -> str:
        try:
            import edge_tts

            rate = f"{'+' if self.speed >= 1 else '-'}{int(abs(self.speed - 1) * 50)}%"
            communicate = edge_tts.Communicate(text, self.voice_id, rate=rate)
            await communicate.save(output_path)
            return output_path
        except ImportError:
            logger.warning("edge-tts not installed, TTS disabled")
            return ""
        except Exception as e:
            logger.error(f"[EdgeTTS] 合成失败: {e}")
            return ""


# ============================================================================
# OpenAI Whisper ASR（远程 API 备选）
# ============================================================================


class OpenAIWhisperASRProvider(ASRProvider):
    """OpenAI-compatible Whisper ASR（远程 API）"""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str = "whisper-1",
        language: str = "zh",
        timeout: int = 30,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.language = language
        self.timeout = timeout

    async def recognize(self, audio_path: str) -> str:
        try:
            import aiohttp
        except ImportError:
            logger.warning("aiohttp not installed, ASR disabled")
            return ""

        url = f"{self.base_url}/audio/transcriptions"
        headers = {"Authorization": f"Bearer {self.api_key}"}

        try:
            async with aiohttp.ClientSession() as session:
                data = aiohttp.FormData()
                data.add_field(
                    "file",
                    open(audio_path, "rb"),
                    filename=Path(audio_path).name,
                    content_type="audio/ogg",
                )
                data.add_field("model", self.model)
                data.add_field("language", self.language)

                async with session.post(
                    url,
                    data=data,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(self.timeout),
                ) as resp:
                    resp.raise_for_status()
                    result = await resp.json()
                    return result.get("text", "")
        except Exception as e:
            logger.error(f"[ASR] OpenAI Whisper API 调用失败: {e}")
            return ""


# ============================================================================
# Whisper ASR（本地模型备选）
# ============================================================================


class WhisperASRProvider(ASRProvider):
    """OpenAI Whisper ASR（本地模型）"""

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


# ============================================================================
# 唤醒词
# ============================================================================


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
# AI 语音决策
# ============================================================================


def _parse_voice_decision(content: str) -> tuple[str, bool]:
    """解析 LLM 回复中的 [VOICE] 标记。返回 (清理后文本, 是否使用语音)。"""
    use_voice = "[VOICE]" in content
    clean_content = content.replace("[VOICE]", "").strip()
    clean_content = re.sub(r"\n{3,}", "\n\n", clean_content)
    return clean_content, use_voice


def _build_style_hint(character, config) -> str:
    """从角色 personality 推断 TTS 风格指令。"""
    if config.voice.tts.mimo_style:
        return config.voice.tts.mimo_style
    personality = getattr(character, "personality", "")
    if not personality:
        return "用温柔自然的语调说话"
    return f"用{personality}的语调说话"


# ============================================================================
# 工具函数
# ============================================================================


async def convert_audio(input_path: str, output_path: str,
                        output_format: str = "ogg",
                        ffmpeg_path: str = "ffmpeg") -> str | None:
    """通过 ffmpeg 转换音频格式。成功返回输出路径，失败返回原始路径。"""
    if output_format in ("wav", ""):
        return input_path

    if output_format == "ogg":
        cmd = [ffmpeg_path, "-i", input_path, "-c:a", "libopus",
               "-b:a", "64k", output_path, "-y"]
    elif output_format == "mp3":
        cmd = [ffmpeg_path, "-i", input_path, "-c:a", "libmp3lame",
               "-b:a", "128k", output_path, "-y"]
    else:
        return input_path

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        if proc.returncode == 0:
            logger.info(f"Audio converted: {input_path} → {output_path}")
            return output_path
        else:
            logger.warning(f"ffmpeg conversion failed (exit code {proc.returncode})")
            return input_path
    except FileNotFoundError:
        logger.warning("ffmpeg not found, sending original format")
        return input_path


def create_tts(config) -> TTSProvider | None:
    """TTS 工厂函数。优先级：mimo(fallback→edge) > cosyvoice2 > edge"""
    if not config.enabled:
        return None

    provider = config.tts.provider.lower()

    try:
        if provider == "mimo":
            primary = MiMoTTSProvider(config.tts)
            fallback = EdgeTTSProvider(config.tts.voice_id, config.tts.speed)
            return TTSFallbackProvider(primary, fallback)

        if provider == "cosyvoice2":
            logger.warning("[TTS] cosyvoice2 provider 已弃用，回退到 edge-tts")
            return EdgeTTSProvider(config.tts.voice_id, config.tts.speed)

        return EdgeTTSProvider(config.tts.voice_id, config.tts.speed)
    except Exception as e:
        logger.error(f"[TTS] Provider 初始化失败: {e}")
        return None


def create_asr(config, ai_config=None) -> ASRProvider | None:
    """ASR 工厂函数。优先级：sensevoice > openai > whisper"""
    if not config.enabled:
        return None

    provider = config.asr.provider

    if provider == "sensevoice":
        try:
            return SenseVoiceASRProvider(
                model=getattr(config.asr, "model", "iic/SenseVoiceSmall"),
                language=config.asr.language,
                device=getattr(config.asr, "device", "cuda:0"),
            )
        except Exception as e:
            logger.error(f"[ASR] SenseVoice 初始化失败: {e}，回退到 openai")

    if provider == "openai" or (provider == "sensevoice"):
        # openai 作为主选或 SenseVoice 失败的回退
        base_url = getattr(config.asr, "base_url", "") or (
            ai_config.openai.base_url if ai_config else ""
        )
        api_key = getattr(config.asr, "api_key", "") or (
            ai_config.openai.api_key if ai_config else ""
        )
        if base_url and api_key:
            return OpenAIWhisperASRProvider(
                base_url=base_url,
                api_key=api_key,
                model=getattr(config.asr, "model", "whisper-1"),
                language=config.asr.language,
            )
        elif provider == "openai":
            logger.error("[ASR] OpenAI Whisper 需要 base_url 和 api_key")
            return None

    if provider == "whisper":
        return WhisperASRProvider(config.asr.model, config.asr.language)

    return None


def create_wake_word(config) -> WakeWordProvider | None:
    if not config.enabled:
        return None
    if config.wake_word.provider == "porcupine":
        return PorcupineWakeWordProvider(config.wake_word.keywords)
    return None
