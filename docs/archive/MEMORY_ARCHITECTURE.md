# vir-bot 长期记忆架构

## 目标

记忆系统的目标不是"尽量多存聊天记录"，而是让 AI 在多会话、多天、多设备的场景下，能够：

1. 记住稳定的用户事实。
2. 回忆重要的历史事件。
3. 保持角色规则和人设不漂移。
4. 在没有证据时明确表示"不确定"，而不是编造。

这要求我们把"记忆形成、存储、检索、更新、拒答"作为一个完整系统设计，而不是把历史消息直接塞进向量库。

---

## 设计原则

1. `角色规则` 和 `用户记忆` 分离。
2. `结构化事实` 和 `自由文本片段` 分离。
3. 每轮对话默认主动检索，不依赖特定关键词触发。
4. 写记忆必须支持 `ADD / UPDATE / DELETE / NOOP`，不能只做 append-only。
5. 所有长期记忆必须可追溯到来源文本、时间戳、用户 ID。
6. 回答前的检索必须按用户隔离，不能混用不同用户的记忆。
7. 查不到时必须允许模型放弃回答，避免幻觉。

---

## 当前已实现架构

```text
                              +----------------------+
                              |   Character Card     |
                              |  SillyTavern JSON    |
                              +----------+-----------+
                                         |
                              +----------v-----------+
                              |   Procedural Memory  |
                              |  Wiki / Rules / SOP  |
                              +----------+-----------+
                                         |
                                         v
+-------------+     +--------------------+--------------------+     +-------------------+
| User Input  +----->  Memory Writer / Updater               |----->| Semantic Memory   |
| Assistant   |     |  ADD / UPDATE / DELETE / NOOP          |      | user profile      |
| Output      |     |  fact extraction + conflict handling   |      | structured store  |
+------+------+     +--------------------+--------------------+      +---------+---------+
       |                                   |                                 |
       |                                   +---------------------------------+
       |                                                                     |
       |                      +-------------------------------+              |
       +--------------------->| Episodic Memory Builder       |------------->|
                              | session summary / event log   |              |
                              +---------------+---------------+              |
                                              |                              |
                                              v                              v
                                      +-------+------------------------------+------+
                                      | Retrieval Router (AI-Powered)               |
                                      | 并行多路检索 + 语义理解 + 规则回退        |
                                      +------------------+--------------------------+
                                                         |
                                                         v
                                      +------------------+--------------------------+
                                      | Response Context Builder                    |
                                      | evidence + constraints + abstention rules   |
                                      +------------------+--------------------------+
                                                         |
                                                         v
                                                   +-----+------+
                                                   | LLM Answer |
                                                   +------------+
```

---

## 已实现模块清单

### 核心模块

| 模块 | 文件 | 状态 | 说明 |
|------|------|------|------|
| ShortTermMemory | `short_term.py` | ✅ 已实现 | 当前会话的最近几轮上下文 |
| LongTermMemory | `long_term.py` | ✅ 已实现 | ChromaDB 向量存储的对话记忆 |
| SemanticMemoryStore | `semantic_store.py` | ✅ 已实现 | 结构化用户事实存储 |
| EpisodicMemoryStore | `episodic_store.py` | ✅ 已实现 | 事件/时间相关记忆 |
| QuestionMemoryStore | `question_memory.py` | ✅ 已实现 | 问题记忆持久化存储 |
| MemoryWriter | `memory_writer.py` | ✅ 已实现 | AI 驱动的事实抽取 |
| MemoryUpdater | `memory_updater.py` | ✅ 已实现 | 冲突处理与更新 |
| RetrievalRouter | `retrieval_router.py` | ✅ 已实现 | AI 语义理解 + 智能路由 |
| MemoryManager | `memory_manager.py` | ✅ 已实现 | 统一管理入口 |

---

## 记忆层分工

### 1. Procedural Memory（程序记忆）

**用途：**
- 角色设定
- 说话风格
- 行为边界
- 系统规则

**当前实现：**
- `data/characters/*.json`
- `data/wiki/characters/*.md`

**要求：**
- 保持人工可审阅
- 不允许对话过程直接覆盖
- 可由后台工具或人工更新

### 2. Semantic Memory（语义记忆）

**用途：**
- 用户偏好（喜欢/讨厌什么）
- 用户身份信息（名字/来自哪里/职业）
- 长期习惯（经常做什么/作息）

**存储形态：**
```json
{
  "memory_id": "uuid",
  "user_id": "web_user",
  "namespace": "profile.preference",
  "subject": "user",
  "predicate": "likes",
  "object": "火锅",
  "confidence": 0.91,
  "source_text": "我最喜欢吃火锅",
  "source_message_id": "msg_xxx",
  "created_at": 1776923138.0,
  "updated_at": 1776923144.0,
  "is_active": true
}
```

**命名空间：**
- `profile.identity` - 身份信息（名字、来自、职业）
- `profile.preference` - 偏好（喜欢、讨厌）
- `profile.habit` - 习惯（经常做、每天做）
- `profile.event` - 事件（提到过）

### 3. Episodic Memory（事件记忆）

**用途：**
- 昨天发生了什么
- 今天聊了什么
- 最近的事件

**存储形态：**
```json
{
  "episode_id": "uuid",
  "user_id": "web_user",
  "summary": "用户说：我喜欢吃香蕉",
  "entities": ["喜好", "香蕉"],
  "start_at": 1776923138.0,
  "end_at": 1776923144.0,
  "importance": 0.5,
  "source_message_ids": ["web_test"],
  "episode_type": "session",
  "is_active": true
}
```

### 4. Question Memory（问题记忆）

**用途：**
- 记录用户问过的问题
- 支持查询"我今天问了什么"

**存储形态：**
```json
{
  "question_id": "uuid",
  "user_id": "web_user",
  "question_text": "我喜欢吃什么",
  "question_type": "preference_query",
  "topic": "preference",
  "answer_text": "根据记忆，你喜欢吃香蕉。",
  "answer_summary": "根据记忆，你喜欢吃香蕉。",
  "timestamp": 1776923138.0,
  "importance": 0.5
}
```

### 5. Long-Term Memory（长期对话记忆）

**用途：**
- 存储对话片段的向量表示（ChromaDB）
- 支持语义搜索历史对话
- 跨会话的长期记忆

**增强字段：**
- `type`: 记忆类型（event/preference/personality/conversation/habit）
- `importance`: 重要性权重 (0.0-1.0)
- `entities`: 实体标签列表（知识图谱初级版）
- `sentiment`: 情感维度（初级情感分析）
- `timestamp`: 时间戳（用于时序推理）

### 6. Short-term Memory（短期记忆）

**用途：**
- 当前线程的最近几轮上下文
- 工作记忆

---

## AI 语义理解架构

### RetrievalRouter - AI 驱动的意图分类

**核心改进：使用大模型理解问题意图，替代硬编码关键词匹配**

```python
class RetrievalRouter:
    """检索路由器 - 使用大模型理解问题意图。"""

    def __init__(
        self,
        semantic_store: SemanticMemoryStore,
        episodic_store: EpisodicMemoryStore,
        question_store: QuestionMemoryStore,
        long_term: LongTermMemory | None = None,
        ai_provider: AIProvider | None = None,  # 新增：AI Provider
    ):
        ...

    async def classify_query_async(self, query: str) -> dict:
        """使用 AI 分类问题意图，失败时回退到规则匹配"""
        # 1. 检查缓存
        # 2. 尝试 AI 分类
        # 3. 失败时回退规则
```

### AI 分类提示词

实际使用的提示词（`retrieval_router.py` 中的 `CLASSIFY_PROMPT`）：

```
你是一个意图分类器。分析用户问题，判断需要查询哪种记忆。

用户问题：{query}

必须以纯JSON格式返回，不要有任何其他内容：
{
    "query_type": "preference",
    "needs_memory_lookup": true,
    "reason": "用户询问偏好"
}

query_type 可选值（必须选一个）：
- "time_query": 时间查询（现在几点、今天几号、现在什么日期等）
- "preference": 查询用户偏好（喜欢/讨厌什么）
- "identity": 查询用户身份（名字/来自哪里/职业）
- "habit": 查询用户习惯（经常做什么/作息）
- "episodic": 查询时间相关事件（昨天/今天/最近发生了什么）
- "question": 查询之前问过的问题
- "conversation": 查询之前的对话内容
- "general": 普通对话，不需要查记忆

needs_memory_lookup: 布尔值，当用户的问题需要查询记忆库时为 true。

输出要求：只输出一个合法的JSON对象，不要 markdown 代码块，不要解释。
```

注意：分类结果中的 `query_type` 主要用于 `retrieve_for_context()` 决定跳过策略（如 `time_query` 直接返回 None）以及为检索结果添加上下文提示。`retrieve()` 方法始终并行检索所有记忆层，不按 `query_type` 路由。

### 分类流程

```text
用户问题
    ↓
RetrievalRouter.classify_query_async()
    ↓
┌─────────────────────────────────┐
│  1. 检查缓存（5分钟TTL）         │
│  2. AI 分类（优先）              │
│     - 调用大模型理解语义         │
│     - 返回 query_type + needs   │
│  3. 规则回退（极简保守）         │
│     - 不做关键词匹配             │
│     - 仅处理空查询等边界情况     │
└─────────────────────────────────┘
    ↓
{"query_type": "preference", "needs_memory_lookup": true}
    ↓
retrieve_for_context() 使用分类结果决定是否跳过检索
    ↓
RetrievalRouter.retrieve() 并行检索所有记忆层
```

注意：AI 分类失败时回退策略非常保守，不做关键词匹配，相信 AI 的语义理解能力。

### 查询类型与记忆层映射

> **注意：** 当前实现不再按类型路由到特定记忆层，而是**并行检索所有记忆层**（语义/事件/问题/长期对话），然后使用 `query_type` 为结果添加上下文提示（hint）。分类结果主要用于 `retrieve_for_context()` 决定是否跳过时间查询、是否强制检索等。

| query_type | 上下文提示 | 示例问题 |
|------------|----------|----------|
| `time_query` | 时间查询，跳过记忆检索 | "现在几点"、"今天几号" |
| `preference` | （这是用户偏好相关的记忆） | "我喜欢吃什么" |
| `identity` | （这是用户身份相关的记忆） | "我叫什么名字" |
| `habit` | （这是用户习惯相关的记忆） | "我平时做什么" |
| `episodic` | （这是时间相关的事件记忆） | "昨天我们聊了什么" |
| `question` | （这是之前问过的问题） | "我今天问了什么" |
| `conversation` | （这是之前的对话记录） | "我们之前聊过什么" |
| `general` | 无特定提示 | 普通对话 |

---

## 读写路径

### 写路径

每轮对话结束后：

```text
User Input + Assistant Output
    ↓
MemoryWriter.extract()  ← AI 驱动的事实抽取
    ↓
MemoryOperation[]
    ├── ADD: 新增事实
    ├── UPDATE: 更新已有事实
    ├── DELETE: 删除过时事实
    └── NOOP: 无操作
    ↓
MemoryUpdater.apply()
    ↓
┌─────────────────────────────────┐
│ SemanticMemoryStore (JSON)      │
│ EpisodicMemoryStore (JSON)      │
│ QuestionMemoryStore (JSON)      │
│ LongTermMemory (ChromaDB)       │
└─────────────────────────────────┘
```

### 读路径

回答前统一执行：

```text
用户问题
    ↓
RetrievalRouter.classify_query_async()  ← AI 语义理解
    ↓
RetrievalRouter.retrieve()
    ↓
┌─────────────────────────────────┐
│ 并行多路检索（不受分类限制）      │
│ - 语义记忆 (SemanticMemory)      │
│ - 问题记忆 (QuestionMemory)      │
│ - 事件记忆 (EpisodicMemory)      │
│ - 长期对话 (LongTermMemory)      │
└─────────────────────────────────┘
    ↓
RetrievalResult.to_context_string()
    ↓
注入系统提示词
    ↓
LLM 生成回答
```

注意：`retrieve()` 始终并行检索所有记忆层，分类结果（`query_type`）仅用于 `retrieve_for_context()` 决定是否跳过（如时间查询）以及为返回的上下文添加提示（hint）。

---

## 持久化存储

### 文件结构

```
data/
├── memory/
│   ├── semantic_memory.json    # 结构化用户事实
│   ├── episodic_memory.json    # 事件记忆
│   ├── question_memory.json    # 问题记忆
│   └── chroma/                 # ChromaDB 向量存储
├── wiki/
│   └── characters/
│       └── 小雅.md             # 角色设定
└── characters/
    └── 小雅.json               # 角色卡
```

### 重启恢复

服务启动时自动加载：
1. `SemanticMemoryStore` 从 JSON 加载所有记录
2. `EpisodicMemoryStore` 从 JSON 加载事件
3. `QuestionMemoryStore` 从 JSON 加载问题
4. `QuestionMemoryIndex` 重建索引
5. `RetrievalRouter` 初始化（带 AI Provider）

---

## 与旧架构的对比

| 特性 | 旧架构 | 新架构 |
|------|--------|--------|
| 意图分类 | 硬编码关键词 | AI 语义理解 + 极简规则回退 |
| 记忆触发 | 特定关键词触发 | 每轮主动检索 |
| 问题记忆 | 仅内存存储 | JSON 持久化 |
| 事件记忆 | 无 | EpisodicMemoryStore |
| 检索策略 | 无 | 并行多路检索（语义+事件+问题+长期对话） |
| 重启恢复 | 部分丢失 | 完全恢复 |

> **注：** 新架构中 `RetrievalRouter` 不再按分类结果路由到特定记忆层，而是对多个记忆层并行检索，分类结果仅用于上下文提示和跳过判断（如时间查询）。

---

## 配置示例

```yaml
# config.yaml
memory:
  short_term:
    window_size: 10

  long_term:
    persist_dir: "./data/memory/chroma"
    collection_name: "vir_bot_memory"

ai:
  provider: "ollama"
  ollama:
    base_url: "http://localhost:11434"
    model: "qwen2.5:7b"
    timeout: 120
```

---

## 未来演进

### Phase F: 记忆评估系统

- preference recall（偏好召回率）
- episodic recall（事件召回率）
- false memory rate（错误记忆率）
- abstention accuracy（拒答准确率）

### Phase G: 多用户隔离增强

- 用户 ID 强校验
- 跨用户记忆隔离测试

### Phase H: 记忆压缩与遗忘

- 自动合并相似记忆
- 低重要性记忆自动降级
- 过期记忆自动清理

---

## 结论

当前架构已实现：

- ✅ 传统 Wiki / 角色卡负责规则和人设
- ✅ 结构化语义记忆负责用户事实
- ✅ 事件记忆负责跨天回顾
- ✅ 问题记忆持久化存储
- ✅ AI 驱动的语义理解与检索路由
- ✅ 统一的 MemoryManager 入口

这是一条长期可维护、可测试、可扩展的路线。
