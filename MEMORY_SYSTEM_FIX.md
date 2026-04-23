# vir-bot 记忆系统修复总结

**修复日期**: 2025年  
**状态**: ✅ 已完成并测试  
**版本**: 记忆系统 v0.2

---

## 问题诊断

### 问题1️⃣：语义记忆被过激清理

**症状**：
- 系统启动时自动删除包含"什么"等疑问词的记忆
- 用户说"我喜欢吃什么，回答我"时，被误写为记忆并随后被清理
- 导致用户记忆库逐渐空化

**根本原因**：
在 `semantic_store.py` 的 `__init__` 方法中无条件调用 `cleanup_invalid_records()`：

```python
# 原代码（第45行）
removed = self.cleanup_invalid_records()
if removed:
    logger.info(f"SemanticMemoryStore cleaned invalid records: removed={removed}")
```

这导致每次应用启动都会扫描整个记忆库，将任何包含疑问词的记录标记为失效。

### 问题2️⃣：AI 缺乏明确的记忆使用指导

**症状**：
- AI 被给予了用户记忆，但没有被明确要求使用它们
- 即使记忆中有"喜欢吃火锅"的记录，问"你还记得我喜欢吃什么吗"时，AI 仍会编造
- AI 倾向于生成通用回答，而不是参考检索到的记忆

**根本原因**：
在 `build_enhanced_system_prompt()` 中：
1. 语义记忆检索逻辑过于严格（仅精确词项匹配）
2. 记忆部分在提示词中的格式不够突出
3. 系统提示词中的指导不够明确，缺少"必须"的强制要求

### 问题3️⃣：MemoryWriter 提示词不够明确

**症状**：
- 用户的提问也被当作事实写入记忆
- "你还记得我喜欢吃什么吗"被写成了事实记忆
- 导致记忆污染

**根本原因**：
`memory_writer.py` 的提示词中没有清晰的示例，说明什么是"提问"而不是"陈述"。

---

## 修复方案

### 修复1：移除初始化时的过激清理 ✓

**文件**: `vir-bot/vir_bot/core/memory/semantic_store.py`

**改动**：
```python
# 移除以下代码（第45-48行）
removed = self.cleanup_invalid_records()
if removed:
    logger.info(f"SemanticMemoryStore cleaned invalid records: removed={removed}")

# 改为仅在手动调用时清理
def cleanup_invalid_records(self) -> int:
    """清理明确无效的记录（仅在手动调用时）"""
    removed = 0
    for record in self._records.values():
        if not record.is_active:
            continue
        # 只清理那些完全是疑问词的记录
        if self._is_pure_question_word(record.object):
            record.is_active = False
            record.updated_at = time.time()
            removed += 1
    if removed:
        self._save()
    return removed

def _is_pure_question_word(self, value: str) -> bool:
    """检查是否是纯疑问词"""
    lowered = value.strip().lower()
    pure_question_words = {"什么", "哪些", "哪个", "吗", "呢", "吧", "么", "啥"}
    return lowered in pure_question_words
```

**效果**：
- ✅ 应用启动时不再自动删除任何记忆
- ✅ 已有的记忆得以保留
- ✅ 减少了非预期的数据丢失

---

### 修复2：改进语义记忆检索逻辑 ✓

**文件**: `vir-bot/vir_bot/core/memory/memory_manager.py`

**新增方法**：`_infer_semantic_namespaces()`

```python
def _infer_semantic_namespaces(self, query: str) -> set[str]:
    """根据查询文本推断相关的语义记忆命名空间"""
    normalized = query.lower()
    namespaces: set[str] = set()

    # 根据查询关键词推断命名空间
    if any(keyword in normalized for keyword in ["喜欢", "讨厌", "爱吃", "吃什么"]):
        namespaces.add("profile.preference")
    if any(keyword in normalized for keyword in ["习惯", "经常", "每天", "平时"]):
        namespaces.add("profile.habit")
    if any(keyword in normalized for keyword in ["名字", "叫", "来自", "哪里"]):
        namespaces.add("profile.identity")
    if any(keyword in normalized for keyword in ["昨天", "最近", "上次", "上周"]):
        namespaces.add("profile.event")

    if not namespaces:
        namespaces.add("profile.preference")
        namespaces.add("profile.habit")
    
    return namespaces
```

**改进的检索策略**：

```python
# 第一步：精确查询（基于词项匹配）
semantic_memories = self.search_semantic_memory(
    user_id=user_id,
    query=current_query,
    top_k=6,
)

# 第二步：如果精确查询无果，基于查询意图扩展搜索
if len(semantic_memories) < 3:
    inferred_namespaces = self._infer_semantic_namespaces(current_query)
    if inferred_namespaces:
        all_matching = self.semantic_store.list_by_user(
            user_id=user_id,
            namespaces=list(inferred_namespaces),
        )
        # 合并结果，去重
        seen_ids = {m.memory_id for m in semantic_memories}
        for record in all_matching:
            if record.memory_id not in seen_ids:
                semantic_memories.append(record)
        semantic_memories = semantic_memories[:6]
```

**效果**：
- ✅ 即使精确词项无匹配，也能基于意图找到相关记忆
- ✅ "我喜欢吃什么"能命中所有偏好记忆，即使措辞不同
- ✅ 减少了"记得没有"的假负例

---

### 修复3：增强系统提示词的记忆使用指导 ✓

**改进的提示词结构**：

```python
# 按命名空间分类展示记忆
memory_sections = []
for ns in sorted(organized.keys()):
    records = organized[ns]
    ns_label = {
        "profile.preference": "【用户偏好】",
        "profile.habit": "【用户习惯】",
        "profile.identity": "【用户身份】",
        "profile.event": "【用户事件】",
    }.get(ns, f"【{ns}】")

    memory_sections.append(ns_label)
    for record in records:
        pred_label = {
            "likes": "喜欢",
            "dislikes": "讨厌",
            "often_does": "经常做",
            "daily_does": "每天做",
            "name_is": "名字是",
            "from": "来自",
        }.get(record.predicate, record.predicate)
        memory_sections.append(f"- {pred_label}：{record.object}")
```

**新增的记忆使用规则**：

```
【记忆使用规则】
- 上述各类记忆（偏好、习惯、身份、事件）都是你对用户的确切了解
- 当用户提及这些记忆相关的话题时（如'我喜欢吃什么'），必须优先从【用户偏好】等记忆中回答
- 如果用户问的是记忆中明确记录的内容，直接使用这些信息回答，不要含糊其辞
- 如果记忆中完全没有该信息，直接坦诚说'我现在不确定'或'我没有记住'，不要编造或猜测
- 在自然交流中，可以适当引用这些记忆来展示你对用户的了解
```

**效果**：
- ✅ AI 有明确的"必须"指导
- ✅ 不知道时被要求坦诚，而不是编造
- ✅ 记忆展示形式更清晰，AI 更容易理解

---

### 修复4：改进 MemoryWriter 的提示词 ✓

**文件**: `vir-bot/vir_bot/core/memory/memory_writer.py`

**核心规则清晰化**：

```
【核心规则】
1. 只抽取用户主动、明确陈述的事实，而非他们的提问。
2. 提问、让你回忆、测试记忆、反问等 → 不生成事实，返回 []。
3. 仅当用户用"我...""我是...""我叫...""我来自..."等明确陈述句时，才抽取。
4. object 不能是纯疑问词（什么、哪些、吗、呢、吧、么、啥）。
5. 不从助手回复中抽取信息，只从用户消息抽取。
6. 每条用户消息最多生成 1-2 条记忆操作。
```

**完善的判断要点**：

```
- "我喜欢..." → 抽取偏好
- "我讨厌..." → 抽取厌恶
- "你还记得我喜欢吃什么吗?" → 不抽取（这是测试性提问）
- "我好像..." / "可能..." → 信息不确定，返回 []
```

**具体示例**：

```
例1 - 清晰偏好：
用户: 我最喜欢吃麻辣烫
输出: [{"op":"ADD",...,"object":"麻辣烫","confidence":0.94}]

例2 - 测试性提问（不抽取）：
用户: 你记得我喜欢吃什么吗
输出: []
```

**效果**：
- ✅ MemoryWriter 能正确区分"陈述"和"提问"
- ✅ 减少了记忆污染
- ✅ 提高了抽取的精准度

---

## 测试验证

### 诊断结果

运行 `debug_memory.py`：

```
📊 记忆统计
  - 总记录数: 2
  - 活跃记录: 1
  - 失效记录: 1

【web_user】
  ✓ [profile.preference] likes: 香蕉 (confidence: 0.93)
  ✗ [profile.preference] likes: 什么 (confidence: 0.88) [已失效]
```

### 修复后的功能测试

运行 `test_memory_fix.py`：

```
[3️⃣] 测试记忆提取和写入...
  测试: '我叫张三' ✓
  测试: '我最喜欢吃火锅' ✓
  测试: '我来自北京' ✓
  测试: '我每天早上都要跑步' ✓

[4️⃣] 验证语义记忆检索...
  查询: '我喜欢吃什么'
    ✓ [profile.preference] likes: 火锅

  查询: '我叫什么名字'
    ✓ [profile.identity] name_is: 张三
    ✓ [profile.identity] from: 北京

  查询: '我每天做什么'
    ✓ [profile.habit] daily_does: 早上都要跑步
```

### 系统提示词输出示例

```
你是一个友好的助手。

【用户偏好】
- 喜欢：火锅

【相关历史问答】
- 用户之前问过：我最喜欢吃火锅
  回答概要：很好呀

【记忆使用规则】
- 上述各类记忆（偏好、习惯、身份、事件）都是你对用户的确切了解
- 当用户提及这些记忆相关的话题时（如'我喜欢吃什么'），必须优先从【用户偏好】等记忆中回答
- 如果用户问的是记忆中明确记录的内容，直接使用这些信息回答，不要含糊其辞
- 如果记忆中完全没有该信息，直接坦诚说'我现在不确定'或'我没有记住'，不要编造或猜测
```

---

## 修复前后对比

| 场景 | 修复前 | 修复后 |
|------|-------|-------|
| **用户问"你还记得我喜欢吃什么吗"** | AI 编造答案或说不记得 | 直接从【用户偏好】回答"火锅" |
| **启动时的记忆**| 记忆逐次减少 | 记忆稳定保留 |
| **记忆检索覆盖率** | 仅精确词项匹配 | 精确 + 意图推断 + 宽泛搜索 |
| **记忆污染** | "什么"等疑问词被当作事实 | 智能区分，不写入提问 |
| **AI 指导** | 模糊（"可以参考记忆") | 明确（"必须从记忆中回答"） |

---

## 关键改进

1. **数据持久性** ✅
   - 移除初始化清理逻辑，记忆不再自动丢失
   - 用户偏好、习惯等关键信息得以保留

2. **检索策略** ✅
   - 三层检索：精确词项 → 意图推断 → 宽泛搜索
   - 大大提高了记忆命中率

3. **AI 行为指导** ✅
   - 提示词中明确要求使用记忆
   - 不知道时明确要求坦诚

4. **记忆抽取质量** ✅
   - MemoryWriter 能正确区分陈述和提问
   - 减少了记忆污染

---

## 使用建议

### 立即行动

1. ✅ **应用补丁**
   ```bash
   # 已修改的文件
   - vir_bot/core/memory/semantic_store.py
   - vir_bot/core/memory/memory_manager.py
   - vir_bot/core/memory/memory_writer.py
   ```

2. ✅ **验证修复**
   ```bash
   python debug_memory.py    # 诊断记忆系统
   python test_memory_fix.py # 完整功能测试
   ```

3. 💬 **测试对话**
   ```
   用户: 我喜欢吃火锅
   （AI 记录了这个偏好）
   
   用户: 你还记得我喜欢吃什么吗？
   （AI 从记忆中回答"火锅"，而不是编造）
   ```

### 后续优化（Phase 2+）

- 实现 `episodic_store.py`（事件记忆）来支持"昨天说了什么"
- 添加事件摘要和时间排序
- 实现明确的 `retrieval_router`，区分不同类型查询的路由
- 建立回归测试基线，锁住记忆系统质量

---

## 故障排查

### Q: 修复后记忆仍然被清除
**A**: 检查是否有其他代码调用了 `cleanup_invalid_records()`。这个方法现在应该仅在需要手动维护时调用。

### Q: AI 仍然不从记忆回答
**A**: 
1. 检查系统提示词是否包含【记忆使用规则】部分
2. 运行 `test_prompt_output.py` 查看实际生成的提示词
3. 确保 `user_id` 被正确传递到 `build_enhanced_system_prompt()`

### Q: "什么"等疑问词仍被写入记忆
**A**: 检查 `MemoryWriter` 的提示词是否已更新。最新版本应该明确标注示例"你记得我喜欢吃什么吗? → 输出: []"

---

## 文件修改清单

- `vir-bot/vir_bot/core/memory/semantic_store.py` ✅
  - 移除初始化清理逻辑
  - 添加 `_is_pure_question_word()` 方法
  - 改进 `_is_invalid_object()` 逻辑

- `vir-bot/vir_bot/core/memory/memory_manager.py` ✅
  - 添加 `_infer_semantic_namespaces()` 方法
  - 改进 `build_enhanced_system_prompt()` 中的语义记忆检索
  - 改进记忆展示格式和 AI 使用指导

- `vir-bot/vir_bot/core/memory/memory_writer.py` ✅
  - 完善提示词中的规则说明
  - 添加更多清晰的示例

- `vir-bot/debug_memory.py` (新建) ✅
  - 记忆系统诊断工具

- `vir-bot/test_memory_fix.py` (新建) ✅
  - 完整的修复验证测试

---

**记忆系统恢复完成！🎉**