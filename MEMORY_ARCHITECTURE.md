# vir-bot 长期记忆架构

## 目标

记忆系统的目标不是“尽量多存聊天记录”，而是让 AI 在多会话、多天、多设备的场景下，能够：

1. 记住稳定的用户事实。
2. 回忆重要的历史事件。
3. 保持角色规则和人设不漂移。
4. 在没有证据时明确表示“不确定”，而不是编造。

这要求我们把“记忆形成、存储、检索、更新、拒答”作为一个完整系统设计，而不是把历史消息直接塞进向量库。

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

## 目标架构

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
                                      | Retrieval Router                            |
                                      | semantic / episodic / procedural / short    |
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

## 记忆层分工

### 1. Procedural Memory

用途：

- 角色设定
- 说话风格
- 行为边界
- 系统规则

当前实现：

- `data/characters/*.json`
- `data/wiki/characters/*.md`

长期要求：

- 保持人工可审阅
- 不允许对话过程直接覆盖
- 可由后台工具或人工更新

这部分适合继续使用传统 Wiki，不适合让 LLM 自行“生长”为主事实源。

### 2. Semantic Memory

用途：

- 用户偏好
- 用户厌恶
- 用户身份信息
- 稳定关系信息
- 长期习惯

示例：

- 用户喜欢火锅
- 用户不喜欢香菜
- 用户来自厦门
- 用户每天早上跑步

目标存储形态：

```json
{
  "memory_id": "uuid",
  "user_id": "u123",
  "namespace": "profile.preference",
  "subject": "user",
  "predicate": "likes_food",
  "object": "火锅",
  "confidence": 0.91,
  "source_text": "我最喜欢吃火锅",
  "source_message_id": "msg_xxx",
  "updated_at": "2026-04-22T16:00:00Z"
}
```

要求：

- 支持幂等更新
- 支持冲突判断
- 支持失效和删除
- 不依赖向量相似度作为唯一读取手段

### 3. Episodic Memory

用途：

- 昨天发生了什么
- 最近聊过什么
- 某次连续对话的结论

示例：

- 昨天用户提到加班到很晚
- 上周用户说准备考研
- 今天用户确认喜欢吃火锅，不喜欢香菜

目标存储形态：

```json
{
  "episode_id": "uuid",
  "user_id": "u123",
  "summary": "用户今天确认喜欢火锅，不喜欢香菜，并提到最近工作很忙。",
  "entities": ["火锅", "香菜", "工作"],
  "start_at": "2026-04-22T15:00:00Z",
  "end_at": "2026-04-22T15:20:00Z",
  "importance": 0.82,
  "source_message_ids": ["m1", "m2", "m3"]
}
```

要求：

- 由原始消息聚合生成，而不是把每条原文都当 episode
- 适合走向量检索和时间排序
- 要和结构化事实层协同，而不是替代结构化事实

### 4. Short-term Memory

用途：

- 当前线程的最近几轮上下文

要求：

- 只承担工作记忆
- 不承担跨会话长期记忆职责

---

## 读写路径

### 写路径

每轮对话结束后，写入流程应分三步：

1. `Raw Conversation Log`
   保留原始用户输入和助手输出，用于审计和离线重建。

2. `Memory Writer`
   使用单独的低成本模型或规则+模型混合方案，从本轮对话中输出记忆操作：

```json
[
  {
    "op": "ADD",
    "memory_type": "semantic",
    "namespace": "profile.preference",
    "predicate": "likes_food",
    "object": "火锅",
    "confidence": 0.91
  },
  {
    "op": "ADD",
    "memory_type": "episodic",
    "summary": "用户今天再次提到喜欢火锅。",
    "importance": 0.72
  }
]
```

3. `Memory Updater`
   负责冲突处理、版本更新、去重、失效标记。

### 读路径

回答前统一执行检索，不依赖关键词触发。

推荐顺序：

1. 解析问题意图
2. 路由到对应记忆层
3. 检索证据
4. 构造回答上下文
5. 加入拒答规则

路由示例：

- “我喜欢吃什么” -> 优先查 `semantic memory`
- “昨天我们聊了什么” -> 优先查 `episodic memory`
- “你的人设是什么” -> 查 `procedural memory`
- 普通延续对话 -> 主要看 `short-term memory`

---

## 为什么不采用 LLM Wiki 作为主记忆

不建议把 LLM Wiki 作为主事实源，原因是：

1. LLM 自动写 wiki 的误写成本高。
2. 冲突合并复杂，难以审计。
3. 一旦模型把错误事实写入 wiki，后续回答会被持续污染。
4. 当前项目的核心问题不在“缺少自动整理”，而在“缺少可靠的事实抽取、更新和检索”。

更合理的位置是：

- 传统 Wiki 作为 `procedural memory`
- LLM 作为 `memory writer` 和 `episode summarizer`
- 结构化存储作为用户事实真相源

---

## 推荐演进路线

### Phase A: 修正当前系统

目标：

- 每轮默认主动检索
- 检索按 `user_id` 隔离
- 未命中时拒绝编造

交付：

- 强化当前 `MemoryManager`
- 维持 ChromaDB 作为过渡层

### Phase B: 引入结构化用户画像

目标：

- 新增 `SemanticMemoryStore`
- 支持 `ADD / UPDATE / DELETE / NOOP`

交付：

- `profile.preference`
- `profile.identity`
- `profile.habit`
- `relationship.*`

### Phase C: 引入会话摘要与事件记忆

目标：

- 从消息日志生成 episode
- 不再把整段对话直接当长期记忆主表示

交付：

- `EpisodeStore`
- session summarizer
- event timeline

### Phase D: 引入记忆写入器

目标：

- 用独立 memory-writer 模型替代大量规则抽取
- 支持冲突解析和事实更新

交付：

- 结构化输出 schema
- writer prompt
- 冲突合并器

### Phase E: 观测与评估

目标：

- 让记忆系统可测量，而不是靠主观感觉

核心指标：

- preference recall
- episodic recall
- false memory rate
- abstention accuracy
- memory update correctness

---

## 落地边界

短期内不建议做的事：

- 不建议把所有记忆都交给向量库
- 不建议让 LLM 直接写主 Wiki
- 不建议用单一 prompt 拼接所有历史
- 不建议把“是否查记忆”绑在特定中文关键词上

应该优先做的事：

- 结构化用户画像
- 事件摘要
- 统一检索路由
- 拒绝编造策略
- 评测基线和回归测试

---

## 当前代码与目标架构的映射

现有模块：

- `vir_bot/core/memory/short_term.py`
- `vir_bot/core/memory/long_term.py`
- `vir_bot/core/memory/memory_manager.py`
- `vir_bot/core/memory/question_memory.py`
- `vir_bot/core/wiki/__init__.py`

建议新增模块：

- `vir_bot/core/memory/semantic_store.py`
- `vir_bot/core/memory/episodic_store.py`
- `vir_bot/core/memory/memory_writer.py`
- `vir_bot/core/memory/retrieval_router.py`
- `vir_bot/core/memory/memory_updater.py`
- `vir_bot/core/memory/evaluation.py`

---

## 结论

长期方案不应该是“继续堆规则修补当前 RAG”。

长期可演进的方向是：

- `传统 Wiki / 角色卡` 负责规则和人设
- `结构化语义记忆` 负责用户事实
- `事件记忆` 负责跨天回顾
- `短期记忆` 负责当前上下文
- `memory writer + updater + retrieval router` 负责把整个系统真正串起来

这条路线复杂度高于“勉强能用”的 patch，但它是长期可维护、可测试、可扩展的方案。
