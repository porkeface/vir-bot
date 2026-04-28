# 角色蒸馏方案

**文档版本**: v1.0
**创建日期**: 2026-04-22
**目标**: 从聊天记录自动生成高还原度角色人设卡

---

## 1. 背景与目标

### 1.1 当前状态

vir-bot 目前的人设卡依赖**纯手工编写**（`data/wiki/characters/` 下的 `.md` 文件），需要用户对照模板逐项填写，工作量大且依赖用户的表达能力。不同人写出来的角色卡质量差异巨大，导致蒸馏出的 AI 人格还原度低。

### 1.2 目标

设计一套**半自动化的角色蒸馏流程**：

- **输入**：聊天记录（微信/QQ/Discord 导出，JSON/TXT/HTML）
- **处理**：LLM 分析 + 结构化提取 + 向量评估
- **输出**：可直接使用的 Wiki 人设卡 + SillyTavern JSON 角色卡
- **核心约束**：所有处理在本地完成，不上传原始数据

### 1.3 还原度目标

| 等级 | 描述 | 达标方式 |
|------|------|---------|
| L1 基础 | 说话风格像 | Wiki 人设卡 + 少量对话示例 |
| L2 进阶 | 性格特点像 | Big Five 分析 + 情绪模式提取 |
| L3 高阶 | 细节记忆像 | RAG 长期记忆 + 事件时间线 |
| L4 高度还原 | Turing Test 通过 | LoRA 微调（可选，成本较高） |

---

## 2. 数据输入类型

### 2.1 支持的格式

| 平台 | 导出格式 | 支持状态 | 备注 |
|------|---------|---------|------|
| 微信 PC 版 | HTML | 待实现 | 导出为 HTML 文件 |
| QQ PC 版 | JSON / HTML | 待实现 | 消息管理器导出 |
| Discord | CSV / JSON | 待实现 | Discord Data Download |
| 通用 | JSON / TXT | 已规划 | 自定义字段映射 |

### 2.2 数据质量要求

| 指标 | 最低要求 | 推荐要求 | 最优要求 |
|------|---------|---------|---------|
| 对话轮数 | 500 轮 | 2000 轮 | 5000+ 轮 |
| 场景覆盖 | 2 个 | 5 个 | 10+ 个 |
| 时间跨度 | 1 周 | 1 个月 | 3 个月+ |
| 角色占比 | > 30% | > 50% | > 70% |

**质量判断标准**：

- 目标角色的回复占总消息 30% 以上（噪音太多无法蒸馏）
- 对话包含正常闲聊、情绪表达、话题讨论（不是只有"好的"）
- 无大量平台水印/自动消息污染对话

### 2.3 隐私脱敏（可选）

蒸馏前可选择脱敏处理：

- 人名 → `[朋友A]`、`[家人B]`
- 地名 → `[城市X]`、`[地点Y]`
- 账号/ID → `[账号Z]`
- 日期精确度 → 仅保留月/周

脱敏后的数据仍可有效蒸馏（因为分析的是**说话风格**，不是身份信息）。

---

## 3. 蒸馏方法详解

### 3.1 方法一：LLM 分析蒸馏（核心方案，L1-L3）

**原理**：用强 LLM 对聊天记录进行多维度分析，结构化输出人格特征。

**优势**：成本低、可解释、可迭代、无需 GPU
**劣势**：依赖 LLM 理解能力、有一定幻觉风险

#### 分析维度

```
人格特质（Big Five 延伸）
├── 开放性 Openness：好奇心、创意、思考深度
├── 尽责性 Conscientiousness：计划性、自律、责任感
├── 外向性 Extraversion：社交能量、独处偏好
├── 宜人性 Agreeableness：同理心、信任、合作
└── 情绪稳定性 Neuroticism：情绪波动、抗压性

语言风格
├── 句式偏好：短句/长句/复合句比例
├── 语气词频率：~、呀、嘛、哈哈、emmm...
├── 标点习惯：感叹号/问号频率、省略号使用
├── emoji 使用：频率、类型、场景偏好
├── 称呼习惯：对不同人的叫法
└── 表达密度：信息量/每句话

情感模式
├── 高频情绪：开心/焦虑/愤怒/温柔的表现方式
├── 情绪触发词：什么话题让这个人情绪波动
├── 情绪恢复方式：难过时如何表达和恢复
└── 安慰/关心别人的方式

知识与价值观
├── 经常讨论的话题领域
├── 对某些事件的态度倾向
├── 人生观/爱情观/工作观
└── 幽默方式：冷幽默/自嘲/玩梗/吐槽
```

#### 多轮分析流程

```
第一轮：粗粒度提取
├─ 提取人格 Big Five 评分
├─ 提取说话风格特点（语气词、口头禅、句式）
├─ 识别核心性格（5 个关键词 + 具体表现）
└─ 输出：结构化 JSON v1

第二轮：细粒度提取
├─ 提取情绪模式（正面/负面/触发/恢复）
├─ 提取价值观和兴趣领域
├─ 识别特殊习惯和怪癖
└─ 输出：结构化 JSON v2

第三轮：对话示例生成
├─ 从原始对话中选取 5-10 个代表性场景
├─ 标注触发条件（何时会这样说话）
├─ 保留原文，不改写
└─ 输出：对话示例列表

第四轮：一致性校验
├─ 检查性格描述与对话示例是否一致
├─ 检查口头禅是否真实存在于原文
├─ 标记冲突项供人工确认
└─ 输出：带标注的角色卡草稿
```

### 3.2 方法二：向量嵌入对比（评估蒸馏效果）

**原理**：将蒸馏角色的回复与原始聊天记录做语义相似度对比，量化还原程度。

```
步骤：
1. 原始对话 → embedding（text-embedding-3-small 或本地模型）
2. 蒸馏角色回复（同类问题）→ embedding
3. cosine_similarity(original, distilled) → 分数

评估标准：
- similarity > 0.85：还原度高
- similarity 0.70-0.85：基本还原
- similarity < 0.70：需要重蒸
```

### 3.3 方法三：LoRA 微调（可选，L4 最高还原）

**原理**：用原始聊天记录直接 fine-tune 小模型，让它学会这个人的语言模式。

**适用场景**：蒸馏后 Turing Test 无法通过，且原始数据充足（5000+ 轮）。

| 方案 | 工具 | 显存需求 | 成本 | 推荐度 |
|------|------|---------|------|-------|
| QLoRA 微调 | LLaMA-Factory / Axolotl | 12GB GPU | ¥50-100 | ⭐⭐⭐ |
| DPO 偏好微调 | LLaMA-Factory | 24GB GPU | 中等 | ⭐⭐ |
| 全量微调 | 不推荐 | 80GB+ | 高 | ⭐ |

**不建议作为首选**：成本高、周期长、难以迭代更新。

---

## 4. 完整蒸馏流程

```
阶段1: 数据收集与预处理
│
├─ 1.1 导入聊天记录（支持微信/QQ/Discord 导出）
├─ 1.2 文本清洗
│   ├─ 去除时间戳、平台水印
│   ├─ 过滤系统消息（"xxx 撤回了一条消息"）
│   └─ 过滤非目标角色的消息（群聊场景）
├─ 1.3 对话分段
│   ├─ 识别单轮对话（问-答）
│   └─ 识别多轮对话（话题连贯性）
├─ 1.4 隐私脱敏（可选）
│   ├─ 人名 → [朋友A]
│   ├─ 地名 → [地点X]
│   └─ 账号 → [账号Z]
└─ 1.5 数据统计
    ├─ 对话轮数
    ├─ 消息字数分布
    ├─ 时间跨度
    └─ 话题分布
        │
        ▼
阶段2: LLM 分析蒸馏（核心）
│
├─ 2.1 第一轮粗粒度分析
│   ├─ 输入：清洗后的聊天记录
│   ├─ 提示词：人格分析提示词 v1
│   └─ 输出：Big Five + 说话风格 + 核心性格
│
├─ 2.2 第二轮细粒度分析
│   ├─ 输入：聊天记录 + 第一轮结果
│   ├─ 提示词：情绪模式 + 价值观分析
│   └─ 输出：情感模式 + 特殊习惯 + 价值观
│
├─ 2.3 第三轮对话示例提取
│   ├─ 输入：聊天记录 + 分析结果
│   ├─ 提示词：从原文中选取代表性场景
│   └─ 输出：5-10 个对话示例（保留原文）
│
└─ 2.4 一致性校验
    ├─ 检查性格与示例是否一致
    ├─ 标记冲突项
    └─ 输出：带标注的角色卡草稿
        │
        ▼
阶段3: 角色卡生成
│
├─ 3.1 Wiki Markdown 生成
│   ├─ 映射分析结果 → template.md 格式
│   └─ 输出：data/wiki/characters/{name}.md
│
├─ 3.2 SillyTavern JSON 生成
│   ├─ 映射分析结果 → CharacterCard 格式
│   └─ 输出：data/characters/{name}.json
│
├─ 3.3 补充信息生成
│   ├─ 生成个人喜好描述
│   ├─ 生成禁忌事项描述
│   └─ 生成特殊设定
│
└─ 3.4 版本信息写入
    ├─蒸馏日期
    ├─原始数据条数
    └─分析模型版本
        │
        ▼
阶段4: 评估与迭代
│
├─ 4.1 Turing Test 自测
│   ├─ 对比蒸馏角色 vs 原始对话（同类问题）
│   ├─ 人工打分：1-5 分
│   └─ < 3 分需要重蒸
│
├─ 4.2 向量相似度测试
│   ├─ 计算原始 vs 蒸馏 语义相似度
│   └─ < 0.70 需要补充数据或修正
│
└─ 4.3 迭代修正
    ├─ 补充特定维度的对话数据
    ├─ 修正 AI 理解偏差
    └─ 重新蒸馏或手动修正 Wiki
```

---

## 5. 模块设计

### 5.1 目录结构

```
vir_bot/core/distillation/
├── __init__.py
├── parser/                          # 聊天记录解析器
│   ├── __init__.py
│   ├── base.py                      # Parser 基类
│   ├── wechat.py                    # 微信 HTML 解析
│   ├── qq.py                        # QQ JSON/HTML 解析
│   ├── discord.py                   # Discord CSV/JSON 解析
│   └── generic.py                   # 通用 JSON/TXT 解析
│
├── analyzer/                        # LLM 分析引擎
│   ├── __init__.py
│   ├── extractor.py                 # 结构化人格提取
│   ├── big_five.py                  # Big Five 评分
│   ├── style_analyzer.py            # 语言风格分析
│   ├── emotion_mapper.py            # 情绪模式提取
│   └── dialogue_sampler.py          # 对话示例选取
│
├── generator/                       # 角色卡生成器
│   ├── __init__.py
│   ├── wiki_generator.py            # → data/wiki/characters/*.md
│   ├── card_generator.py            # → SillyTavern JSON
│   └── prompt_templates.py          # LLM 分析提示词模板
│
├── evaluator/                       # 评估模块
│   ├── __init__.py
│   ├── similarity.py                # 向量相似度测试
│   └── turing_test.py               # Turing Test 自测
│
├── pipeline.py                      # 蒸馏流程编排
├── config.py                        # 蒸馏配置
└── cli.py                           # 命令行入口
```

### 5.2 核心类设计

```python
# parser/base.py
class ChatParser(ABC):
    @abstractmethod
    def parse(self, path: str) -> list[DialogueTurn]:
        """解析聊天记录文件，返回对话轮次列表"""

# analyzer/extractor.py
@dataclass
class PersonaProfile:
    summary: str                           # 一句话整体印象
    big_five: dict[str, float]             # Big Five 评分
    speaking_style: SpeakingStyle          # 说话风格
    emotional_patterns: EmotionalPatterns  # 情绪模式
    values: ValueProfile                   # 价值观
    dialogue_examples: list[DialogueExample]  # 对话示例
    taboos: list[str]                      # 禁忌事项
    special_quirks: list[str]              # 特殊习惯

class PersonaExtractor:
    async def extract(self, turns: list[DialogueTurn]) -> PersonaProfile:
        """从对话轮次提取人格画像"""

# generator/wiki_generator.py
class WikiGenerator:
    def generate(self, profile: PersonaProfile, name: str) -> str:
        """将人格画像生成为 Wiki Markdown"""
    def save(self, profile: PersonaProfile, name: str, output_dir: str):
        """保存到 data/wiki/characters/{name}.md"""

# pipeline.py
class DistillationPipeline:
    def __init__(self, ai_provider: AIProvider, config: DistillationConfig):
        ...

    async def run(self, input_path: str, name: str) -> DistillationResult:
        """
        完整蒸馏流程：
        1. 解析聊天记录
        2. 多轮 LLM 分析
        3. 生成角色卡
        4. 评估并输出结果
        """
```

### 5.3 CLI 使用方式

```bash
# 标准蒸馏
python -m vir_bot.core.distillation.cli \
    --input ./data/chat_records/myfriend.json \
    --name "小雅" \
    --output ./data/wiki/characters/

# 完整蒸馏（含评估）
python -m vir_bot.core.distillation.cli \
    --input ./data/chat_records/myfriend.json \
    --name "小雅" \
    --output ./data/wiki/characters/ \
    --evaluate

# 仅解析 + 预览（不生成文件）
python -m vir_bot.core.distillation.cli \
    --input ./data/chat_records/myfriend.json \
    --name "小雅" \
    --dry-run

# 增量更新（基于已有角色卡 + 新对话）
python -m vir_bot.core.distillation.cli \
    --input ./data/chat_records/new_chats.json \
    --name "小雅" \
    --incremental \
    --existing ./data/wiki/characters/小雅.md
```

---

## 6. LLM 分析提示词模板

### 6.1 第一轮：人格与风格分析

```
你是一个专业的人格分析专家。请分析以下聊天记录，提取目标人物的人格特征。

**分析原则：**
- 只分析聊天记录中明确体现的特征，不要过度推断
- 口头禅和语气词必须来自原文，标注来源句子
- 对话示例必须是原文，不要改写
- 如果某个维度数据不足，明确标注"数据不足"

**输出格式（严格按此 JSON 输出，不要添加任何解释）：**
{
  "summary": "一句话描述这个人给你的整体印象（50字以内）",
  "big_five_scores": {
    "openness": {"score": 0-10, "evidence": "原文证据"},
    "conscientiousness": {"score": 0-10, "evidence": "原文证据"},
    "extraversion": {"score": 0-10, "evidence": "原文证据"},
    "agreeableness": {"score": 0-10, "evidence": "原文证据"},
    "neuroticism": {"score": 0-10, "evidence": "原文证据"}
  },
  "core_traits": [
    {"trait": "性格特点", "description": "具体表现", "examples": ["原文例子1", "原文例子2"]}
  ],
  "speaking_style": {
    "avg_sentence_length": "short/medium/long",
    "characteristic_fillers": [{"word": "语气词", "frequency": "high/medium/low", "example": "原文"}],
    "punctuation_habits": "标点使用特点描述",
    "emoji_frequency": "high/medium/low",
    "emoji_types": ["常用的 emoji 类型"],
    "special_expressions": [{"expression": "口头禅", "scenario": "使用场景", "example": "原文"}],
    "greeting_style": "打招呼方式（原文示例）",
    "goodbye_style": "告别方式（原文示例）"
  }
}
```

### 6.2 第二轮：情绪与价值观分析

```
基于以下聊天记录和已有人格分析，请继续提取情绪模式和价值观。

**分析原则：**
- 关注对话中的情感表达和价值判断
- 识别这个人的情绪触发点和恢复方式
- 价值观要从实际对话中推断，不要空洞

**输出格式（严格按此 JSON 输出）：**
{
  "emotional_patterns": {
    "positive_expressions": [
      {"emotion": "开心/兴奋/满足", "expression": "具体说法", "example": "原文"}
    ],
    "negative_expressions": [
      {"emotion": "难过/生气/焦虑", "expression": "具体说法", "example": "原文"}
    ],
    "comforting_style": {"approach": "安慰方式描述", "example": "原文"},
    "sensitive_topics": [
      {"topic": "敏感话题", "reaction": "反应表现", "example": "原文"}
    ]
  },
  "values_and_interests": {
    "frequently_discussed": [
      {"topic": "话题", "frequency": "high/medium/low", "example": "原文"}
    ],
    "life_views": ["人生观要点（来自原文推断）"],
    "humor_style": "幽默风格描述（原文示例）",
    "relationship_style": "人际/亲密关系风格（原文示例）"
  },
  "taboos": [
    {"forbidden": "禁忌行为/话语", "consequence": "后果表现", "example": "原文"}
  ],
  "special_quirks": [
    {"quirk": "特殊习惯/怪癖", "description": "描述", "example": "原文"}
  ]
}
```

### 6.3 第三轮：对话示例选取

```
从以下聊天记录中，选取 5-10 个最能代表这个角色性格的对话场景。

**选取原则：**
- 每个场景要覆盖不同情绪/话题
- 必须保留原始对话，不要改写
- 每个场景标注触发条件和角色表现

**输出格式：**
{
  "dialogue_examples": [
    {
      "scenario": "场景描述（如：随意闲聊、情绪安慰、撒娇、反驳等）",
      "trigger": "触发条件（用户说了什么）",
      "character_behavior": "角色如何表现",
      "dialogue": [
        {"role": "user", "content": "用户说的原文"},
        {"role": "assistant", "content": "角色回复的原文"}
      ]
    }
  ]
}
```

---

## 7. 评估标准

### 7.1 质量评估维度

| 维度 | 权重 | 评估方式 |
|------|------|---------|
| 说话风格还原度 | 30% | 向量相似度 + 人工判断 |
| 性格特点准确性 | 25% | 对话示例一致性校验 |
| 口头禅覆盖率 | 15% | 原文中口头禅出现率 |
| 情绪模式完整性 | 15% | 各情绪类型示例数量 |
| 禁忌事项准确性 | 10% | 冲突对话数量 |
| 特殊习惯识别率 | 5% | 人工标注怪癖数量 |

### 7.2 通过标准

```
L1 基础通过：说话风格还原度 > 0.70
L2 进阶通过：L1 + 性格特点准确性 > 0.60
L3 高阶通过：L2 + 情绪模式完整性 > 0.70
L4 高度还原：Turing Test 通过率 > 70%（盲测）
```

### 7.3 不合格处理

| 问题 | 解决方案 |
|------|---------|
| 对话轮数不足 | 补充更多数据 |
| 口头禅覆盖率低 | 手动添加，标注"人工补充" |
| 性格描述与示例冲突 | 重新分析 + 人工确认 |
| 特定维度数据不足 | 定向补充该场景数据 |

---

## 8. 迭代更新机制

### 8.1 增量更新

蒸馏不是一次性操作，需要随着对话积累持续迭代：

```
触发条件：
├─ 每积累 500 条新对话
├─ 用户明确说"不像我了"
└─ 每 3 个月定期更新

更新流程：
1. 对比新旧对话中的差异
2. 识别新出现的行为模式
3. 更新对应 Wiki 字段
4. 标记"最后更新"时间戳
```

### 8.2 完全重蒸

```
触发条件：
├─ Wiki 频繁被手动修改（> 5 次）
├─ 用户要求"重新蒸馏"
└─ 数据量增加 3 倍以上

操作：
1. 保留旧版本（version_history/）
2. 用新数据重新蒸馏
3. 对比新旧版本差异
4. 人工合并或选择新版本
```

---

## 9. 实施计划

### Phase 1：核心模块（优先级：高）

- [ ] `parser/base.py` + `parser/generic.py`（通用 JSON/TXT 解析）
- [ ] `analyzer/extractor.py`（人格提取，调用 LLM）
- [ ] `generator/wiki_generator.py`（生成 Wiki Markdown）
- [ ] `pipeline.py`（串联流程）
- [ ] `cli.py`（命令行入口）

**预计工作量**：3-5 天

### Phase 2：平台解析器（优先级：中）

- [ ] `parser/wechat.py`（微信 HTML 解析）
- [ ] `parser/qq.py`（QQ 格式解析）
- [ ] `parser/discord.py`（Discord CSV 解析）

**预计工作量**：2-3 天

### Phase 3：评估与迭代（优先级：低）

- [ ] `evaluator/similarity.py`（向量相似度测试）
- [ ] `evaluator/turing_test.py`（Turing Test 框架）
- [ ] 增量更新逻辑

**预计工作量**：2-3 天

### Phase 4：进阶蒸馏（优先级：可选）

- [ ] LoRA 微调集成（QLoRA）
- [ ] 多模态蒸馏（语音 + 文字）

**预计工作量**：5-7 天

---

## 10. 常见问题

### Q1: 聊天记录怎么导出？

**微信 PC 版**：微信设置 → 聊天记录迁移 → 选择聊天 → 导出 HTML

**QQ PC 版**：消息管理器 → 选择联系人 → 导出（JSON 或 HTML）

**Discord**：Settings → Privacy & Safety → Request Data Download → 下载 CSV

**通用格式**：任何 JSON/TXT，只要包含 `[{user, message, timestamp}]` 格式即可。

### Q2: 数据量多少够用？

| 数据量 | 效果 | 说明 |
|--------|------|------|
| < 200 轮 | 勉强可用 | 只能提取粗粒度特征 |
| 500-1000 轮 | 基础可用 | 能提取主要性格和风格 |
| 2000-5000 轮 | 较好 | 覆盖多场景，还原度高 |
| 5000+ 轮 | 优秀 | 可支持 L4 微调 |

### Q3: 蒸馏后的角色多久更新一次？

- **常规检查**：每月一次
- **对话积累**：每 500 条新对话触发一次增量更新
- **完全重蒸**：每 3-6 个月，或用户要求

### Q4: 数据隐私安全吗？

所有处理在本地完成：

- 不上传原始聊天记录到任何外部服务
- LLM 调用使用你配置的 API（DeepSeek/OpenAI）
- 支持隐私脱敏（人名/地名自动替换）
- 原始数据保留在你本地

### Q5: 为什么蒸馏出来"不太像"？

常见原因：

1. **数据质量问题**：对话中对方回复太少（噪音太多）
2. **场景单一**：只有某一类话题（如工作），缺少日常闲聊
3. **数据量不足**：200 轮以下难以还原复杂人格
4. **LLM 幻觉**：分析结果有偏差，需要人工修正关键字段

解决：补充数据 + 手动修正 Wiki 中的关键描述。

---

## 11. 相关文档

- [AI_Robot_Project.md](./AI_Robot_Project.md) — 项目总体方案
- [MEMORY_ARCHITECTURE.md](./MEMORY_ARCHITECTURE.md) — 三层记忆系统设计
- [data/wiki/README.md](./data/wiki/README.md) — Wiki 知识库使用指南
- [data/wiki/characters/template.md](./data/wiki/characters/template.md) — 人设卡编辑模板
- [data/wiki/characters/小雅.md](./data/wiki/characters/小雅.md) — 示例人设卡