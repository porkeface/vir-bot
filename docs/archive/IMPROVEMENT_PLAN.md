# vir-bot 改进计划 & 进度追踪

**文档创建时间**: 2026-04-21  
**最后更新**: 2026-04-21  
**项目阶段**: Phase 1 → Phase 2 (核心人设系统)

---

## 📊 项目概况

### 当前状态
- ✅ 核心框架搭建完成（FastAPI + ChromaDB + MCP）
- ✅ DeepSeek API 集成正常
- ⚠️ 长期记忆系统仅基于 RAG，人设一致性不足
- ❌ 多平台接入未开始
- ❌ 视觉感知未开始
- ❌ 个性蒸馏未开始

### 核心问题
1. **人设不够稳定** - AI 每次回答的风格和语气不一致
2. **记忆缺乏结构** - 所有对话混在一起，无分类
3. **无单点信任源** - 缺乏"宪法性"的人设定义
4. **Prompt 注入不当** - 直接拼接，无优先级

### 成功指标
- 🎯 问 AI 同样问题 5 次，答案风格一致度 > 80%
- 🎯 能准确记住用户的 3 个核心喜好
- 🎯 不会做出违反人设的事
- 🎯 对话流畅，无生硬感

---

## 🗓️ 分阶段计划

### Phase 2.1: Wiki + 增强 RAG（现在 → 2周）⭐⭐⭐ 优先

**目标**: 建立"宪法性"人设库 + 结构化记忆系统

| 子任务 | 预计时间 | 状态 | 完成日期 |
|-------|---------|------|---------|
| 创建 Wiki 目录结构 | 1 天 | ⬜ 待做 | - |
| 编写示例人设卡 (xiaoya.md) | 1 天 | ⬜ 待做 | - |
| 改进 ChromaDB 数据结构 | 1 天 | ⬜ 待做 | - |
| 实现记忆类型过滤检索 | 1 天 | ⬜ 待做 | - |
| 实现人设提取器 | 1 天 | ⬜ 待做 | - |
| 改进 Prompt 注入逻辑 | 1 天 | ⬜ 待做 | - |
| 集成 Wiki + RAG 混合检索 | 1 天 | ⬜ 待做 | - |
| 端到端测试 + 调优 | 2 天 | ⬜ 待做 | - |

**完成后的代码变化**:
- `data/wiki/` - 新增 Wiki 知识库
- `vir_bot/core/memory/long_term.py` - 增强结构
- `vir_bot/core/memory/wiki.py` - 新增 Wiki 解析器
- `vir_bot/core/pipeline/__init__.py` - Prompt 注入改进
- `vir_bot/core/character/personality.py` - 新增人设提取

---

### Phase 2.2: 测试 & 优化（2-3周后）

**目标**: 验证人设一致性，收集问题，迭代调整

| 子任务 | 内容 |
|-------|------|
| 一致性测试 | 重复问题测试，对比答案 |
| Wiki 内容完善 | 基于测试结果调整人设卡 |
| 记忆优先级调优 | 调整 importance 权重 |
| Prompt 微调 | 优化系统提示词模板 |

---

### Phase 2.3: 多平台接入（4-6周后）

**目标**: 支持 QQ / 微信 / Discord

| 平台 | 方案 | 优先级 | 预计时间 |
|-----|------|-------|---------|
| QQ | go-cqhttp + OneBot v11 | 🔴 P1 | 1-2 周 |
| 微信 | wxpy 或 WeChat-Bot-Framework | 🟠 P2 | 1-2 周 |
| Discord | discord.py 官方库 | 🟠 P2 | 1-2 周 |

---

### Phase 2.4: 视觉感知（6-8周后）

**目标**: 集成摄像头，理解环境并做出反应

| 子任务 | 方案 |
|-------|------|
| ESP32 摄像头集成 | xiaozhi-esp32 + MQTT |
| 图像理解 | Qwen-VL / LLaVA |
| 视觉触发反应 | "看到你进门" → 自动问候 |

---

### Phase 2.5: 个性蒸馏（8-10周后）

**目标**: LoRA 微调，真正的"你的聊天风格"

| 子任务 | 方案 |
|-------|------|
| 数据预处理 | 聊天记录 → Alpaca 格式 |
| LoRA 微调 | Unsloth 或 Llama-Factory |
| 量化部署 | int4 量化到 Pi |

---

## 🎯 第一阶段详细计划

### Phase 2.1: Wiki + 增强 RAG（现在开始）

#### 任务 1.1: Wiki 目录结构创建 (完成时间: 第 1 天)

```
data/wiki/
├── README.md                          # Wiki 说明文档
├── characters/
│   ├── xiaoya.md                      # 小雅人设卡 (示例)
│   ├── template.md                    # 人设卡模板
│   └── _index.md                      # 角色索引
├── relationships/
│   ├── users.md                       # 用户/朋友关系
│   └── events.md                      # 重要关系事件
└── events/
    ├── timeline.md                    # 大事件时间线
    └── milestones.md                  # 里程碑事件
```

**检查清单**:
- [ ] 创建 `data/wiki/` 目录
- [ ] 创建所有子目录
- [ ] 创建各个模板文件

---

#### 任务 1.2: 编写人设卡示例 (完成时间: 第 1-2 天)

**文件**: `data/wiki/characters/xiaoya.md`

内容包括:
- ✅ 基本信息
- ✅ 核心性格（4-5 个关键词）
- ✅ 常用口头禅（5-10 个）
- ✅ 说话风格规则
- ✅ 个人喜好（5 个）
- ✅ 禁忌事项（3-4 个）
- ✅ 对话示例（3-5 个场景）
- ✅ 更新日期

**检查清单**:
- [ ] 文件创建成功
- [ ] 内容完整、具体
- [ ] 对话示例涵盖不同场景

---

#### 任务 1.3: 改进 ChromaDB 数据结构 (完成时间: 第 2-3 天)

**文件**: `vir_bot/core/memory/long_term.py`

改动点:
1. 增强 `MemoryRecord` 数据类
   - 添加 `type` 字段（event/preference/personality/conversation/habit）
   - 添加 `importance` 字段（0.0-1.0）
   - 添加 `timestamp` 字段
   - 添加 `entities` 字段（知识图谱初级版）
   - 添加 `sentiment` 字段（情感分析）

2. 改进 ChromaDB 存储
   - metadata 中存储所有新字段
   - 支持多维度过滤查询

3. 改进检索方法
   - `search()` → 支持按 type/importance 过滤
   - `search_by_type()` → 按类型检索
   - `search_by_entity()` → 按实体检索

**检查清单**:
- [ ] 新增字段不破坏现有数据
- [ ] 支持向后兼容
- [ ] 检索效率不下降
- [ ] 代码测试通过

---

#### 任务 1.4: 实现 Wiki 解析器 (完成时间: 第 3 天)

**文件**: `vir_bot/core/wiki/__init__.py` (新建模块)

类和方法:
```python
class WikiKnowledgeBase:
    async def load_character(name: str) -> CharacterProfile
    async def get_personality_traits() -> dict
    async def get_habits() -> list[str]
    async def get_preferences() -> dict
    async def get_relationships() -> dict
    async def get_timeline_events() -> list[Event]
```

**检查清单**:
- [ ] 能正确解析 Markdown 文件
- [ ] 提取关键字段
- [ ] 支持多角色
- [ ] 返回结构化数据

---

#### 任务 1.5: 实现人设提取器 (完成时间: 第 3-4 天)

**文件**: `vir_bot/core/character/personality.py` (新建或扩展)

类:
```python
class PersonalityExtractor:
    async def extract_from_records(
        records: list[MemoryRecord],
        top_k: int = 10
    ) -> PersonalityTraits
    
    async def extract_from_wiki(
        character_name: str
    ) -> PersonalityTraits
    
    async def merge_traits(
        wiki_traits: PersonalityTraits,
        inferred_traits: PersonalityTraits
    ) -> PersonalityTraits
```

**检查清单**:
- [ ] 能从记忆中提取人格特征
- [ ] 能从 Wiki 中读取
- [ ] 支持合并
- [ ] 返回结构化特征

---

#### 任务 1.6: 改进 Prompt 注入逻辑 (完成时间: 第 4-5 天)

**文件**: `vir_bot/core/pipeline/__init__.py`

改动:
1. 改进 `_build_system_prompt()` 方法
   ```python
   async def _build_system_prompt(self, query: str) -> str:
       # 1. 从 Wiki 获取核心人设
       wiki_traits = await self.wiki.load_character(...)
       
       # 2. 搜索相关记忆（按类型和重要性）
       personality_memories = await self.memory.search(
           query=query,
           filters={"type": ["personality", "habit"]},
           top_k=10,
           sort_by="importance"
       )
       
       # 3. 构建增强的系统提示词
       system = f"""
       你是 {character.name}。
       
       【核心人设（Wiki 定义，必须遵守）】
       {self._format_wiki_traits(wiki_traits)}
       
       【个人习惯与偏好】
       {self._format_memories(personality_memories)}
       
       【相关背景】
       {relevant_rag_results}
       
       【重要提醒】
       ...
       """
       return system
   ```

2. 改进记忆注入函数
   - 按优先级排序
   - 按重要性加权
   - 不超过 token 限制

**检查清单**:
- [ ] Prompt 结构清晰
- [ ] 优先级明确
- [ ] Token 数量控制
- [ ] 测试通过

---

#### 任务 1.7: 集成 Wiki + RAG 混合检索 (完成时间: 第 5 天)

**文件**: `vir_bot/core/memory/memory_manager.py`

新增方法:
```python
async def build_enhanced_context(
    self,
    current_query: str,
    system_prompt: str,
    character_name: str,
    long_term_top_k: int = 5,
) -> tuple[str, list[dict]]:
    """
    增强的上下文构建：Wiki + RAG 混合
    
    1. 从 Wiki 获取人设
    2. 从 RAG 搜索相关记忆
    3. 按优先级合并
    4. 返回增强后的系统提示和对话历史
    """
```

**检查清单**:
- [ ] Wiki 和 RAG 正确合并
- [ ] 优先级逻辑正确
- [ ] 无冗余内容
- [ ] 性能可接受

---

#### 任务 1.8: 测试 & 调优 (完成时间: 第 5-7 天)

**创建测试脚本**: `test_personality_consistency.py`

测试场景:
1. **一致性测试**
   ```python
   questions = [
       "你好，自我介绍一下",
       "你叫什么",
       "你的性格是什么样的",
       "你喜欢什么",
   ]
   
   for q in questions:
       responses = []
       for i in range(5):  # 问 5 次
           r = await ai.chat(q)
           responses.append(r)
       
       # 对比相似度
       similarity = calculate_similarity(responses)
       print(f"一致度: {similarity}%")
   ```

2. **记忆准确性测试**
   ```python
   # 在 Wiki 中设置"喜欢猫"
   # 然后问："你喜欢什么动物"
   # 验证 AI 是否回答"喜欢猫"
   ```

3. **禁忌遵守测试**
   ```python
   # 在 Wiki 中设置"不喜欢冷落"
   # 然后长时间不理它
   # 验证 AI 是否表现出不满
   ```

**检查清单**:
- [ ] 一致性 > 80%
- [ ] 记忆准确率 > 90%
- [ ] 人设遵守率 100%
- [ ] 没有生硬或不自然的表现

---

## 📝 进度追踪表

### 第一阶段 (Wiki + 增强 RAG) 进度

```
第 1 周 (4月21-27日)
├─ [ ] 4月21日: 任务1.1 - Wiki 目录创建
├─ [ ] 4月22日: 任务1.2 - 人设卡编写
├─ [ ] 4月23日: 任务1.3 - ChromaDB 改进
├─ [ ] 4月24日: 任务1.4 - Wiki 解析器
└─ [ ] 4月25日: 任务1.5 - 人设提取器

第 2 周 (4月28-5月4日)
├─ [ ] 4月28日: 任务1.6 - Prompt 注入改进
├─ [ ] 4月29日: 任务1.7 - 混合检索集成
├─ [ ] 4月30日: 任务1.8 - 测试第一部分
└─ [ ] 5月1-4日: 测试 + 调优 + 文档
```

### 关键里程碑

| 里程碑 | 目标 | 完成状态 | 完成日期 |
|------|------|--------|---------|
| ✅ Wiki 框架完成 | 所有文件创建 | ⬜ | - |
| ✅ 代码集成完成 | 所有模块改完 | ⬜ | - |
| ✅ 一致性测试通过 | 一致度 > 80% | ⬜ | - |
| ✅ 第一阶段完成 | Wiki + RAG 正式上线 | ⬜ | - |

---

## 📁 文件清单

### 待创建的新文件

| 文件路径 | 说明 | 优先级 |
|---------|------|-------|
| `data/wiki/README.md` | Wiki 使用说明 | P0 |
| `data/wiki/characters/xiaoya.md` | 小雅人设卡 | P0 |
| `data/wiki/characters/template.md` | 人设卡模板 | P1 |
| `data/wiki/characters/_index.md` | 角色索引 | P2 |
| `data/wiki/relationships/users.md` | 用户关系 | P2 |
| `data/wiki/events/timeline.md` | 事件时间线 | P2 |
| `vir_bot/core/wiki/__init__.py` | Wiki 解析器 | P0 |
| `vir_bot/core/character/personality.py` | 人设提取器 | P0 |
| `test_personality_consistency.py` | 一致性测试脚本 | P1 |

### 待修改的现有文件

| 文件路径 | 改动内容 | 优先级 |
|---------|---------|-------|
| `vir_bot/core/memory/long_term.py` | 增强数据结构，改进检索 | P0 |
| `vir_bot/core/memory/memory_manager.py` | 添加混合检索方法 | P0 |
| `vir_bot/core/pipeline/__init__.py` | 改进 Prompt 注入 | P0 |
| `vir_bot/core/character/__init__.py` | 扩展系统提示词构建 | P1 |

---

## 🚨 风险与对策

| 风险 | 可能性 | 严重性 | 对策 |
|-----|-------|-------|------|
| ChromaDB 结构改变导致现有数据不兼容 | 中 | 高 | 做数据迁移脚本，保留旧数据 |
| Prompt 过长超过 token 限制 | 中 | 中 | 实现分级截断，重要信息优先 |
| Wiki 内容难以维护 | 低 | 低 | 编写明确的编辑指南 |
| RAG 检索不准确 | 中 | 中 | 调整 embedding 模型或搜索权重 |
| 人设提取不稳定 | 中 | 中 | 使用规则引擎替代 AI 推断 |

---

## 📚 参考资源

### 文档
- [ChromaDB 官方文档](https://docs.trychroma.com/)
- [Sentence Transformers](https://www.sbert.net/)
- [OpenAI Prompt Engineering](https://platform.openai.com/docs/guides/prompt-engineering)

### 代码示例
- [向量数据库最佳实践](https://cookbook.openai.com/articles/vector_databases)
- [RAG 系统设计](https://github.com/run-llama/llama_index)

---

## 📞 联系与反馈

- 计划制定人: AI Assistant
- 最后更新: 2026-04-21
- 文档版本: v1.0

如有任何疑问或需要调整计划，请更新此文档。

---

**祝你成功！加油！** 💪✨