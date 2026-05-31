# TTS 质量改进 — 任务清单

## Phase 1: MiMo TTS Provider 实现（最高优先级）

- [x] 1.1 实现 `MiMoTTSProvider` 类（调用 MiMo-V2.5-TTS API，OpenAI 兼容格式）
- [x] 1.2 在 `config.py` 中新增 MiMo TTS 配置字段（mimo_voice、mimo_style、mimo_model）
- [x] 1.3 更新 `create_tts()` 工厂函数，支持 `provider: "mimo"`
- [x] 1.4 实现 MiMo 风格控制（从角色 personality 自动推断 + 手动配置）
- [x] 1.5 编写 MiMo TTS Provider 单元测试

## Phase 2: 音频格式转换

- [x] 2.1 实现 ffmpeg 音频格式转换工具函数（WAV → OGG/Opus）
- [x] 2.2 在 MiMoTTSProvider 输出后集成格式转换
- [x] 2.3 修复 Edge-TTS 输出格式转换
- [x] 2.4 添加 ffmpeg 不可用时的优雅降级

## Phase 3: AI 语音决策 + 双发模式

- [x] 3.1 在 `VoiceConfig` 中新增 `voice_mode` 和 `voice_decision` 配置字段
- [x] 3.2 实现 `_parse_voice_decision()` 解析 [VOICE] 标记
- [x] 3.3 在 system prompt 中注入语音决策指令
- [x] 3.4 修改 `telegram_adapter.py` 支持双发模式（both/replace/voice_only）
- [x] 3.5 修改 `base_adapter.py` 适配 voice_mode
- [x] 3.6 更新 config.yaml 默认值

## Phase 4: Fallback 策略

- [x] 4.1 更新 fallback 链：MiMo → Edge-TTS → None
- [x] 4.2 实现 MiMo API 错误自动 fallback 到 Edge-TTS
- [x] 4.3 标记 CosyVoice2TTSProvider 为 deprecated

## Phase 5: 主动消息 TTS

- [x] 5.1 在 ProactiveService 中注入 TTS provider
- [x] 5.2 实现主动消息的语音合成逻辑
- [x] 5.3 确保主动消息遵循 voice_mode 配置

## Phase 6: 配置与清理

- [x] 6.1 更新 config.yaml 启用语音系统，切换到 mimo provider
- [x] 6.2 清理 CosyVoice2 相关死代码（sys.path 拼接等）
- [x] 6.3 更新 config_router.py 的音色列表（MiMo 音色替换 Edge-TTS 音色）
- [x] 6.4 更新 docs/voice_sticker_plan.md 反映新架构

## Phase 7: 测试与验证

- [x] 7.1 端到端测试：Telegram 发送语音消息
- [x] 7.2 测试 fallback 机制（MiMo 失败 → Edge-TTS）
- [x] 7.3 测试双发模式（文字+语音）
- [x] 7.4 测试风格控制（从 personality 推断）
