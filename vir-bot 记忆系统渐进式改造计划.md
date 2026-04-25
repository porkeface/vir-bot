     vir-bot 记忆系统渐进式改造计划
    
     Context
    
     用户希望按照 记忆架构分层详解.md
     蓝图改造当前记忆系统，但担心破坏现有语义理解能力。
    
     现状：当前系统语义理解健康（AI 模型分类 + 并行检索 +
     主动查询，无硬编码），但缺少蓝图中的增强组件（Re-Ranker、Composer、Quality Gate
     等）。
    
     目标：渐进式改造，每阶段独立可运行，不破坏语义理解。
    
     关键调整：将评测系统（原 Phase 8）提前到 Phase 2。原因：没有科学的分数，无法判断改造是否真的让检索质量变好。先有尺，再丈量。

---

## 总体原则

1. **不破坏语义理解**：现有 AI 分类 + 并行检索 + 主动查询能力必须保留
2. **接口稳定**：`MemoryManager.build_context()`、`add_interaction()`、`RetrievalRouter.retrieve()` 签名不变
3. **特性开关**：所有新功能通过 `config.yaml` 控制，默认关闭
4. **测试先行**：Phase 1 补测试，后续每阶段附带测试
5. **可回滚**：每阶段完成后打 git tag，出问题立即回退
6. **评测驱动**：Phase 2 建立评测系统，每次改进后跑分，确保分数单调不减

---

## Phase 1: 测试框架 + 配置开关（不影响现有功能）✅ 已完成！

### 目标
- 为核心模块建立测试覆盖（目前项目无自动化测试）
- 添加特性开关配置框架
- 不改变任何现有行为

### 任务清单

#### 1.1 创建测试目录结构

```
 tests/
 ├── __init__.py
 ├── conftest.py
 ├── unit/
 │   ├── test_memory_manager.py
 │   ├── test_retrieval_router.py
 │   ├── test_memory_writer.py
 │   ├── test_memory_updater.py
 │   ├── test_semantic_store.py
 │   ├── test_episodic_store.py
 │   └── test_short_term.py
 └── integration/
     └── test_pipeline_memory.py
```

#### 1.2 编写核心模块测试

 - tests/unit/test_retrieval_router.py：测试 AI 分类、并行检索、跳过策略
 - tests/unit/test_memory_manager.py：测试上下文构建、记忆注入
 - tests/integration/test_pipeline_memory.py：端到端测试，验证问 AI 伴侣能正确回忆

#### 1.3 添加配置开关框架

```
 修改 config.yaml：
 memory:
   # 现有配置保持不变
   short_term:
     max_turns: 20
   long_term:
     enabled: true
     persist_dir: "./data/memory/chroma_db"

   # 新功能开关（默认关闭）
   features:
     reranker:
       enabled: false
       model: "cross-encoder/ms-marco-MiniLM-L-6-v2"
     composer:
       enabled: false
     quality_gate:
       enabled: false
     lifecycle:
       enabled: false
     graph:
       enabled: false
```

#### 1.4 修改 memory_manager.py 支持特性开关

 - 在 __init__() 中读取 features 配置
 - 添加 _is_feature_enabled(feature_name) 辅助方法

```
验证方法

 # 运行测试
 pytest tests/ -v

 # 确认现有功能正常
 python -m vir-bot.main
 # 问 AI 伴侣："我叫什么名字？"（验证语义记忆）
 # 问 AI 伴侣："我喜欢吃什么？"（验证语义理解）

 回滚方案

 - 此阶段只添加测试和新配置，不改变行为
 - 如果出问题：删除 tests/ 目录和 config.yaml 中的 features 配置
```



---

## Phase 2: 评测系统

### 目标
- 基于 LongMemEval 思想构建封闭测试集
- 覆盖五大指标：偏好召回、事件回忆、知识更新、时间推理、拒答准确率
- **在改造之前建立基线分数**，作为后续所有改进的量化基准

### 为什么提前？

> 没有科学的分数，你如何判断 Phase 3 的 Re-Ranker 真的让检索质量变好了，而不是"感觉"变好了？
> 先有尺，再丈量。哪怕先构建一个只有 20 条测试用例的小型"偏好召回"数据集，它也能在 Phase 3、4、5 完成后立刻给出量化分数，让你看到改造的真实收益。
> 防止倒退：这是长期项目进化最可靠的伙伴。每次改进后，跑一遍分，确保分数箭头一直向上。

### 任务清单

#### 2.1 创建 `tests/eval/` 目录结构
```
tests/eval/
├── __init__.py
├── benchmark.py         # 评测主入口
├── metrics.py           # 五项指标计算
├── runner.py            # 自动跑分脚本
└── datasets/
    ├── preference_recall.json      # 偏好召回测试集
    ├── episodic_recall.json       # 事件回忆测试集
    ├── knowledge_update.json      # 知识更新测试集
    ├── temporal_reasoning.json   # 时间推理测试集
    └── abstention_accuracy.json  # 拒答准确率测试集
```

#### 2.2 实现评测数据集（先构建小规模基线）
每个测试集包含：
- `question`: 测试问题
- `expected_behavior`: 期望行为（"recall:火锅" 或 "abstain:不知道"）
- `user_id`: 测试用户 ID
- `setup_data`: 需要预加载到记忆系统的数据（可选）

示例 `preference_recall.json`:
```json
[
  {
    "id": "pref_001",
    "question": "我喜欢吃什么？",
    "expected_behavior": "recall:火锅",
    "user_id": "eval_user",
    "setup_data": [
      {"namespace": "profile.preference", "predicate": "likes", "object": "火锅"}
    ]
  },
  {
    "id": "pref_002",
    "question": "我叫什么名字？",
    "expected_behavior": "abstain:不知道",
    "user_id": "eval_user",
    "setup_data": []
  }
]
```

**目标**：每个测试集至少 20 条用例，覆盖：
- 能正确回忆的（应该答对）
- 不存在的记忆（应该回答"不知道"）
- 边界情况（模糊查询、矛盾记忆等）

#### 2.3 实现评测指标 (`metrics.py`)
```python
def preference_recall_score(results: list) -> float:
    """偏好召回率：能正确回忆用户偏好的比例"""

def episodic_recall_score(results: list) -> float:
    """事件回忆率：能正确回忆历史事件的比例"""

def knowledge_update_score(results: list) -> float:
    """知识更新准确率：更新后能获取最新信息的比例"""

def temporal_reasoning_score(results: list) -> float:
    """时间推理准确率：正确处理时间相关查询的比例"""

def abstention_accuracy_score(results: list) -> float:
    """拒答准确率：对于不存在的记忆，正确回答"不知道"的比例"""

def overall_score(results: dict) -> float:
    """综合分数：五大指标的加权平均"""
    weights = {
        "preference_recall": 0.25,
        "episodic_recall": 0.20,
        "knowledge_update": 0.20,
        "temporal_reasoning": 0.20,
        "abstention_accuracy": 0.15,
    }
    ...
```

#### 2.4 实现自动跑分脚本 (`runner.py`)
- 加载测试数据集
- 预加载 setup_data 到记忆系统
- 调用 AI 伴侣回答问题
- 对比回答与期望行为
- 计算分数并输出报告

#### 2.5 实现评测主入口 (`benchmark.py`)
```python
async def run_benchmark(config_path: str = "config.yaml") -> dict:
    """运行完整评测套件"""
    # 1. 初始化系统
    # 2. 运行五大评测
    # 3. 输出分数报告
    # 4. 保存历史分数（用于对比）
```

#### 2.6 建立基线分数
```bash
# 运行评测，记录当前系统的基线分数
cd "D:/code Project/vir-bot"
pytest tests/eval/ -v

# 或使用专门的跑分脚本
python -m tests.eval.runner

# 输出示例：
# Baseline Scores (Before any 改造):
# - Preference Recall: 0.65
# - Episodic Recall: 0.40
# - Knowledge Update: 0.50
# - Temporal Reasoning: 0.80
# - Abstention Accuracy: 0.70
# - Overall: 0.61
```

### 验证方法
```bash
# 运行评测
pytest tests/eval/ -v

# 或运行完整跑分
python -m tests.eval.runner --config config.yaml

# 确保基线分数已记录（保存到 tests/eval/baseline_scores.json）
```

### 回滚方案
```bash
# 评测系统是纯测试代码，不影响生产功能
# 如果出问题，不运行评测即可
git tag phase2-complete  # 评测系统完成
```

---

## Phase 3: Re-Ranker 实现（Layer 2 核心）

### 目标
- 实现 Cross-Encoder 重排序，对并行检索结果统一评分
- 作为可选组件，通过配置开关
- 提升检索结果相关性
- **用 Phase 2 的评测系统量化验证效果**

### 任务清单

#### 3.1 创建 `vir_bot/core/memory/reranker.py`
```python
class MemoryReranker:
    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        self.model = None  # 懒加载
        self.model_name = model_name

    async def rerank(self, query: str, records: list, top_k: int = 5) -> list:
        """对候选记忆重排序，返回带 relevance score 的列表"""
        # 使用 Cross-Encoder 计算 query-document 相关性
        # 返回排序后的记录列表
```

#### 3.2 修改 `retrieval_router.py`
在 `retrieve()` 方法中：
```python
# 并行检索完成后
if self._is_reranker_enabled():
    all_records = self._collect_all_records(result)
    reranked = await self.reranker.rerank(query, all_records, top_k)
    # 更新 result 中的记录
```

#### 3.3 编写测试
- `tests/unit/test_reranker.py`：测试重排序逻辑

#### 3.4 验证改进效果（关键！）
```bash
# 1. 记录改造前分数（基线）
python -m tests.eval.runner --tag "before-reranker"

# 2. 开启 reranker
# config.yaml 中设置 memory.features.reranker.enabled: true

# 3. 记录改造后分数
python -m tests.eval.runner --tag "after-reranker"

# 4. 对比分数
# Preference Recall: 0.65 → 0.72 ✅
# Overall: 0.61 → 0.66 ✅
```

### 验证方法
```bash
# 开启 reranker
# config.yaml 中设置 memory.features.reranker.enabled: true

# 对比开启前后的评测分数
python -m tests.eval.runner --compare baseline after-reranker

# 验证：
# 1. 评测分数提升（或至少不下降）
# 2. 问同一个问题，观察返回的记忆上下文是否更相关
```

### 回滚方案
```bash
# 关闭 reranker 即可回退
# config.yaml 中设置 memory.features.reranker.enabled: false
git tag phase3-complete
```

---

## Phase 4: Memory Composer 实现（Layer 2 核心）

### 目标
- 实现去重（相似度 >0.95 保留高置信度者）
- 冲突消解（同一事实有矛盾时，按时间新近和来源可靠性择优）
- Token Budget 分配（按相关性截断，不超过 LLM 上下文窗口的 30%）
- **用评测系统验证上下文质量提升**

### 任务清单

#### 4.1 创建 `vir_bot/core/memory/composer.py`
```python
class MemoryComposer:
    def __init__(self, max_tokens: int = 2000):
        self.max_tokens = max_tokens

    def compose(self, result: RetrievalResult) -> str:
        """将多路检索结果去重、冲突消解、分配 Token 预算"""
        # 1. 去重：相似度 >0.95 保留高置信度
        # 2. 冲突消解：同一 predicate 取时间最新的
        # 3. Token 预算：按相关性截断
        # 4. 格式化输出
```

#### 4.2 修改 `retrieval_router.py`
- `RetrievalResult.to_context_string()` 委托给 Composer（如果启用）
- 保持原有逻辑作为 fallback

#### 4.3 编写测试
- `tests/unit/test_composer.py`：测试去重、冲突消解、Token 截断

#### 4.4 验证改进效果
```bash
# 记录改造前分数
python -m tests.eval.runner --tag "after-reranker"

# 开启 composer
# config.yaml 中设置 memory.features.composer.enabled: true

# 记录改造后分数
python -m tests.eval.runner --tag "after-composer"

# 对比分数，确保提升
```

### 验证方法
```bash
# 开启 composer
# config.yaml 中设置 memory.features.composer.enabled: true

# 验证：
# 1. 评测分数提升
# 2. 重复记忆被去重
# 3. 矛盾记忆（如"喜欢火锅"和"讨厌火锅"）只保留最新的
# 4. 上下文长度不超过限制
```

### 回滚方案
```bash
# 关闭 composer 即可回退
# config.yaml 中设置 memory.features.composer.enabled: false
git tag phase4-complete
```

---

## Phase 5: Quality Gate + Write Verifier（Layer 4）

### 目标
- Quality Gate：规则引擎先行，拦截低质量记忆写入
- Write Verifier：检测重复写入和冲突
- **用评测系统验证写入质量提升**

### 任务清单

#### 5.1 创建 `vir_bot/core/memory/quality_gate.py`
```python
class QualityGate:
    def check(self, operation: MemoryOperation) -> tuple[bool, str]:
        """
        检查记忆操作是否应通过质量门。
        返回 (通过?, 原因)
        """
        # 规则1：识别时间性模糊词（"最近"、"经常"等）
        # 规则2：情绪化表达（"最讨厌"、"超级喜欢"等）
        # 规则3：随意猜测（来源不可靠）
        # 灰色地带：调用 LLM 二次判断
```

#### 5.2 创建 `vir_bot/core/memory/verifier.py`
```python
class WriteVerifier:
    def __init__(self, semantic_store: SemanticMemoryStore):
        self.semantic_store = semantic_store

    async def verify(self, operation: MemoryOperation, user_id: str) -> tuple[bool, str]:
        """检测重复和冲突"""
        # 1. 语义相似度比对（防止重复写入）
        # 2. 与现有高置信度记忆冲突检测
        # 3. 标记为 candidate 或直接通过
```

#### 5.3 修改 `memory_writer.py` 和 `memory_updater.py`
- 在写入前调用 Quality Gate 和 Verifier
- 通过特性开关控制

#### 5.4 编写测试
- `tests/unit/test_quality_gate.py`
- `tests/unit/test_verifier.py`

#### 5.5 验证改进效果
```bash
# 记录改造前分数
python -m tests.eval.runner --tag "after-composer"

# 开启 quality_gate 和 verifier
# config.yaml 中设置 memory.features.quality_gate.enabled: true

# 记录改造后分数
python -m tests.eval.runner --tag "after-quality-gate"

# 对比分数，确保提升
```

### 验证方法
```bash
# 开启 quality_gate 和 verifier
# config.yaml 中设置 memory.features.quality_gate.enabled: true

# 验证：
# 1. 评测分数提升（特别是知识更新指标）
# 2. 低质量记忆（如"我喜欢..."来自情绪化表达）被拦截或降权
# 3. 重复记忆不再写入
# 4. 冲突记忆标记为 candidate
```

### 回滚方案
```bash
# 关闭新功能即可回退
git tag phase5-complete
```

---

## Phase 6: 多版本支持（Layer 5）

### 目标
- 扩展 SemanticMemoryRecord 支持多版本（valid_from, valid_to, previous_version_id）
- Memory Updater 支持版本链
- **用评测系统的"知识更新"指标验证版本管理效果**

### 任务清单

#### 6.1 修改 `semantic_store.py`
扩展 `SemanticMemoryRecord` 数据模型：
```python
@dataclass
class SemanticMemoryRecord:
    # 现有字段保持不变
    memory_id: str
    user_id: str
    namespace: str
    # ...

    # 新增版本字段
    valid_from: float = field(default_factory=time.time)
    valid_to: float | None = None
    previous_version_id: str | None = None
    confidence_history: list[float] = field(default_factory=list)
```

#### 6.2 修改 `memory_updater.py`
- UPDATE 操作创建新版本，设置旧版本的 `valid_to`
- 支持版本链查询

#### 6.3 数据迁移
- 现有 `semantic_memory.json` 中的记录自动填充新字段（默认值）
- 保持向后兼容

#### 6.4 编写测试
- `tests/unit/test_semantic_store.py`：测试版本链操作

#### 6.5 验证改进效果
```bash
# 运行评测，特别关注"知识更新"指标
python -m tests.eval.runner --focus knowledge_update
```

### 验证方法
```bash
# 验证：
# 1. 评测分数提升（特别是知识更新指标）
# 2. 更新记忆后，旧版本仍然可查（通过 valid_from/valid_to）
# 3. 版本链完整（previous_version_id 正确指向）
# 4. 现有数据正常加载
```

### 回滚方案
```bash
# 数据迁移是向后兼容的，回滚只需恢复代码
git tag phase6-complete
```

---

## Phase 7: Memory Graph（Layer 6）

### 目标
- 新增 `graph_store.py`，使用 NetworkX 存储实体间关系
- 弥补向量检索无法处理多跳关系推理的缺陷
- **用评测系统的"事件回忆"和"时间推理"指标验证关系推理效果**

### 任务清单

#### 7.1 创建 `vir_bot/core/memory/graph_store.py`
```python
class MemoryGraphStore:
    def __init__(self, persist_path: str = "./data/memory/memory_graph.json"):
        self.graph = nx.DiGraph()
        self.persist_path = persist_path

    def add_relation(self, subject: str, predicate: str, object: str, confidence: float = 1.0):
        """添加三元组关系"""
        self.graph.add_edge(subject, object, predicate=predicate, confidence=confidence)

    def query(self, subject: str, predicate: str | None = None) -> list[tuple]:
        """查询关系"""
        # 支持多跳推理
```

#### 7.2 修改 `memory_writer.py`
- 从对话中抽取实体关系
- 写入 Memory Graph（如果启用）

#### 7.3 修改 `retrieval_router.py`
- 在 `retrieve()` 中并行查询 Memory Graph
- 将关系推理结果加入上下文

#### 7.4 编写测试
- `tests/unit/test_graph_store.py`

#### 7.5 验证改进效果
```bash
# 运行评测，特别关注"事件回忆"和"时间推理"指标
python -m tests.eval.runner --focus episodic_recall temporal_reasoning
```

### 验证方法
```bash
# 开启 graph
# config.yaml 中设置 memory.features.graph.enabled: true

# 验证：
# 1. 评测分数提升（特别是事件回忆和时间推理指标）
# 2. 实体关系正确存储（如"用户-[喜欢]->火锅"）
# 3. 多跳查询（如"我喜欢什么？"→"火锅"→"火锅是川菜"）
```

### 回滚方案
```bash
# 关闭 graph 即可回退
# config.yaml 中设置 memory.features.graph.enabled: false
git tag phase7-complete
```

---

## Phase 8: Lifecycle Manager（Layer 7）

### 目标
- 后台 Cron 任务，不阻塞在线流程
- 衰减降权、相似记忆合并、低置信度归档
- **用评测系统长期监控记忆质量**

### 任务清单

#### 8.1 创建 `vir_bot/core/memory/lifecycle/`
```
lifecycle/
├── __init__.py
├── janitor.py          # 生命周期管理器主入口
├── decay.py            # 衰减算法
└── merge.py            # 记忆合并逻辑
```

#### 8.2 实现衰减算法 (`decay.py`)
- 根据重要性、最后访问时间、来源可靠性计算留存分数
- 低于阈值的降权

#### 8.3 实现记忆合并 (`merge.py`)
- 定期（如每周）对 Semantic Memory 和 Episodic Memory 做语义聚类
- 将描述同一事实的多条记录合并为一

#### 8.4 实现 Lifecycle Manager (`janitor.py`)
- 作为后台任务运行（使用 asyncio.create_task）
- 或作为独立脚本（`python -m vir_bot.core.memory.lifecycle.janitor`）

#### 8.5 编写测试
- `tests/unit/lifecycle/test_decay.py`
- `tests/unit/lifecycle/test_merge.py`

#### 8.6 验证改进效果
```bash
# 运行评测，监控长期记忆质量
python -m tests.eval.runner --tag "after-lifecycle"
```

### 验证方法
```bash
# 开启 lifecycle
# config.yaml 中设置 memory.features.lifecycle.enabled: true

# 验证：
# 1. 评测分数保持或提升（特别是长期运行后）
# 2. 低置信度记忆被归档（confidence < 0.1 且长期未访问）
# 3. 相似记忆被合并
# 4. 在线服务不受影响
```

### 回滚方案
```bash
# 关闭 lifecycle 即可回退
# config.yaml 中设置 memory.features.lifecycle.enabled: false
git tag phase8-complete
```

---

## 总结：调整后的执行顺序

```
Phase 1: 测试 + 配置开关 ✅ 已完成（tag: phase1-complete）
    ↓
Phase 2: 评测系统 ⭐ 提前执行（建立基线分数）
    ↓
Phase 3: Re-Ranker（用评测验证检索质量提升）
    ↓
Phase 4: Memory Composer（用评测验证上下文质量提升）
    ↓
Phase 5: Quality Gate + Write Verifier（用评测验证写入质量提升）
    ↓
Phase 6: 多版本支持（用评测验证知识更新效果）
    ↓
Phase 7: Memory Graph（用评测验证关系推理效果）
    ↓
Phase 8: Lifecycle Manager（用评测长期监控记忆质量）
```

**关键改变**：
1. **Phase 2（评测系统）提前到 Phase 3（Re-Ranker）之前**
2. **每个 Phase 完成后立即跑分**，对比改进效果
3. **基线分数**：在改造之前就知道当前系统的能力边界
4. **防止倒退**：分数单调不减是改造的唯一可靠标准

**每阶段完成后**：
1. 运行完整测试套件（`pytest tests/ -v`）
2. 运行评测系统（`python -m tests.eval.runner`）
3. 对比分数，确保提升（或至少不下降）
4. 手动验证语义理解未被破坏（问 AI 伴侣几个关键问题）
5. 打 git tag（`git tag phaseX-complete`）
6. 提交到分支（`git commit`）

**如果任何阶段出现问题**：
- 立即关闭对应特性开关（`config.yaml`）
- 或回退到上一个 git tag（`git checkout phaseX-complete`）
- 检查评测分数，定位倒退原因
