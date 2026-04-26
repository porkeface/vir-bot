```
Phase 2: 评测系统实现计划

 Context

 vir-bot 项目处于 Phase 1 完成状态（测试框架 + 配置开关已就位）。Phase 2
 的目标是在开始任何功能改造前，建立科学的评测基线分数。

 为什么提前做评测系统？
 - 没有量化指标，无法判断 Phase 3+ 的改造是否真的提升了检索质量
 - 先有尺，再丈量——防止"感觉变好了"的错觉
 - 每次改进后跑分，确保分数单调不减

 评测维度（基于 LongMemEval）：
 1. 偏好召回（preference_recall）：能正确回忆用户偏好的比例
 2. 事件回忆（episodic_recall）：能正确回忆历史事件的比例
 3. 知识更新（knowledge_update）：更新后能获取最新信息的比例
 4. 时间推理（temporal_reasoning）：正确处理时间相关查询的比例
 5. 拒答准确率（abstention_accuracy）：对不存在的记忆正确回答"不知道"的比例

 ---
 实现方案

 文件创建清单

 ┌─────┬────────────────────────────────────────┬─────────────────────┬──────────┐
 │ 序  │                文件路径                │        说明         │   依赖   │
 │ 号  │                                        │                     │          │
 ├─────┼────────────────────────────────────────┼─────────────────────┼──────────┤
 │ 1   │ tests/eval/__init__.py                 │ 评测包初始化        │ 无       │
 ├─────┼────────────────────────────────────────┼─────────────────────┼──────────┤
 │ 2   │ tests/eval/metrics.py                  │ 五项指标计算 +      │ 无       │
 │     │                                        │ 判断逻辑            │          │
 ├─────┼────────────────────────────────────────┼─────────────────────┼──────────┤
 │ 3   │ tests/eval/datasets/preference_recall. │ 偏好召回测试集（MVP │ 无       │
 │     │ json                                   │ : 8条）             │          │
 ├─────┼────────────────────────────────────────┼─────────────────────┼──────────┤
 │ 4   │ tests/eval/datasets/episodic_recall.js │ 事件回忆测试集（MVP │ 无       │
 │     │ on                                     │ : 8条）             │          │
 ├─────┼────────────────────────────────────────┼─────────────────────┼──────────┤
 │ 5   │ tests/eval/datasets/knowledge_update.j │ 知识更新测试集（MVP │ 无       │
 │     │ son                                    │ : 8条）             │          │
 ├─────┼────────────────────────────────────────┼─────────────────────┼──────────┤
 │ 6   │ tests/eval/datasets/temporal_reasoning │ 时间推理测试集（MVP │ 无       │
 │     │ .json                                  │ : 8条）             │          │
 ├─────┼────────────────────────────────────────┼─────────────────────┼──────────┤
 │ 7   │ tests/eval/datasets/abstention_accurac │ 拒答准确率测试集（M │ 无       │
 │     │ y.json                                 │ VP: 8条）           │          │
 ├─────┼────────────────────────────────────────┼─────────────────────┼──────────┤
 │ 8   │ tests/eval/runner.py                   │ 自动跑分脚本        │ metrics. │
 │     │                                        │                     │ py       │
 ├─────┼────────────────────────────────────────┼─────────────────────┼──────────┤
 │ 9   │ tests/eval/benchmark.py                │ CLI 主入口          │ runner.p │
 │     │                                        │                     │ y        │
 ├─────┼────────────────────────────────────────┼─────────────────────┼──────────┤
 │ 10  │ vir_bot/core/memory/monitoring.py      │ 线上监控模块        │ 无       │
 ├─────┼────────────────────────────────────────┼─────────────────────┼──────────┤
 │ 11  │ vir_bot/core/memory/debug_tools.py     │ 调试工具模块        │ 无       │
 ├─────┼────────────────────────────────────────┼─────────────────────┼──────────┤
 │ 12  │ tests/unit/test_eval_metrics.py        │ metrics.py 单元测试 │ metrics. │
 │     │                                        │                     │ py       │
 └─────┴────────────────────────────────────────┴─────────────────────┴──────────┘

 关键设计决策

 1. 对话模拟方式：直接调用 memory_manager.add_interaction() + build_context() +
 ai_provider.chat()，不依赖 API 网络
 2. 正确性判断：关键词 AND 匹配（快速确定）+ 拒答关键词检测
 3. AI Provider：默认使用配置文件中的真实 Provider，支持 --mock 参数快速验证流程
 4. 状态隔离：每个测试用例运行前调用 memory_manager.clear_all() 避免污染
 5. 数据集大小：MVP 阶段每个数据集 8 条，后续扩充到 20+ 条

 ---
 详细实现

 1. tests/eval/metrics.py - 评测指标核心

 关键函数：
 # 拒答关键词
 REJECTION_KEYWORDS = ["不知道", "没记住", "没有这条记录", "不清楚", "没有相关信息",
 "没有找到", "没有查到", "不记得"]

 def judge_correctness(question, expected_keywords, rejection_expected,
 actual_response) -> tuple[str, str]:
     """
     判断回答正确性
     返回: (judgment, reason)
     - judgment: "correct" / "wrong" / "unknown"
     """
     response_lower = actual_response.strip().lower()

     # 1. 检测是否拒答
     is_rejection = any(kw in response_lower for kw in REJECTION_KEYWORDS)

     # 2. 期望拒答
     if rejection_expected:
         return ("correct", "正确拒答") if is_rejection else ("wrong",
 "应拒答但未拒答")

     # 3. 不应拒答但拒答了
     if is_rejection:
         return ("wrong", "不应拒答但拒答了")

     # 4. 关键词 AND 匹配
     if not expected_keywords:
         return ("unknown", "无期望关键词")
     matched = [kw for kw in expected_keywords if kw.lower() in response_lower]
     if len(matched) == len(expected_keywords):
         return ("correct", f"关键词全命中: {matched}")
     return ("wrong", f"关键词未全命中，缺失: {[kw for kw in expected_keywords if
 kw.lower() not in response_lower]}")

 # 五项指标计算函数
 def preference_recall_score(results: list) -> float:
     correct = sum(1 for r in results if r["judgment"] == "correct")
     return correct / len(results) if results else 0.0

 # 类似实现: episodic_recall_score, knowledge_update_score, temporal_reasoning_score,
 abstention_accuracy_score

 def overall_score(scores: dict) -> float:
     """加权平均: preference 0.25, episodic 0.20, knowledge 0.20, temporal 0.20,
 abstention 0.15"""
     weights = {"preference_recall": 0.25, "episodic_recall": 0.20,
 "knowledge_update": 0.20, "temporal_reasoning": 0.20, "abstention_accuracy": 0.15}
     total = sum(scores.get(k, 0) * w for k, w in weights.items())
     return total

 2. tests/eval/runner.py - 评测运行器

 核心流程：
 class EvaluationRunner:
     async def run_dataset(self, dataset_name: str, use_mock: bool = False) ->
 list[dict]:
         """
         1. 加载数据集 (tests/eval/datasets/{dataset_name}.json)
         2. 对每个测试用例:
            a. await self._reset_memory()  # 清空状态
            b. 模拟多轮对话: await memory_manager.add_interaction(user_msg,
 assistant_msg)
            c. 构建上下文: await memory_manager.build_context(test_question,
 system_prompt, user_id)
            d. 生成回答: await ai_provider.chat(messages, system=enhanced_system)
            e. 判断: judge_correctness(...)
         3. 返回结果列表
         """

     async def run_all(self, dataset_names: list[str] | None = None) -> dict:
         """运行所有数据集，计算分数，保存到 history.json"""

 注意： 初始化 EvaluationRunner 时需要传入 memory_manager 和
 ai_provider，使用临时目录避免污染真实数据。

 3. tests/eval/benchmark.py - CLI 入口

 # 命令行参数:
 #   --dataset: 指定运行的数据集（默认全部）
 #   --mock: 使用 Mock AI Provider
 #   --config: 配置文件路径（默认 config.yaml）
 #   --report: 报告输出路径（默认 tests/eval/report.json）

 async def main():
     # 1. 加载配置
     config = load_config(args.config)

     # 2. 创建临时目录（避免污染真实数据）
     temp_dir = tempfile.mkdtemp(prefix="vir-bot-eval-")

     # 3. 初始化组件（使用临时目录）
     semantic_store =
 SemanticMemoryStore(persist_path=f"{temp_dir}/semantic_memory.json")
     episodic_store = EpisodicStore()
     short_term = ShortTermMemory(max_turns=20)
     # ... 其他组件

     # 4. 运行评测
     runner = EvaluationRunner(memory_manager, ai_provider)
     report = await runner.run_all(...)

     # 5. 输出报告 + 保存历史
     # 6. 清理临时目录

 4. 数据集格式（示例：preference_recall.json）

 [
   {
     "id": "pref_001",
     "conversations": [
       [
         {"role": "user", "content": "你猜我最喜欢吃什么？"},
         {"role": "assistant", "content": "哈哈，我猜是火锅？"}
       ],
       [
         {"role": "user", "content": "对，就是火锅！"},
         {"role": "assistant", "content": "那我记下了，你喜欢火锅。"}
       ]
     ],
     "test_question": "我喜欢吃什么？",
     "expected_keywords": ["火锅"],
     "rejection_expected": false,
     "user_id": "eval_user_001"
   },
   {
     "id": "pref_002",
     "conversations": [
       [
         {"role": "user", "content": "我最喜欢的运动是篮球"},
         {"role": "assistant", "content": "好的，我记住了，你喜欢篮球。"}
       ]
     ],
     "test_question": "我喜欢什么运动？",
     "expected_keywords": ["篮球"],
     "rejection_expected": false,
     "user_id": "eval_user_002"
   }
   // ... 至少 8 条
 ]

 其他数据集类型：
 - episodic_recall.json：测试事件回忆（如"昨天我们聊了什么？"）
 - knowledge_update.json：测试知识更新（先教旧信息，再教新信息，问最新信息）
 - temporal_reasoning.json：测试时间推理（如"上个月的计划是什么？"）
 - abstention_accuracy.json：测试拒答能力（查询不存在的记忆，期望回答"不知道"）

 5. vir_bot/core/memory/monitoring.py - 线上监控

 class MemoryMonitor:
     def record_retrieval(self, query, result_count, latency_ms, user_id=""):
         """记录检索事件，计算命中率"""
     def record_conflict(self, predicate, conflicting_count):
         """记录冲突事件"""
     def record_correction(self, user_id, predicate):
         """记录用户纠正事件"""
     def get_summary(self) -> dict:
         """返回汇总指标: retrieval_hit_rate, avg_latency_ms, conflict_rate,
 correction_rate"""
     def export_prometheus(self) -> str:
         """导出为 Prometheus 格式"""

 6. vir_bot/core/memory/debug_tools.py - 调试工具

 class MemoryDebugTools:
     def __init__(self, memory_manager):
         self.memory_manager = memory_manager

     def replay_timeline(self, user_id, start_time=None, end_time=None) -> list[dict]:
         """回放用户记忆时间线（语义+事件）"""

     def get_version_chain(self, memory_id) -> list[dict]:
         """查看记忆版本链（待 versioning 特性支持）"""

     def manual_intervention(self, memory_id, action, **kwargs) -> bool:
         """手动干预: deactivate / update / delete"""

     def export_user_memory(self, user_id, output_path) -> None:
         """导出用户所有记忆到 JSON 文件"""

 7. 修改 vir_bot/core/memory/__init__.py

 在 __all__ 中添加：
 "MemoryMonitor",
 "MemoryDebugTools",

 ---
 执行顺序

 并行执行（无依赖）:
 ├── 创建 tests/eval/__init__.py
 ├── 实现 tests/eval/metrics.py
 ├── 实现 vir_bot/core/memory/monitoring.py
 └── 实现 vir_bot/core/memory/debug_tools.py

 并行执行（依赖 metrics.py）:
 ├── 实现 tests/eval/runner.py
 └── 编写 tests/unit/test_eval_metrics.py

 并行执行（数据集）:
 ├── 创建 tests/eval/datasets/preference_recall.json
 ├── 创建 tests/eval/datasets/episodic_recall.json
 ├── 创建 tests/eval/datasets/knowledge_update.json
 ├── 创建 tests/eval/datasets/temporal_reasoning.json
 └── 创建 tests/eval/datasets/abstention_accuracy.json

 最后执行:
 └── 实现 tests/eval/benchmark.py（依赖 runner.py）

 ---
 验证方法

 1. 单元测试

 # 测试 metrics.py 判断逻辑
 pytest tests/unit/test_eval_metrics.py -v

 # 测试运行器（使用 mock）
 pytest tests/eval/ -v

 2. Mock 模式验证流程

 # 使用 Mock AI Provider 验证整个评测流程
 python -m tests.eval.benchmark --mock --report tests/eval/baseline_mock.json
 预期：流程不报错，生成报告文件。

 3. 真实评测建立基线

 # 确保 config.yaml 中配置了有效的 AI Provider
 # 运行完整评测
 python -m tests.eval.benchmark --report tests/eval/baseline_v1.json

 4. 检查输出

 # 查看评测报告
 cat tests/eval/report.json

 # 查看历史分数
 cat tests/eval/history.json

 5. 手动验证

 - 问 AI 伴侣几个测试问题，对比评测结果
 - 验证拒答逻辑：问不存在的记忆，检查是否返回"不知道"
 - 验证时间推理：问"昨天我们聊了什么？"

 ---
 基线分数记录

 评测完成后，创建 tests/eval/baseline.md 记录基线分数：

 # vir-bot Phase 2 基线分数

 ## 评测时间
 2026-04-26

 ## 环境
 - AI Provider: [从 config.yaml 读取]
 - 数据集大小: 各 8 条 (MVP)


 5. 手动验证

 - 问 AI 伴侣几个测试问题，对比评测结果
 - 验证拒答逻辑：问不存在的记忆，检查是否返回"不知道"
 - 验证时间推理：问"昨天我们聊了什么？"

 ---
 基线分数记录

 评测完成后，创建 tests/eval/baseline.md 记录基线分数：

 # vir-bot Phase 2 基线分数

 ## 评测时间
 2026-04-26

 ## 环境
 - AI Provider: [从 config.yaml 读取]
 - 数据集大小: 各 8 条 (MVP)

 ## 基线分数
 | 指标 | 分数 | 正确/总数 |
 |------|------|-----------|
 | preference_recall | XX% | X/8 |
 | episodic_recall | XX% | X/8 |
 | knowledge_update | XX% | X/8 |
 | temporal_reasoning | XX% | X/8 |
 | abstention_accuracy | XX% | X/8 |
 | **overall** | **XX%** | - |

 ## 备注
 - 这是改造前的基线分数
 - Phase 3+ 的改进应该使分数提升
 - 数据集后续扩充到 20+ 条后重新评测

 ---
 关键文件引用

 ┌─────────────────────────────────────────┬───────────────────────────────────────┐
 │                  文件                   │                 用途                  │
 ├─────────────────────────────────────────┼───────────────────────────────────────┤
 │ vir_bot/core/memory/memory_manager.py   │ MemoryManager 接口（build_context,    │
 │                                         │ add_interaction, clear_all）          │
 ├─────────────────────────────────────────┼───────────────────────────────────────┤
 │ vir_bot/core/memory/retrieval_router.py │ RetrievalRouter（retrieve,            │
 │                                         │ retrieve_for_context）                │
 ├─────────────────────────────────────────┼───────────────────────────────────────┤
 │ vir_bot/core/ai_provider.py             │ AI Provider 接口（chat 方法）         │
 ├─────────────────────────────────────────┼───────────────────────────────────────┤
 │ tests/conftest.py                       │ 现有测试 fixtures（可复用             │
 │                                         │ memory_manager, mock_ai_provider 等） │
 ├─────────────────────────────────────────┼───────────────────────────────────────┤
 │ config.yaml                             │ 配置文件（已有 memory.features 配置） │
 └─────────────────────────────────────────┴───────────────────────────────────────┘
```

