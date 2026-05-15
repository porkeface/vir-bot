# 角色蒸馏系统改造规划

**文档版本**: v1.0
**创建日期**: 2026-05-15
**基于**: 当前 Pipeline 代码审计 + 学术研究 + 开源生态调研
**前置文档**: [DISTILLATION_PLAN.md](./DISTILLATION_PLAN.md)（v1.0, 2026-04-22）

---

## 1. 现状评估

### 1.1 当前实现

现有蒸馏流水线位于 `vir_bot/core/distillation/`，核心流程：

```
聊天文件 → GenericParser → DialogueTurn[] → PersonaExtractor(4轮LLM) → WikiGenerator → Markdown
```

已实现的模块：

| 模块 | 状态 | 质量 |
|------|------|------|
| `pipeline.py` 流水线编排 | ✅ 已实现 | 能跑通，但有结构性缺陷 |
| `parser/generic.py` 通用解析器 | ✅ 已实现 | 支持 JSON/NDJSON/TXT |
| `analyzer/extractor.py` 人格提取 | ✅ 已实现 | 4轮LLM，有明显瓶颈 |
| `generator/wiki_generator.py` 文档生成 | ✅ 已实现 | 输出格式合理 |
| `prompt_templates.py` 提示词模板 | ✅ 已实现 | 英文 prompt，保守原则 |
| `cli.py` 命令行入口 | ✅ 已实现 | 功能完整 |
| `api/routers/distillation.py` Web API | ✅ 已实现 | 上传/启动/状态/下载/WebSocket |
| `api/static/distillation/index.html` Web UI | ✅ 已实现 | 基础可用 |
| 微信/QQ/Discord 解析器 | ❌ 只注册未实现 | 空壳 |
| `CardGenerator` SillyTavern JSON 输出 | ❌ 只注册未实现 | 空壳 |
| 评测模块（similarity/turing_test） | ❌ 未实现 | 空壳 |
| 增量蒸馏 `--incremental` | ❌ 参数预留 | 空壳 |

### 1.2 核心问题（代码审计发现）

**问题 1：上下文窗口截断 — 最致命**

```python
# extractor.py:202-208
if len(dialogue_text) > self.max_chunk_chars:  # 默认 40,000 字符
    dialogue_text = dialogue_text[:self.max_chunk_chars]
```

直接截断到前 40k 字符。5000 轮对话轻松超过 20 万字符，只喂了不到 1/5。角色的低频但重要特质（特定场景反应、偶尔的习惯）会因截断丢失。这不是"信息不够"的问题，是系统性偏差——LLM 只能看到对话前段。

**问题 2：4 轮之间没有真正的迭代**

Round 4 一致性校验发现冲突后只存入 `raw_notes`，不回过头修正前 3 轮的提取结果。校验是摆设。

**问题 3：说话风格靠 LLM 猜，不靠程序统计**

`SpeakingStyle` 定义了 `sentence_length_avg`、`filler_words`、`punctuation_habits` 等字段，但提取全靠 LLM 一句话概括。句子平均长度、语气词频率、emoji 使用率这些完全可以从原始数据直接统计，比让 LLM 猜准确得多。

**问题 4：评估指标自欺欺人**

```python
# pipeline.py:293-317
# Jaccard similarity between source tokens and distilled persona tokens
score = 0.5 * jaccard + 0.5 * weighted
```

Jaccard 重叠度只能衡量"蒸馏结果是否包含源数据中的词汇"，完全不能衡量"角色还原度"。说话风格的关键在于语气、节奏、反应模式，不是词汇重叠。

**问题 5：Big Five 打分缺乏可信度**

LLM 给大五人格打 0.0-1.0 分数，但没有校准基准、没有置信度指标。聊天记录本身不适合精确量化人格——微信群里表现的外向性 ≠ 真实外向性。

### 1.3 当前还原度评级

| 维度 | 还原效果 | 原因 |
|------|---------|------|
| 说话风格 | 中等 | LLM 能捕捉大方向，缺少统计验证 |
| 性格大方向 | 中等 | Big Five 打分参考价值有限 |
| 情绪模式 | 较好 | 触发词和恢复行为 LLM 擅长提取 |
| 价值观/禁忌 | 较好 | LLM 的强项 |
| 语言细节（口癖、标点、emoji） | 差 | 应该用统计方法而不是 LLM 猜 |
| 场景覆盖 | 差 | 截断导致后段对话丢失 |
| 一致性 | 差 | Round 4 校验结果没有回流修正 |

**综合评级：L1~L2 之间**（说话风格大方向像，但细节和场景覆盖不足）

---

## 2. 研究调研结论

### 2.1 开源生态：没有现成方案

搜遍 GitHub、学术论文、SillyTavern 社区，**没有一个开源项目能从聊天记录直接蒸馏出角色卡**。这是真实的生态空白。

现有工具对比：

| 工具 | Stars | 输入 | 输出 | 与 vir-bot 的关系 |
|------|-------|------|------|-------------------|
| [fount](https://github.com/steve02081504/fount) | 698 | 手动描述 | ST 角色卡 | 运行时框架，不做蒸馏 |
| [Nika-Character-Studio](https://github.com/HiUnikitty/Nika-Character-Studio) | 198 | 手动描述 | ST 角色卡 | 一键生成，不做聊天分析 |
| [airole](https://github.com/easychen/airole) | 116 | 图片 | ST 角色卡 | 图片→角色，不做聊天分析 |
| [lorecard](https://github.com/bmen25124/lorecard) | 73 | URL/Wiki | 角色卡+Lorebook | 从网页提取，不做聊天分析 |
| [ChatHaruhi](https://github.com/LC1332/ChatHaruhi) | - | 角色描述 | RAG+Prompt 角色扮演 | 可参考其检索增强方法 |

**结论**：vir-bot 的蒸馏方向是有价值的，没有捷径可抄。

### 2.2 学术界共识（2024-2025）

#### 关键论文

| 论文 | 会议 | 核心发现 | 对 vir-bot 的意义 |
|------|------|---------|-------------------|
| Character-LLM (arXiv:2310.10158) | EMNLP 2023 | "经验培养"：把角色特征转化为训练数据做 LoRA 微调，比纯 prompt 效果好 | 微调 > Prompt，是长期方向 |
| CharacterBot / CharLoRA (arXiv:2502.12988) | ACL 2025 Findings | 通用风格专家 + 任务专家分离的 LoRA 变体 | LoRA 微调的新范式 |
| RoleLLM (arXiv:2310.00746) | - | 四阶段框架：角色档案→指令生成→角色提示→角色条件微调 | 训练数据构造方法 |
| InCharacter (arXiv:2310.17976) | ACL 2024 | 心理量表式面试评测，80.7% 人格对齐 | 评测方法论 |
| Generative Agents (arXiv:2304.03442) | UIST 2023 | Memory Stream + Retrieval + Reflection | 记忆架构金标准 |
| LLMs Can Infer Personality (arXiv:2405.13052) | 2024 | LLM 能从自由对话中推断大五人格 | 验证了 LLM 提取方向的可行性 |

#### RAG vs LoRA 共识

多篇论文一致结论：**Fine-tune for style, RAG for knowledge**。

| 维度 | RAG | LoRA 微调 |
|------|-----|----------|
| 人格一致性 | 中等（依赖检索质量） | 高（烧进权重） |
| 语气/风格匹配 | 低~中 | 高 |
| 知识更新 | 容易（更新文档） | 需要重新训练 |
| 前置成本 | 低 | 高 |
| 推理延迟 | 较高（检索步骤） | 较低 |
| 最佳用途 | 事实性知识、事件记忆 | 语气、风格、行为模式 |

**最佳实践**：LoRA 微调负责风格/语气/行为模式，RAG 负责事实性知识/事件记忆/上下文。两者互补。

### 2.3 SillyTavern 社区最佳实践

角色卡设计核心洞察：

- **Description 字段最重要**（每轮都注入 prompt），长度 200-2000 tokens
- **First Message 决定输出风格**——模型会 mirror 它的语气和长度
- **Example Dialogue** 用 `<START>` 标签分隔，展示说话模式
- Character Card V2 规范支持 `system_prompt`、`character_book`（lorebook）、`extensions`
- 社区常用格式：W++ 结构化伪代码 / AliChat 对话驱动 / 纯散文

---

## 3. 改造方案：三个层次

### 层次一：修好当前 Pipeline

**目标**：让现有 4 轮 LLM 提取真正可靠地工作
**周期**：1~2 周
**前置**：无

#### 3.1.1 分块 + 合并（解决截断问题）

```
聊天记录（20万字符）
  │
  ├── Chunk 1（前500轮）→ Round1-3 提取 → Profile_1
  ├── Chunk 2（501-1000轮）→ Round1-3 提取 → Profile_2
  ├── Chunk 3（1001-1500轮）→ Round1-3 提取 → Profile_3
  └── ...
  │
  └── Merge Round：LLM 合并所有 Profile → 最终 PersonaProfile
```

实现要点：
- 按对话轮数分块（每块 300~500 轮），不是按字符截断
- 每块独立跑 Round 1~3
- 新增 Round 0（Merge）：把多块结果合并，发现矛盾时取"多块一致"的结论
- 合并 prompt 需要明确指令：当多块结论冲突时如何处理

#### 3.1.2 Round 4 校验回流

当前 Round 4 只记录冲突不修正。改造为：

```
Round 4 输出: {"conflicts": [...], "validated_persona": {...}}
  │
  ├── 如果 conflicts 为空 → 直接使用 validated_persona
  └── 如果 conflicts 不为空 →
        ├── 对每个冲突字段生成修正 prompt
        ├── 调用 LLM 修正有冲突的字段
        └── 合并修正结果到最终 profile
```

#### 3.1.3 增量蒸馏

支持"已有角色卡 + 新聊天记录 → 更新角色卡"：

```
输入: existing_profile.md + new_chats.json
  │
  ├── 解析 new_chats → new_turns
  ├── 从 existing_profile 提取当前人格特征
  ├── 对 new_turns 跑 Round 1~3
  ├── Merge Round：对比新旧结论
  │     ├── 一致的特征 → 保持
  │     ├── 新发现的特征 → 追加
  │     └── 矛盾的特征 → 标记为"演变"，附时间戳
  └── 输出: updated_profile.md（带版本历史）
```

#### 3.1.4 评估指标替换

用 LLM-as-judge 替换 Jaccard：

```
评测流程:
  1. 从角色卡提取 5~10 个关键特征（语气、情绪反应、价值观等）
  2. 对每个特征构造一个测试场景
  3. 让 LLM 以角色卡为 system prompt 回复测试场景
  4. 让另一个 LLM（judge）判断回复是否符合特征
  5. 输出各维度得分（0~1）+ 总分
```

参考 InCharacter（ACL 2024）的心理量表式面试方法。

---

### 层次二：统计 + LLM 混合提取

**目标**：各取所长——程序做统计，LLM 做推理
**周期**：3~4 周
**前置**：层次一完成

#### 3.2.1 程序统计层（新增模块）

从原始聊天记录直接计算，不依赖 LLM：

```python
class StyleAnalyzer:
    """从 DialogueTurn 列表中统计说话风格特征"""

    def analyze(self, turns: List[DialogueTurn]) -> StyleStats:
        return StyleStats(
            # 句子长度
            sentence_length_mean=self._calc_sentence_lengths(turns),
            sentence_length_median=...,
            short_sentence_ratio=...,  # <10字的比例

            # 语气词频率
            filler_words=self._count_filler_words(turns),
            # → {"哈哈": 45, "嗯": 32, "emmm": 12, "~": 89, ...}

            # 标点习惯
            punctuation_stats=self._calc_punctuation(turns),
            # → {"exclamation_rate": 0.15, "question_rate": 0.08, "ellipsis_rate": 0.12, ...}

            # emoji 使用
            emoji_stats=self._count_emojis(turns),
            # → {"total": 120, "top": ["💕": 23, "😊": 18, ...], "rate_per_msg": 0.3}

            # 称呼方式
            calling_conventions=self._extract_calling(turns),
            # → {"对方": "宝贝", "自称": "我"}

            # 活跃时间段
            active_hours=self._calc_active_hours(turns),
            # → {"peak": [21, 22, 23], "low": [3, 4, 5]}

            # 回复速度（如果有时间戳）
            reply_speed=self._calc_reply_speed(turns),
        )
```

#### 3.2.2 话题聚类（新增模块）

```python
class TopicClusterer:
    """用 embedding 模型做话题聚类"""

    def cluster(self, turns: List[DialogueTurn], n_clusters: int = 10) -> List[TopicCluster]:
        # 1. 对每条消息做 embedding（text2vec-chinese 或 BGE）
        # 2. K-Means / HDBSCAN 聚类
        # 3. 每个聚类用 LLM 生成话题标签
        # 4. 返回: [{topic: "音乐", count: 45, keywords: [...], example_msgs: [...]}, ...]
```

#### 3.2.3 融合层

```
程序统计 → StyleStats（精确数据）
LLM 分析 → PersonaProfile（推断数据）
  │
  └── Fusion:
        ├── SpeakingStyle 填入 StyleStats（确定性数据）
        ├── 大五人格保留 LLM 输出，但附加置信度
        ├── 情绪模式/价值观/禁忌保留 LLM 输出
        ├── 程序验证 LLM 输出与统计是否矛盾
        │     例：LLM 说"说话简短"，但统计显示平均句长 30 字 → 标记矛盾
        └── 对话示例：优先选统计特征最突出的消息
```

#### 3.2.4 话题-人格关联分析

```
话题聚类结果 × 情绪分析 → 话题-情绪关联矩阵
  例：
  - 聊"工作"时 → 60% 焦虑, 20% 抱怨, 20% 平静
  - 聊"游戏"时 → 80% 兴奋, 15% 抱怨, 5% 平静
  - 聊"感情"时 → 50% 开心, 30% 害羞, 20% 担忧
```

这比让 LLM 一句话概括"情绪模式"精确得多。

---

### 层次三：LoRA 微调人格

**目标**：从"描述角色"到"成为角色"——质变
**周期**：2~3 个月
**前置**：层次一完成 + 足够的干净聊天数据（2000+ 轮）

#### 3.3.1 训练数据构造

参考 RoleLLM（arXiv:2310.00746）的四阶段方法：

```
阶段 A：风格对话对
  聊天记录 → 清洗 → (context, response) 对
  - 保留原始回复作为 target
  - 去除系统消息、自动回复、表情包等噪音
  - 按场景分类（闲聊/安慰/吵架/撒娇/...）

阶段 B：指令对
  从角色卡生成问答对（RoleLLM 的 RoCIT 方法）
  - "你今天心情怎么样？" → 以角色风格回复
  - "你对加班怎么看？" → 以角色价值观回复
  - "用一句话形容你自己" → 以角色自我认知回复

阶段 C：场景对
  不同场景下的反应模式
  - 构造边界场景（禁忌触发、情绪转折、意外事件）
  - 让 LLM 以角色卡为参考生成回复
  - 人工审核筛选
```

#### 3.3.2 LoRA 训练

参考 CharacterBot/CharLoRA（ACL 2025 Findings）：

```
基座模型: Qwen2.5-7B（中文场景推荐）或 Llama-3-8B

训练配置:
  - LoRA rank: 16~64
  - LoRA alpha: 32~128
  - target_modules: q_proj, v_proj, k_proj, o_proj
  - epochs: 3~5
  - learning_rate: 2e-4

训练任务（CharLoRA 思路）:
  Task 1: 风格预训练 — 在对话对上做 SFT，学习语言模式
  Task 2: 指令跟随 — 在问答对上做 SFT，学习角色认知
  Task 3: 场景反应 — 在场景对上做 SFT，学习行为模式
```

工具链：
- 训练框架：LLaMA-Factory 或 Unsloth（消费级 GPU 可跑）
- PEFT：HuggingFace PEFT 库
- 量化：QLoRA（4-bit 量化 + LoRA，8GB VRAM 可跑 7B 模型）

#### 3.3.3 推理集成

```
用户输入
  │
  ├──→ RAG 检索层（记忆系统）
  │     ├── 短期记忆：最近 N 轮对话
  │     ├── 语义记忆：相关事实
  │     ├── 情景记忆：相关事件
  │     └── 图记忆：实体关系
  │
  ├──→ System Prompt（角色卡 + Wiki）
  │
  └──→ LoRA 模型推理
        ├── 基座模型 + LoRA adapter
        ├── 注入 RAG 检索结果
        └── 输出：以角色风格回复
```

#### 3.3.4 质量保障

参考 InCharacter（ACL 2024）的评测方法：

```
评测流程:
  1. 选择 14 个心理量表维度（大五 × 30 facets 子集）
  2. 对每个维度设计 3~5 个面试问题
  3. 让角色模型回答这些问题
  4. 用 AI rater 对回答打分
  5. 与参考人格对比，计算对齐度

目标：人格对齐度 ≥ 80%（InCharacter 论文中 SOTA 为 80.7%）
```

---

## 4. 与当前架构的兼容性

vir-bot 的 8 层记忆系统已经为改造打好了基础：

| 当前层 | 状态 | 改造影响 |
|--------|------|---------|
| Layer 1 短期记忆 | ✅ | 不变 |
| Layer 2 检索路由 | ✅ | 需要加 LoRA 推理路径 |
| Layer 3 响应生成 | ✅ | 需要支持 LoRA adapter 加载 |
| Layer 4 记忆写入 | ✅ | 不变 |
| Layer 5 版本管理 | ✅ | 不变 |
| Layer 6 混合存储 | ✅ | 不变 |
| Layer 7 生命周期 | ✅ | 不变 |
| Layer 8 评测 | ✅ | 需要加人格评测指标 |
| 蒸馏 Pipeline | ✅ | 大改（层次一+二） |
| LoRA 训练模块 | ❌ 新增 | 层次三 |
| 统计分析模块 | ❌ 新增 | 层次二 |

RAG 与 LoRA 的职责分工：

| 维度 | RAG 负责 | LoRA 负责 |
|------|---------|----------|
| 事实性知识 | 记忆系统（语义/情景/图） | — |
| 说话风格 | — | 权重固化 |
| 情感反应模式 | — | 权重固化 |
| 事件记忆 | 时间线检索 | — |
| 价值观表达 | Wiki 角色卡 | 表达方式 |
| 口癖/语气词 | 统计数据辅助 | 自然涌现 |

---

## 5. 执行计划

### Phase 1：修好 Pipeline（1~2 周）

| 任务 | 优先级 | 预估工时 | 依赖 |
|------|--------|---------|------|
| 分块 + 合并提取 | P0 | 3 天 | 无 |
| Round 4 校验回流 | P0 | 1 天 | 无 |
| 增量蒸馏 | P1 | 2 天 | 分块合并 |
| LLM-as-judge 评测 | P1 | 2 天 | 无 |
| Prompt 中文化 | P2 | 0.5 天 | 无 |

### Phase 2：统计 + LLM 混合提取（3~4 周）

| 任务 | 优先级 | 预估工时 | 依赖 |
|------|--------|---------|------|
| StyleAnalyzer 统计模块 | P0 | 3 天 | 无 |
| TopicClusterer 话题聚类 | P1 | 3 天 | embedding 模型 |
| 话题-情绪关联分析 | P1 | 2 天 | TopicClusterer |
| 融合层（统计 + LLM 结果合并） | P0 | 2 天 | StyleAnalyzer |
| 矛盾检测（统计 vs LLM） | P1 | 1 天 | 融合层 |
| SillyTavern V2 JSON 输出 | P2 | 2 天 | 无 |
| 微信/QQ 解析器 | P2 | 3 天 | 无 |

### Phase 3：LoRA 微调（2~3 个月）

| 任务 | 优先级 | 预估工时 | 依赖 |
|------|--------|---------|------|
| 训练数据构造工具 | P0 | 1 周 | 清洗后的聊天数据 |
| LoRA 训练脚本 | P0 | 1 周 | LLaMA-Factory/Unsloth |
| QLoRA 量化训练 | P1 | 3 天 | 训练脚本 |
| 推理集成（LoRA adapter 加载） | P0 | 1 周 | Layer 2/3 改造 |
| InCharacter 式人格评测 | P1 | 1 周 | 无 |
| A/B 测试（prompt-only vs LoRA） | P2 | 3 天 | 推理集成 |
| 基座模型选型（Qwen2.5 vs Llama-3） | P0 | 3 天 | 无 |

### Phase 4：持续迭代

| 任务 | 周期 | 说明 |
|------|------|------|
| 评测数据集扩充 | 持续 | 增加测试场景和维度 |
| 蒸馏质量回归测试 | 每次改动后 | 确保分数单调不减 |
| CharLoRA 多专家方案探索 | 视情况 | 通用风格专家 + 任务专家分离 |
| 角色卡版本管理 | 持续 | 跟踪人格演变 |

---

## 6. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 聊天数据量不足（<500 轮） | 蒸馏质量差 | 降低还原度目标，只做 L1 |
| LLM 幻觉（编造人格特征） | 角色失真 | 统计层交叉验证 + Round 4 回流 |
| LoRA 训练过拟合 | 角色僵化 | 控制训练轮数 + dropout + 评测监控 |
| 基座模型更换导致 LoRA 失效 | 需要重新训练 | 选择主流基座（Qwen/Llama），LoRA adapter 独立存储 |
| 隐私泄露（训练数据中的个人信息） | 合规风险 | 训练前脱敏处理，LoRA 不直接存储原始数据 |

---

## 7. 参考文献

### 学术论文

- [Character-LLM: A Trainable Agent for Role-Playing](https://arxiv.org/abs/2310.10158) — Shao et al., EMNLP 2023
- [Beyond Profile: From Surface-Level Facts to Deep Persona Simulation in LLMs](https://arxiv.org/abs/2502.12988) — Wang et al., ACL 2025 Findings
- [RoleLLM: Benchmarking, Eliciting, and Enhancing Role-Playing Abilities of LLMs](https://arxiv.org/abs/2310.00746) — Wang et al., 2023
- [InCharacter: Evaluating Personality Fidelity in Role-Playing Agents through Psychological Interviews](https://arxiv.org/abs/2310.17976) — Wang et al., ACL 2024
- [Generative Agents: Interactive Simulacra of Human Behavior](https://arxiv.org/abs/2304.03442) — Park et al., UIST 2023
- [Large Language Models Can Infer Personality from Free-Form User Interactions](https://arxiv.org/abs/2405.13052) — 2024
- [ChatHaruhi: Reviving Anime Character in Reality via Large Language Model](https://arxiv.org/abs/2308.09597) — Li et al., 2023
- [Fine-Tuning or Retrieval? Comparing Knowledge Injection in LLMs](https://arxiv.org/abs/2312.05934) — Ovadia et al., 2023
- [From Persona to Personalization: A Survey on Role-Playing Language Agents](https://arxiv.org/abs/2404.18231) — Chen et al., 2024

### 开源工具

- [SillyTavern](https://github.com/SillyTavern/SillyTavern) — AI 角色扮演前端
- [Character Card V2 Spec](https://github.com/malfoyslastname/character-card-spec-v2) — 角色卡规范
- [LLaMA-Factory](https://github.com/hiyouga/LLaMA-Factory) — LLM 微调框架
- [Unsloth](https://github.com/unslothai/unsloth) — 快速 LoRA 训练
- [ChatHaruhi](https://github.com/LC1332/ChatHaruhi) — 角色扮演 RAG 系统
- [Nika-Character-Studio](https://github.com/HiUnikitty/Nika-Character-Studio) — 角色卡创建工具
- [lorecard](https://github.com/bmen25124/lorecard) — URL→角色卡生成

### 社区资源

- [SillyTavern 角色设计指南](https://docs.sillytavern.app/usage/core-concepts/characterdesign/)
- [CHUB.ai](https://chub.ai) — 角色卡分享平台
- [Awesome-Role-Play-Papers](https://github.com/nuochenpku/Awesome-Role-Play-Papers) — 角色扮演论文合集
