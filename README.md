# vir-bot

> 基于聊天记录蒸馏的AI机器人 — 数字分身

## 功能特性

- **AI人格蒸馏**：角色卡 + RAG知识库，让AI"像那个人一样说话"
- **多平台接入**：QQ (OneBot v11/v12)、Discord、企业微信（预留）
- **记忆系统**：短期上下文 (Ring Buffer) + 长期向量记忆 (ChromaDB)
- **MCP工具协议**：内置工具 + 可扩展注册，支持 AI 主动调用工具
- **可切换AI后端**：Ollama / OpenAI兼容API / 本地模型文件，一行配置切换
- **Web 控制台**：角色卡管理、记忆查询、MCP工具测试、平台状态、日志查看
- **视觉感知**：ESP32摄像头 / 本地摄像头 → 视觉LLM描述（预留接口）
- **语音交互**：Edge TTS / Whisper ASR / Porcupine唤醒词（预留接口）
- **硬件控制**：ESP32 + MQTT 协议，舵机/LED/表情控制（预留接口）
- **隐私优先**：所有数据本地处理，无外部依赖

## 技术栈

Python 3.11+ · FastAPI · asyncio · ChromaDB · Loguru

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 AI 后端（编辑 config.yaml 或设置环境变量）
# 云端 API：
export VIRBOT_OPENAI_KEY=sk-xxxxxxxx
# 编辑 config.yaml: ai.provider = "openai", ai.openai.model = "qwen-plus"

# 本地 Ollama：
# 先启动 ollama serve
# 编辑 config.yaml: ai.provider = "ollama", ai.ollama.model = "qwen2.5:7b"

# 3. 配置角色卡
# 编辑 data/characters/default.json（SillyTavern JSON格式）

# 4. 启动
python -m vir-bot.main

# 5. 打开 Web 控制台
# http://localhost:7860
# API 文档：http://localhost:7860/docs
```

## 目录结构

```
vir-bot/
├── vir-bot/
│   ├── core/                    # 核心抽象层（与平台/硬件无关）
│   │   ├── ai_provider.py       # AI策略模式（Ollama/OpenAI/本地模型）
│   │   ├── memory/              # 记忆系统
│   │   │   ├── short_term.py    # 短期记忆（asyncio Ring Buffer）
│   │   │   ├── long_term.py     # 长期记忆（ChromaDB 向量检索）
│   │   │   └── memory_manager.py# 记忆融合管理
│   │   ├── character/           # 角色卡系统（SillyTavern兼容JSON）
│   │   ├── mcp/                 # MCP工具协议
│   │   │   └── __init__.py      # 内置工具：计算器/记忆查询/角色卡更新
│   │   └── pipeline/            # 消息处理管道（核心编排器）
│   ├── platforms/               # 平台适配器（平台隔离）
│   │   ├── qq_adapter.py        # QQ (OneBot v11/v12 WebSocket)
│   │   ├── discord_adapter.py   # Discord (discord.py)
│   │   └── wechat_adapter.py    # 企业微信（预留）
│   ├── modules/                 # 可插拔模块（后续加硬件）
│   │   ├── voice/               # TTS (Edge) / ASR (Whisper) / 唤醒词
│   │   ├── visual/              # 摄像头 + 视觉LLM
│   │   └── hardware/            # MQTT + ESP32 协议
│   ├── api/                     # Web 控制台（FastAPI）
│   │   └── routers/             # 路由：character/memory/tools/logs/platforms/chat
│   ├── config.py                # 配置加载（YAML → Pydantic）
│   ├── main.py                  # 应用入口 + 生命周期管理
│   └── utils/                   # 日志等工具
├── data/
│   ├── characters/              # 角色卡（.json）
│   ├── knowledge/               # RAG 知识库原始文档
│   ├── memory/chroma_db/        # ChromaDB 持久化
│   └── logs/                    # 日志文件
├── config.yaml                  # 全局配置（所有配置集中于此）
├── requirements.txt             # Python 依赖
└── pyproject.toml               # 项目元数据
```

## Web 控制台

| 路由 | 功能 |
|------|------|
| `GET /api/character` | 获取当前角色卡 |
| `POST /api/character` | 更新角色卡字段 |
| `POST /api/character/upload` | 上传 SillyTavern JSON 角色卡文件 |
| `GET /api/memory` | 记忆统计（短期/长期条数） |
| `GET /api/memory/recent` | 最近对话记录 |
| `GET /api/memory/search` | 长期记忆向量检索 |
| `DELETE /api/memory` | 清空所有记忆 |
| `GET /api/tools` | 列出所有 MCP 工具 |
| `POST /api/tools/call` | 手动调用 MCP 工具 |
| `GET /api/config/ai/status` | AI Provider 健康检查 |
| `POST /api/chat` | Web 控制台直接对话测试 |
| `GET /api/logs` | 日志文件列表 |

## AI 后端切换

```yaml
# config.yaml — 只需改这一处
ai:
  provider: "openai"   # 或 "ollama" / "local_model"

  # Qwen / DeepSeek 等 OpenAI 兼容 API
  openai:
    api_key: ""        # 或设置环境变量 VIRBOT_OPENAI_KEY
    model: "qwen-plus"
    base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"

  # 本地 Ollama
  ollama:
    model: "qwen2.5:7b"
    base_url: "http://localhost:11434"

  # 本地模型文件（llama.cpp server / vLLM）
  local_model:
    model: "local-model"
    base_url: "http://localhost:8080"
```

## 平台接入配置

```yaml
# QQ (OneBot — 正向 WebSocket 模式)
platforms:
  qq:
    enabled: true
    connection:
      type: "正向WebSocket"
      host: "0.0.0.0"
      port: 8080
    access_token: ""   # 可选，设置环境变量 VIRBOT_QQ_TOKEN

# Discord
platforms:
  discord:
    enabled: true
    bot_token: ""      # 设置环境变量 VIRBOT_DISCORD_TOKEN
```

## 添加自定义 MCP 工具

```python
from vir_bot.core.mcp import Tool, ToolDefinition, ToolRegistry

class MyTool(Tool):
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="my_tool",
            description="我的自定义工具",
            parameters={
                "type": "object",
                "properties": {
                    "arg1": {"type": "string", "description": "参数说明"}
                },
                "required": ["arg1"],
            },
        )

    async def execute(self, arguments: dict) -> str:
        return f"执行结果: {arguments.get('arg1')}"

# 在 main.py 中注册
registry.register(MyTool())
```

## 项目阶段

| 阶段 | 内容 | 状态 |
|------|------|------|
| Phase 1 | 项目框架 + 核心抽象层 | ✅ 完成 |
| Phase 2 | 平台适配器（QQ/Discord/微信） | ✅ 完成 |
| Phase 3 | Web 控制台（7个API路由） | ✅ 完成 |
| Phase 4 | 可插拔模块（Voice/Visual/Hardware） | ✅ 完成 |
| Phase 5 | 硬件接入（ESP32 + MQTT） | 🔲 预留接口 |

架构设计详见 [ARCHITECTURE.md](./ARCHITECTURE.md)（可由本项目生成）

## 许可证

MIT