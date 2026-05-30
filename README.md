# vir-bot

> 基于聊天记录蒸馏的AI数字分身 — 8层记忆系统 + 知识图谱 + 多平台接入

## 功能特性

- **AI人格蒸馏**：从聊天记录中提取说话风格、性格特征、人设信息，生成 SillyTavern 兼容角色卡
- **8层记忆系统**：短期上下文 → 长期向量记忆 → 结构化语义记忆 → 事件记忆 → 问题记忆 → 知识图谱 → 版本管理 → 生命周期
- **知识图谱**：NetworkX 驱动的实体关系图谱，支持多跳查询、冲突检测、LLM 自动抽取
- **主动消息**：驱动系统（孤独/好奇/关心）+ 灵感触发 + 内容种子 + 质量反思，模拟"想你了"的自然消息
- **多平台接入**：Telegram（轮询）、QQ (OneBot v11/v12 WebSocket)、Discord、企业微信（预留）
- **MCP工具协议**：内置工具（计算器/记忆查询/记忆遗忘/角色卡更新）+ 可扩展注册
- **可切换AI后端**：Ollama / OpenAI兼容API / 本地模型 / LoRA微调，一行配置切换
- **Wiki知识库**：Markdown 格式的角色人设卡，自动注入系统提示词
- **表达管理**：基于文件夹的表情/贴图管理，支持用户上传、情绪分类
- **Web 控制台**：角色卡管理、记忆查询、主动消息控制、蒸馏任务、平台状态、日志查看
- **视觉感知**：ESP32摄像头 / 本地摄像头 → 视觉LLM描述（预留接口）
- **语音交互**：CosyVoice2 语音克隆 / Edge TTS / SenseVoice ASR / Whisper（部分实现）
- **硬件控制**：ESP32 + MQTT 协议，舵机/LED/表情控制（预留接口）
- **隐私优先**：所有数据本地处理，敏感信息不出设备

## 技术栈

| 类别 | 技术 |
|------|------|
| 语言 | Python 3.11+ |
| Web 框架 | FastAPI + uvicorn |
| 异步 | asyncio |
| 向量数据库 | ChromaDB |
| 知识图谱 | NetworkX |
| AI 推理 | PyTorch 2.6 (CUDA 12.4) |
| Embedding | sentence-transformers（Windows 下禁用，见已知问题） |
| 日志 | Loguru |
| 配置 | Pydantic + YAML |
| 包管理 | uv |
| 代码规范 | ruff |
| 测试 | pytest + pytest-asyncio |

## 快速开始

```bash
# 1. 安装依赖
uv sync

# 2. 配置 AI 后端
# 复制并编辑配置文件
cp config.yaml.example config.yaml  # 如有模板
# 或直接编辑 config.yaml：
#   ai.provider = "openai"
#   ai.openai.api_key = "sk-xxx"
#   ai.openai.model = "qwen-plus"

# 3. 配置平台（以 Telegram 为例）
# 编辑 config.yaml：
#   platforms.telegram.enabled = true
#   platforms.telegram.bot_token = "你的Bot Token"

# 4. 启动
uv run python -m vir_bot.main

# 5. 打开 Web 控制台
# http://localhost:7860
# API 文档：http://localhost:7860/docs
```

## 目录结构

```
vir-bot/
├── vir_bot/
│   ├── core/                        # 核心抽象层
│   │   ├── ai_provider.py           # AI策略模式（Ollama/OpenAI/本地模型/LoRA）
│   │   ├── character/               # 角色卡系统（SillyTavern 兼容 JSON/V1/V2）
│   │   ├── pipeline/                # 消息处理管道（核心编排器）
│   │   │   ├── __init__.py          #   主管道：消息→上下文→AI→工具→记忆→响应
│   │   │   └── message_splitter.py  #   消息拆分（多段发送）
│   │   ├── memory/                  # 8层记忆系统
│   │   │   ├── memory_manager.py    #   记忆融合管理（中央枢纽）
│   │   │   ├── short_term.py        #   短期记忆（Ring Buffer）
│   │   │   ├── long_term.py         #   长期记忆（ChromaDB 向量检索）
│   │   │   ├── semantic_store.py    #   结构化语义记忆（JSON 持久化）
│   │   │   ├── episodic_store.py    #   事件记忆（今天/昨天/最近发生了什么）
│   │   │   ├── question_memory.py   #   问题记忆（倒排索引、追问计数）
│   │   │   ├── graph_store.py       #   知识图谱（NetworkX 三元组存储）
│   │   │   ├── graph_extractor.py   #   图谱关系抽取（LLM 驱动）
│   │   │   ├── memory_writer.py     #   LLM 记忆写入器
│   │   │   ├── memory_updater.py    #   结构化记忆更新器
│   │   │   ├── retrieval_router.py  #   智能检索路由（意图分类→多路并行检索）
│   │   │   ├── quality_gate.py      #   写入质量门控（规则+LLM二次判断）
│   │   │   ├── verifier.py          #   写入前查重（语义相似度+文本匹配）
│   │   │   ├── feedback_handler.py  #   用户纠正处理
│   │   │   ├── monitoring.py        #   在线监控（命中率/冲突率/纠正率）
│   │   │   ├── debug_tools.py       #   调试工具（时间线回放、版本链查看）
│   │   │   ├── enhancements/        #   增强组件
│   │   │   │   ├── reranker.py      #     CrossEncoder 重排（Windows 下降级为关键词匹配）
│   │   │   │   └── composer.py      #     记忆组合（去重/冲突解决/token预算）
│   │   │   └── lifecycle/           #   生命周期管理
│   │   │       ├── decay.py         #     记忆衰减算法
│   │   │       ├── janitor.py       #     后台清理（衰减/合并/归档）
│   │   │       └── merge.py         #     重复记忆合并
│   │   ├── proactive/               # 主动消息系统 v4
│   │   │   ├── proactive_service.py #   主服务（驱动+灵感+种子+生成+反思）
│   │   │   ├── drive_system.py      #   内驱系统（孤独/好奇/关心）
│   │   │   ├── inspiration_trigger.py # 灵感触发（LLM 内心独白）
│   │   │   ├── seed_selector.py     #   内容种子选择
│   │   │   ├── reflector.py         #   质量反思（反模式检测+4轴评分）
│   │   │   ├── expression.py        #   消息生成层
│   │   │   ├── mood_model.py        #   5维情绪模型
│   │   │   ├── fact_extractor.py    #   事实提取器
│   │   │   └── concern_engine.py    #   关心引擎（v3，已被驱动系统替代）
│   │   ├── mcp/                     # MCP工具协议
│   │   │   └── __init__.py          #   工具注册/执行/定义
│   │   ├── wiki/                    # Wiki知识库（Markdown 人设卡解析）
│   │   ├── distillation/            # 聊天记录蒸馏
│   │   │   ├── pipeline.py          #   蒸馏管道（解析→提取→生成→评估）
│   │   │   ├── analyzer/            #   分析器（人设提取/风格分析/话题聚类/融合）
│   │   │   ├── parser/              #   聊天记录解析器
│   │   │   ├── generator/           #   Wiki/角色卡生成器
│   │   │   ├── evaluator.py         #   LLM-as-Judge 评估
│   │   │   └── finetune/            #   LoRA 微调（训练/推理/数据构建）
│   │   └── sticker/                 # 表情/贴图管理
│   │       ├── __init__.py          #   ExpressionManager（文件夹分类/随机选择）
│   │       └── downloader.py        #   用户上传表情保存
│   ├── platforms/                   # 平台适配器
│   │   ├── base_adapter.py          #   抽象基类（收消息→管道→拆分发送）
│   │   ├── telegram_adapter.py      #   Telegram（轮询模式，支持代理）
│   │   ├── qq_adapter.py            #   QQ (OneBot v11/v12 正向WebSocket)
│   │   ├── qq_official_adapter.py   #   QQ官方机器人 (OpenAPI v2 HTTP回调)
│   │   ├── discord_adapter.py       #   Discord
│   │   └── wechat_adapter.py        #   企业微信（预留）
│   ├── modules/                     # 可插拔模块
│   │   ├── voice/                   #   TTS (CosyVoice2/EdgeTTS) / ASR (SenseVoice/Whisper)
│   │   ├── visual/                  #   摄像头 + 视觉LLM
│   │   └── hardware/                #   MQTT + ESP32
│   ├── api/                         # Web 控制台 API
│   │   └── routers/                 #   路由：chat/character/memory/tools/config/logs/platforms/distillation/proactive
│   ├── config.py                    # 配置加载（YAML → Pydantic，环境变量覆盖）
│   ├── main.py                      # 应用入口 + 生命周期管理
│   └── utils/
│       └── logger.py                # Loguru 日志（控制台+文件，按天轮转）
├── data/
│   ├── characters/default.json      # 角色卡（SillyTavern JSON）
│   ├── wiki/characters/             # Wiki 人设卡（Markdown）
│   ├── knowledge/                   # RAG 知识库原始文档
│   ├── memory/                      # 记忆数据（运行时生成，不提交）
│   │   ├── chroma_db/               #   ChromaDB 持久化
│   │   ├── semantic_memory.json     #   语义记忆
│   │   ├── episodic_memory.json     #   事件记忆
│   │   ├── question_memory.json     #   问题记忆
│   │   └── memory_graph.json        #   知识图谱
│   ├── stickers/                    # 表情/贴图（按情绪分类）
│   └── logs/                        # 日志文件（运行时生成）
├── tests/                           # 测试
│   ├── unit/                        #   单元测试（14个文件）
│   ├── integration/                 #   集成测试
│   └── eval/                        #   评测框架
├── docs/                            # 文档
├── config.yaml                      # 全局配置（不提交，含敏感信息）
├── pyproject.toml                   # 项目元数据 + ruff/pytest 配置
└── uv.lock                          # 依赖锁文件
```

## 记忆系统

8层记忆架构，详见 [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md)：

| 层 | 组件 | 存储 | 用途 |
|----|------|------|------|
| L1 | ShortTermMemory | 内存 deque | 最近20轮对话上下文 |
| L2 | LongTermMemory | ChromaDB | 向量检索历史对话 |
| L3 | SemanticMemoryStore | JSON | 结构化事实（偏好/习惯/身份/事件） |
| L4 | EpisodicMemoryStore | JSON | 事件记忆（今天/昨天/最近） |
| L5 | QuestionMemory | JSON | 问题追踪（倒排索引、追问计数） |
| L6 | MemoryGraphStore | NetworkX+JSON | 知识图谱（实体关系三元组） |
| L7 | 版本管理 | semantic_store 内置 | valid_from/valid_to 版本链 |
| L8 | 生命周期 | janitor | 衰减/合并/归档/清理 |

检索路由：`RetrievalRouter` 根据查询意图分类（时间/偏好/身份/习惯/事件/问题/对话/通用），并行搜索多个记忆层，通过 `MemoryComposer` 去重+冲突解决+token预算分配。

## 主动消息系统

v4 架构，详见 [docs/proactive/](./docs/proactive/)：

```
驱动积累 → 概率触发 → 灵感判断 → 种子选择 → 消息生成 → 质量反思 → 发送
```

- **驱动系统**：孤独感（指数增长）、好奇心（线性+事实boost）、关心（事件驱动）
- **灵感触发**：LLM 内心独白"我现在想不想给她发消息？"
- **内容种子**：callback（回提事实）、interest（兴趣话题）、situation（时境）、shared_memory（共同记忆）
- **质量反思**：反模式自动拒绝 + LLM 4轴评分（具体性/时机/价值/新鲜度）

## Web 控制台 API

| 路由 | 功能 |
|------|------|
| `POST /api/chat` | Web 控制台直接对话测试 |
| `GET/POST /api/character` | 角色卡获取/更新 |
| `GET/POST/DELETE /api/memory` | 记忆统计/搜索/清空 |
| `GET /api/memory/semantic` | 查询结构化语义记忆 |
| `GET /api/memory/semantic/search` | 搜索语义记忆 |
| `GET /api/tools` | 列出所有 MCP 工具 |
| `POST /api/tools/call` | 手动调用 MCP 工具 |
| `GET/PUT /api/config/sections/{section}` | 配置管理（敏感字段脱敏） |
| `GET /api/logs` | 日志文件列表和内容 |
| `GET/POST /api/platforms` | 平台状态/QQ官方回调 |
| `POST /api/distillation/upload` | 上传聊天记录文件 |
| `POST /api/distillation/start` | 启动蒸馏任务 |
| `GET /api/distillation/status` | 蒸馏任务状态 |
| `WS /api/distillation/ws` | 蒸馏进度实时推送 |
| `GET/POST /api/proactive` | 主动消息状态/启用/触发/统计 |

## AI 后端切换

```yaml
# config.yaml
ai:
  provider: "openai"   # 或 "ollama" / "local_model" / "lora"

  openai:
    api_key: ""        # 或环境变量 VIRBOT_OPENAI_KEY
    model: "qwen-plus"
    base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"

  ollama:
    model: "qwen2.5:7b"
    base_url: "http://localhost:11434"
```

## 平台接入配置

```yaml
# Telegram（推荐）
platforms:
  telegram:
    enabled: true
    bot_token: "123456:ABC-DEF"    # 从 @BotFather 获取
    proxy: "http://127.0.0.1:7890" # 可选，国内需要代理
    allowed_users: []               # 可选，限制用户ID

# QQ (OneBot — 正向 WebSocket)
platforms:
  qq:
    enabled: true
    connection:
      type: "正向WebSocket"
      host: "0.0.0.0"
      port: 8080

# Discord
platforms:
  discord:
    enabled: true
    bot_token: ""      # 环境变量 VIRBOT_DISCORD_TOKEN
```

## 测试

```bash
# 运行所有测试
uv run pytest tests/ -q

# 运行单元测试
uv run pytest tests/unit/ -q

# 运行集成测试
uv run pytest tests/integration/ -q

# 运行评测
uv run python -m tests.eval.runner --dataset data/eval_dataset.jsonl
```

## 已知问题

### Windows DLL 冲突

`sentence-transformers` 5.5.0 与 PyTorch CUDA 在 Windows 上存在 DLL 加载冲突，会导致原生段错误（segfault）。当前已禁用以下组件：

- **CrossEncoder 重排器**（`reranker.py`）→ 降级为关键词匹配
- **写入查重器**（`verifier.py`）→ 降级为文本匹配
- **SentenceTransformer Embedding**（`long_term.py`）→ 降级为 Ollama Embedding 或哈希向量
- **话题聚类**（`topic_clusterer.py`）→ 聚类功能不可用

影响：记忆检索精度降低，但核心功能正常运行。Linux/Docker 环境不受影响。

### 其他

- `eval()` 安全风险：`long_term.py` 和 `CalculatorTool` 中使用了 `eval()`，生产环境应替换
- 全局状态模式：`app_state` 使用 `sys.modules["__main__"]` 共享状态，测试不够友好

## 项目阶段

| 阶段 | 内容 | 状态 |
|------|------|------|
| Phase 1 | 项目框架 + 核心抽象层 | ✅ 完成 |
| Phase 2 | 平台适配器（Telegram/QQ/Discord） | ✅ 完成 |
| Phase 3 | Web 控制台（9个API路由组） | ✅ 完成 |
| Phase 4 | 记忆系统（8层架构 + 知识图谱 + 生命周期） | ✅ 完成 |
| Phase 5 | 主动消息系统 v4（驱动+灵感+种子+反思） | ✅ 完成 |
| Phase 6 | 聊天记录蒸馏（解析→提取→生成→评估→LoRA微调） | ✅ 完成 |
| Phase 7 | 语音交互（CosyVoice2/EdgeTTS + SenseVoice/Whisper） | 🔲 部分实现 |
| Phase 8 | 视觉感知 + 硬件控制 | 🔲 预留接口 |

## 许可证

MIT
