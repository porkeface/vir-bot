# vir-bot 记忆系统使用文档

> 架构设计、实施计划、进度追踪见 [ARCHITECTURE.md](./ARCHITECTURE.md)
> 主动消息系统见 [proactive/](./proactive/)

## 目录

- [概述](#概述)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [API 使用指南](#api-使用指南)
- [知识图谱](#知识图谱)
- [质量门控与查重](#质量门控与查重)
- [测试与验证](#测试与验证)
- [常见问题](#常见问题)

---

## 概述

AI 数字分身的记忆系统采用 8 层架构：

| 层 | 组件 | 存储 | 用途 |
|----|------|------|------|
| L1 短期记忆 | `ShortTermMemory` | 内存 deque | 最近 20 轮对话上下文 |
| L2 长期记忆 | `LongTermMemory` | ChromaDB | 历史对话的向量检索 |
| L3 语义记忆 | `SemanticMemoryStore` | JSON | 结构化事实（偏好、习惯、身份、事件） |
| L4 事件记忆 | `EpisodicMemoryStore` | JSON | 事件记录（今天/昨天/最近发生了什么） |
| L5 问题记忆 | `QuestionMemory` | JSON | 用户问题追踪（倒排索引、追问计数） |
| L6 知识图谱 | `MemoryGraphStore` | NetworkX+JSON | 实体关系三元组（多跳查询） |
| L7 版本管理 | semantic_store 内置 | — | valid_from/valid_to 版本链 |
| L8 生命周期 | `MemoryJanitor` | — | 衰减/合并/归档/清理 |

检索入口为 **RetrievalRouter**，根据查询意图分类后并行搜索多个记忆层，通过 **MemoryComposer** 去重+冲突解决+token预算分配。

所有记忆写入都经过 **Quality Gate**（质量门控）和 **WriteVerifier**（写入查重），低信息量、不可靠或重复的内容会被拦截。

---

## 快速开始

### 1. 安装依赖

```bash
cd "D:/code Project/vir-bot"
uv sync
```

### 2. 配置 API Key

```bash
# 设置环境变量（DeepSeek / OpenAI 兼容接口）
export VIRBOT_OPENAI_KEY="your-api-key-here"

# 或在 config.yaml 中直接填写（不推荐）
# ai.openai.api_key: "sk-..."
```

### 3. 启动服务

```bash
uv run python -m vir_bot.main
```

看到如下输出表示启动成功：

```
vir-bot 0.1.0 启动
AI Provider: openai/mimo-v2.5-pro (健康: True)
Wiki 系统已初始化，角色: 陈暖树
主动消息系统已启动（v4 驱动+灵感）
Web 控制台: http://0.0.0.0:7860
API 文档: http://0.0.0.0:7860/docs
```

### 4. 开始对话

```bash
# 使用 curl
curl -X POST http://localhost:7860/api/chat/ \
  -H "Content-Type: application/json" \
  -d '{"content": "我叫张三，最喜欢火锅", "user_id": "user1"}'
```

---

## 配置说明

配置文件：`config.yaml`

### 基础记忆配置

```yaml
memory:
  short_term:
    max_turns: 20        # 短期记忆保留轮数
    window_size: 10       # 上下文窗口大小

  long_term:
    enabled: true           # 是否启用向量长期记忆
    vector_db: "chroma"      # 向量数据库类型
    persist_dir: "./data/memory/chroma_db"
    collection_name: "persona_memory"
    top_k: 5                 # 检索返回数量
    embedding_model: "all-MiniLM-L6-v2"
    auto_index: true          # 自动索引新对话
```

### 功能开关配置

```yaml
memory:
  features:
    # Re-Ranker（重排序）— CrossEncoder 重排检索结果
    reranker:
      enabled: true
      model: "cross-encoder/ms-marco-MiniLM-L-6-v2"
      top_k: 5

    # Composer（记忆组合）— 去重/冲突解决/token预算
    composer:
      enabled: true
      max_tokens: 2000

    # Quality Gate — 规则+LLM 质量门控
    quality_gate:
      enabled: true

    # Verifier — 写入前查重（语义相似度+文本匹配）
    verifier:
      enabled: true

    # Versioning — 多版本时间感知
    versioning:
      enabled: true
      max_versions: 10

    # Memory Graph — 知识图谱（NetworkX 三元组）
    graph:
      enabled: true
      persist_path: "./data/memory/memory_graph.json"

    # Lifecycle Manager — 衰减/合并/归档
    lifecycle:
      enabled: true
      interval_hours: 24
```

> **注意**：在 Windows 上，`reranker` 和 `verifier` 的语义匹配功能因 DLL 冲突自动降级为关键词匹配。详见 [已知问题](#已知问题)。

---

## API 使用指南

服务启动后，访问 `http://localhost:7860/docs` 查看完整 Swagger 文档。

### 1. 对话接口

**POST** `/api/chat/`

```json
{
  "content": "我叫张三，最喜欢火锅",
  "user_id": "user1",
  "user_name": "张三"
}
```

**响应：**

```json
{
  "reply": "哇～原来你叫张三呀！名字真好听呢～😊\n最喜欢火锅？！啊啊啊我也超爱的！🍲🥰..."
}
```

### 2. 记忆统计

**GET** `/api/memory/`

```bash
curl http://localhost:7860/api/memory/
```

**响应：**

```json
{
  "short_term": {"count": 14},
  "long_term": {
    "total_count": 7,
    "type_distribution": {"conversation": 7},
    "average_importance": 0.5
  },
  "semantic_count": 4,
  "episodic_count": 7,
  "question_count": 7,
  "character": "陈暖树"
}
```

### 3. 查询语义记忆

**GET** `/api/memory/semantic?user_id=user1`

```json
[
  {
    "memory_id": "b39e9855-...",
    "namespace": "profile.identity",
    "predicate": "name_is",
    "object": "张三",
    "confidence": 0.95,
    "updated_at": 1777209282.65,
    "source_text": "我叫张三，最喜欢火锅"
  }
]
```

### 4. 搜索语义记忆

**GET** `/api/memory/semantic/search?query=我喜欢吃什么&user_id=user1`

返回与查询相关的语义记忆列表。

### 5. 清空记忆

**DELETE** `/api/memory/`

```bash
curl -X DELETE http://localhost:7860/api/memory/
```

### 6. 配置管理

**GET** `/api/config/sections/{section}`

```bash
# 获取记忆配置（敏感字段自动脱敏）
curl http://localhost:7860/api/config/sections/memory
```

**PUT** `/api/config/sections/{section}`

```bash
# 更新配置
curl -X PUT http://localhost:7860/api/config/sections/memory \
  -H "Content-Type: application/json" \
  -d '{"features": {"reranker": {"enabled": true}}}'
```

### 7. 主动消息

**GET** `/api/proactive`

```bash
# 获取主动消息状态
curl http://localhost:7860/api/proactive
```

**POST** `/api/proactive`

```bash
# 手动触发主动消息
curl -X POST http://localhost:7860/api/proactive \
  -H "Content-Type: application/json" \
  -d '{"action": "trigger"}'
```

---

## 知识图谱

知识图谱使用 NetworkX 存储实体关系三元组（subject-predicate-object），弥补向量检索无法处理多跳关系推理的缺陷。

### 自动抽取

每轮对话结束后，`GraphRelationExtractor` 会调用 LLM 从对话中抽取实体关系，自动写入图谱。

### 手动查询

```python
from vir_bot.core.memory.graph_store import MemoryGraphStore

store = MemoryGraphStore(persist_path="data/memory/memory_graph.json")

# 添加关系
store.add_relation("user:user1", "likes", "火锅")
store.add_relation("火锅", "属于", "川菜")

# 查询实体的所有关系
edges = store.query_entity("user:user1")

# 多跳查询
paths = store.query_multi_hop("user:user1", max_hops=2)
```

### 配置

```yaml
memory:
  features:
    graph:
      enabled: true
      persist_path: "./data/memory/memory_graph.json"
```

---

## 质量门控与查重

### Quality Gate

写入记忆前的规则引擎 + LLM 二次判断：

| 规则 | 示例 | 处理 |
|------|------|------|
| 时间模糊词 | "我最近好像..." | 拦截，置信度 ×0.3 |
| 情绪化表达 | "我超级超级喜欢！" | 拦截，置信度 ×0.5 |
| 信息不足 | 短于 5 字符 | 拦截，拒绝写入 |
| 纯疑问词 | "什么"、"吗" | 拦截，不写入 |

灰色地带（置信度 0.5-0.7）会调用 LLM 二次判断。

### Write Verifier

写入前与已有记忆做比对：

- **重复检测**：语义相似度 > 0.95 的记忆会被标记为重复
- **冲突检测**：与现有高置信度记忆矛盾时，标记为 `candidate` 待确认

### 用户纠正

用户纠正/否认会触发 `FeedbackHandler`：
- 第一次纠正：置信度降低 70%
- 24 小时内第二次纠正同一事实：自动触发 UPDATE 操作

---

## 测试与验证

### 1. 运行单元测试

```bash
cd "D:/code Project/vir-bot"

# 运行所有测试
uv run pytest tests/ -v

# 只运行特定模块
uv run pytest tests/unit/test_versioning.py -v
uv run pytest tests/unit/lifecycle/ -v
```

**当前测试覆盖**：16 个测试文件，覆盖记忆系统各组件。

### 2. 运行评测系统

```bash
# Mock 模式（快速验证流程）
uv run python -m tests.eval.benchmark --mock

# 真实评测（需要 API Key）
uv run python -m tests.eval.benchmark

# 指定数据集
uv run python -m tests.eval.benchmark --dataset preference_recall knowledge_update
```

**评测指标**：

| 指标 | 权重 | 说明 |
|------|------|------|
| preference_recall | 25% | 偏好召回率 |
| episodic_recall | 20% | 事件回忆率 |
| knowledge_update | 20% | 知识更新准确率 |
| temporal_reasoning | 20% | 时间推理准确率 |
| abstention_accuracy | 15% | 拒答准确率 |

### 3. 测试运行中的服务

```bash
# 首先确保服务已启动
uv run python -m vir_bot.main

# 在另一个终端运行测试脚本
uv run python tests/test_live_service.py
```

### 4. 手动验证清单

```bash
# 1. 教 AI 一个事实
curl -X POST http://localhost:7860/api/chat/ \
  -H "Content-Type: application/json" \
  -d '{"content": "我叫张三", "user_id": "test"}'

# 2. 查询验证
curl "http://localhost:7860/api/chat/" \
  -H "Content-Type: application/json" \
  -d '{"content": "我叫什么名字？", "user_id": "test"}'
# 期望回复包含 "张三"

# 3. 纠正验证
curl -X POST http://localhost:7860/api/chat/ \
  -H "Content-Type: application/json" \
  -d '{"content": "我不叫张三，我叫李四", "user_id": "test"}'

# 4. 再次查询
curl "http://localhost:7860/api/chat/" \
  -H "Content-Type: application/json" \
  -d '{"content": "我叫什么名字？", "user_id": "test"}'
# 期望回复包含 "李四"

# 5. 检查记忆
curl "http://localhost:7860/api/memory/semantic?user_id=test"
```

---

## 常见问题

### Q1: 服务启动失败，提示 "Authorization Required"

**原因**：API Key 未正确设置。

**解决**：
```bash
# 确认环境变量已设置
echo $VIRBOT_OPENAI_KEY

# 如未设置，在 .env 或系统中设置
export VIRBOT_OPENAI_KEY="your-key"
```

### Q2: 语义记忆查询返回空数组

**原因**：
1. `user_id` 不一致（写入和查询用的 ID 不同）
2. 记忆未成功写入
3. API 路径问题

**解决**：
```python
# 直接检查语义记忆文件
import json
with open('data/memory/semantic_memory.json', 'r') as f:
    data = json.load(f)
    print(f"Total records: {len(data.get('records', []))}")
```

### Q3: 纠正后旧记忆仍然存在

**原因**：`versioning.enabled: false`，未启用版本管理。

**解决**：在 `config.yaml` 中设置：
```yaml
memory:
  features:
    versioning:
      enabled: true
```

### Q4: 如何回滚某个功能？

**解决**：在 `config.yaml` 中将该功能设置为 `false`：

```yaml
memory:
  features:
    lifecycle:
      enabled: false  # 关闭即可回退
```

或使用 git 回退：
```bash
git checkout phase6-complete
```

### Q5: 评测分数很低怎么办？

**诊断步骤**：

1. 检查 AI Provider 是否健康：`curl http://localhost:7860/health`
2. 检查记忆是否正确写入：`curl http://localhost:7860/api/memory/`
3. 查看评测详细报告：`cat tests/eval/report.json`
4. 检查配置：`cat config.yaml | grep -A 5 "features:"`

**提升分数的方法**：
- 启用 `reranker` 提升检索相关性
- 启用 `composer` 优化上下文质量
- 启用 `quality_gate` 减少低质量记忆

### Q6: 如何清理测试数据？

```bash
# 通过 API 清空
curl -X DELETE http://localhost:7860/api/memory/

# 或手动删除
rm data/memory/semantic_memory.json
rm -rf data/memory/chroma_db/
rm data/memory/episodic_memory.json
rm data/memory/question_memory.json
rm data/memory/memory_graph.json
```

### Q7: Windows 上 sentence_transformers 导致段错误（segfault）

**原因**：`sentence-transformers` 5.5.0 与 PyTorch CUDA 在 Windows 上存在 DLL 加载冲突。

**表现**：服务在处理第一条消息时崩溃，faulthandler.log 显示 `Windows fatal exception: access violation`。

**解决**：当前代码已自动禁用受影响组件，降级为替代方案：
- CrossEncoder 重排器 → 关键词匹配
- 写入查重器 → 文本匹配
- SentenceTransformer Embedding → Ollama Embedding 或哈希向量

**影响**：记忆检索精度降低，但核心功能正常运行。Linux/Docker 环境不受影响。

---

*文档版本：2.1 — 更新至 8 层架构 + 知识图谱 + 质量门控*
*最后更新：2026-05-30*
*最后更新：2026-04-27*
