---
comet_change: chat-web-ui
role: technical-design
canonical_spec: openspec
archived-with: 2026-06-04-chat-web-ui
status: final
---

# Chat Web UI — 技术设计文档

## 概述

为 vir-bot 新增 Web 聊天界面，支持流式文字对话和实时语音对话。单文件 Vue 3 应用，挂载到 `/chat/` 路径。

## 架构

```
Browser (Vue 3 CDN)                    FastAPI Backend
┌─────────────────────┐               ┌─────────────────────┐
│  Chat UI            │  WebSocket    │  /api/chat/ws       │
│  ├── MessageList    │◀─────────────▶│  ├── text handler   │
│  ├── ChatInput      │               │  ├── voice handler  │
│  ├── AudioPlayer    │               │  └── interrupt      │
│  └── CharacterPanel │               │                     │
│                     │               │  MessagePipeline    │
│  Web Speech API     │               │  ├── chat_stream()  │
│  (ASR, Chrome)      │               │  ├── ASR            │
│                     │               │  └── TTS            │
│  MediaRecorder      │               │                     │
│  (audio capture)    │               │  /api/chat/voice/*  │
│                     │               │  (audio file serve) │
└─────────────────────┘               └─────────────────────┘
```

## WebSocket 消息协议

### 客户端 → 服务端

```json
{"type": "text", "content": "你好"}
{"type": "voice", "audio": "<base64>", "format": "webm"}
{"type": "interrupt"}
```

### 服务端 → 客户端

```json
{"type": "text_delta", "content": "你"}         // 流式文字 chunk
{"type": "text_done", "content": "完整回复"}     // 文字完成
{"type": "voice_url", "url": "/api/chat/voice/xxx.wav"}  // 语音文件
{"type": "voice_done"}                          // 语音播放完毕
{"type": "error", "message": "错误信息"}
{"type": "status", "state": "thinking|speaking|listening|idle"}
```

## 语音对话 — 流式并行 pipeline

### 优化策略

串行流程延迟过高（5-16s），采用流式并行优化：

1. **ASR**: Web Speech API（Chrome），实时识别，零延迟
2. **AI 生成**: 流式输出，按句分段
3. **TTS**: 每句完成立即触发合成，不等全文
4. **播放**: 音频队列，合成一段播一段，无缝拼接

### 数据流

```
用户说话 → Web Speech API（实时 ASR）
         → WebSocket 发送文字
         → AI 流式生成（逐句）
         → 每句完成 → TTS 合成 → 音频 URL → 前端播放队列
```

### 延迟目标

| 阶段 | 延迟 |
|------|------|
| ASR | 0s（Web Speech API 实时） |
| 首句 AI + TTS | ~2-3s |
| 后续 | 边生成边播放，用户感知无等待 |

### ASR 降级策略

| 场景 | ASR 方案 |
|------|---------|
| Chrome 浏览器 | Web Speech API（前端实时识别） |
| 非 Chrome 浏览器 | 后端 ASR（pipeline 已有 SenseVoice/Whisper） |
| 检测方式 | `window.SpeechRecognition` 存在性检查 |

## 打断机制

```
用户开口说话
  → SpeechRecognition.onstart 触发
  → 前端发送 {"type":"interrupt"}
  → 前端暂停 <audio> 播放，清空音频队列
  → 后端收到 interrupt
  → asyncio.Task.cancel() 取消当前 AI 生成
  → 取消待合成的 TTS 任务
  → 发送 {"type":"status","state":"listening"}
```

防误触：前端加 200ms 延迟确认，短噪音不触发打断。

## TTS Provider

支持可切换：
- `mimo-v2.5-tts` — mimo TTS 系列（含 voiceclone、voicedesign）
- `edge-tts` — Microsoft Edge TTS（免费兜底）

前端提供切换 UI，通过 WebSocket 消息或 API 参数指定。

## 前端 UI 设计

### 设计风格

暗色科技感，与 vir-bot 配置页统一：
- 主色: `#6366f1` (indigo)
- 背景: `#0f1117`
- 表面: `#1a1d27`
- 边框: `#2d3140`
- 文字: `#e4e4e7` (主) / `#a1a1aa` (次) / `#71717a` (弱)

### 组件结构

- `ChatHeader` — 顶栏（标题 + 角色卡按钮 + 设置按钮）
- `MessageList` — 消息列表（自动滚动 + 流式渲染）
- `MessageBubble` — 单条消息气泡（区分 user/assistant）
- `ChatInput` — 输入区（文字输入 + 录音按钮 + 发送按钮）
- `CharacterPanel` — 角色卡侧边栏（可展开/收起）
- `AudioPlayer` — 内嵌音频播放器

### 交互状态

| 状态 | 输入区 | 录音按钮 | 发送按钮 |
|------|--------|---------|---------|
| 空闲 | 可输入 | 可点击 | 灰色 |
| 有文字 | 可输入 | 可点击 | 高亮可点 |
| 录音中 | 禁用 | 红色脉冲 | 禁用 |
| AI 回复中 | 可输入 | 可点击 | 灰色 |
| 播放语音 | 可输入 | 可点击 | 灰色 |

### 动画

- 消息出现: fadeIn + slideUp (0.3s ease-out)
- 录音按钮: 红色呼吸灯脉冲 (1.5s infinite)
- 打字指示器: 三点弹跳动画
- 语音播放: 声波动画 (equalizer bars)
- 侧边栏: slideInRight (0.2s)

### 响应式

- ≥768px: 居中卡片式布局，max-width 800px
- <768px: 全屏布局，底部固定输入区

### 语音模式 UI

- 录音按钮居中放大 (64px)
- 按住时显示声波纹动画
- 松开后显示 "识别中..." → "AI 思考中..." → 播放回复
- 底部显示识别到的文字（实时）

## 边界条件

| 场景 | 处理 |
|------|------|
| 空消息 | 前端拦截，不允许发送 |
| 超长消息 | 后端截断到 max_content_length |
| 网络断开 | 前端显示重连提示，自动重连 |
| AI 响应超时 | 后端返回错误消息 |
| TTS 合成失败 | 降级为纯文字回复 |
| Web Speech API 不可用 | 提示切换 Chrome |
| 麦克风权限拒绝 | 提示用户授权 |
| 多标签页 | 每个标签独立 WebSocket 连接 |

## 浏览器兼容性

| 浏览器 | 文字聊天 | 语音输入 | 语音回复 |
|--------|---------|---------|---------|
| Chrome 90+ | ✅ | ✅ Web Speech API | ✅ |
| Firefox | ✅ | ⚠️ 后端 ASR | ✅ |
| Safari | ✅ | ⚠️ 后端 ASR | ✅ |
| 移动端 Chrome | ✅ | ✅ (需 HTTPS) | ✅ |

## 文件结构

### 新增文件

- `vir_bot/api/routers/chat_ws.py` — WebSocket 端点
- `vir_bot/api/static/chat/index.html` — 聊天 UI 单文件

### 修改文件

- `vir_bot/main.py` — 注册路由 + 挂载静态文件
- `vir_bot/core/pipeline/__init__.py` — 暴露流式接口

### 后端 API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/chat/ws` | WebSocket | 聊天双向通信 |
| `/api/chat/voice/{filename}` | GET | 音频文件服务 |
| `/api/chat/` | POST | 保留，同步文字聊天 |

### 前端 CDN 依赖

- Vue 3: `https://unpkg.com/vue@3/dist/vue.global.prod.js`
- marked.js: `https://cdn.jsdelivr.net/npm/marked/marked.min.js`
- highlight.js: `https://cdn.jsdelivr.net/gh/highlightjs/cdn-release/build/highlight.min.js`
