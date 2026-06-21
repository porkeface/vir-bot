---
archived-with: 2026-06-04-chat-web-ui
status: final
---
# Chat Web UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 vir-bot 新增 Web 聊天界面，支持流式文字对话和实时语音对话。

**Architecture:** WebSocket 双向通信 + Vue 3 CDN 单文件。后端新增 `/api/chat/ws` 端点，调用 pipeline 的流式接口。前端使用 Web Speech API 做 ASR，后端 TTS 合成语音。

**Tech Stack:** FastAPI WebSocket, Vue 3 CDN, marked.js, highlight.js, Web Speech API, MediaRecorder API

**Design Doc:** `docs/superpowers/specs/2026-06-03-chat-web-ui-design.md`

**Base Ref:** 5297d70c9d52cffad5951409c50b6433df0d8083

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `vir_bot/api/routers/chat_ws.py` | Create | WebSocket 端点，消息协议解析，流式文字/语音处理 |
| `vir_bot/api/static/chat/index.html` | Create | 聊天 UI 单文件（Vue 3 + CSS + JS） |
| `vir_bot/main.py` | Modify | 注册 chat_ws 路由 + 挂载 /chat/ 静态文件 |
| `tests/unit/test_chat_ws.py` | Create | WebSocket 端点单元测试 |

---

### Task 1: WebSocket 端点 — 基础连接 + 文字消息

**Files:**
- Create: `vir_bot/api/routers/chat_ws.py`
- Create: `tests/unit/test_chat_ws.py`

- [ ] **Step 1: 编写 WebSocket 连接测试**

```python
# tests/unit/test_chat_ws.py
"""WebSocket 聊天端点测试"""
from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from vir_bot.api.routers.chat_ws import ChatMessage, parse_message


def test_parse_text_message():
    """解析文字消息"""
    raw = json.dumps({"type": "text", "content": "你好"})
    msg = parse_message(raw)
    assert msg.type == "text"
    assert msg.content == "你好"


def test_parse_interrupt_message():
    """解析打断消息"""
    raw = json.dumps({"type": "interrupt"})
    msg = parse_message(raw)
    assert msg.type == "interrupt"


def test_parse_invalid_json():
    """无效 JSON 返回 None"""
    msg = parse_message("not json")
    assert msg is None


def test_parse_missing_type():
    """缺少 type 字段返回 None"""
    msg = parse_message('{"content": "hello"}')
    assert msg is None
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /d/codeProject/vir-bot && PYTHONPATH=. uv run python -m pytest tests/unit/test_chat_ws.py -v
```

Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 WebSocket 端点基础框架**

```python
# vir_bot/api/routers/chat_ws.py
"""WebSocket 聊天端点"""
from __future__ import annotations

import json
import asyncio
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from vir_bot.core.pipeline import PlatformMessage, Platform, MessageType
from vir_bot.utils.logger import logger

router = APIRouter()


@dataclass
class ChatMessage:
    """解析后的 WebSocket 消息"""
    type: str
    content: str = ""
    audio: str = ""
    format: str = "webm"


def parse_message(raw: str) -> ChatMessage | None:
    """解析 JSON 消息，失败返回 None"""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    msg_type = data.get("type")
    if not msg_type:
        return None
    return ChatMessage(
        type=msg_type,
        content=data.get("content", ""),
        audio=data.get("audio", ""),
        format=data.get("format", "webm"),
    )


@router.websocket("/ws")
async def websocket_chat(ws: WebSocket):
    """WebSocket 聊天主端点"""
    await ws.accept()
    logger.info("[ChatWS] 客户端已连接")

    try:
        while True:
            raw = await ws.receive_text()
            msg = parse_message(raw)
            if msg is None:
                await ws.send_json({"type": "error", "message": "无效消息格式"})
                continue

            if msg.type == "text":
                await _handle_text(ws, msg)
            elif msg.type == "interrupt":
                await _handle_interrupt(ws)
            elif msg.type == "voice":
                await _handle_voice(ws, msg)
            else:
                await ws.send_json({"type": "error", "message": f"未知消息类型: {msg.type}"})

    except WebSocketDisconnect:
        logger.info("[ChatWS] 客户端断开连接")
    except Exception as e:
        logger.error(f"[ChatWS] 异常: {e}")
        try:
            await ws.close()
        except Exception:
            pass


async def _handle_text(ws: WebSocket, msg: ChatMessage) -> None:
    """处理文字消息 — 同步回复模式（流式在后续 task 实现）"""
    from vir_bot.main import _get_app_state

    app_state = _get_app_state()
    if app_state.pipeline is None:
        await ws.send_json({"type": "error", "message": "Pipeline 未初始化"})
        return

    platform_msg = PlatformMessage(
        platform=Platform.API,
        msg_id="ws_chat",
        user_id="web_user",
        user_name="Web用户",
        content=msg.content,
        msg_type=MessageType.TEXT,
    )

    await ws.send_json({"type": "status", "state": "thinking"})
    response = await app_state.pipeline.process(platform_msg)
    await ws.send_json({"type": "status", "state": "idle"})

    if response:
        await ws.send_json({"type": "text_done", "content": response.content})
    else:
        await ws.send_json({"type": "text_done", "content": "[无回复]"})


async def _handle_interrupt(ws: WebSocket) -> None:
    """处理打断消息"""
    logger.info("[ChatWS] 收到打断信号")
    await ws.send_json({"type": "status", "state": "idle"})


async def _handle_voice(ws: WebSocket, msg: ChatMessage) -> None:
    """处理语音消息 — 后续 task 实现"""
    await ws.send_json({"type": "error", "message": "语音功能尚未实现"})
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd /d/codeProject/vir-bot && PYTHONPATH=. uv run python -m pytest tests/unit/test_chat_ws.py -v
```

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add vir_bot/api/routers/chat_ws.py tests/unit/test_chat_ws.py
git commit -m "feat: 新增 WebSocket 聊天端点基础框架"
```

---

### Task 2: 流式文字输出

**Files:**
- Modify: `vir_bot/api/routers/chat_ws.py`

- [ ] **Step 1: 编写流式输出测试**

```python
# tests/unit/test_chat_ws.py（追加）

@pytest.mark.asyncio
async def test_handle_text_sends_status():
    """文字处理发送 status 消息"""
    from unittest.mock import AsyncMock

    ws = AsyncMock()
    ws.send_json = AsyncMock()

    msg = ChatMessage(type="text", content="你好")
    # mock pipeline
    with patch("vir_bot.api.routers.chat_ws._get_app_state") as mock_state:
        mock_state.return_value.pipeline = None
        from vir_bot.api.routers.chat_ws import _handle_text
        await _handle_text(ws, msg)

    # 应该发送 error 因为 pipeline 为 None
    ws.send_json.assert_called()
    call_args = ws.send_json.call_args[0][0]
    assert call_args["type"] == "error"
```

- [ ] **Step 2: 运行测试确认通过**

```bash
cd /d/codeProject/vir-bot && PYTHONPATH=. uv run python -m pytest tests/unit/test_chat_ws.py -v
```

- [ ] **Step 3: 实现流式文字输出**

修改 `_handle_text` 函数，调用 pipeline 的流式接口：

```python
async def _handle_text(ws: WebSocket, msg: ChatMessage) -> None:
    """处理文字消息 — 流式回复"""
    from vir_bot.main import _get_app_state

    app_state = _get_app_state()
    if app_state.pipeline is None:
        await ws.send_json({"type": "error", "message": "Pipeline 未初始化"})
        return

    platform_msg = PlatformMessage(
        platform=Platform.API,
        msg_id="ws_chat",
        user_id="web_user",
        user_name="Web用户",
        content=msg.content,
        msg_type=MessageType.TEXT,
    )

    await ws.send_json({"type": "status", "state": "thinking"})

    # 尝试流式输出
    full_content = ""
    try:
        stream = app_state.pipeline.ai.chat_stream(
            messages=[{"role": "user", "content": msg.content}],
            system=app_state.pipeline._build_system_prompt(),
        )
        async for chunk in stream:
            if chunk.finish_reason == "stop":
                break
            if chunk.delta:
                full_content += chunk.delta
                await ws.send_json({"type": "text_delta", "content": chunk.delta})
    except Exception as e:
        logger.warning(f"[ChatWS] 流式输出异常: {e}，回退到同步模式")
        response = await app_state.pipeline.process(platform_msg)
        if response:
            full_content = response.content

    await ws.send_json({"type": "status", "state": "idle"})

    if full_content:
        await ws.send_json({"type": "text_done", "content": full_content})
    else:
        await ws.send_json({"type": "text_done", "content": "[无回复]"})
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd /d/codeProject/vir-bot && PYTHONPATH=. uv run python -m pytest tests/unit/test_chat_ws.py -v
```

- [ ] **Step 5: 提交**

```bash
git add vir_bot/api/routers/chat_ws.py tests/unit/test_chat_ws.py
git commit -m "feat: WebSocket 流式文字输出"
```

---

### Task 3: 语音消息接收 + ASR 转录

**Files:**
- Modify: `vir_bot/api/routers/chat_ws.py`

- [ ] **Step 1: 实现 base64 音频解码和临时文件保存**

```python
import base64
import tempfile
from pathlib import Path


async def _handle_voice(ws: WebSocket, msg: ChatMessage) -> None:
    """处理语音消息：base64 音频 → ASR 转文字 → 流式回复"""
    from vir_bot.main import _get_app_state

    app_state = _get_app_state()
    if app_state.pipeline is None:
        await ws.send_json({"type": "error", "message": "Pipeline 未初始化"})
        return

    if not msg.audio:
        await ws.send_json({"type": "error", "message": "缺少音频数据"})
        return

    # 解码 base64 音频
    try:
        audio_bytes = base64.b64decode(msg.audio)
    except Exception as e:
        await ws.send_json({"type": "error", "message": f"音频解码失败: {e}"})
        return

    # 保存为临时文件
    suffix = f".{msg.format}" if msg.format else ".webm"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False, dir="./data/cache")
    tmp.write(audio_bytes)
    tmp.close()
    audio_path = tmp.name

    await ws.send_json({"type": "status", "state": "thinking"})

    # ASR 转文字
    transcription = ""
    if app_state.pipeline.asr:
        try:
            transcription = await app_state.pipeline.asr.recognize(audio_path)
            logger.info(f"[ChatWS] ASR 转录: {transcription[:50]}")
        except Exception as e:
            logger.error(f"[ChatWS] ASR 失败: {e}")
            await ws.send_json({"type": "error", "message": "语音识别失败"})
            Path(audio_path).unlink(missing_ok=True)
            return
    else:
        await ws.send_json({"type": "error", "message": "ASR 服务未配置"})
        Path(audio_path).unlink(missing_ok=True)
        return

    Path(audio_path).unlink(missing_ok=True)

    if not transcription or not transcription.strip():
        await ws.send_json({"type": "text_done", "content": "抱歉，没有听清你说的话。"})
        return

    # 用转录文字调用流式输出
    text_msg = ChatMessage(type="text", content=transcription.strip())
    await _handle_text(ws, text_msg)

    # TODO: TTS 合成在 Task 5 实现
```

- [ ] **Step 2: 运行现有测试确认不破坏**

```bash
cd /d/codeProject/vir-bot && PYTHONPATH=. uv run python -m pytest tests/unit/test_chat_ws.py -v
```

- [ ] **Step 3: 提交**

```bash
git add vir_bot/api/routers/chat_ws.py
git commit -m "feat: WebSocket 语音消息接收 + ASR 转录"
```

---

### Task 4: 音频文件服务端点

**Files:**
- Modify: `vir_bot/api/routers/chat_ws.py`

- [ ] **Step 1: 实现音频文件服务**

```python
from fastapi.responses import FileResponse
import hashlib
import time as _time


@router.get("/voice/{filename}")
async def serve_voice(filename: str):
    """提供 TTS 合成的音频文件"""
    import re
    from pathlib import Path

    # 安全校验：只允许特定格式的文件名
    if not re.match(r'^voice_[a-f0-9]{8,}_\d+\.(wav|mp3|ogg)$', filename):
        return {"error": "无效文件名"}

    file_path = Path("./data/cache") / filename
    if not file_path.exists():
        return {"error": "文件不存在"}

    media_type = "audio/wav" if filename.endswith(".wav") else "audio/mpeg"
    return FileResponse(str(file_path), media_type=media_type)
```

- [ ] **Step 2: 提交**

```bash
git add vir_bot/api/routers/chat_ws.py
git commit -m "feat: 音频文件服务端点"
```

---

### Task 5: TTS 语音合成

**Files:**
- Modify: `vir_bot/api/routers/chat_ws.py`

- [ ] **Step 1: 实现 TTS 合成逻辑**

在 `_handle_text` 中，流式输出完成后追加 TTS 处理：

```python
async def _synthesize_and_send(ws: WebSocket, text: str) -> None:
    """合成语音并发送音频 URL"""
    from vir_bot.main import _get_app_state

    app_state = _get_app_state()
    if not app_state.pipeline.tts:
        return

    try:
        text_hash = hashlib.md5(text.encode()).hexdigest()[:8]
        output_path = f"./data/cache/voice_{text_hash}_{int(_time.time())}.wav"
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        style = ""
        if app_state.pipeline.character and app_state.pipeline.voice_config:
            style = _build_style_hint(
                app_state.pipeline.character,
                app_state.pipeline.voice_config,
            )

        result_path = await app_state.pipeline.tts.synthesize(
            text, output_path, style_hint=style
        )
        if result_path:
            filename = Path(result_path).name
            await ws.send_json({
                "type": "voice_url",
                "url": f"/api/chat/ws/voice/{filename}",
            })
    except Exception as e:
        logger.error(f"[ChatWS] TTS 合成失败: {e}")
```

- [ ] **Step 2: 在 `_handle_text` 末尾调用 TTS**

```python
# 在 _handle_text 的 text_done 发送之后追加：
await _synthesize_and_send(ws, full_content)
```

- [ ] **Step 3: 运行测试确认不破坏**

```bash
cd /d/codeProject/vir-bot && PYTHONPATH=. uv run python -m pytest tests/unit/test_chat_ws.py -v
```

- [ ] **Step 4: 提交**

```bash
git add vir_bot/api/routers/chat_ws.py
git commit -m "feat: TTS 语音合成集成"
```

---

### Task 6: 路由注册 + 静态文件挂载

**Files:**
- Modify: `vir_bot/main.py`

- [ ] **Step 1: 注册 WebSocket 路由**

在 `create_app()` 函数中，现有路由注册之后添加：

```python
from vir_bot.api.routers import chat_ws
app.include_router(chat_ws.router, prefix="/api/chat/ws", tags=["聊天WebSocket"])
```

- [ ] **Step 2: 挂载聊天静态文件**

在现有静态文件挂载代码之后添加：

```python
# 聊天界面
try:
    from pathlib import Path
    from fastapi.staticfiles import StaticFiles

    chat_static_dir = Path(__file__).parent / "api" / "static" / "chat"
    if chat_static_dir.exists():
        app.mount(
            "/chat",
            StaticFiles(directory=str(chat_static_dir), html=True),
            name="chat",
        )
except Exception:
    pass
```

- [ ] **Step 3: 运行测试确认不破坏**

```bash
cd /d/codeProject/vir-bot && PYTHONPATH=. uv run python -m pytest tests/ -v --timeout=10
```

- [ ] **Step 4: 提交**

```bash
git add vir_bot/main.py
git commit -m "feat: 注册聊天 WebSocket 路由 + 挂载 /chat/ 静态文件"
```

---

### Task 7: 前端聊天界面 — 基础框架

**Files:**
- Create: `vir_bot/api/static/chat/index.html`

- [ ] **Step 1: 创建 HTML 骨架 + Vue 3 应用**

创建 `vir_bot/api/static/chat/index.html`，包含：
- HTML 结构（消息列表、输入区、角色卡侧边栏）
- CSS 暗色主题（与配置页统一）
- Vue 3 应用骨架
- WebSocket 连接管理

关键代码结构：

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>vir-bot 聊天</title>
<script src="https://unpkg.com/vue@3/dist/vue.global.prod.js"></script>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<style>
/* 暗色主题 CSS — 与配置页统一 */
:root {
  --bg: #0f1117;
  --surface: #1a1d27;
  --surface2: #232733;
  --border: #2d3140;
  --text: #e4e4e7;
  --text2: #a1a1aa;
  --text3: #71717a;
  --accent: #6366f1;
  --accent-hover: #818cf8;
  --accent-bg: rgba(99,102,241,.12);
  --success: #22c55e;
  --danger: #ef4444;
  --radius: 12px;
  --radius-sm: 8px;
}
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family: -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; background: var(--bg); color: var(--text); height: 100vh; overflow: hidden; }

/* 布局 */
.app { display:flex; flex-direction:column; height:100vh; max-width:800px; margin:0 auto; }
.header { padding:16px 20px; border-bottom:1px solid var(--border); display:flex; align-items:center; justify-content:space-between; }
.messages { flex:1; overflow-y:auto; padding:20px; }
.input-area { padding:16px 20px; border-top:1px solid var(--border); }

/* 消息气泡 */
.msg { margin-bottom:16px; display:flex; flex-direction:column; animation: fadeIn 0.3s ease-out; }
.msg-user { align-items:flex-end; }
.msg-assistant { align-items:flex-start; }
.bubble { max-width:80%; padding:12px 16px; border-radius:var(--radius-sm); font-size:14px; line-height:1.6; }
.msg-user .bubble { background:var(--accent); color:#fff; border-bottom-right-radius:4px; }
.msg-assistant .bubble { background:var(--surface2); color:var(--text); border-bottom-left-radius:4px; }
.bubble-time { font-size:11px; color:var(--text3); margin-top:4px; }

/* 输入区 */
.input-row { display:flex; gap:8px; align-items:flex-end; }
.input-text { flex:1; padding:10px 14px; background:var(--surface2); border:1px solid var(--border); border-radius:var(--radius-sm); color:var(--text); font-size:14px; font-family:inherit; outline:none; resize:none; min-height:44px; max-height:120px; }
.input-text:focus { border-color:var(--accent); }
.btn-send { padding:10px 20px; background:var(--accent); color:#fff; border:none; border-radius:var(--radius-sm); cursor:pointer; font-size:14px; font-weight:500; transition:background 0.15s; }
.btn-send:hover { background:var(--accent-hover); }
.btn-send:disabled { opacity:0.4; cursor:not-allowed; }
.btn-mic { width:44px; height:44px; border-radius:50%; border:2px solid var(--border); background:var(--surface2); color:var(--text2); cursor:pointer; font-size:18px; display:flex; align-items:center; justify-content:center; transition:all 0.15s; }
.btn-mic:hover { border-color:var(--accent); color:var(--accent); }
.btn-mic.recording { border-color:var(--danger); color:var(--danger); animation:pulse 1.5s infinite; }

/* 状态指示 */
.status { text-align:center; padding:8px; font-size:12px; color:var(--text3); }

/* 动画 */
@keyframes fadeIn { from { opacity:0; transform:translateY(8px); } to { opacity:1; transform:translateY(0); } }
@keyframes pulse { 0%,100% { box-shadow:0 0 0 0 rgba(239,68,68,0.4); } 50% { box-shadow:0 0 0 12px rgba(239,68,68,0); } }
@keyframes bounce { 0%,80%,100% { transform:translateY(0); } 40% { transform:translateY(-6px); } }
.typing-dot { display:inline-block; width:6px; height:6px; border-radius:50%; background:var(--text3); margin:0 2px; animation:bounce 1.4s infinite; }
.typing-dot:nth-child(2) { animation-delay:0.2s; }
.typing-dot:nth-child(3) { animation-delay:0.4s; }

/* 音频播放器 */
.audio-player { display:flex; align-items:center; gap:8px; padding:8px 12px; background:var(--surface); border-radius:var(--radius-sm); margin-top:8px; }
.audio-player button { background:none; border:none; color:var(--accent); cursor:pointer; font-size:16px; }

/* 响应式 */
@media (max-width:768px) {
  .app { max-width:100%; }
  .messages { padding:12px; }
  .bubble { max-width:90%; }
}
</style>
</head>
<body>
<div id="app" class="app">
  <!-- Header -->
  <div class="header">
    <div style="display:flex;align-items:center;gap:10px">
      <span style="font-size:20px">🤖</span>
      <div>
        <div style="font-weight:600;font-size:15px">vir-bot 聊天</div>
        <div style="font-size:11px;color:var(--text3)">{{ statusText }}</div>
      </div>
    </div>
    <div style="display:flex;gap:8px">
      <button @click="showCharacter = !showCharacter" style="background:var(--surface2);border:1px solid var(--border);border-radius:var(--radius-sm);padding:6px 12px;color:var(--text2);cursor:pointer;font-size:12px">👤 角色卡</button>
    </div>
  </div>

  <!-- Messages -->
  <div class="messages" ref="messagesEl">
    <div v-for="(msg, i) in messages" :key="i" :class="['msg', msg.role === 'user' ? 'msg-user' : 'msg-assistant']">
      <div class="bubble" v-html="renderMarkdown(msg.content)"></div>
      <div v-if="msg.audioUrl" class="audio-player">
        <button @click="playAudio(msg.audioUrl)">🔊</button>
        <span style="font-size:11px;color:var(--text3)">语音回复</span>
      </div>
      <div class="bubble-time">{{ msg.time }}</div>
    </div>
    <div v-if="streaming" class="msg msg-assistant">
      <div class="bubble">
        <span v-html="renderMarkdown(streamingContent)"></span>
        <span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span>
      </div>
    </div>
  </div>

  <!-- Input -->
  <div class="input-area">
    <div class="input-row">
      <textarea class="input-text" v-model="inputText" @keydown="handleKeydown" placeholder="输入消息..." rows="1"></textarea>
      <button class="btn-mic" :class="{recording: isRecording}" @mousedown="startRecording" @mouseup="stopRecording" @touchstart="startRecording" @touchend="stopRecording">🎤</button>
      <button class="btn-send" :disabled="!inputText.trim() || streaming" @click="sendMessage">发送</button>
    </div>
  </div>
</div>

<script>
const { createApp, ref, reactive, onMounted, nextTick, computed } = Vue;

// marked.js 配置
marked.setOptions({ breaks: true, gfm: true });

createApp({
  setup() {
    const messages = ref([]);
    const inputText = ref('');
    const streaming = ref(false);
    const streamingContent = ref('');
    const isRecording = ref(false);
    const showCharacter = ref(false);
    const messagesEl = ref(null);

    let ws = null;
    let recognition = null;

    const statusText = computed(() => {
      if (streaming.value) return 'AI 思考中...';
      if (isRecording.value) return '录音中...';
      return '在线';
    });

    function connect() {
      const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
      ws = new WebSocket(`${protocol}//${location.host}/api/chat/ws/ws`);

      ws.onopen = () => console.log('WebSocket 已连接');
      ws.onclose = () => { console.log('WebSocket 断开，3秒后重连'); setTimeout(connect, 3000); };
      ws.onerror = (e) => console.error('WebSocket 错误:', e);

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        switch (data.type) {
          case 'text_delta':
            streaming.value = true;
            streamingContent.value += data.content;
            scrollToBottom();
            break;
          case 'text_done':
            if (streaming.value) {
              messages.value.push({
                role: 'assistant',
                content: data.content,
                time: new Date().toLocaleTimeString('zh-CN', {hour:'2-digit',minute:'2-digit'}),
                audioUrl: null,
              });
            }
            streaming.value = false;
            streamingContent.value = '';
            scrollToBottom();
            break;
          case 'voice_url':
            const lastMsg = messages.value[messages.value.length - 1];
            if (lastMsg && lastMsg.role === 'assistant') {
              lastMsg.audioUrl = data.url;
            }
            break;
          case 'status':
            // 状态更新由 statusText 计算属性处理
            break;
          case 'error':
            messages.value.push({
              role: 'system',
              content: '⚠️ ' + data.message,
              time: new Date().toLocaleTimeString('zh-CN', {hour:'2-digit',minute:'2-digit'}),
            });
            streaming.value = false;
            break;
        }
      };
    }

    function sendMessage() {
      const text = inputText.value.trim();
      if (!text || streaming.value) return;
      messages.value.push({
        role: 'user',
        content: text,
        time: new Date().toLocaleTimeString('zh-CN', {hour:'2-digit',minute:'2-digit'}),
      });
      ws.send(JSON.stringify({ type: 'text', content: text }));
      inputText.value = '';
      scrollToBottom();
    }

    function handleKeydown(e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    }

    function startRecording() {
      if (!('webkitSpeechRecognition' in window || 'SpeechRecognition' in window)) {
        alert('当前浏览器不支持语音识别，请使用 Chrome');
        return;
      }
      const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
      recognition = new SpeechRecognition();
      recognition.lang = 'zh-CN';
      recognition.continuous = false;
      recognition.interimResults = true;

      recognition.onstart = () => { isRecording.value = true; };
      recognition.onresult = (event) => {
        const result = event.results[event.results.length - 1];
        if (result.isFinal) {
          const text = result[0].transcript;
          inputText.value = text;
          // 语音模式自动发送
          messages.value.push({
            role: 'user',
            content: text,
            time: new Date().toLocaleTimeString('zh-CN', {hour:'2-digit',minute:'2-digit'}),
          });
          ws.send(JSON.stringify({ type: 'text', content: text }));
          inputText.value = '';
          scrollToBottom();
        }
      };
      recognition.onerror = (e) => { console.error('语音识别错误:', e); isRecording.value = false; };
      recognition.onend = () => { isRecording.value = false; };

      recognition.start();
    }

    function stopRecording() {
      if (recognition) recognition.stop();
    }

    function playAudio(url) {
      const audio = new Audio(url);
      audio.play();
    }

    function renderMarkdown(text) {
      if (!text) return '';
      return marked.parse(text);
    }

    function scrollToBottom() {
      nextTick(() => {
        if (messagesEl.value) messagesEl.value.scrollTop = messagesEl.value.scrollHeight;
      });
    }

    onMounted(() => { connect(); });

    return {
      messages, inputText, streaming, streamingContent,
      isRecording, showCharacter, messagesEl, statusText,
      sendMessage, handleKeydown, startRecording, stopRecording,
      playAudio, renderMarkdown,
    };
  }
}).mount('#app');
</script>
</body>
</html>
```

- [ ] **Step 2: 浏览器验证**

启动服务后访问 `http://localhost:8000/chat/`，确认：
- 页面正常加载
- WebSocket 连接成功（控制台日志）
- 消息可以发送和接收

- [ ] **Step 3: 提交**

```bash
git add vir_bot/api/static/chat/index.html
git commit -m "feat: 聊天界面前端 — 基础框架 + 流式文字 + 语音输入"
```

---

### Task 8: 打断机制实现

**Files:**
- Modify: `vir_bot/api/routers/chat_ws.py`
- Modify: `vir_bot/api/static/chat/index.html`

- [ ] **Step 1: 后端打断支持**

在 `chat_ws.py` 中添加打断状态管理：

```python
# 在 websocket_chat 函数中添加打断逻辑
_current_task: asyncio.Task | None = None

async def _handle_interrupt(ws: WebSocket) -> None:
    """处理打断消息"""
    global _current_task
    logger.info("[ChatWS] 收到打断信号")
    if _current_task and not _current_task.done():
        _current_task.cancel()
        logger.info("[ChatWS] 已取消当前 AI 任务")
    await ws.send_json({"type": "status", "state": "idle"})
```

- [ ] **Step 2: 前端打断逻辑**

在 `index.html` 的 `startRecording` 中添加打断发送：

```javascript
recognition.onstart = () => {
  isRecording.value = true;
  // 发送打断信号
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'interrupt' }));
  }
};
```

- [ ] **Step 3: 提交**

```bash
git add vir_bot/api/routers/chat_ws.py vir_bot/api/static/chat/index.html
git commit -m "feat: 打断机制 — 用户说话时取消 AI 生成"
```

---

### Task 9: 集成测试 + 最终验证

**Files:**
- 无新文件，验证所有功能

- [ ] **Step 1: 运行全部测试**

```bash
cd /d/codeProject/vir-bot && PYTHONPATH=. uv run python -m pytest tests/ -v --timeout=30
```

Expected: 全部 PASS

- [ ] **Step 2: 手动功能验证**

启动服务：
```bash
cd /d/codeProject/vir-bot && uv run python -m vir_bot.main
```

访问 `http://localhost:8000/chat/`，验证：
1. 文字消息发送 → 流式回复显示
2. 录音按钮 → Web Speech API 识别 → 自动发送
3. AI 回复后自动 TTS → 音频播放
4. 打断机制 → 录音时取消 AI

- [ ] **Step 3: 最终提交**

```bash
git add -A
git commit -m "feat: 聊天 Web UI 完整功能验证通过"
```
