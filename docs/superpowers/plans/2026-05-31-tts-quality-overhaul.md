---
change: tts-quality-overhaul
design-doc: docs/superpowers/specs/2026-05-31-tts-quality-overhaul-design.md
base-ref: a6bb7c3e4bd0ed1aa9b75087c77842159dda6a96
archived-with: 2026-05-31-tts-quality-overhaul
---

# MiMo TTS 质量改进 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 TTS 引擎从 CosyVoice2 替换为 MiMo-V2.5-TTS API，实现 AI 语音决策和文字+语音双发。

**Architecture:** MiMoTTSProvider 调用 tp-api.com 的 MiMo TTS API，输出 WAV 经 ffmpeg 转换为 OGG/Opus。LLM 通过 [VOICE] 标记决定是否使用语音。Telegram adapter 支持文字+语音双发。

**Tech Stack:** Python 3.12, httpx, ffmpeg (subprocess), edge-tts (fallback), Pydantic

archived-with: 2026-05-31-tts-quality-overhaul
---

## 文件结构

| 文件 | 职责 |
|------|------|
| `vir_bot/config.py` | 新增 MiMo TTS 配置字段 |
| `vir_bot/modules/voice/__init__.py` | MiMoTTSProvider、convert_audio、_parse_voice_decision |
| `vir_bot/core/pipeline/__init__.py` | 集成 AI 语音决策、格式转换 |
| `vir_bot/platforms/telegram_adapter.py` | 双发模式 |
| `vir_bot/platforms/base_adapter.py` | voice_mode 抽象 |
| `vir_bot/core/proactive/proactive_service.py` | 主动消息 TTS |
| `tests/test_tts.py` | TTS 测试 |
| `config.yaml` | 启用语音、切换到 mimo |

archived-with: 2026-05-31-tts-quality-overhaul
---

### Task 1: Config 新增 MiMo TTS 字段

**Files:**
- Modify: `vir_bot/config.py:234-264`
- Modify: `config.yaml:161-182`

- [ ] **Step 1: 在 VoiceTTSConfig 中新增字段**

在 `vir_bot/config.py` 的 `VoiceTTSConfig` 类中添加：

```python
class VoiceTTSConfig(BaseModel):
    provider: str = "mimo"  # mimo | edge（cosyvoice2 已废弃）
    voice_id: str = "zh-CN-XiaoxiaoNeural"  # Edge-TTS 音色
    speed: float = 1.0
    # CosyVoice2 专用配置（deprecated）
    model_dir: str = "pretrained_models/CosyVoice2-0.5B"
    voice_sample_path: str = ""
    voice_sample_text: str = ""
    instruct_text: str = "用温柔甜美的女声说话"
    # MiMo TTS 新增
    mimo_voice: str = "冰糖"  # MiMo 音色：冰糖/茉莉/苏打/白桦
    mimo_style: str = ""  # 风格指令（空=从 personality 推断）
    mimo_model: str = "mimo-v2.5-tts"  # mimo-v2.5-tts | voicedesign | voiceclone
    # 格式转换
    ffmpeg_path: str = "ffmpeg"
    output_format: str = "ogg"  # "ogg" | "wav" | "mp3"
```

- [ ] **Step 2: 在 VoiceConfig 中新增字段**

在 `vir_bot/config.py` 的 `VoiceConfig` 类中添加：

```python
class VoiceConfig(BaseModel):
    enabled: bool = False
    voice_response: bool = True
    voice_mode: str = "replace"  # replace | both | voice_only
    voice_decision: str = "ai"  # always | ai | never
    tts: VoiceTTSConfig = Field(default_factory=VoiceTTSConfig)
    asr: VoiceASRConfig = Field(default_factory=VoiceASRConfig)
    wake_word: VoiceWakeWordConfig = Field(default_factory=VoiceWakeWordConfig)
```

- [ ] **Step 3: 更新 config.yaml**

```yaml
voice:
  enabled: true
  voice_response: true
  voice_mode: "replace"
  voice_decision: "ai"
  tts:
    provider: "mimo"
    mimo_voice: "冰糖"
    mimo_style: ""
    mimo_model: "mimo-v2.5-tts"
    ffmpeg_path: "ffmpeg"
    output_format: "ogg"
    speed: 1.0
    voice_id: "zh-CN-XiaoxiaoNeural"
```

- [ ] **Step 4: 提交**

```bash
git add vir_bot/config.py config.yaml
git commit -m "feat: add MiMo TTS config fields and voice_decision"
```

archived-with: 2026-05-31-tts-quality-overhaul
---

### Task 2: 实现 MiMoTTSProvider

**Files:**
- Modify: `vir_bot/modules/voice/__init__.py`

- [ ] **Step 1: 添加 import 和 MiMoTTSProvider 类**

在 `vir_bot/modules/voice/__init__.py` 的 `TTSProvider` 抽象接口之后，EdgeTTSProvider 之前添加：

```python
import base64
import httpx


class MiMoTTSProvider(TTSProvider):
    """MiMo-V2.5-TTS API Provider（通过 tp-api.com 调用）"""

    def __init__(self, config):
        from vir_bot.config import config as app_config
        self.api_key = app_config.ai.api_key
        self.base_url = app_config.ai.base_url.rstrip("/")
        self.model = config.mimo_model or "mimo-v2.5-tts"
        self.voice = config.mimo_voice or "冰糖"
        self.speed = config.speed
        self.timeout = 10

    async def synthesize(self, text: str, output_path: str,
                         style_hint: str = "") -> str | None:
        """合成语音，返回输出文件路径"""
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
```

- [ ] **Step 2: 更新 create_tts() 工厂函数**

在 `create_tts()` 函数中添加 mimo 分支：

```python
def create_tts(config):
    if not config.enabled:
        return None

    provider = config.tts.provider.lower()
    try:
        if provider == "mimo":
            return MiMoTTSProvider(config.tts)
        elif provider == "cosyvoice2":
            logger.warning("CosyVoice2 is deprecated, falling back to edge-tts")
            return EdgeTTSProvider(config.tts)
        else:
            return EdgeTTSProvider(config.tts)
    except Exception as e:
        logger.error(f"Failed to create TTS provider '{provider}': {e}")
        return None
```

- [ ] **Step 3: 提交**

```bash
git add vir_bot/modules/voice/__init__.py
git commit -m "feat: implement MiMoTTSProvider for MiMo-V2.5-TTS API"
```

archived-with: 2026-05-31-tts-quality-overhaul
---

### Task 3: 音频格式转换

**Files:**
- Modify: `vir_bot/modules/voice/__init__.py`

- [ ] **Step 1: 添加 convert_audio 工具函数**

在 `voice/__init__.py` 中添加：

```python
async def convert_audio(input_path: str, output_path: str,
                        output_format: str = "ogg",
                        ffmpeg_path: str = "ffmpeg") -> str | None:
    """通过 ffmpeg 转换音频格式"""
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
```

- [ ] **Step 2: 提交**

```bash
git add vir_bot/modules/voice/__init__.py
git commit -m "feat: add ffmpeg audio format conversion utility"
```

archived-with: 2026-05-31-tts-quality-overhaul
---

### Task 4: AI 语音决策机制

**Files:**
- Modify: `vir_bot/modules/voice/__init__.py`
- Modify: `vir_bot/core/pipeline/__init__.py`

- [ ] **Step 1: 添加 _parse_voice_decision 函数**

在 `voice/__init__.py` 中添加：

```python
import re


def _parse_voice_decision(content: str) -> tuple[str, bool]:
    """解析 LLM 回复中的 [VOICE] 标记"""
    use_voice = "[VOICE]" in content
    clean_content = content.replace("[VOICE]", "").strip()
    clean_content = re.sub(r"\n{3,}", "\n\n", clean_content)
    return clean_content, use_voice
```

- [ ] **Step 2: 添加 _build_style_hint 函数**

```python
def _build_style_hint(character, config) -> str:
    """从角色 personality 推断 TTS 风格"""
    if config.voice.tts.mimo_style:
        return config.voice.tts.mimo_style

    personality = getattr(character, "personality", "")
    if not personality:
        return "用温柔自然的语调说话"

    return f"用{personality}的语调说话"
```

- [ ] **Step 3: 修改 Pipeline 集成 AI 语音决策**

在 `vir_bot/core/pipeline/__init__.py` 的 `_synthesize_tts` 方法和 TTS 触发点修改：

```python
# 在 AI 回复生成后
from vir_bot.modules.voice import _parse_voice_decision, _build_style_hint, convert_audio

# 解析 [VOICE] 标记
content, use_voice = _parse_voice_decision(response.content)

voice_decision = self.voice_config.voice_decision
should_synthesize = (
    self.tts
    and self.voice_config
    and (
        voice_decision == "always"
        or (voice_decision == "ai" and use_voice)
    )
)

voice_file = None
if should_synthesize:
    style = _build_style_hint(character, self.config)
    voice_file = await self._synthesize_tts(content, style)
    if voice_file and self.voice_config.tts.output_format != "wav":
        ogg_path = voice_file.rsplit(".", 1)[0] + ".ogg"
        converted = await convert_audio(
            voice_file, ogg_path,
            self.voice_config.tts.output_format,
            self.voice_config.tts.ffmpeg_path,
        )
        if converted:
            voice_file = converted

metadata["voice_file"] = voice_file
metadata["use_voice"] = should_synthesize
```

- [ ] **Step 4: 修改 _synthesize_tts 支持 style_hint**

```python
async def _synthesize_tts(self, text: str, style_hint: str = "") -> str | None:
    """合成语音"""
    try:
        import hashlib
        text_hash = hashlib.md5(text.encode()).hexdigest()[:8]
        output_path = f"./data/cache/voice_{int(time.time())}_{text_hash}.wav"
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        return await self.tts.synthesize(text, output_path, style_hint)
    except Exception as e:
        logger.error(f"TTS synthesis failed: {e}")
        return None
```

- [ ] **Step 5: 提交**

```bash
git add vir_bot/modules/voice/__init__.py vir_bot/core/pipeline/__init__.py
git commit -m "feat: integrate AI voice decision and format conversion into pipeline"
```

archived-with: 2026-05-31-tts-quality-overhaul
---

### Task 5: Telegram 双发模式

**Files:**
- Modify: `vir_bot/platforms/telegram_adapter.py`
- Modify: `vir_bot/platforms/base_adapter.py`

- [ ] **Step 1: 修改 base_adapter.py 的 send_message**

在 `base_adapter.py` 的 `send_message` 方法中添加 voice_mode 支持：

```python
async def send_message(self, chat_id: str, response: PlatformResponse):
    """发送消息（文字/语音）"""
    voice_file = response.metadata.get("voice_file")
    use_voice = response.metadata.get("use_voice", False)
    voice_mode = getattr(self, "voice_mode", "replace")

    if use_voice and voice_file:
        if voice_mode == "both":
            if response.content:
                await self._send_text(chat_id, response)
            await self._send_voice(chat_id, voice_file)
        elif voice_mode == "voice_only":
            await self._send_voice(chat_id, voice_file)
        else:  # replace
            await self._send_voice(chat_id, voice_file)
        self._cleanup_voice_file(voice_file)
    else:
        await self._send_text(chat_id, response)
```

- [ ] **Step 2: 修改 telegram_adapter.py**

在 `telegram_adapter.py` 的 `send_message` 方法中实现双发逻辑：

```python
async def send_message(self, chat_id: str, response: PlatformResponse):
    voice_file = response.metadata.get("voice_file")
    use_voice = response.metadata.get("use_voice", False)

    if use_voice and voice_file:
        # 先发文字（如果有）
        if response.content:
            await self.bot.send_message(chat_id, response.content)
        # 再发语音
        await self._send_voice(chat_id, voice_file)
        self._cleanup_voice_file(voice_file)
    else:
        # 纯文字
        await self._send_text_impl(chat_id, response)
```

- [ ] **Step 3: 提交**

```bash
git add vir_bot/platforms/telegram_adapter.py vir_bot/platforms/base_adapter.py
git commit -m "feat: implement voice+text dual-send mode for Telegram"
```

archived-with: 2026-05-31-tts-quality-overhaul
---

### Task 6: Fallback 策略

**Files:**
- Modify: `vir_bot/modules/voice/__init__.py`

- [ ] **Step 1: 实现 TTSFallbackProvider**

在 `voice/__init__.py` 中添加：

```python
class TTSFallbackProvider(TTSProvider):
    """带 Fallback 的 TTS Provider"""

    def __init__(self, primary: TTSProvider, fallback: TTSProvider):
        self.primary = primary
        self.fallback = fallback

    async def synthesize(self, text: str, output_path: str,
                         style_hint: str = "") -> str | None:
        result = await self.primary.synthesize(text, output_path, style_hint)
        if result:
            return result
        logger.warning("Primary TTS failed, falling back to Edge-TTS")
        return await self.fallback.synthesize(text, output_path)
```

- [ ] **Step 2: 更新 create_tts() 使用 Fallback**

```python
def create_tts(config):
    if not config.enabled:
        return None

    provider = config.tts.provider.lower()
    try:
        if provider == "mimo":
            primary = MiMoTTSProvider(config.tts)
            fallback = EdgeTTSProvider(config.tts)
            return TTSFallbackProvider(primary, fallback)
        elif provider == "cosyvoice2":
            logger.warning("CosyVoice2 is deprecated, using Edge-TTS")
            return EdgeTTSProvider(config.tts)
        else:
            return EdgeTTSProvider(config.tts)
    except Exception as e:
        logger.error(f"Failed to create TTS provider: {e}")
        return None
```

- [ ] **Step 3: 提交**

```bash
git add vir_bot/modules/voice/__init__.py
git commit -m "feat: implement TTS fallback chain (MiMo → Edge-TTS)"
```

archived-with: 2026-05-31-tts-quality-overhaul
---

### Task 7: System Prompt 注入语音决策指令

**Files:**
- Modify: `vir_bot/core/pipeline/__init__.py`

- [ ] **Step 1: 在 system prompt 中注入语音指令**

在 pipeline 构建 system prompt 时，如果 voice_decision == "ai"，追加：

```python
VOICE_DECISION_PROMPT = """
当你想用语音回复用户时，在回复末尾加上 [VOICE] 标记。

适合用语音的场景：
- 情感表达（关心、安慰、开心、撒娇）
- 日常问候和闲聊
- 简短的回复（< 200 字）

适合用文字的场景：
- 代码、技术说明
- 列表、表格
- 长文（> 200 字）
"""
```

- [ ] **Step 2: 提交**

```bash
git add vir_bot/core/pipeline/__init__.py
git commit -m "feat: inject voice decision prompt into system prompt"
```

archived-with: 2026-05-31-tts-quality-overhaul
---

### Task 8: 主动消息 TTS 集成

**Files:**
- Modify: `vir_bot/core/proactive/proactive_service.py`

- [ ] **Step 1: 在 ProactiveService 中注入 TTS**

在 `ProactiveService` 的 `send_proactive_message` 方法中添加 TTS 支持：

```python
async def send_proactive_message(self, user_id: str, content: str):
    """发送主动消息（支持 TTS）"""
    voice_file = None
    if self.tts and self.voice_config and self.voice_config.voice_response:
        voice_file = await self._synthesize_tts(content)

    await self.adapter.send_message(
        user_id,
        PlatformResponse(
            content=content,
            metadata={"voice_file": voice_file, "use_voice": voice_file is not None},
        ),
    )
```

- [ ] **Step 2: 提交**

```bash
git add vir_bot/core/proactive/proactive_service.py
git commit -m "feat: integrate TTS into proactive message service"
```

archived-with: 2026-05-31-tts-quality-overhaul
---

### Task 9: 清理 CosyVoice2 死代码

**Files:**
- Modify: `vir_bot/modules/voice/__init__.py`

- [ ] **Step 1: 标记 CosyVoice2TTSProvider 为 deprecated**

在 `CosyVoice2TTSProvider` 类上方添加：

```python
import warnings

# @deprecated - CosyVoice2 已被 MiMo TTS 替换，保留代码供参考
class CosyVoice2TTSProvider(TTSProvider):
    ...
```

- [ ] **Step 2: 移除 sys.path 拼接**

移除 `voice/__init__.py` 中的 `sys.path.append` 调用（约 190-195 行）。

- [ ] **Step 3: 更新模块 docstring**

```python
"""语音模块（TTS / ASR）

架构：
  ASR: SenseVoice (主) → OpenAI Whisper API (备) → Vosk (离线备)
  TTS: MiMo-V2.5-TTS (主，API) → edge-tts (备)
"""
```

- [ ] **Step 4: 提交**

```bash
git add vir_bot/modules/voice/__init__.py
git commit -m "refactor: deprecate CosyVoice2, clean up sys.path hacks"
```

archived-with: 2026-05-31-tts-quality-overhaul
---

### Task 10: 更新 config_router.py 音色列表

**Files:**
- Modify: `vir_bot/api/routers/config_router.py`

- [ ] **Step 1: 替换 Edge-TTS 音色列表为 MiMo 音色**

在 `config_router.py` 中将 Edge-TTS 音色列表替换为：

```python
TTS_VOICE_OPTIONS = [
    {"label": "冰糖（中文女声·温柔甜美）", "value": "冰糖"},
    {"label": "茉莉（中文女声·清新自然）", "value": "茉莉"},
    {"label": "苏打（中文男声·阳光开朗）", "value": "苏打"},
    {"label": "白桦（中文男声·沉稳磁性）", "value": "白桦"},
]
```

- [ ] **Step 2: 提交**

```bash
git add vir_bot/api/routers/config_router.py
git commit -m "feat: update voice options to MiMo TTS voices"
```

archived-with: 2026-05-31-tts-quality-overhaul
---

### Task 11: 测试

**Files:**
- Create: `tests/test_tts.py`

- [ ] **Step 1: 编写 MiMoTTSProvider 单元测试**

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from vir_bot.modules.voice import MiMoTTSProvider, _parse_voice_decision, _build_style_hint


class TestMiMoTTSProvider:
    def test_init(self):
        config = MagicMock()
        config.mimo_model = "mimo-v2.5-tts"
        config.mimo_voice = "冰糖"
        config.speed = 1.0
        provider = MiMoTTSProvider(config)
        assert provider.model == "mimo-v2.5-tts"
        assert provider.voice == "冰糖"

    @pytest.mark.asyncio
    async def test_synthesize_success(self):
        config = MagicMock()
        config.mimo_model = "mimo-v2.5-tts"
        config.mimo_voice = "冰糖"
        config.speed = 1.0
        provider = MiMoTTSProvider(config)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"audio": {"data": "UklGRiQAAABXQVZFZm10"}}}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
            with patch("builtins.open", MagicMock()):
                result = await provider.synthesize("hello", "/tmp/test.wav")
                assert result == "/tmp/test.wav"

    @pytest.mark.asyncio
    async def test_synthesize_timeout(self):
        config = MagicMock()
        config.mimo_model = "mimo-v2.5-tts"
        config.mimo_voice = "冰糖"
        config.speed = 1.0
        provider = MiMoTTSProvider(config)

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=Exception("timeout")):
            result = await provider.synthesize("hello", "/tmp/test.wav")
            assert result is None


class TestVoiceDecision:
    def test_parse_voice_tag(self):
        content, use_voice = _parse_voice_decision("Hello world [VOICE]")
        assert use_voice is True
        assert content == "Hello world"

    def test_parse_no_voice_tag(self):
        content, use_voice = _parse_voice_decision("Hello world")
        assert use_voice is False
        assert content == "Hello world"

    def test_parse_cleans_extra_newlines(self):
        content, _ = _parse_voice_decision("Hello\n\n\n\nWorld [VOICE]")
        assert "\n\n\n" not in content


class TestStyleHint:
    def test_manual_style(self):
        config = MagicMock()
        config.voice.tts.mimo_style = "用磁性的声音说话"
        result = _build_style_hint(MagicMock(), config)
        assert result == "用磁性的声音说话"

    def test_auto_from_personality(self):
        config = MagicMock()
        config.voice.tts.mimo_style = ""
        character = MagicMock()
        character.personality = "温柔活泼"
        result = _build_style_hint(character, config)
        assert "温柔活泼" in result

    def test_default_style(self):
        config = MagicMock()
        config.voice.tts.mimo_style = ""
        character = MagicMock()
        character.personality = ""
        result = _build_style_hint(character, config)
        assert "温柔" in result
```

- [ ] **Step 2: 运行测试**

```bash
PYTHONPATH=. uv run pytest tests/test_tts.py -v
```

- [ ] **Step 3: 提交**

```bash
git add tests/test_tts.py
git commit -m "test: add MiMo TTS provider and voice decision tests"
```

archived-with: 2026-05-31-tts-quality-overhaul
---

### Task 12: 端到端验证

- [ ] **Step 1: 运行全量测试**

```bash
PYTHONPATH=. uv run pytest tests/ -q
```

- [ ] **Step 2: 手动验证 Telegram 语音发送**

启动 bot，发送消息，确认：
- AI 回复包含 [VOICE] 标记时，Telegram 收到语音消息
- 音频格式为 OGG/Opus
- fallback 到 Edge-TTS 时仍能正常工作

- [ ] **Step 3: 最终提交**

```bash
git add -A
git commit -m "chore: TTS quality overhaul complete"
```
