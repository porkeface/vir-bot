"""评测指标计算模块。"""

from dataclasses import dataclass, field
from typing import Optional

# 拒答关键词列表
REJECTION_KEYWORDS = [
    "不知道",
    "没记住",
    "还没有",
    "没有记住",
    "没有这条记录",
    "不清楚",
    "没有相关信息",
    "没有找到",
    "没有查到",
    "不记得",
    "没告诉",
    "没有告诉过",
    "没有提",
    "尚无记录",
]


@dataclass
class EvaluationResult:
    """单条评测结果。"""

    test_id: str
    dataset_type: str
    expected_behavior: str
    actual_response: str
    expected_keywords: list
    rejection_expected: bool

    # 计算结果
    judgment: str = "unknown"
    score: float = 0.0
    reason: str = ""


@dataclass
class DatasetScore:
    """数据集级别评分。"""

    dataset_type: str
    total: int
    correct: int
    wrong: int
    unknown: int
    score: float

    details: list = field(default_factory=list)


def judge_correctness(
    question: str,
    expected_keywords: list,
    rejection_expected: bool,
    actual_response: str,
) -> tuple:
    """
    判断回答正确性。

    策略：
    - 拒答判断：检查是否包含拒绝关键词
    - 召回判断：关键词全命中（AND 逻辑）

    返回:
        (judgment, reason)
    """
    response_lower = actual_response.strip().lower()

    # 1. 检测是否拒答
    is_rejection = any(kw in response_lower for kw in REJECTION_KEYWORDS)

    # 2. 期望拒答
    if rejection_expected:
        if is_rejection:
            return ("correct", "正确拒答")
        else:
            return (
                "wrong",
                "应拒答但未拒答，期望拒答但得到了: %s..." % actual_response[:50],
            )

    # 3. 不应拒答但拒答了
    if is_rejection:
        return ("wrong", "不应拒答但拒答了: %s..." % actual_response[:50])

    # 4. 关键词匹配（AND 逻辑：必须全部命中）
    if not expected_keywords:
        return ("unknown", "无期望关键词，无法判断")

    matched = [kw for kw in expected_keywords if kw.lower() in response_lower]
    if len(matched) == len(expected_keywords):
        return ("correct", "关键词全命中: %s" % matched)
    else:
        missing = [
            kw for kw in expected_keywords if kw.lower() not in response_lower
        ]
        return ("wrong", "关键词未全命中，缺失: %s" % missing)


def calculate_dataset_score(
    dataset_type: str,
    results: list,
) -> DatasetScore:
    """计算数据集级别分数。"""
    correct = sum(1 for r in results if r.judgment == "correct")
    wrong = sum(1 for r in results if r.judgment == "wrong")
    unknown = sum(1 for r in results if r.judgment == "unknown")
    total = len(results)

    score = correct / total if total > 0 else 0.0

    return DatasetScore(
        dataset_type=dataset_type,
        total=total,
        correct=correct,
        wrong=wrong,
        unknown=unknown,
        score=score,
        details=results,
    )


def preference_recall_score(results: list) -> float:
    """偏好召回率：能正确回忆用户偏好的比例。"""
    return calculate_dataset_score("preference_recall", results).score


def episodic_recall_score(results: list) -> float:
    """事件回忆率：能正确回忆历史事件的比例。"""
    return calculate_dataset_score("episodic_recall", results).score


def knowledge_update_score(results: list) -> float:
    """知识更新准确率：更新后能获取最新信息的比例。"""
    return calculate_dataset_score("knowledge_update", results).score


def temporal_reasoning_score(results: list) -> float:
    """时间推理准确率：正确处理时间相关查询的比例。"""
    return calculate_dataset_score("temporal_reasoning", results).score


def abstention_accuracy_score(results: list) -> float:
    """拒答准确率：对于不存在的记忆，正确回答"不知道"的比例。"""
    return calculate_dataset_score("abstention_accuracy", results).score


def overall_score(scores: dict, weights: Optional[dict] = None) -> float:
    """
    计算加权平均总分。
    """
    if weights is None:
        weights = {
            "preference_recall": 0.25,
            "episodic_recall": 0.20,
            "knowledge_update": 0.20,
            "temporal_reasoning": 0.20,
            "abstention_accuracy": 0.15,
        }

    total_weight = 0.0
    weighted_sum = 0.0

    for key, weight in weights.items():
        if key in scores:
            weighted_sum += scores[key] * weight

    return weighted_sum
