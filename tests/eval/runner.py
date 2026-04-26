"""评测运行器 — 执行测试并收集结果。"""

import json
import time
from pathlib import Path
from typing import Optional

from tests.eval.metrics import (
    EvaluationResult,
    DatasetScore,
    judge_correctness,
    calculate_dataset_score,
    preference_recall_score,
    episodic_recall_score,
    knowledge_update_score,
    temporal_reasoning_score,
    abstention_accuracy_score,
    overall_score,
)


class EvaluationRunner:
    """评测运行器。"""

    def __init__(
        self,
        memory_manager,
        ai_provider,
        datasets_dir: str = "tests/eval/datasets",
        history_path: str = "tests/eval/history.json",
    ):
        self.memory_manager = memory_manager
        self.ai_provider = ai_provider
        self.datasets_dir = Path(datasets_dir)
        self.history_path = Path(history_path)
        self.history = self._load_history()

    async def run_dataset(
        self,
        dataset_name: str,
        use_mock: bool = False,
    ) -> list:
        """
        运行单个数据集评测。

        流程：
        1. 加载数据集
        2. 为每个测试用例模拟多轮对话并提问
        3. 判断回答正确性
        """
        dataset_path = self.datasets_dir / f"{dataset_name}.json"
        if not dataset_path.exists():
            raise FileNotFoundError(f"数据集不存在: {dataset_path}")

        with open(dataset_path, "r", encoding="utf-8") as f:
            test_cases = json.load(f)

        results = []

        for case in test_cases:
            # 重新初始化记忆系统（避免状态污染）
            await self._reset_memory()

            test_id = case["id"]
            user_id = case.get("user_id", "eval_user")

            # 模拟多轮对话
            conversations = case.get("conversations", [])
            for turn in conversations:
                if len(turn) >= 2:
                    user_msg = turn[0]["content"]
                    assistant_msg = turn[1]["content"]

                    await self.memory_manager.add_interaction(
                        user_msg=user_msg,
                        assistant_msg=assistant_msg,
                        metadata={"user_id": user_id},
                    )

            # 问测试问题
            test_question = case["test_question"]
            expected_keywords = case.get("expected_keywords", [])
            rejection_expected = case.get("rejection_expected", False)

            # 构建上下文
            system_prompt = (
                "你是一个友好的AI助手，请根据记忆回答用户问题。"
                "如果记忆中没有相关信息，请直接说不知道。"
            )
            enhanced_system, conversation = await self.memory_manager.build_context(
                current_query=test_question,
                system_prompt=system_prompt,
                user_id=user_id,
            )

            # 生成回答
            messages = conversation + [
                {"role": "user", "content": test_question}
            ]

            if not use_mock:
                response = await self.ai_provider.chat(
                    messages=messages,
                    system=enhanced_system,
                )
                actual_response = response.content
            else:
                # Mock 模式：返回简单回应
                actual_response = f"Mock response for: {test_question}"

            # 判断正确性
            judgment, reason = judge_correctness(
                question=test_question,
                expected_keywords=expected_keywords,
                rejection_expected=rejection_expected,
                actual_response=actual_response,
            )

            result = EvaluationResult(
                test_id=test_id,
                dataset_type=dataset_name,
                expected_behavior="reject" if rejection_expected else "recall",
                actual_response=actual_response,
                expected_keywords=expected_keywords,
                rejection_expected=rejection_expected,
                judgment=judgment,
                score=1.0 if judgment == "correct" else 0.0,
                reason=reason,
            )
            results.append(result)

        return results

    async def _reset_memory(self) -> None:
        """重置记忆系统（清空所有记忆）。"""
        # 清空短期记忆
        if hasattr(self.memory_manager, "short_term"):
            self.memory_manager.short_term.clear()

        # 清空语义记忆
        if hasattr(self.memory_manager, "semantic_store"):
            self.memory_manager.semantic_store.clear()

        # 清空事件记忆
        if hasattr(self.memory_manager, "episodic_store"):
            self.memory_manager.episodic_store.clear()

        # 清空问题记忆
        if hasattr(self.memory_manager, "question_store"):
            self.memory_manager.question_store.clear()

        # 清空长期记忆
        if (
            hasattr(self.memory_manager, "long_term")
            and self.memory_manager.long_term
        ):
            try:
                await self.memory_manager.long_term.clear()
            except Exception:
                pass

    async def run_all(
        self,
        dataset_names: Optional[list] = None,
        use_mock: bool = False,
    ) -> dict:
        """运行所有/指定数据集评测。"""
        if dataset_names is None:
            dataset_names = [
                "preference_recall",
                "episodic_recall",
                "knowledge_update",
                "temporal_reasoning",
                "abstention_accuracy",
            ]

        all_results = {}
        scores = {}

        for name in dataset_names:
            print(f"\n{'=' * 60}")
            print(f"运行数据集: {name}")
            print(f"{'=' * 60}")

            results = await self.run_dataset(name, use_mock=use_mock)
            all_results[name] = [self._result_to_dict(r) for r in results]

            # 计算分数
            dataset_score = calculate_dataset_score(name, results)
            scores[name] = dataset_score.score

            print(f"  总分: {dataset_score.score:.2%} ({dataset_score.correct}/{dataset_score.total})")

        # 计算总分
        overall = overall_score(scores)

        report = {
            "scores": scores,
            "overall": overall,
            "timestamp": time.time(),
            "results": all_results,
        }

        # 保存历史
        self._save_to_history(report)

        return report

    def _result_to_dict(self, result: EvaluationResult) -> dict:
        """将 EvaluationResult 转为字典。"""
        return {
            "test_id": result.test_id,
            "dataset_type": result.dataset_type,
            "expected_behavior": result.expected_behavior,
            "actual_response": result.actual_response,
            "expected_keywords": result.expected_keywords,
            "rejection_expected": result.rejection_expected,
            "judgment": result.judgment,
            "score": result.score,
            "reason": result.reason,
        }

    def _load_history(self) -> list:
        """加载历史分数。"""
        if self.history_path.exists():
            with open(self.history_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return []

    def _save_to_history(self, report: dict) -> None:
        """保存分数到历史。"""
        self.history.append(
            {
                "timestamp": report["timestamp"],
                "scores": report["scores"],
                "overall": report["overall"],
            }
        )
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.history_path, "w", encoding="utf-8") as f:
            json.dump(self.history, f, ensure_ascii=False, indent=2)
