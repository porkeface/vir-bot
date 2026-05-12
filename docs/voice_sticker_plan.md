# 语音 & 表情包功能技术方案

> 状态：方案设计阶段
> 目标：让机器人能听（语音识别）、能说（语音合成）、能发表情包
> 前提：设备联网，云端+本地混合架构
> 核心发现：阿里巴巴 FunAudioLLM 团队的 SenseVoice + CosyVoice 2 是目前中文最优方案

---

## 一、技术选型结论

### 最终选型

| 功能 | 主引擎 | 降级引擎 | 费用 |
|------|--------|---------|------|
| **STT 语音识别** | SenseVoice (Alibaba) | Vosk | 全免费 |
| **TTS 语音合成** | CosyVoice 2 (Alibaba) | Piper TTS | 全免费 |
| **表情包** | 文件夹+metadata 管理 | - | 全免费 |

### 为什么选这套

**SenseVoice vs Whisper vs Vosk：**

| 对比项 | SenseVoice | Whisper Large-v3 | Vosk |
|--------|-----------|-----------------|------|
| 中文准确率 | ★★★★★ (~97%) | ★★★★ (~93%) | ★★★ (~90%) |
| 推理速度 | <10ms/段 | ~500ms/段 | ~100ms/段 |
| 情绪检测 | ✅ 内置 | ❌ | ❌ |
| 音频事件检测 | ✅ 内置 | ❌ | ❌ |
| 多语言 | 中英日韩粤 | 99语言 | 20语言 |
| 模型大小 | ~450MB | ~3GB | ~50MB |
| 开源 | ✅ MIT | ✅ MIT | ✅ Apache |

**CosyVoice 2 vs Fish Audio vs Piper TTS：**

| 对比项 | CosyVoice 2 | Fish Audio | Piper TTS |
|--------|------------|------------|-----------|
| 中文质量 | ★★★★★ | ★★★★★ | ★★★ |
| 声音克隆 | ✅ 10秒音频 | ✅ 需上传 | ❌ |
| 流式输出 | ✅ 支持 | ✅ 支持 | ❌ |
| 延迟 | ~300ms | ~300ms | ~300ms |
| 费用 | 免费 | 付费 | 免费 |
| 离线可用 | ✅ | ❌ | ✅ |
| 开源 | ✅ Apache 2.0 | 部分开源 | ✅ MIT |

---

## 二、整体架构

```
用户发送语音 (Telegram OGG/Opus)
    ↓
┌─────────────────────────────────────┐
│   STT 语音识别                       │
│                                     │
│   网络正常 → SenseVoice (本地模型)   │
│     • 中文准确率 97%                  │
│     • 速度 <10ms/段                   │
│     • 自带情绪检测                    │
│                                     │
│   网络异常/资源不足 → Vosk           │
│     • 模型仅 50MB                     │
│     • CPU 即可运行                    │
│     • 作为兜底保障                    │
└─────────────────────────────────────┘
    ↓ 文字 + 情绪标签
┌─────────────────────────────────────┐
│   Pipeline 消息处理 (现有逻辑不变)   │
└─────────────────────────────────────┘
    ↓ AI 回复文字
┌──────────────────────────────────────────┐
│          回复路由 (ResponseRouter)         │
│                                          │
│  文字模式 → send_message (现有)           │
│  语音模式 → TTS → send_voice             │
│  表情模式 → send_sticker (file_id)       │
│  混合模式 → 文字 + 表情 或 文字 + 语音    │
└──────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│   TTS 语音合成                       │
│                                     │
│   网络正常 → CosyVoice 2 (本地模型)  │
│     • 中文效果最好                    │
│     • 支持声音克隆                    │
│     • 流式输出，延迟低                │
│                                     │
│   网络异常/资源不足 → Piper TTS      │
│     • 模型仅 60MB                     │
│     • CPU 即可运行                    │
│     • 作为兜底保障                    │
└─────────────────────────────────────┘
    ↓ OGG/Opus 音频
┌─────────────────────────────────────┐
│   Telegram send_voice               │
└─────────────────────────────────────┘
```

**架构说明：**
- SenseVoice 和 CosyVoice 2 都是**本地模型**，不需要调用云端 API
- 有网络时可以下载模型、更新模型，但推理完全在本地
- 断网时用 Vosk + Piper 兜底，确保不瘫痪
- 全程**零 API 费用**

---

## 三、STT 语音识别模块

### 3.1 SenseVoice（主引擎）

**简介：** 阿里巴巴 FunAudioLLM 团队开发，专为中文优化的语音理解模型。

**核心能力：**
- 语音识别（ASR）：中文准确率 ~97%
- 情绪识别：自动检测说话人情绪
- 音频事件检测：识别笑声、掌声、音乐等
- 语言识别：自动判断语种

**Python 集成：**

```python
from funasr import AutoModel

# 加载模型（首次运行会自动下载）
model = AutoModel(
    model="iic/SenseVoiceSmall",
    vad_model="fsmn-vad",           # 语音活动检测
    vad_kwargs={"max_single_segment_time": 30000},
    trust_remote_code=True,
)

async def transcribe(audio_path: str) -> dict:
    """转录音频，返回文字和情绪"""
    result = model.generate(
        input=audio_path,
        cache={},
        language="auto",              # 自动检测语言
        use_itn=True,                 # 逆文本正则化（数字、日期等）
        batch_size_s=60,
    )
    # result 包含: text, emotion, event, language
    return {
        "text": result[0]["text"],
        "emotion": result[0].get("emotion", "neutral"),
        "language": result[0].get("language", "zh"),
    }
```

**资源需求：**

| 资源 | 用量 |
|------|------|
| 模型大小 | ~450MB (SenseVoiceSmall) |
| 内存占用 | ~1GB |
| 推理速度 | <10ms/段 (GPU) / ~100ms/段 (CPU) |
| 磁盘 | ~500MB |

**部署要求：**
- GPU（推荐）：NVIDIA 显卡，2GB+ 显存
- CPU（可用）：推理稍慢但可用
- Python 3.8+
- PyTorch

### 3.2 Vosk（降级引擎）

**简介：** 轻量级离线语音识别，适合资源受限环境。

**Python 集成：**

```python
import vosk
import json
import wave

class VoskRecognizer:
    def __init__(self, model_path: str = "vosk-model-cn-0.22"):
        self.model = vosk.Model(model_path)

    def transcribe(self, wav_path: str) -> str:
        rec = vosk.KaldiRecognizer(self.model, 16000)
        wf = wave.open(wav_path, "rb")
        while True:
            data = wf.readframes(4000)
            if len(data) == 0:
                break
            rec.AcceptWaveform(data)
        result = json.loads(rec.FinalResult())
        return result.get("text", "")
```

**资源需求：**

| 资源 | 用量 |
|------|------|
| 模型大小 | ~50MB |
| 内存占用 | ~100MB |
| 推理速度 | ~100ms/段 |
| 磁盘 | ~50MB |

### 3.3 STT 自动降级逻辑

```python
class SpeechRecognizer:
    def __init__(self):
        self.sensevoice = None  # 延迟加载
        self.vosk = None

    async def transcribe(self, audio_path: str) -> str:
        # 优先用 SenseVoice
        try:
            if self.sensevoice is None:
                self.sensevoice = self._load_sensevoice()
            result = self._sensevoice_transcribe(audio_path)
            return result["text"]
        except Exception as e:
            logger.warning(f"SenseVoice 失败，降级到 Vosk: {e}")

        # 降级到 Vosk
        try:
            if self.vosk is None:
                self.vosk = self._load_vosk()
            return self._vosk_transcribe(audio_path)
        except Exception as e:
            logger.error(f"Vosk 也失败了: {e}")
            return ""

    def _load_sensevoice(self):
        from funasr import AutoModel
        return AutoModel(
            model="iic/SenseVoiceSmall",
            vad_model="fsmn-vad",
            trust_remote_code=True,
        )

    def _load_vosk(self):
        import vosk
        return vosk.Model("vosk-model-cn-0.22")
```

---

## 四、TTS 语音合成模块

### 4.1 CosyVoice 2（主引擎）

**简介：** 阿里巴巴通义实验室开发，目前中文效果最好的开源 TTS。

**核心能力：**
- 中文语音合成：最自然的中文语音
- 声音克隆：10秒音频即可克隆
- 流式输出：支持实时合成
- 多语言：中英日韩粤

**Python 集成：**

```python
from cosyvoice.cli.cosyvoice import CosyVoice2
import torchaudio

class CosyVoiceSynthesizer:
    def __init__(self, model_path: str = "pretrained_models/CosyVoice2-0.5B"):
        self.model = CosyVoice2(model_path)

    async def synthesize(self, text: str, output_path: str) -> str:
        """合成语音"""
        # 使用预设音色
        output = self.model.inference_sft(
            tts_text=text,
            speaker="中文女",              # 预设音色
        )
        # 保存音频
        torchaudio.save(output_path, output["tts_speech"], 22050)
        return output_path

    async def synthesize_with_clone(self, text: str, prompt_audio: str,
                                     prompt_text: str, output_path: str) -> str:
        """用克隆的声音合成"""
        output = self.model.inference_zero_shot(
            tts_text=text,
            prompt_text=prompt_text,
            prompt_speech=prompt_audio,
        )
        torchaudio.save(output_path, output["tts_speech"], 22050)
        return output_path
```

**资源需求：**

| 资源 | 用量 |
|------|------|
| 模型大小 | ~1GB (CosyVoice2-0.5B) |
| 内存占用 | ~2GB |
| 推理速度 | ~300ms/句 |
| 磁盘 | ~1.5GB |

**部署要求：**
- GPU（推荐）：NVIDIA 显卡，4GB+ 显存
- CPU（可用）：推理较慢，但可接受
- Python 3.8+
- PyTorch

### 4.2 Piper TTS（降级引擎）

**简介：** 轻量级离线 TTS，适合资源受限环境。

**Python 集成：**

```python
import subprocess

class PiperSynthesizer:
    def __init__(self, model_path: str = "zh_CN-huayan-medium.onnx"):
        self.model_path = model_path

    def synthesize(self, text: str, output_path: str) -> str:
        proc = subprocess.run(
            ["piper", "--model", self.model_path, "--output_file", output_path],
            input=text.encode("utf-8"),
            capture_output=True,
        )
        return output_path
```

**资源需求：**

| 资源 | 用量 |
|------|------|
| 模型大小 | ~60MB |
| 内存占用 | ~100MB |
| 推理速度 | ~300ms/句 |
| 磁盘 | ~60MB |

### 4.3 TTS 自动降级逻辑

```python
class VoiceSynthesizer:
    def __init__(self):
        self.cosyvoice = None  # 延迟加载
        self.piper = None

    async def synthesize(self, text: str) -> Path:
        # 优先用 CosyVoice 2
        try:
            if self.cosyvoice is None:
                self.cosyvoice = self._load_cosyvoice()
            wav_path = f"/tmp/tts_{hash(text)}.wav"
            await self.cosyvoice.synthesize(text, wav_path)
            ogg_path = await self._convert_to_ogg(wav_path)
            return Path(ogg_path)
        except Exception as e:
            logger.warning(f"CosyVoice 失败，降级到 Piper: {e}")

        # 降级到 Piper
        try:
            if self.piper is None:
                self.piper = self._load_piper()
            wav_path = f"/tmp/tts_{hash(text)}.wav"
            self.piper.synthesize(text, wav_path)
            ogg_path = await self._convert_to_ogg(wav_path)
            return Path(ogg_path)
        except Exception as e:
            logger.error(f"Piper 也失败了: {e}")
            return None

    async def _convert_to_ogg(self, wav_path: str) -> str:
        """转换为 Telegram 要求的 OGG/Opus 格式"""
        ogg_path = wav_path.replace(".wav", ".ogg")
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-i", wav_path,
            "-c:a", "libopus", "-b:a", "32k", "-ac", "1", "-ar", "48000",
            "-y", ogg_path,
        )
        await proc.wait()
        return ogg_path
```

### 4.4 声音克隆（给"陈暖树"独特声音）

**流程：**
1. 收集"陈暖树"参考音频（10秒清晰语音）
2. 准备参考文本（对应音频的文字内容）
3. 用 CosyVoice 2 的零样本克隆功能
4. 保存到角色卡配置

```python
# 声音克隆配置
{
    "extensions": {
        "voice": {
            "engine": "cosyvoice2",
            "clone_enabled": true,
            "prompt_audio": "data/voices/chennuanshu_prompt.wav",
            "prompt_text": "你好呀，我是陈暖树，很高兴认识你。",
            "speaker": "中文女"  # 克隆失败时的降级音色
        }
    }
}
```

---

## 五、表情包系统

### 5.1 设计方案：文件夹 + 元数据

采用**文件夹结构 + metadata.yaml 配置**的组合方案：
- 文件夹管理图片（简单直观，加图就是加文件）
- metadata 管理映射关系（灵活，支持权重、标签、动画）
- 跨平台共用（Telegram/QQ/微信都用同一套资源）

### 5.2 文件夹结构

```
data/characters/陈暖树/expressions/
├── metadata.yaml          # 配置文件
├── neutral/
│   ├── 01.png
│   └── 02.png
├── joy/
│   ├── 01.png
│   ├── 02.png
│   └── 03.gif            # 支持动画
├── anger/
│   ├── 01.png
│   └── 02.png
├── sadness/
│   ├── 01.png
│   └── 02.png
├── surprise/
│   ├── 01.png
│   └── 02.png
├── fear/
│   └── 01.png
├── disgust/
│   └── 01.png
├── embarrassment/
│   ├── 01.png
│   ├── 02.png
│   └── 03.png
├── smirk/
│   ├── 01.png
│   └── 02.png
├── blush/
│   ├── 01.png
│   ├── 02.png
│   └── 03.png
├── thinking/
│   └── 01.png
└── wink/
    ├── 01.png
    └── 02.png
```

### 5.3 metadata.yaml 配置

```yaml
# 角色表情配置
expressions:
  neutral:
    tags: ["嗯", "好吧", "知道了"]
    weight: 1
  joy:
    tags: ["哈哈", "开心", "高兴", "嘻嘻", "笑", "太好了"]
    weight: 1
  anger:
    tags: ["生气", "讨厌", "哼", "烦", "气死了"]
    weight: 1
  sadness:
    tags: ["难过", "伤心", "呜呜", "哭", "好难过"]
    weight: 1
  surprise:
    tags: ["啊", "诶", "真的吗", "不会吧", "天哪"]
    weight: 1
  fear:
    tags: ["害怕", "好可怕", "吓死了"]
    weight: 0.5
  disgust:
    tags: ["恶心", "讨厌死了", "呕"]
    weight: 0.3
  embarrassment:
    tags: ["害羞", "才没有", "不要说", "讨厌啦"]
    weight: 0.8
  smirk:
    tags: ["哼哼", "嘿嘿", "是吗"]
    weight: 0.6
  blush:
    tags: ["脸红", "心跳", "好害羞"]
    weight: 0.5
  thinking:
    tags: ["嗯...", "让我想想", "这个嘛"]
    weight: 0.4
  wink:
    tags: [" wink", "😉"]
    weight: 0.3
```

**配置说明：**
- `tags`：触发该表情的关键词列表
- `weight`：出现权重（1=正常，0.5=较少出现，0.3=很少出现）

### 5.4 ExpressionManager 实现

```python
import random
from pathlib import Path

class ExpressionManager:
    def __init__(self, character_dir: str):
        self.base_path = Path(character_dir) / "expressions"
        self.metadata = {}
        self.emotions = {}
        self._load()

    def _load(self):
        """加载 metadata 和表情图片"""
        import yaml
        meta_path = self.base_path / "metadata.yaml"
        if meta_path.exists():
            with open(meta_path, encoding="utf-8") as f:
                self.metadata = yaml.safe_load(f).get("expressions", {})

        # 扫描文件夹
        for emotion_dir in self.base_path.iterdir():
            if emotion_dir.is_dir():
                images = list(emotion_dir.glob("*.*"))
                images = [f for f in images if f.suffix.lower() in (".png", ".jpg", ".gif", ".webp")]
                if images:
                    self.emotions[emotion_dir.name] = images

    def detect_emotion(self, text: str) -> str | None:
        """从文本中检测情绪（基于 metadata 中的 tags）"""
        for emotion, config in self.metadata.items():
            tags = config.get("tags", [])
            if any(tag in text for tag in tags):
                return emotion
        return None

    def get_expression(self, emotion: str = None, text: str = None) -> Path | None:
        """获取表情图片（随机选择）"""
        if emotion is None and text:
            emotion = self.detect_emotion(text)
        if emotion is None:
            emotion = "neutral"

        images = self.emotions.get(emotion)
        if not images:
            images = self.emotions.get("neutral", [])
        if not images:
            return None

        # 按权重决定是否返回（weight < 1 时有概率返回 neutral）
        weight = self.metadata.get(emotion, {}).get("weight", 1)
        if weight < 1 and random.random() > weight:
            images = self.emotions.get("neutral", images)

        return random.choice(images)
```

### 5.5 跨平台适配

表情资源只维护一份，每个平台适配器自己处理格式：

```python
# Telegram 适配器
async def send_expression(self, image_path: Path):
    await self.bot.send_photo(chat_id, photo=open(image_path, "rb"))

# QQ 适配器
async def send_expression(self, image_path: Path):
    await self.bot.send_image(group_id, image=open(image_path, "rb"))

# 微信适配器
async def send_expression(self, image_path: Path):
    await self.bot.send_image(user_id, image=open(image_path, "rb"))
```

---

## 六、回复路由策略

| 模式 | 行为 | 触发方式 |
|------|------|---------|
| `text` | 只发文字 | 默认 |
| `voice` | 语音回复 | `/voice` 或 "说给我听" |
| `sticker` | 文字 + 表情 | `/sticker` |
| `mixed` | 文字 + 表情 + 偶尔语音 | `/mixed` |

### 回复路由实现

```python
class ResponseRouter:
    def __init__(self, tts: VoiceSynthesizer, expressions: ExpressionManager):
        self.tts = tts
        self.expressions = expressions
        self.mode = "text"  # 用户可切换

    async def route(self, text: str, msg: PlatformMessage,
                    send_callback) -> None:
        """根据模式路由回复"""
        if self.mode == "text":
            await send_callback(PlatformResponse(
                msg_id=msg.msg_id, content=text, reply=True
            ))

        elif self.mode == "voice":
            audio_path = await self.tts.synthesize(text)
            if audio_path:
                await send_callback(PlatformResponse(
                    msg_id=msg.msg_id, content="", reply=True,
                    metadata={"voice": str(audio_path)}
                ))
            else:
                await send_callback(PlatformResponse(
                    msg_id=msg.msg_id, content=text, reply=True
                ))

        elif self.mode == "sticker":
            await send_callback(PlatformResponse(
                msg_id=msg.msg_id, content=text, reply=True
            ))
            # 发送表情
            expr_path = self.expressions.get_expression(text=text)
            if expr_path:
                await send_callback(PlatformResponse(
                    msg_id=msg.msg_id, content="", reply=True,
                    metadata={"expression": str(expr_path)}
                ))

        elif self.mode == "mixed":
            await send_callback(PlatformResponse(
                msg_id=msg.msg_id, content=text, reply=True
            ))
            # 随机决定是否发语音（30%概率）
            if random.random() < 0.3:
                audio_path = await self.tts.synthesize(text)
                if audio_path:
                    await send_callback(PlatformResponse(
                        msg_id=msg.msg_id, content="", reply=True,
                        metadata={"voice": str(audio_path)}
                    ))
            # 发送表情
            expr_path = self.expressions.get_expression(text=text)
            if expr_path:
                await send_callback(PlatformResponse(
                    msg_id=msg.msg_id, content="", reply=True,
                    metadata={"expression": str(expr_path)}
                ))
```

---

## 七、可靠性设计

### 7.1 自动降级链

```
STT: SenseVoice → 失败 → Vosk → 失败 → 返回空文字
TTS: CosyVoice 2 → 失败 → Piper → 失败 → 降级到纯文字
全部失败 → 纯文字回复（不中断服务）
```

### 7.2 健康检查

```python
class HealthChecker:
    def __init__(self, stt: SpeechRecognizer, tts: VoiceSynthesizer):
        self.stt = stt
        self.tts = tts

    async def check(self) -> dict:
        return {
            "stt_sensevoice": await self._check_sensevoice(),
            "stt_vosk": self._check_vosk(),
            "tts_cosyvoice": await self._check_cosyvoice(),
            "tts_piper": self._check_piper(),
        }

    async def _check_sensevoice(self) -> bool:
        try:
            result = await self.stt.transcribe("test.wav")
            return len(result) > 0
        except:
            return False

    def _check_vosk(self) -> bool:
        try:
            result = self.stt._vosk_transcribe("test.wav")
            return True
        except:
            return False

    async def _check_cosyvoice(self) -> bool:
        try:
            await self.tts.cosyvoice.synthesize("测试", "/tmp/test.wav")
            return True
        except:
            return False

    def _check_piper(self) -> bool:
        try:
            self.tts.piper.synthesize("测试", "/tmp/test.wav")
            return True
        except:
            return False
```

### 7.3 资源限制

| 限制项 | 阈值 | 处理 |
|--------|------|------|
| 内存占用 | >80% | 切换到轻量模型 (Vosk + Piper) |
| CPU 占用 | >90% | 降低并发，优先文字回复 |
| 磁盘空间 | <1GB | 清理临时音频文件 |
| 语音时长 | >60秒 | 拒绝或拆分 |

### 7.4 临时文件清理

```python
async def cleanup_temp_files():
    """每小时清理超过 1 小时的临时音频文件"""
    temp_dir = Path("/tmp/vir_bot_audio")
    for f in temp_dir.glob("*"):
        if f.stat().st_mtime < time.time() - 3600:
            f.unlink()
```

---

## 八、配置文件设计

```yaml
voice:
  # STT 语音识别
  stt:
    enabled: true
    primary: "sensevoice"
    fallback: "vosk"
    sensevoice:
      model: "iic/SenseVoiceSmall"
      vad_model: "fsmn-vad"
      language: "auto"
    vosk:
      model_path: "models/vosk-model-cn-0.22"

  # TTS 语音合成
  tts:
    enabled: true
    primary: "cosyvoice"
    fallback: "piper"
    cosyvoice:
      model_path: "pretrained_models/CosyVoice2-0.5B"
      speaker: "中文女"
      clone:
        enabled: true
        prompt_audio: "data/voices/chennuanshu_prompt.wav"
        prompt_text: "你好呀，我是陈暖树，很高兴认识你。"
    piper:
      model_path: "models/zh_CN-huayan-medium.onnx"

  # 表情包
  sticker:
    enabled: true
    map_file: "data/stickers/chennuanshu.json"

  # 回复模式
  default_mode: "text"

  # 资源限制
  max_audio_duration: 60
  temp_dir: "/tmp/vir_bot_audio"
  cleanup_interval: 3600
```

---

## 九、依赖清单

### Python 包

| 依赖 | 用途 | 安装 |
|------|------|------|
| `funasr` | SenseVoice STT | `pip install funasr` |
| `cosyvoice` | CosyVoice 2 TTS | 从 GitHub 安装 |
| `vosk` | STT 降级引擎 | `pip install vosk` |
| `piper-tts` | TTS 降级引擎 | `pip install piper-tts` |
| `torch` | 深度学习框架 | `pip install torch` |
| `torchaudio` | 音频处理 | `pip install torchaudio` |
| `ffmpeg` | 音频转码 | 系统安装 |

### 模型文件下载

```bash
# SenseVoice 模型（首次运行自动下载，或手动）
# ~450MB，从 ModelScope 或 HuggingFace 下载

# CosyVoice 2 模型
# ~1GB，从 GitHub 下载
git clone https://github.com/FunAudioLLM/CosyVoice.git
cd CosyVoice
# 按照 README 下载预训练模型

# Vosk 中文模型（降级用）
wget https://alphacephei.com/vosk/models/vosk-model-cn-0.22.zip
unzip vosk-model-cn-0.22.zip -d models/

# Piper 中文语音模型（降级用）
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/zh_CN/zh_CN-huayan-medium.onnx
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/zh_CN/zh_CN-huayan-medium.onnx.json
```

### 系统依赖

```bash
# Ubuntu/Debian
sudo apt install ffmpeg

# Windows
# 下载 ffmpeg 并添加到 PATH
```

---

## 十、硬件部署方案

### 方案 A：入门级 (Raspberry Pi 5)

| 组件 | 选型 | 资源 |
|------|------|------|
| STT | Vosk (降级) | 50MB 模型 |
| TTS | Piper (降级) | 60MB 模型 |
| 内存 | ~300MB | Pi 5 4GB 足够 |
| 备注 | SenseVoice/CosyVoice 需要 GPU，Pi 上用降级方案 |

### 方案 B：推荐级 (x86 迷你主机 + GPU)

| 组件 | 选型 | 资源 |
|------|------|------|
| STT | SenseVoice | 450MB 模型 |
| TTS | CosyVoice 2 | 1GB 模型 |
| GPU | NVIDIA T4 / RTX 3060 | 4GB+ 显存 |
| 内存 | ~4GB | 推荐 8GB |
| 备注 | 最佳体验，全功能可用 |

### 方案 C：生产级 (Jetson Nano / 迷你 PC)

| 组件 | 选型 | 资源 |
|------|------|------|
| STT | SenseVoice (small) | 450MB |
| TTS | CosyVoice 2 (0.5B) | 1GB |
| GPU | Jetson Nano 4GB | 4GB 显存 |
| 内存 | ~4GB | 推荐 8GB |
| 备注 | 适合嵌入式部署 |

---

## 十一、实施计划

| 阶段 | 功能 | 工作量 | 优先级 |
|------|------|--------|--------|
| P0 | STT 模块 (SenseVoice + Vosk 降级) | 2 天 | ★★★★★ |
| P1 | TTS 模块 (CosyVoice 2 + Piper 降级) | 2 天 | ★★★★★ |
| P2 | 表情包系统 | 1 天 | ★★★★ |
| P3 | 声音克隆（陈暖树专属声音） | 1 天 | ★★★★ |
| P4 | 回复路由 + 模式切换 | 1 天 | ★★★ |
| P5 | 健康检查 + 资源管理 | 1 天 | ★★★ |

**总工期：约 8 天**

---

## 十二、与现有代码集成

| 模块 | 改动 |
|------|------|
| `telegram_adapter.py` | 接收语音消息、发送语音/贴纸 |
| `base_adapter.py` | 回复路由逻辑 |
| `pipeline/__init__.py` | 语音输入支持、情绪传递 |
| `character/__init__.py` | 扩展 voice、stickers 字段 |
| `config.py` | 新增 VoiceConfig |
| 新增 `voice/stt.py` | STT 引擎封装 (SenseVoice + Vosk) |
| 新增 `voice/tts.py` | TTS 引擎封装 (CosyVoice + Piper) |
| 新增 `voice/audio_utils.py` | ffmpeg 转码 |
| 新增 `sticker/router.py` | 表情包路由 |

---

## 十三、关键优势总结

1. **全免费** — 无任何 API 费用，所有模型开源
2. **中文最优** — SenseVoice + CosyVoice 2 是目前中文效果最好的方案
3. **同一团队** — 都是阿里巴巴 FunAudioLLM 出品，兼容性最好
4. **情绪检测** — SenseVoice 内置情绪识别，表情包更智能
5. **声音克隆** — CosyVoice 2 支持 10 秒音频克隆，角色声音独特
6. **自动降级** — 网络异常自动切换本地轻量方案，不中断服务
7. **硬件友好** — 支持从 Pi 5 到 GPU 设备的多种部署方案

---

## 参考资源

- SenseVoice GitHub: https://github.com/FunAudioLLM/SenseVoice
- CosyVoice GitHub: https://github.com/FunAudioLLM/CosyVoice
- FunASR GitHub: https://github.com/modelscope/FunASR
- Vosk 官网: https://alphacephei.com/vosk/
- Piper TTS: https://github.com/rhasspy/piper
