# Design: Post-Review Integration Fixes

## 设计原则

- **不改架构**：所有修复都在现有文件内完成
- **向后兼容**：所有新功能仍然通过 feature flag 控制
- **最小改动**：每个修复只改必要的代码，不引入额外复杂度

---

## 修复方案

### 🔴 CRITICAL-1: SQLite 存储是空壳

**现状**：`memory_manager.py:185-195` 创建 `SqliteSemanticMemoryStore` 存入 `self._sqlite_store`，但所有读写仍走 `self.semantic_store`（JSON）。

**方案**：当 `sqlite_store` feature 启用时，将 `self.semantic_store` 替换为 SQLite 实例。

```python
# memory_manager.py __init__ 中，sqlite_store 初始化后：
if self._sqlite_store:
    self.semantic_store = self._sqlite_store  # 替换引用
    # 重新初始化依赖 semantic_store 的组件
    self.memory_updater = MemoryUpdater(
        semantic_store=self.semantic_store,
        enable_versioning=enable_versioning,
        verifier=verifier,
    )
    self.retrieval_router.semantic_store = self.semantic_store
    if self.memory_integrator:
        self.memory_integrator._store = self.semantic_store
```

**风险**：低。只是替换引用，接口兼容。

---

### 🔴 CRITICAL-2: MemoryIntegrator 类型不兼容

**现状**：`MemoryIntegrator.__init__` 接收 `SemanticMemoryStore`，调用其同步 `find_by_predicate`。但 `SqliteSemanticMemoryStore.find_by_predicate` 是 async。

**方案**：让 `MemoryIntegrator.try_integrate` 内部判断 store 类型，异步版用 `await`，同步版直接调用。

```python
async def try_integrate(self, ...):
    if hasattr(self._store.find_by_predicate, '__await__'):
        existing = await self._store.find_by_predicate(...)
    else:
        existing = self._store.find_by_predicate(...)
```

更简洁的方案：统一 `find_by_predicate` 为 async。JSON 版的 `SemanticMemoryStore` 也改为 async（内部同步实现，外面包 async）。这样 `MemoryIntegrator` 可以统一用 `await`。

**选择**：统一为 async，因为 SQLite 版已经是 async 了。

---

### 🔴 CRITICAL-3: Buffer Zone 参数错用

**现状**：`_batch_extract` 把 `"用户: xxx\n助手: xxx"` 全塞进 `user_msg`，`assistant_msg="(批量提取)"`。

**方案**：改用 `MemoryWriter.extract` 的合理调用方式。因为批量提取的对话文本包含多轮，将最后一条作为 user_msg/assistant_msg，其余作为上下文：

```python
async def _batch_extract(self, messages, user_id):
    # 取最后一条作为主对话
    last = messages[-1]
    # 其余作为上下文
    context_lines = []
    for msg in messages[:-1]:
        context_lines.append(f"用户: {msg.user_msg}")
        context_lines.append(f"助手: {msg.assistant_msg}")
    context = "\n".join(context_lines) if context_lines else ""

    operations = await self._writer.extract(
        user_msg=last.user_msg,
        assistant_msg=last.assistant_msg,
        user_id=user_id,
        extra_context=context,  # 如果 extract 支持
    )
```

如果 `MemoryWriter.extract` 不支持 `extra_context` 参数，则将多轮对话格式化后作为 `user_msg`，但 `assistant_msg` 用最后一条实际回复：

```python
operations = await self._writer.extract(
    user_msg="\n".join(f"{'用户' if i % 2 == 0 else '助手'}: {m.user_msg if i % 2 == 0 else m.assistant_msg}" for i, m in enumerate(messages)),
    assistant_msg=messages[-1].assistant_msg,
    user_id=user_id,
)
```

---

### 🟠 HIGH-4: 流式路径不更新叙事摘要

**现状**：`_update_memory_from_content`（line 831）只更新工作记忆，不更新叙事摘要。

**方案**：在 `_update_memory_from_content` 中加上 `_maybe_update_narrative` 调用：

```python
async def _update_memory_from_content(self, msg, content):
    # ... 现有代码 ...
    self._update_working_memory(msg.user_id, msg.content, content)
    asyncio.create_task(self._maybe_update_narrative(msg.user_id))  # 新增
```

---

### 🟠 HIGH-5: 关系阶段硬编码

**现状**：`proactive_service.py:271` 写死 `relationship_stage="acquaintance"`。

**方案**：从 pipeline 的 `_turn_counts` 获取轮数，计算关系阶段。proactive_service 需要能访问 pipeline 的 turn_count。

最简方案：让 proactive_service 自己维护 turn_count（通过 `on_user_message` 通知）。

```python
# proactive_service.py
def on_user_message(self, user_id, message=""):
    # ... 现有代码 ...
    self._turn_counts[user_id] = self._turn_counts.get(user_id, 0) + 1

def _get_relationship_stage(self, user_id):
    turn_count = self._turn_counts.get(user_id, 0)
    if turn_count < 10: return "stranger"
    elif turn_count < 30: return "acquaintance"
    elif turn_count < 80: return "friend"
    else: return "close"
```

---

### 🟠 HIGH-6: 未使用的 import

**方案**：删除 `action_selector.py` 中的 `import time`。

---

### 🟠 HIGH-7: 工作记忆不追踪实体

**方案**：在 `_update_working_memory` 中用简单规则提取实体：

```python
# 从用户消息中提取可能的实体（人名、地名、事物名）
import re
# 中文实体：2-4字的名词短语（简化规则）
entities = re.findall(r'[一-鿿]{2,4}', user_msg)
# 过滤常见停用词
stopwords = {"什么", "怎么", "为什么", "可以", "不是", "但是", "因为", "所以"}
wm.mentioned_entities = [e for e in entities if e not in stopwords][-5:]
```

---

### 🟠 HIGH-8: 图搜索边不去重

**方案**：在 `_search_graph_activated` 返回前去重：

```python
seen = set()
unique_edges = []
for edge in edges:
    key = (edge.subject, edge.predicate, edge.object)
    if key not in seen:
        seen.add(key)
        unique_edges.append(edge)
return unique_edges[:top_k]
```

---

### 🟠 HIGH-9: 死代码 `_build_batch_prompt`

**方案**：删除 `buffer_zone.py` 中的 `_build_batch_prompt` 方法（line 188-217）。

---

### 🟠 HIGH-10: 时间段逻辑不清晰

**方案**：重写 `_get_time_context` 的分支，让 22-24 有独立描述：

```python
if 0 <= hour < 6:
    return "现在是深夜。说话简短温柔..."
elif 6 <= hour < 9:
    return "现在是早上..."
elif 9 <= hour < 12:
    return "现在是上午..."
elif 12 <= hour < 14:
    return "现在是中午..."
elif 14 <= hour < 18:
    return "现在是下午..."
elif 18 <= hour < 22:
    return "现在是晚上..."
else:  # 22-24
    return "现在是深夜。说话简短温柔，像要睡觉了的状态。适合低语、晚安。"
```

---

### 🟡 MEDIUM-11: snapshot 有副作用

**方案**：将 `_decay_all()` 从 `snapshot()` 中移出，改为定时调用或在事件驱动时调用。

```python
def snapshot(self) -> DriveSnapshot:
    """获取当前驱动力快照（只读）。"""
    return DriveSnapshot(...)  # 不再调用 _decay_all

def tick(self):
    """定期调用，执行衰减。"""
    self._decay_all()
```

---

### 🟡 MEDIUM-12: SQLite search/list_by_user 无并发保护

**方案**：给 `search` 和 `list_by_user` 加 `asyncio.Lock`：

```python
async def search(self, user_id, query, top_k=5):
    async with self._lock:
        return self._search_sync(user_id, query, top_k)

async def list_by_user(self, user_id, namespace=None, limit=100):
    async with self._lock:
        return self._list_by_user_sync(user_id, namespace, limit)
```

注意：这会改变方法签名（sync → async），需要检查调用方。

---

### 🟡 MEDIUM-13: 补充 AI 味词汇

**方案**：在 `ANTI_AI_PHRASES` 末尾追加：

```python
"从某种程度上来说",
"这是一个值得思考的问题",
"让我们来看看",
"你提到的这一点很重要",
"根据我的理解",
"从XX角度来看",
"不可否认",
"事实上",
"坦白说",
"说实话",
```

---

### 🟡 MEDIUM-14: hasattr 检查私有方法

**方案**：改为检查 quality_gate 是否存在：

```python
if self.memory_writer._quality_gate is not None:
```

或在 MemoryWriter 上加一个公开的 `has_quality_gate()` 方法。

---

### 🟡 MEDIUM-15: 关系阶段阈值不可配置

**方案**：在 pipeline config 或 character extensions 中配置：

```python
# 从 character.extensions 读取，有默认值
thresholds = self.character.extensions.get("relationship_thresholds", {})
stranger_max = thresholds.get("stranger", 10)
acquaintance_max = thresholds.get("acquaintance", 30)
friend_max = thresholds.get("friend", 80)
```

---

## 不改的部分

- `drive_system.py` 的 5D 驱动力逻辑本身没问题
- `action_selector.py` 的评分逻辑本身没问题
- `graph_store.py` 的 BFS 激活扩散逻辑本身没问题
- `memory_integrator.py` 的 LLM 整合逻辑本身没问题

这些模块的**逻辑**是对的，只是**集成**有问题。
