# TTS 质量全面改进

## 问题背景

当前 vir-bot 的 TTS（文字转语音）系统存在严重质量问题：

1. **CosyVoice2 音质差** — 0.5B 模型生成的语音听起来像噪音，不像人声，用户体验极差
2. **推理速度慢** — 本地模型加载慢、合成慢，首字延迟高
3. **音频格式错配** — CosyVoice2 输出 WAV，pipeline 保存为 `.mp3`（实际仍是 WAV），Telegram 最佳格式为 OGG/Opus，ffmpeg 转换未实现
4. **Telegram 发语音时文字被吞** — `telegram_adapter.py` 收到 voice_file 后直接 return，用户只收到语音、看不到文字
5. **Instruct2 模式依赖 edge-tts** — 本地模型的参考音频通过 edge-tts 在线生成，"本地"名不副实
6. **CosyVoice2 的 sys.path 拼接脆弱** — 运行时动态拼接 `third_party/CosyVoice/` 路径
7. **主动消息不走 TTS** — `proactive_service.py` 直接发文字

## 目标

- **替换 TTS 引擎**：用 MiMo-V2.5-TTS API 替换 CosyVoice2 本地模型，彻底解决音质和速度问题
- 实现 WAV → OGG/Opus 音频格式转换（通过 ffmpeg）
- 实现文字+语音双发模式
- 支持 MiMo TTS 的精细风格控制（情绪、方言、角色扮演）
- 保留 Edge-TTS 作为免费 fallback
- 支持主动消息的 TTS 合成
- 保持向后兼容

## 方案选型：MiMo-V2.5-TTS API

### 为什么选 MiMo TTS

| 对比项 | CosyVoice2（当前） | MiMo-V2.5-TTS（新方案） |
|--------|-------------------|------------------------|
| 音质 | 差（噪音） | 优（专业级） |
| 速度 | 慢（本地加载+推理） | 快（云端 API） |
| GPU 依赖 | 需要 | 不需要 |
| 模型大小 | ~2GB | 0（云端） |
| 风格控制 | 仅 instruct_text | 自然语言 + 音频标签 + 导演模式 |
| 声音克隆 | 基础 zero-shot | 专业级 voiceclone |
| 中文音色 | 1 个（自动生成） | 4 个精品（冰糖/茉莉/苏打/白桦） |
| API Key | 不需要 | 已有（同一 Key） |

### MiMo TTS 核心特性

- **API 端点**：`https://api.xiaomimimo.com/v1/chat/completions`（OpenAI 兼容格式）
- **3 个模型**：`mimo-v2.5-tts`（预置音色）、`mimo-v2.5-tts-voicedesign`（文字设计音色）、`mimo-v2.5-tts-voiceclone`（声音克隆）
- **输出格式**：WAV / PCM16，24kHz 采样率
- **风格控制**：支持情绪（温柔/悲伤/愤怒）、方言（东北话/四川话/粤语）、角色扮演、唱歌
- **用户已有 API Key**，零额外成本

## 范围

### 包含
- 实现 MiMoTTSProvider（调用 MiMo-V2.5-TTS API）
- 音频格式转换（WAV → OGG/Opus via ffmpeg）
- Telegram 文字+语音双发逻辑
- MiMo TTS 风格控制集成（从角色 personality 自动推断风格）
- 保留 Edge-TTS 作为 fallback
- 主动消息 TTS 集成
- 清理 CosyVoice2 相关死代码
- 相关测试用例

### 不包含
- CosyVoice2 修复（直接替换，不再维护）
- Piper TTS 实现（MiMo API + Edge-TTS 双层已足够）
- 语音识别（ASR）改进
- 唤醒词功能改进
- 前端语音控制 UI

## 非目标
- 支持所有平台的语音发送（先聚焦 Telegram，其他平台后续迭代）
- 完全离线 TTS（MiMo API 需要网络，Edge-TTS 作为轻量 fallback）
