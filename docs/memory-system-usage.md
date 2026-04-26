# vir-bot 记忆系统使用文档

## 目录

- [系统概述](#系统概述)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [API 使用指南](#api-使用指南)
- [功能模块详解](#功能模块详解)
- [测试与验证](#测试与验证)
- [常见问题](#常见问题)

---

## 系统概述

vir-bot 记忆系统是一个多层次、渐进式增强的 AI 记忆架构，支持：

| 层级 | 组件 | 用途 |
|------|------|------|
| **短期记忆** | ShortTermMemory | 最近 N 轮对话，滑动窗口 |
| **长期记忆** | LongTermMemory (ChromaDB) | 向量存储，语义搜索 |
| **语义记忆** | SemanticMemoryStore | 结构化事实（用户偏好、身份、习惯） |
| **事件记忆** | EpisodicMemoryStore | 时间线事件记录 |
| **问题记忆** | QuestionMemoryStore | 用户问过的问题索引 |
| **关系图谱** | MemoryGraphStore | 实体关系推理（多跳查询） |

### 增强组件（可开关）

| 功能 | 配置项 | 作用 |
|------|--------|------|
| Re-Ranker | `reranker.enabled` | 对检索结果重排序，提升相关性 |
| Composer | `composer.enabled` | 去重、冲突消解、Token 预算分配 |
| Quality Gate | `quality_gate.enabled` | 拦截低质量记忆写入 |
| Verifier | `verifier.enabled` | 检测重复和冲突 |
| Versioning | `versioning.enabled` | 记忆多版本管理 |
| Graph | `graph.enabled` | 关系图谱推理 |
| Lifecycle | `lifecycle.enabled` | 后台衰减、合并、归档 |

---

## 快速开始

### 1. 安装依赖

```bash
cd "D:\code Project\vir-bot"
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
python -m vir_bot.main
```

看到如下输出表示启动成功：

```
=== vir-bot 0.1.0 启动 ===
AI Provider: openai/deepseek-v4-flash (健康: True)
记忆系统就绪
Wiki 系统已初始化，当前角色: 小雅
Web 控制台: http://0.0.0.0:7860
API 文档: http://0.0.0.0:7860/docs
```

### 4. 开始对话

```bash
# 使用 curl
curl -X POST http://localhost:7860/api/chat/ \
  -H "Content-Type: application/json" \
  -d '{"content": "我叫张三，最喜欢火锅", "user_id": "user1"}'

# 或使用 Python
python -c "
import httpx
resp = httpx.post('http://localhost:7860/api/chat/',
              json={'content': '我叫张三，最喜欢火锅', 'user_id': 'user1'})
print(resp.json())
"
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
    # Phase 3: Re-Ranker（重排序）
    reranker:
      enabled: false          # 建议：先 false，验证后开启
      model: "cross-encoder/ms-marco-MiniLM-L-6-v2"
      top_k: 5

    # Phase 4: Composer（记忆组合）
    composer:
      enabled: false
      max_tokens: 2000      # 分配给记忆的 Token 预算

    # Phase 5: Quality Gate + Verifier
    quality_gate:
      enabled: false          # 拦截低质量记忆
    verifier:
      enabled: false          # 检测重复/冲突

    # Phase 6: Versioning（版本管理）
    versioning:
      enabled: false
      max_versions: 10        # 每个记忆保留的最大版本数

    # Phase 7: Memory Graph（关系图谱）
    graph:
      enabled: false
      persist_path: "./data/memory/memory_graph.json"

    # Phase 8: Lifecycle Manager（生命周期）
    lifecycle:
      enabled: false
      interval_hours: 24       # 后台任务执行间隔
```

### 渐进式启用建议

```bash
# 1. 先启用版本管理（Phase 6 基础）
# config.yaml: versioning.enabled: true

# 2. 再启用质量门 + 验证器（Phase 5）
# config.yaml: quality_gate.enabled: true, verifier.enabled: true

# 3. 启用关系图谱（Phase 7）
# config.yaml: graph.enabled: true

# 4. 最后启用生命周期管理（Phase 8）
# config.yaml: lifecycle.enabled: true

# 5. 可选：Re-Ranker 和 Composer（Phase 3-4）
# config.yaml: reranker.enabled: true, composer.enabled: true
```

**每次开启一个功能后，运行评测验证效果：**

```bash
cd "D:/code Project/vir-bot"
uv run python -m tests.eval.benchmark
```

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
  "character": "小雅"
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
  },
  {
    "memory_id": "c1c78b25-...",
    "namespace": "profile.preference",
    "predicate": "likes",
    "object": "火锅",
    "confidence": 0.94,
    "updated_at": 1777209282.66,
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

---

## 功能模块详解

### Phase 5: Quality Gate（质量门）

**作用**：在记忆写入前检查质量，拦截低质量内容。

**拦截规则**：

| 规则 | 示例 | 处理 |
|------|------|------|
| 时间模糊词 | "我最近好像..." | 拦截，置信度 ×0.3 |
| 情绪化表达 | "我超级超级喜欢！" | 拦截，置信度 ×0.5 |
| 信息不足 | 短于 5 字符 | 拦截，拒绝写入 |
| 纯疑问词 | "什么"、"吗" | 拦截，不写入 |

**启用后效果**：

```python
# 用户输入："我最近好像喜欢吃什么来着..."
# AI 回复："唔...这个嘛～🤔 我还没有存下你喜欢吃的具体东西呢～"
# 记忆系统：不写入（被 Quality Gate 拦截）
```

### Phase 5: Write Verifier（写入验证器）

**作用**：检测重复写入和事实冲突。

| 检测项 | 处理方式 |
|--------|----------|
| 语义重复（相似度 > 0.8） | 标记为 candidate，不直接写入 |
| 事实冲突（同一 predicate 不同值） | 标记为 candidate，等待确认 |
| ADD 操作 | 检查是否已存在相同事实 |
| UPDATE 操作 | 检查是否存在要更新的记录 |
| DELETE 操作 | 检查是否存在要删除的记录 |

### Phase 6: Versioning（版本管理）

**作用**：为语义记忆支持多版本，追踪事实变更历史。

**数据模型新增字段**：

```python
SemanticMemoryRecord(
    memory_id="...",
    predicate="name_is",
    object="张三",           # v1
    # 版本字段
    valid_from=1777209282.65,    # 版本生效时间
    valid_to=None,               # 版本失效时间（None 表示当前有效）
    previous_version_id="...",    # 上一版本 ID
    version_number=2,              # 版本号
    confidence_history=[0.95, 0.88],  # 置信度变化历史
    is_deprecated=False,           # 是否废弃
    deprecation_reason=None,        # 废弃原因
)
```

**示例：用户纠正名字**

```python
# 第一轮：用户说 "我叫张三"
# → 创建 name_is: 张三 (v1, active=True)

# 第二轮：用户纠正 "我不叫张三，我叫李四"
# → 禁用旧版本 (v1: valid_to=now, is_active=False)
# → 创建新版本 (v2: name_is: 李四, previous_version_id=v1)
```

**查询历史版本**：

```python
# 通过 MemoryManager 查询
version_chain = memory_manager.semantic_store.get_version_chain(memory_id)
# 返回：[v2(李四), v1(张三)]
```

### Phase 6: Feedback Handler（反馈处理器）

**作用**：处理用户纠正，自动调整记忆。

**工作流程**：

```
用户纠正："我不叫张三，我叫李四"
    ↓
FeedbackHandler.handle_correction()
    ↓
检查纠正历史（24h 内）
    ↓
┌─────────────┬─────────────────────────────────┐
│ 首次纠正    │ 降低旧记忆置信度 (×0.3)      │
│             │ 标记 deprecated=True              │
└─────────────┴─────────────────────────────────┘
    ↓ （如果 24h 内连续两次）
┌─────────────┬─────────────────────────────────┐
│ 连续纠正    │ 自动生成 UPDATE 操作            │
│             │ 创建新版本 (versioning)         │
└─────────────┴─────────────────────────────────┘
```

### Phase 3: Re-Ranker（重排序）

**作用**：对并行检索结果统一评分和重排序，提升相关性。

**配置**：

```yaml
memory:
  features:
    reranker:
      enabled: true
      model: "cross-encoder/ms-marco-MiniLM-L-6-v2"
      top_k: 5
```

**测试覆盖（12 个测试）**：

| 测试文件 | 测试内容 | 数量 |
|----------|----------|------|
| test_reranker.py | 禁用时返回原结果 | 2 |
| test_reranker.py | 启用标志正确读取 | 1 |
| test_reranker.py | 收集各类记录（语义/事件/问题/长期） | 4 |
| test_reranker.py | 结果更新和排序 | 2 |
| test_reranker.py | 错误处理和边界情况 | 3 |

### Phase 4: Composer（记忆组合）

**作用**：去重 + 冲突消解 + Token Budget 分配。

**三个核心功能**：

| 功能 | 说明 | 配置项 |
|------|------|----------|
| 去重 | 相似度 > threshold 保留高优先级者 | `dedup_threshold: 0.95` |
| 冲突消解 | 同一事实有矛盾时，按策略择优 | `conflict_strategy: "newest_first"` |
| Token Budget | 按优先级截断，不超过 max_tokens | `max_tokens: 2000` |

**优先级计算**：`优先级 = 置信度/重要性 × 时间衰减因子`

**配置**：

```yaml
memory:
  features:
    composer:
      enabled: true
      max_tokens: 2000
      dedup_threshold: 0.95
      conflict_strategy: "newest_first"  # 或 "highest_confidence"
```

**测试覆盖（12 个测试）**：

| 测试文件 | 测试内容 | 数量 | 状态 |
|----------|----------|------|------|
| test_composer.py | 禁用时返回原格式 | 2 | ✅ |
| test_composer.py | 精确匹配去重 | 2 | ✅ |
| test_composer.py | 冲突消解（newest_first / highest_confidence） | 3 | ✅ |
| test_composer.py | Token Budget 截断和全量保留 | 2 | ✅ |
| test_composer.py | 优先级计算（含不同类型记录） | 3 | ✅ |
| test_composer.py | 集成测试（compose 输出、tiktoken） | 2 | ✅ |

**集成测试结果**：

```
✅ Composer 去重功能（通过单元测试验证）
✅ Composer 冲突消解（通过单元测试验证）
✅ Composer Token Budget（通过单元测试验证）
✅ Composer 集成到 RetrievalRouter
```

**运行中的服务验证**：

```bash
# 启用 composer: true 后重启服务
# 1. 写入相似记忆（火锅、火锅、串串）
# 2. 查询 "我喜欢吃什么？" → Composer 去重后只保留高置信度记录
# 3. 写入冲突记忆（喜欢火锅 vs 喜欢日料）
# 4. 查询后 Composer 按冲突策略保留最优记录
# 5. 写入大量记忆触发 Token Budget 截断
```

### Phase 5: Quality Gate（质量门）

**作用**：存储实体间关系，支持多跳推理。

**示例**：

```python
# 添加关系
graph_store.add_relation("user:user1", "likes", "火锅")
graph_store.add_relation("火锅", "属于", "川菜")

# 查询：用户喜欢什么？
results = graph_store.query(subject="user:user1")
# → [("user:user1", "likes", "火锅")]

# 多跳查询：用户喜欢什么菜？
paths = graph_store.query_multi_hop("user:user1", max_hops=2)
# → [["user:user1", "likes", "火锅"], ["火锅", "属于", "川菜"]]
# 推理：用户喜欢川菜（通过火锅关联）
```

### Phase 8: Lifecycle Manager（生命周期）

**作用**：后台任务，自动维护记忆质量。

**三个维护任务**：

| 任务 | 频率 | 作用 |
|------|------|------|
| 衰减降权 | 每天 | 根据时间降低不活跃记忆的置信度 |
| 相似合并 | 每天 | 合并描述同一事实的多条记录 |
| 低置信归档 | 每天 | 将置信度 < 0.1 且 90 天未访问的记忆归档 |

**衰减配置**：

```python
DecayConfig(
    base_decay_rate=0.01,      # 每天衰减率
    importance_factor=0.5,    # 重要性影响（重要性高则衰减慢）
    access_factor=0.3,       # 访问时间影响
    min_confidence=0.1,       # 最低置信度
    archive_threshold=0.1,    # 归档阈值
    delete_threshold=0.05,     # 删除阈值
)
```

---

## 测试与验证

### 1. 运行单元测试

```bash
cd "D:\code Project\vir-bot"

# 运行所有测试
uv run python -m pytest tests/ -v

# 只运行特定模块
uv run python -m pytest tests/unit/test_versioning.py -v
uv run python -m pytest tests/unit/lifecycle/ -v
```

**当前测试覆盖**：

| 测试文件 | 测试内容 | 数量 |
|----------|----------|------|
| test_versioning.py | 版本管理 | 8 |
| test_feedback_handler.py | 反馈处理 | 5 |
| test_quality_gate.py | 质量门 | 5 |
| test_verifier.py | 写入验证 | 4 |
| test_graph_store.py | 关系图谱 | 8 |
| lifecycle/test_decay.py | 衰减算法 | 4 |
| lifecycle/test_merge.py | 记忆合并 | 2 |
| lifecycle/test_janitor.py | 生命周期 | 3 |
| test_composer.py | 记忆组合 | 12 |
| test_reranker.py | 重排序 | 12 |
| integration/ | 集成测试 | 6 |
| **总计** | | **~70** |

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
| **综合分数** | **100%** | 加权平均 |

### 3. 测试运行中的服务

```bash
# 首先确保服务已启动
python -m vir_bot.main

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
git tag phase6-complete  # 如果之前打了 tag
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
```

---

## 总结

| 阶段 | 功能 | 配置项 | 建议顺序 |
|------|------|--------|----------|
| Phase 1 | 测试框架 + 配置开关 | - | ✅ 已完成 |
| Phase 2 | 评测系统 | - | ✅ 已完成 |
| Phase 6 | 版本管理 | `versioning.enabled` | 第 1 步 |
| Phase 5 | Quality Gate + Verifier | `quality_gate` + `verifier` | 第 2 步 |
| Phase 7 | Memory Graph | `graph.enabled` | 第 3 步 |
| Phase 8 | Lifecycle Manager | `lifecycle.enabled` | 第 4 步 |
| Phase 3 | Re-Ranker | `reranker.enabled` | 可选 |
| Phase 4 | Composer | `composer.enabled` | 可选 |

**关键原则**：
1. 每次只启用一个功能
2. 启用后运行评测：`uv run python -m tests.eval.benchmark`
3. 确保分数单调不减
4. 出问题时立即关闭对应开关

---

*文档版本：1.0*
*最后更新：2026-04-26*
