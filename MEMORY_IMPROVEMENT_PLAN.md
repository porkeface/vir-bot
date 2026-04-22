# vir-bot 记忆系统落地计划

## 文档目的

这份文档不是“怎么把当前 patch 再补一层”，而是把记忆系统从当前实现迁移到长期可演进架构的执行路线图。

目标文档见：[MEMORY_ARCHITECTURE.md](/D:/code%20Project/vir-bot/MEMORY_ARCHITECTURE.md)

---

## 当前结论

当前系统已经有以下基础：

- 短期记忆窗口
- 长期向量记忆
- Wiki / 角色卡
- 主动检索的主链路
- 结构化语义记忆存储
- LLM 记忆写入器与更新器雏形

但它仍不满足“长期记忆系统”的要求，主要缺口是：

1. 事件记忆仍然混在 conversation 里。
2. LLM writer 已接入，但还没有独立的模型路由和质量评估。
3. 问题记忆和部分索引仍是进程内状态，不是持久化存储。
4. 没有正式的 retrieval router。
5. 没有正式的评测基线和回归测试集。

---

## 当前进度快照

已完成：

- `Phase 0` 的主要代码工作
  - 每轮默认主动检索
  - 检索按 `user_id` 过滤
  - 回答加入“不知道就别编造”约束
- `Phase 1` 的核心骨架
  - 新增 `semantic_store.py`
  - 新增结构化语义记忆 API
  - 启动时持久化加载 `semantic_memory.json`
- `Phase 3` 的第一版骨架
  - 新增 `memory_writer.py`
  - 新增 `memory_updater.py`
  - `MemoryManager.add_interaction()` 已切到 writer -> updater -> semantic_store
  - 问句污染语义记忆的问题已加防护

未完成：

- `Phase 1`
  - 结构化记忆去重和冲突更新策略仍需增强
  - 目前只覆盖有限 namespace / predicate
- `Phase 2`
  - 尚未实现 `episodic_store.py`
- `Phase 4`
  - 尚未实现正式 `retrieval_router.py`
- `Phase 5`
  - 尚未建立回归测试基线

---

## 北极星目标

当用户问这些问题时，系统应有稳定表现：

- “我喜欢吃什么？”
- “我昨天说了什么？”
- “你记得我最近在忙什么吗？”
- “如果你不确定，就直接告诉我不确定。”

对应指标：

- `Preference Recall >= 90%`
- `Episodic Recall >= 80%`
- `False Memory Rate <= 5%`
- `Abstention Accuracy >= 90%`

---

## 分阶段路线

## Phase 0: 基线修正

目标：

- 修正当前主链路，避免明显错误。

范围：

- 每轮默认主动检索
- 检索按 `user_id` 过滤
- 回答时加入“不知道就别编造”的约束
- 修复角色 Wiki 文件命名一致性

完成标准：

- 不再依赖“刚才/上次/还记得”等关键词触发检索
- 同一用户记忆不会串到其他用户

状态：

- 核心代码已完成，文档与验证已完成，剩余少量收尾

---

## Phase 1: 结构化语义记忆

目标：

- 把“用户喜欢什么、讨厌什么、来自哪里、平时做什么”从 conversation 中分离出来。

新增模块：

- `vir_bot/core/memory/semantic_store.py`
- `vir_bot/core/memory/memory_updater.py`
- `vir_bot/api/routers/memory.py` 中的 semantic 查询接口

核心能力：

- `ADD`
- `UPDATE`
- `DELETE`
- `NOOP`

建议数据模型：

```python
@dataclass
class SemanticMemoryRecord:
    memory_id: str
    user_id: str
    namespace: str
    subject: str
    predicate: str
    object: str
    confidence: float
    source_text: str
    source_message_id: str | None
    created_at: float
    updated_at: float
    is_active: bool = True
```

需要完成的任务：

1. 定义 profile namespace 规范
2. 增强基于 predicate 的替换和冲突更新
3. 增加失效/删除审计能力
4. 增加更细粒度的 semantic search 排序
5. 完善 API 的调试和管理接口

完成标准：

- “我喜欢吃什么”优先从语义记忆返回
- 不再单靠向量命中自由文本片段

状态：

- 已完成基础实现，仍需增强更新策略和管理能力

---

## Phase 2: 事件记忆与会话摘要

目标：

- 支持稳定回答“昨天/最近/上次聊了什么”。

新增模块：

- `vir_bot/core/memory/episodic_store.py`
- `vir_bot/core/memory/session_summarizer.py`

核心任务：

1. 定义 `EpisodeRecord`
2. 以 session 或固定窗口聚合原始消息
3. 抽取实体、时间、结论、重要性
4. 让 episode 可向量检索、可时间排序

建议数据模型：

```python
@dataclass
class EpisodeRecord:
    episode_id: str
    user_id: str
    summary: str
    entities: list[str]
    start_at: float
    end_at: float
    importance: float
    source_message_ids: list[str]
```

完成标准：

- “昨天我们说了什么”时，优先查 episode，而不是查 conversation 原文
- 最近历史回顾不依赖固定关键词

---

## Phase 3: LLM 记忆写入器

目标：

- 用专门的 writer 替代大量正则抽取。

新增模块：

- `vir_bot/core/memory/memory_writer.py`

职责：

- 输入：最近几轮对话
- 输出：结构化记忆操作

建议输出 schema：

```json
[
  {
    "op": "ADD",
    "memory_type": "semantic",
    "namespace": "profile.preference",
    "subject": "user",
    "predicate": "likes_food",
    "object": "火锅",
    "confidence": 0.93
  }
]
```

需要完成的任务：

1. 设计 writer prompt
2. 限制输出 schema
3. 增加失败回退
4. 接入 `memory_updater`
5. 为 writer 增加独立质量验证集

完成标准：

- 支持多表达方式抽取，而不是只识别固定句式
- 用户偏好更新具备冲突处理

状态：

- 第一版已接入主链路，仍需调优 prompt 和验证质量

---

## Phase 4: 检索路由器

目标：

- 让“查哪类记忆”成为显式逻辑，而不是隐式拼接 prompt。

新增模块：

- `vir_bot/core/memory/retrieval_router.py`

路由示例：

- `preference_query` -> `semantic_store`
- `episodic_query` -> `episodic_store`
- `persona_query` -> `wiki / character card`
- `general_dialog` -> `short_term + semantic + episodic`

需要完成的任务：

1. 定义 query intent taxonomy
2. 实现规则路由
3. 预留升级为模型路由的接口
4. 输出统一 evidence bundle

完成标准：

- 回答“喜欢吃什么”和“昨天聊了什么”时，走不同读取通道

---

## Phase 5: 评测和回归测试

目标：

- 让记忆系统可验证、可回归、可比较。

新增模块：

- `vir_bot/core/memory/evaluation.py`
- `tests/test_memory_semantic.py`
- `tests/test_memory_episodic.py`
- `tests/test_memory_abstention.py`

评测集应覆盖：

- preference recall
- dislike recall
- identity recall
- episodic recall
- conflicting update
- abstention when no evidence

完成标准：

- 每次改记忆系统后，可跑回归测试，而不是靠手工聊天体感验证

---

## 建议实施顺序

按依赖关系，建议这样推进：

1. `Phase 0`
2. `Phase 1`
3. `Phase 4`
4. `Phase 2`
5. `Phase 3`
6. `Phase 5`

原因：

- 先把语义记忆建起来，最先解决“喜欢吃什么”
- 再把路由做出来，保证读取策略稳定
- 然后做事件记忆，解决“昨天说了什么”
- 再用 LLM writer 替换规则写入，提升鲁棒性
- 最后把评测补齐，锁住质量

---

## 与当前代码的关系

当前保留：

- `short_term.py`
- `long_term.py`
- `wiki/`
- `character/`

当前需要逐步降级为过渡层的内容：

- 用 conversation 兼任长期事实来源
- 用正则作为主要事实抽取器
- 用进程内 `questions` 作为长期问题记忆

未来新增主模块：

- `semantic_store.py`
- `episodic_store.py`
- `memory_writer.py`
- `memory_updater.py`
- `retrieval_router.py`
- `evaluation.py`

---

## 风险与控制

### 风险 1

结构化记忆抽取错误，写入错误事实。

控制：

- 加 `confidence`
- 保留 `source_text`
- 低置信度只缓存不生效

### 风险 2

用户偏好变化导致旧事实污染回答。

控制：

- 支持 `UPDATE / DELETE`
- 记录 `updated_at`
- 回答时优先最近有效事实

### 风险 3

检索层混乱，导致语义记忆和事件记忆混用。

控制：

- 引入显式 `retrieval_router`
- 统一 evidence schema

### 风险 4

改造跨度大，短期影响现有可用性。

控制：

- 按阶段落地
- 每阶段保留回退路径
- 每阶段配套最小回归测试

---

## 近期执行建议

下一批代码工作建议集中在：

1. 落 `retrieval_router.py`
2. 新增 `episodic_store.py`
3. 把问题记忆持久化
4. 给 `memory_writer` 补最小回归测试
5. 给 semantic memory 增加人工修正接口

如果这一步不做，系统仍会继续表现为：

- 能记住部分用户事实
- 但对“昨天说了什么”“最近聊过什么”仍不够稳
- 记忆质量仍缺少系统级评估

---

## 文档状态

- 这是长期路线图，不是临时 patch 清单。
- 如果架构调整，先更新 [MEMORY_ARCHITECTURE.md](/D:/code%20Project/vir-bot/MEMORY_ARCHITECTURE.md)，再更新本计划。
