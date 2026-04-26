"""评测指标模块单元测试。"""

import pytest
from tests.eval.metrics import (
    judge_correctness,
    preference_recall_score,
    episodic_recall_score,
    knowledge_update_score,
    temporal_reasoning_score,
    abstention_accuracy_score,
    overall_score,
    EvaluationResult,
    DatasetScore,
    REJECTION_KEYWORDS,
)


class TestRejectionKeywords:
    """测试拒答关键词列表。"""

    def test_keywords_not_empty(self):
        """拒答关键词列表不应为空。"""
        assert len(REJECTION_KEYWORDS) > 0

    def test_keywords_cover_common_cases(self):
        """拒答关键词应覆盖常见情况。"""
        assert "不知道" in REJECTION_KEYWORDS
        assert "没记住" in REJECTION_KEYWORDS
        assert "没有找到" in REJECTION_KEYWORDS
        assert "还没有" in REJECTION_KEYWORDS


class TestJudgeCorrectness:
    """测试判断逻辑。"""

    def test_rejection_expected_correct(self):
        """测试期望拒答且正确拒答。"""
        judgment, reason = judge_correctness(
            question="我喜欢吃什么？",
            expected_keywords=[],
            rejection_expected=True,
            actual_response="我还没有记住你的饮食偏好。",
        )
        assert judgment == "correct"
        assert "拒答" in reason

    def test_rejection_expected_wrong(self):
        """测试期望拒答但未拒答。"""
        judgment, reason = judge_correctness(
            question="我喜欢吃什么？",
            expected_keywords=["火锅"],
            rejection_expected=True,
            actual_response="你喜欢吃火锅。",
        )
        assert judgment == "wrong"
        assert "拒答" in reason

    def test_no_rejection_but_rejected(self):
        """测试不应拒答但拒答了。"""
        judgment, reason = judge_correctness(
            question="我喜欢吃什么？",
            expected_keywords=["火锅"],
            rejection_expected=False,
            actual_response="我不知道你喜欢吃什么。",
        )
        assert judgment == "wrong"
        assert "拒答" in reason

    def test_keywords_all_match(self):
        """测试关键词全命中。"""
        judgment, reason = judge_correctness(
            question="我喜欢吃什么？",
            expected_keywords=["火锅", "麻辣"],
            rejection_expected=False,
            actual_response="你最喜欢吃的是火锅，特别喜欢麻辣火锅。",
        )
        assert judgment == "correct"
        assert "全命中" in reason

    def test_keywords_partial_match(self):
        """测试关键词部分命中。"""
        judgment, reason = judge_correctness(
            question="我喜欢吃什么？",
            expected_keywords=["火锅", "麻辣"],
            rejection_expected=False,
            actual_response="你喜欢吃火锅。",
        )
        assert judgment == "wrong"
        assert "未全命中" in reason or "缺失" in reason

    def test_empty_keywords(self):
        """测试无期望关键词。"""
        judgment, reason = judge_correctness(
            question="今天天气如何？",
            expected_keywords=[],
            rejection_expected=False,
            actual_response="今天天气晴朗。",
        )
        assert judgment == "unknown"

    def test_case_insensitive_matching(self):
        """测试关键词大小写不敏感。"""
        judgment, reason = judge_correctness(
            question="我喜欢什么运动？",
            expected_keywords=["NBA", "篮球"],
            rejection_expected=False,
            actual_response="你喜欢NBA篮球。",
        )
        assert judgment == "correct"


class TestScoreCalculations:
    """测试分数计算。"""

    def test_preference_recall_score(self):
        """测试偏好召回分数计算。"""
        results = [
            EvaluationResult(
                test_id="test_1",
                dataset_type="preference_recall",
                expected_behavior="recall",
                actual_response="test",
                expected_keywords=["火锅"],
                rejection_expected=False,
                judgment="correct",
                score=1.0,
                reason="test",
            ),
            EvaluationResult(
                test_id="test_2",
                dataset_type="preference_recall",
                expected_behavior="recall",
                actual_response="test",
                expected_keywords=["篮球"],
                rejection_expected=False,
                judgment="wrong",
                score=0.0,
                reason="test",
            ),
        ]
        score = preference_recall_score(results)
        assert score == 0.5

    def test_empty_results(self):
        """测试空结果列表。"""
        score = preference_recall_score([])
        assert score == 0.0

    def test_overall_score(self):
        """测试总分计算。"""
        scores = {
            "preference_recall": 0.8,
            "episodic_recall": 0.7,
            "knowledge_update": 0.6,
            "temporal_reasoning": 0.9,
            "abstention_accuracy": 0.85,
        }
        overall = overall_score(scores)
        # 0.8*0.25 + 0.7*0.20 + 0.6*0.20 + 0.9*0.20 + 0.85*0.15 = 0.7675
        assert abs(overall - 0.7675) < 0.001

    def test_overall_score_partial(self):
        """测试部分指标的总分计算。"""
        scores = {
            "preference_recall": 1.0,
            "episodic_recall": 1.0,
        }
        overall = overall_score(scores)
        # 1.0*0.25 + 1.0*0.20 = 0.45
        assert abs(overall - 0.45) < 0.001


class TestDatasetScore:
    """测试数据集分数。"""

    def test_dataset_score_creation(self):
        """测试 DatasetScore 创建。"""
        score = DatasetScore(
            dataset_type="test",
            total=10,
            correct=8,
            wrong=2,
            unknown=0,
            score=0.8,
        )
        assert score.total == 10
        assert score.correct == 8
        assert score.score == 0.8
