---
comet_change: tts-quality-overhaul
role: technical-design
canonical_spec: openspec
archived-with: 2026-05-31-tts-quality-overhaul
status: final
---

# MiMo TTS 质量改进 — 技术设计文档

## 1. 概述

将 vir-bot 的 TTS 引擎从 CosyVoice2 本地模型替换为 MiMo-V2.5-TTS API，解决音质差、速度慢、格式错配等核心问题。同时引入 AI 驱动的语音决策机制和文字+语音双发模式。

### 核心变更
- **TTS 引擎替换**：CosyVoice2 → MiMo-V2.5-TTS API
- **API 端点**：`tp-api.com/v1/chat/completions`（与 LLM 共用同一端点和 Key）
- **默认音色**：冰糖（中文女声，温柔甜美）
- **语音决策**：AI 驱动（LLM 通过 `[VOICE]` 标记表达意图）
- **音频格式**：WAV → OGG/Opus（via ffmpeg）
- **Fallback**：MiMo → Edge-TTS → None

## 2. 架构设计

### 2.1 整体数据流

```
用户消息 → Pipeline → LLM 生成回复（含 [VOICE] 标记）
                          │
                          ├─ 解析 [VOICE] 标记 → use_voice = true/false
                          │
                          ├─ if use_voice && voice.enabled:
                          │   ├─ _build_style_hint(character) → style
                          │   ├─ MiMoTTSProvider.synthesize(text, path, style)
                          │   │   └─ POST tp-api.com/v1/chat/completions
                          │   │       model: "mimo-v2.5-tts"
                          │   │       messages: [user: style, assistant: text]
                          │   │       audio: {format: "wav", voice: "冰糖"}
                          │   │   └─ base64 decode → WAV file
                          │   ├─ convert_audio(wav, ogg) via ffmpeg
                          │   └─ metadata["voice_file"] = ogg_path
                          │       metadata["use_voice"] = true
                          │
                          └─ Platform Adapter
                              ├─ Telegram: send_text() + send_voice()
                              └─ 其他平台: send_text() (voice TODO)
```

### 2.2 MiMoTTSProvider

```python
class MiMoTTSProvider:
    """MiMo-V2.5-TTS API Provider"""

    def __init__(self, config: VoiceTTSConfig):
        self.api_key = config.api_key  # 复用 LLM 的 Key
        self.base_url = config.base_url  # tp-api.com/v1
        self.model = config.mimo_model or "mimo-v2.5-tts"
        self.voice = config.mimo_voice or "冰糖"
        self.timeout = 10  # 秒

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
            "audio": {"format": "wav", "voice": self.voice}
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"api-key": self.api_key},
                json=payload
            )
            resp.raise_for_status()

        data = resp.json()
        audio_b64 = data["choices"][0]["message"]["audio"]["data"]
        audio_bytes = base64.b64decode(audio_b64)

        with open(output_path, "wb") as f:
            f.write(audio_bytes)

        return output_path
```

### 2.3 AI 语音决策机制

**System Prompt 注入**：
```
当你想用语音回复用户时，在回复末尾加上 [VOICE] 标记。

适合用语音的场景：
- 情感表达（关心、安慰、开心、撒娇）
- 日常问候和闲聊
- 简短的回复（< 200 字）

适合用文字的场景：
- 代码、技术说明
- 列表、表格
- 长文（> 200 字）
- 用户明确要求文字回复
```

**解析逻辑**：
```python
def _parse_voice_decision(content: str) -> tuple[str, bool]:
    use_voice = "[VOICE]" in content
    clean_content = content.replace("[VOICE]", "").strip()
    # 清理多余的空行
    clean_content = re.sub(r'\n{3,}', '\n\n', clean_content)
    return clean_content, use_voice
```

**配置**：
```yaml
voice:
  voice_decision: "ai"  # "always" | "ai" | "never"
```

- `always`：所有回复都用语音（忽略 [VOICE] 标记）
- `ai`：LLM 通过 [VOICE] 标记决定
- `never`：禁用语音（即使 voice.enabled=true）

### 2.4 音频格式转换

```python
async def convert_audio(input_path: str, output_path: str,
                        output_format: str = "ogg") -> str | None:
    """通过 ffmpeg 转换音频格式"""
    if output_format == "ogg":
        cmd = ["ffmpeg", "-i", input_path, "-c:a", "libopus",
               "-b:a", "64k", output_path, "-y"]
    elif output_format == "mp3":
        cmd = ["ffmpeg", "-i", input_path, "-c:a", "libmp3lame",
               "-b:a", "128k", output_path, "-y"]
    else:
        return input_path  # 不转换

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await proc.wait()
        if proc.returncode == 0:
            return output_path
    except FileNotFoundError:
        logger.warning("ffmpeg not found, sending original format")

    return input_path  # fallback 到原始格式
```

### 2.5 Telegram 双发逻辑

```python
# telegram_adapter.py
async def send_message(self, chat_id: str, response: PlatformResponse):
    voice_file = response.metadata.get("voice_file")
    use_voice = response.metadata.get("use_voice", False)

    if use_voice and voice_file:
        # AI 决定用语音：先发文字（如果有），再发语音
        if response.content:
            await self.bot.send_message(chat_id, response.content)
        await self._send_voice(chat_id, voice_file)
        # 清理临时文件
        self._cleanup_voice_file(voice_file)
    else:
        # 纯文字回复
        await self._send_text(chat_id, response)
```

### 2.6 MiMo 风格控制

```python
def _build_style_hint(character, config) -> str:
    """从角色 personality 推断 TTS 风格"""
    # 手动配置优先
    if config.voice.tts.mimo_style:
        return config.voice.tts.mimo_style

    # 从 personality 自动提取
    personality = getattr(character, 'personality', '')
    if not personality:
        return "用温柔自然的语调说话"

    # personality → 风格指令映射
    return f"用{personality}的语调说话，语气温柔亲切"
```

### 2.7 Fallback 策略

```python
class TTSFallbackProvider:
    """带 Fallback 的 TTS Provider"""

    def __init__(self, primary: MiMoTTSProvider, fallback: EdgeTTSProvider):
        self.primary = primary
        self.fallback = fallback

    async def synthesize(self, text, output_path, style_hint=""):
        try:
            return await self.primary.synthesize(text, output_path, style_hint)
        except (httpx.HTTPStatusError, httpx.TimeoutException, Exception) as e:
            logger.warning(f"MiMo TTS failed: {e}, falling back to Edge-TTS")
            return await self.fallback.synthesize(text, output_path)
```

**Fallback 触发条件**：
- MiMo API 返回 429（配额耗尽）
- MiMo API 超时（10s）
- 网络连接错误
- 响应格式异常

## 3. 配置变更

### config.py 新增字段

```python
class VoiceTTSConfig(BaseModel):
    provider: str = "mimo"           # "mimo" | "edge"（cosyvoice2 已废弃）
    voice_id: str = "zh-CN-XiaoxiaoNeural"  # Edge-TTS 音色
    speed: float = 1.0
    model_dir: str = "pretrained_models/CosyVoice2-0.5B"  # deprecated
    voice_sample_path: str = ""      # deprecated
    voice_sample_text: str = ""      # deprecated
    instruct_text: str = "用温柔甜美的女声说话"  # deprecated

    # MiMo TTS 新增
    mimo_voice: str = "冰糖"         # MiMo 音色：冰糖/茉莉/苏打/白桦
    mimo_style: str = ""             # 风格指令（空=从 personality 推断）
    mimo_model: str = "mimo-v2.5-tts"  # mimo-v2.5-tts | voicedesign | voiceclone

    # 格式转换
    ffmpeg_path: str = "ffmpeg"
    output_format: str = "ogg"       # "ogg" | "wav" | "mp3"

class VoiceConfig(BaseModel):
    enabled: bool = False
    voice_response: bool = True
    voice_mode: str = "replace"      # "replace" | "both" | "voice_only"
    voice_decision: str = "ai"       # "always" | "ai" | "never"
    tts: VoiceTTSConfig = Field(default_factory=VoiceTTSConfig)
    asr: VoiceASRConfig = Field(default_factory=VoiceASRConfig)
    wake_word: VoiceWakeWordConfig = Field(default_factory=VoiceWakeWordConfig)
```

### config.yaml 变更

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
```

## 4. 文件变更清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `vir_bot/modules/voice/__init__.py` | 重构 | 新增 MiMoTTSProvider、TTSFallbackProvider、convert_audio、_parse_voice_decision |
| `vir_bot/core/pipeline/__init__.py` | 修改 | 集成 AI 语音决策、格式转换调用 |
| `vir_bot/platforms/telegram_adapter.py` | 修改 | 双发模式实现 |
| `vir_bot/platforms/base_adapter.py` | 修改 | voice_mode 抽象 |
| `vir_bot/config.py` | 修改 | 新增配置字段 |
| `vir_bot/core/proactive/proactive_service.py` | 修改 | TTS 集成 |
| `tests/test_tts.py` | 新增 | MiMo TTS 测试 |
| `config.yaml` | 修改 | 启用语音、切换到 mimo |

## 5. 测试策略

### 单元测试
- MiMoTTSProvider（mock httpx 响应）
- _parse_voice_decision（各种标记场景）
- convert_audio（ffmpeg 可用/不可用）
- _build_style_hint（手动配置/自动推断）

### 集成测试
- TTSFallbackProvider（MiMo 失败 → Edge-TTS）
- Pipeline 完整流程（文本 → [VOICE] 解析 → TTS → 文件）

### 端到端测试
- Telegram 发送语音消息（需手动验证）
- 双发模式（文字+语音）

## 6. 技术风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| MiMo API 超时 | 语音发送延迟 | 10s 超时 + 自动 fallback |
| API 配额耗尽 | 语音功能中断 | 捕获 429 + fallback + 日志告警 |
| ffmpeg 未安装 | 格式转换失败 | 检测可用性，不可用时发 WAV |
| [VOICE] 标记不一致 | 语音决策不准 | "always" 模式兜底 + 标记清理 |
| tp-api.com 不支持 TTS | 无法调用 MiMo TTS | 已确认支持，fallback 到 api.xiaomimimo.com |
