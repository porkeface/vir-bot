# vir-bot 记忆系统使用文档

> 架构设计、实施计划、进度追踪见 [ARCHITECTURE.md](./ARCHITECTURE.md)

## 目录

- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [API 使用指南](#api-使用指南)
- [测试与验证](#测试与验证)
- [常见问题](#常见问题)

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

**当前测试覆盖**：~70 个测试，全部通过。

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
```

---

*文档版本：2.0 — 精简自原 memory-system-usage.md，移除与 ARCHITECTURE.md 重复内容*
*最后更新：2026-04-27*
