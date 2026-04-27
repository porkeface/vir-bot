# vir-bot

## 项目概述

个性化AI机器人（数字分身）— 基于聊天记录蒸馏的AI人格 + 多平台接入 + RAG记忆 + Wiki + MCP工具。

**核心理念**：构建一个具备自我进化能力的记忆推理系统（Memory Reasoning System），而非拼凑的功能集合。长期项目，以评测分数驱动迭代，每次改进确保分数单调不减。

## 技术栈

- **运行时**：Python 3.11+，使用 **uv** 管理虚拟环境和依赖（⚠️ 不是pip！）
- **框架**：FastAPI / asyncio / Loguru
- **向量数据库**：ChromaDB
- **AI后端**：可切换策略 — Ollama / OpenAI兼容API（DeepSeek/Qwen等）/ 本地模型
- **测试**：pytest + 自定义评测系统（基于LongMemEval思想）

## 开发环境（重要）

```bash
# 项目使用 uv 虚拟环境，所有命令前需确保使用 uv
cd "D:/code Project/vir-bot"

# 安装/更新依赖
uv pip install -r requirements.txt

# 或者使用 pyproject.toml
uv sync

# 运行项目
uv run python -m vir_bot.main

# 运行测试
uv run pytest tests/ -v

# 运行评测
uv run python -m tests.eval.runner

# 启动 Web 控制台（启动后访问 http://localhost:7860）
uv run python -m vir_bot.main
```

⚠️ **注意**：不要使用 `pip install` 或 `python -m`，始终使用 `uv run` 前缀或先 `source .venv/Scripts/activate`（Windows）。

## 架构原则

- **核心层独立**：`core/` 不依赖平台或硬件，通过策略模式和适配器隔离变化
- **消息编排**：统一走 Pipeline，支持中间件式扩展
- **记忆分层**：按认知心理学分层（短期/语义/情景/程序），混合存储匹配用途
- **可插拔模块**：`modules/` 下的语音/视觉/硬件模块按需加载
- **评测驱动**：每次功能迭代必跑评测，分数单调不减是唯一可靠标准
- **特性开关**：所有新功能通过 `config.yaml` 的 `memory.features.*.enabled` 控制，默认关闭

## 目录结构

```
vir-bot/
├── vir_bot/
│   ├── core/                        # 核心抽象层（与平台/硬件无关）
│   │   ├── ai_provider.py           # AI策略模式（Ollama/OpenAI/本地模型）
│   │   ├── memory/                  # 记忆系统（8层架构）
│   │   │   ├── short_term.py        # Layer1: 短期记忆（Ring Buffer）
│   │   │   ├── long_term.py         # Layer6: ChromaDB向量存储
│   │   │   ├── semantic_store.py    # Layer6: 结构化语义记忆（JSON+版本链）
│   │   │   ├── episodic_store.py    # Layer6: 事件记忆存储
│   │   │   ├── question_memory.py   # Layer6: 问答历史存储
│   │   │   ├── graph_store.py       # Layer6: 图记忆（NetworkX，实体关系）
│   │   │   ├── retrieval_router.py  # Layer2: 意图路由+多路检索
│   │   │   ├── memory_manager.py    # 总协调器，统一接口
│   │   │   ├── memory_writer.py     # Layer4: 记忆提取器（LLM提取操作）
│   │   │   ├── memory_updater.py    # Layer5: 多版本更新器（ADD/UPDATE/DELETE）
│   │   │   ├── quality_gate.py      # Layer4: 规则+LLM质量门
│   │   │   ├── verifier.py          # Layer4: 重复/冲突检测
│   │   │   ├── feedback_handler.py  # Layer5: 用户纠正处理（置信度衰减）
│   │   │   ├── monitoring.py        # Layer8: 线上监控（命中率/冲突率）
│   │   │   ├── debug_tools.py       # Layer8: 调试工具（时间线回放/版本链）
│   │   │   ├── graph_extractor.py   # Layer6: 对话中抽取实体关系
│   │   │   ├── enhancements/
│   │   │   │   ├── reranker.py     # Layer2: Cross-Encoder重排序
│   │   │   │   └── composer.py     # Layer2: 去重+冲突消解+Token预算
│   │   │   └── lifecycle/
│   │   │       ├── janitor.py       # Layer7: 生命周期管理器
│   │   │       ├── decay.py         # Layer7: 衰减算法
│   │   │       └── merge.py        # Layer7: 相似记忆合并
│   │   ├── character/               # 角色卡系统（SillyTavern兼容JSON）
│   │   ├── mcp/                     # MCP工具协议
│   │   ├── wiki/                    # Wiki知识库（角色人设解析）
│   │   └── pipeline/                # 消息处理管道（核心编排器）
│   ├── platforms/                   # 平台适配器
│   │   ├── qq_adapter.py            # QQ (OneBot v11/v12)
│   │   ├── discord_adapter.py       # Discord
│   │   └── wechat_adapter.py        # 企业微信
│   ├── modules/                     # 可插拔模块
│   │   ├── voice/                   # TTS/ASR/唤醒词
│   │   ├── visual/                  # 摄像头+视觉LLM
│   │   └── hardware/                # ESP32+MQTT协议
│   ├── api/                         # Web控制台（FastAPI）
│   │   └── routers/                 # character/memory/tools/logs/platforms/chat
│   ├── config.py                    # 配置加载（YAML → Pydantic）
│   ├── main.py                      # 应用入口+生命周期管理
│   └── utils/                       # 日志等工具
├── tests/
│   ├── unit/                        # 单元测试（覆盖各记忆模块）
│   ├── integration/                 # 集成测试（端到端Pipeline）
│   ├── eval/                        # 评测系统（Layer8）
│   │   ├── benchmark.py             # 评测主入口
│   │   ├── metrics.py               # 五项指标（偏好/事件/更新/时间/拒答）
│   │   ├── runner.py                # 自动跑分脚本
│   │   ├── __main__.py              # CLI入口
│   │   └── datasets/               # 测试数据集（JSON）
│   ├── test_phase4_composer.py      # Phase4专项测试
│   ├── test_phase6.py               # Phase6专项测试
│   ├── test_phase8.py               # Phase8专项测试
│   └── test_live_service.py         # 在线服务测试
├── data/
│   ├── characters/                  # 角色卡（.json / .md）
│   ├── knowledge/                   # RAG知识库原始文档
│   ├── memory/
│   │   ├── chroma_db/              # ChromaDB持久化
│   │   ├── semantic_memory.json     # 结构化语义记忆
│   │   ├── episodic_memory.json    # 事件记忆
│   │   ├── question_memory.json     # 问答历史
│   │   └── memory_graph.json       # 图记忆
│   ├── wiki/                        # Wiki知识库
│   └── logs/                        # 日志文件
├── docs/
│   ├── 记忆架构分层详解.md           # 8层架构设计文档
│   └── vir-bot 记忆系统渐进式改造计划.md  # 分阶段实施计划
├── config.yaml                      # ⚠️ 全局配置（所有配置集中于此）
├── pyproject.toml                   # uv项目定义
└── uv.lock                          # uv锁定文件
```

## 记忆系统架构（8层）

```
Layer 1: 短期记忆与感知层
  - ShortTermMemory（Ring Buffer，最近N轮对话）

Layer 2: 记忆检索与推理层（核心）
  - RetrievalRouter: 意图分类 → 激活记忆源+分配权重
  - 多路检索: Semantic + Episodic + Question + Graph（并行）
  - ReRanker: Cross-Encoder重排序
  - Composer: 去重 + 冲突消解 + Token预算分配

Layer 3: 响应生成层
  - Response Context Builder: 组装记忆+角色卡+Wiki
  - LLM推理引擎: 可切换后端，强制"不确定就不编造"

Layer 4: 记忆写入与质量控制层
  - MemoryWriter: LLM提取结构化操作（ADD/UPDATE/DELETE/NOOP）
  - QualityGate: 规则引擎 + LLM二次判断
  - WriteVerifier: 重复检测 + 冲突预判

Layer 5: 记忆更新与版本管理层
  - MemoryUpdater: 多版本时间感知（valid_from/to, confidence_history）
  - FeedbackHandler: 用户纠正 → 置信度衰减 + 自动UPDATE

Layer 6: 持久化记忆存储层（混合存储）
  - SemanticMemoryStore: JSON结构化，带版本链
  - EpisodicMemoryStore: 事件记录+摘要+时间戳
  - QuestionMemoryStore: 问答历史
  - LongTermMemory: ChromaDB向量库（会话片段）
  - MemoryGraphStore: NetworkX图数据库（实体关系，多跳推理）

Layer 7: 记忆生命周期管理层
  - Janitor: 后台Cron任务（衰减降权/相似合并/低置信归档）

Layer 8: 质量保证与评测层
  - 评测系统: 五大指标（偏好召回/事件回忆/知识更新/时间推理/拒答准确率）
  - MemoryMonitor: 线上监控（检索命中率/冲突率/修正率）
  - DebugTools: 时间线回放/版本链查看/手动干预
```

## 当前进度

| Phase | 内容 | 状态 |
|-------|------|------|
| Phase 1 | 测试框架 + 配置开关 | ✅ 完成 |
| Phase 2 | 评测系统（baseline + 监控 + 调试工具） | 🔄 进行中 |
| Phase 3 | Re-Ranker（Cross-Encoder重排序） | ✅ 完成（已启用） |
| Phase 4 | Memory Composer（去重+冲突消解+Token预算） | ✅ 完成（已启用） |
| Phase 5 | Quality Gate + Write Verifier | ✅ 完成（已启用） |
| Phase 6 | 多版本支持 + Feedback Handler | ✅ 完成（已启用） |
| Phase 7 | Memory Graph（NetworkX实体关系） | ✅ 完成（已启用） |
| Phase 8 | Lifecycle Manager（衰减+合并+归档） | ✅ 完成（已启用） |

> 当前所有Phase 3-8的功能已在 `config.yaml` 中启用（features 下各 enabled: true）。
> Phase 2 评测系统已搭建，需持续扩充数据集和提升覆盖率。

## 评测系统（Layer 8）

基于 LongMemEval 思想，每次代码变更自动跑分，确保分数单调不减。

**五项指标**：
- **Preference Recall**（0.25）：偏好召回率
- **Episodic Recall**（0.20）：事件回忆率
- **Knowledge Update**（0.20）：知识更新准确率
- **Temporal Reasoning**（0.20）：时间推理准确率
- **Abstention Accuracy**（0.15）：拒答准确率（查不到不编造）

**运行评测**：
```bash
uv run python -m tests.eval.runner
# 或
uv run pytest tests/eval/ -v
```

**历史分数**：保存在 `tests/eval/history.json`，用于对比每次改进效果。

## 上下文管理策略

⚠️ **重要**：当对话上下文达到约60%时，应主动执行以下操作，防止信息丢失：

1. **整理当前进度**：
   - 总结已完成的任务和决策
   - 记录当前正在进行的任务和遇到的阻碍
   - 更新 `tests/eval/history.json` 中的评测分数

2. **持久化到项目文档**：
   - 如有架构变更，更新本文件（CLAUDE.md）
   - 如有新的设计决策，记录到 `docs/` 目录
   - 使用 git commit 保存代码变更

3. **记忆系统同步**：
   - 重要决策和上下文应通过对话让记忆系统自动捕获
   - 关键架构决策可手动写入 `data/memory/semantic_memory.json`

4. **新会话恢复**：
   - 新会话开始时，先读取 CLAUDE.md + 最近的 git log + tests/eval/history.json
   - 不依赖 /compact 或 /clear，通过文档持久化实现上下文延续

## AI自主性原则

本项目不靠硬编码规则或大量提示词驱动AI行为。AI伴侣应具备：

- **自主思考**：基于当前上下文、评测分数、用户反馈自主决策下一步行动
- **意图理解**：理解用户纠正（"我不叫张三"）→ 自动触发 FeedbackHandler
- **动态适应**：根据评测分数变化判断改造是否有效，而非依赖"感觉"
- **长距离规划**：识别长期目标（8层架构完整实现）和短期任务（当前Phase的收尾）
- **最小干预**：只在没有明确依据时才询问用户，有依据的自主决策直接执行

**避免过度提示词化**：角色卡（Wiki）注入已足够定义AI人格，不需要在代码中硬编码行为规则。

## 配置说明

所有配置集中 in `config.yaml`，关键配置项：

```yaml
# AI后端切换（只需改这一处）
ai:
  provider: "openai"  # ollama / openai / local_model

# 记忆系统特性开关（当前全部已启用）
memory:
  features:
    reranker: { enabled: true }
    composer: { enabled: true }
    quality_gate: { enabled: true }
    verifier: { enabled: true }
    lifecycle: { enabled: true }
    graph: { enabled: true }
    versioning: { enabled: true }

# 平台接入（当前全部关闭）
platforms:
  qq: { enabled: false }
  discord: { enabled: false }
  wechat: { enabled: false }

# Web控制台
web_console:
  enabled: true
  port: 7860
```

## 开发工作流

1. **研究 & 规划**：理解需求 → 查文档/资料 → 制定方案
2. **测试先行**：写测试（RED）→ 实现（GREEN）→ 重构（IMPROVE）
3. **评测验证**：跑分 → 对比历史 → 确保分数不减
4. **代码审查**：检查质量/安全/覆盖率
5. **提交 & 记录**：git commit → 更新文档 → 记录评测分数

## Web 控制台 API

| 路由 | 功能 |
|------|------|
| `GET /api/character` | 获取当前角色卡 |
| `POST /api/character` | 更新角色卡字段 |
| `GET /api/memory` | 记忆统计（短期/长期条数） |
| `GET /api/memory/semantic` | 查询结构化语义记忆 |
| `GET /api/memory/search` | 长期记忆向量检索 |
| `GET /api/tools` | 列出所有MCP工具 |
| `POST /api/tools/call` | 手动调用MCP工具 |
| `GET /api/config/ai/status` | AI Provider健康检查 |
| `POST /api/chat` | Web控制台直接对话测试 |

## 参考文档

- [记忆架构分层详解](./docs/记忆架构分层详解.md) — 8层架构完整设计
- [渐进式改造计划](./docs/vir-bot%20记忆系统渐进式改造计划.md) — 分阶段实施计划
- [README.md](./README.md) — 项目概览与快速开始（部分内容已过时，以本文件为准）
