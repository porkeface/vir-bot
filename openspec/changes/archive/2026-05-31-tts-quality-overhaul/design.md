# TTS 质量改进 — 高层设计

## 架构决策

### 1. TTS Provider 替换：CosyVoice2 → MiMo-V2.5-TTS API

**决策**：用 MiMo-V2.5-TTS API 完全替换 CosyVoice2 本地模型。

**方案**：
- 新增 `MiMoTTSProvider` 类，调用 `https://api.xiaomimimo.com/v1/chat/completions`
- 使用 OpenAI 兼容格式，`audio` 参数指定格式和音色
- 复用现有 `config.voice.tts` 配置，新增 `mimo_voice` 和 `mimo_style` 字段
- 保留 `CosyVoice2TTSProvider` 代码但默认不启用，标记为 deprecated

**API 调用流程**：
```
Pipeline._synthesize_tts()
  → MiMoTTSProvider.synthesize(text, output_path)
    → POST /v1/chat/completions
      model: "mimo-v2.5-tts"
      messages: [
        {role: "user", content: style_instruction},      # 风格控制
        {role: "assistant", content: text}                # 合成文本
      ]
      audio: {format: "wav", voice: "冰糖"}
    → base64 decode → WAV file
    → ffmpeg convert → OGG/Opus file
```

### 2. 音频格式转换层

**决策**：在 TTS Provider 输出后统一进行格式转换。

**方案**：
- MiMo TTS 输出 WAV（24kHz）→ ffmpeg 转换为 OGG/Opus
- Edge-TTS 输出 MP3 → ffmpeg 转换为 OGG/Opus
- 转换在 `voice/utils.py` 中实现为独立工具函数
- ffmpeg 不可用时回退到原始格式，日志警告
- Telegram adapter 优先使用 OGG，不支持时回退

### 3. AI 语音决策机制

**决策**：LLM 通过 `[VOICE]` 标记自主决定何时用语音回复。

**方案**：
- 在 system prompt 注入指令，让 LLM 在适合语音的回复末尾加 `[VOICE]`
- Pipeline 解析标记：`use_voice = "[VOICE]" in content`
- 清理标记后发送文字，同时生成语音
- 配置 `voice_decision: "ai"` | `"always"` | `"never"`

**适合语音的场景**：情感表达、问候、关心、闲聊（< 200 字）
**适合文字的场景**：代码、列表、长文、技术说明

### 4. 文字+语音双发模式

**决策**：引入 `voice_mode` 配置项，配合 AI 决策。

**方案**：
- `voice_mode: "replace"` — 语音替换文字（向后兼容）
- `voice_mode: "both"` — 先发文字，再发语音（AI 决策时推荐）
- `voice_mode: "voice_only"` — 只发语音
- Telegram 实现：`both` 模式先 `send_message()` 再 `send_voice()`

### 4. MiMo TTS 风格控制集成

**决策**：从角色 personality 自动推断 TTS 风格指令。

**方案**：
- 新增 `voice.tts.mimo_style` 配置项，可手动指定风格
- 若未指定，从角色的 `personality` 字段自动提取风格关键词
- 风格指令放在 `role: user` 的 message 中（MiMo API 规范）
- 支持标签控制：在文本前加 `(温柔)` 等标签

### 5. Fallback 策略

**决策**：MiMo API 为主，Edge-TTS 为辅。

**方案**：
- 优先级：MiMo TTS → Edge-TTS → None
- MiMo API 调用失败（网络错误、超时、配额耗尽）→ 自动 fallback 到 Edge-TTS
- 移除 CosyVoice2 和 Piper 的 fallback 链（简化维护）
- fallback 事件记录日志，便于监控

### 6. 主动消息 TTS 集成

**决策**：在 `ProactiveService` 中复用 Pipeline 的 TTS 能力。

**方案**：
- `ProactiveService` 持有 TTS provider 引用
- 发送主动消息时，如果 `voice_response` 开启，先合成语音再发送
- 复用 pipeline 的 `_synthesize_tts()` 逻辑

## 配置变更

```yaml
voice:
  enabled: true                   # 开启语音系统
  voice_response: true            # 开启语音回复
  voice_mode: "replace"           # replace | both | voice_only
  voice_decision: "ai"            # always | ai | never
  tts:
    provider: "mimo"              # mimo | edge（cosyvoice2 已废弃）
    mimo_voice: "冰糖"            # MiMo 音色：冰糖/茉莉/苏打/白桦
    mimo_style: ""                # 风格指令（空=从 personality 推断）
    mimo_model: "mimo-v2.5-tts"   # mimo-v2.5-tts | voicedesign | voiceclone
    ffmpeg_path: "ffmpeg"         # ffmpeg 路径
    output_format: "ogg"          # 输出格式：ogg | wav
    speed: 1.0
```

## 文件变更预估

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `vir_bot/modules/voice/__init__.py` | 重构 | 新增 MiMoTTSProvider、格式转换工具、清理 CosyVoice2 |
| `vir_bot/core/pipeline/__init__.py` | 修改 | 格式转换调用、voice_mode 逻辑 |
| `vir_bot/platforms/telegram_adapter.py` | 修改 | 双发模式实现 |
| `vir_bot/platforms/base_adapter.py` | 修改 | voice_mode 抽象 |
| `vir_bot/config.py` | 修改 | 新增配置字段（mimo_voice、mimo_style、voice_mode） |
| `vir_bot/core/proactive/proactive_service.py` | 修改 | TTS 集成 |
| `tests/test_tts.py` | 新增 | MiMo TTS Provider 测试 |
| `config.yaml` | 修改 | 启用语音、切换到 mimo provider |
