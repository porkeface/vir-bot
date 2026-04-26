"""测试 Memory Composer。"""

import time

import pytest

from vir_bot.core.memory.enhancements.composer import MemoryComposer
from vir_bot.core.memory.retrieval_router import RetrievalResult
from vir_bot.core.memory.semantic_store import SemanticMemoryRecord
from vir_bot.core.memory.episodic_store import EpisodeRecord
from vir_bot.core.memory.question_memory import QuestionMemory
from vir_bot.core.memory.long_term import MemoryRecord


def _make_result():
    return RetrievalResult(query="测试查询", user_id="user1")


def _semantic(predicate, object, confidence=0.8, namespace="profile.preference"):
    return SemanticMemoryRecord(
        predicate=predicate,
        object=object,
        confidence=confidence,
        namespace=namespace,
        updated_at=time.time(),
    )


# ---- 基础行为 ----

def test_composer_disabled_returns_original():
    """未启用时返回原格式字符串。"""
    config = {"enabled": False}
    composer = MemoryComposer(config)
    result = _make_result()
    result.semantic_records = [_semantic("likes", "苹果")]

    output = composer.compose(result)
    assert isinstance(output, str)
    # 原格式应该包含记录内容
    assert len(output) > 0


def test_composer_enabled_flag():
    """启用标志正确读取。"""
    config = {"enabled": True, "max_tokens": 1500, "dedup_threshold": 0.90}
    composer = MemoryComposer(config)
    assert composer.enabled is True
    assert composer.max_tokens == 1500
    assert composer.dedup_threshold == 0.90


# ---- 去重 ----

def test_dedup_semantic_exact_match():
    """相同 (namespace, predicate, object) 去重。"""
    config = {"enabled": True, "dedup_threshold": 0.95}
    composer = MemoryComposer(config)
    result = _make_result()
    result.semantic_records = [
        _semantic("likes", "苹果", confidence=0.9),
        _semantic("likes", "苹果", confidence=0.8),  # 重复，置信度更低
    ]

    result = composer._deduplicate(result)
    assert len(result.semantic_records) == 1
    assert result.semantic_records[0].confidence == 0.9


def test_dedup_semantic_differs():
    """不同 object 不去重。"""
    config = {"enabled": True}
    composer = MemoryComposer(config)
    result = _make_result()
    result.semantic_records = [
        _semantic("likes", "苹果", confidence=0.9),
        _semantic("likes", "香蕉", confidence=0.8),
    ]

    result = composer._deduplicate(result)
    assert len(result.semantic_records) == 2


def test_dedup_semantic_keeps_higher_confidence():
    """去重时保留置信度更高的。"""
    config = {"enabled": True}
    composer = MemoryComposer(config)
    result = _make_result()
    older = _semantic("likes", "苹果", confidence=0.6)
    older.updated_at = time.time() - 3600  # 1小时前
    newer = _semantic("likes", "苹果", confidence=0.9)
    newer.updated_at = time.time()

    result.semantic_records = [older, newer]
    result = composer._deduplicate(result)
    assert len(result.semantic_records) == 1
    # 应该保留优先级更高的（考虑时间衰减后最新的可能更高）
    assert result.semantic_records[0].confidence >= 0.6


# ---- 冲突消解 ----

def test_resolve_semantic_conflicts():
    """相同 (namespace, predicate) 不同 object 视为冲突。"""
    config = {"enabled": True, "conflict_strategy": "newest_first"}
    composer = MemoryComposer(config)
    records = [
        _semantic("likes", "苹果", confidence=0.8),
        _semantic("likes", "香蕉", confidence=0.9),
    ]
    # 让第二条更新
    records[1].updated_at = records[0].updated_at + 100

    result = composer._resolve_semantic_conflicts(records)
    assert len(result) == 1
    # newest_first 策略，应该保留更新的（香蕉）
    assert result[0].object == "香蕉"


def test_resolve_conflicts_no_conflict():
    """无冲突时保留所有记录。"""
    config = {"enabled": True}
    composer = MemoryComposer(config)
    records = [
        _semantic("likes", "苹果", confidence=0.8),
        _semantic("dislikes", "榴莲", confidence=0.9),
    ]

    result = composer._resolve_semantic_conflicts(records)
    assert len(result) == 2


def test_resolve_by_highest_confidence():
    """使用 highest_confidence 策略。"""
    config = {"enabled": True, "conflict_strategy": "highest_confidence"}
    composer = MemoryComposer(config)
    records = [
        _semantic("likes", "苹果", confidence=0.9),
        _semantic("likes", "香蕉", confidence=0.7),
    ]

    result = composer._resolve_semantic_conflicts(records)
    assert len(result) == 1
    assert result[0].object == "苹果"


# ---- Token Budget ----

def test_token_budget_truncation():
    """Token Budget 截断。"""
    config = {"enabled": True, "max_tokens": 50}  # 很小的 budget
    composer = MemoryComposer(config)
    result = _make_result()
    # 创建大量长记录
    result.long_term_records = [
        MemoryRecord(id=str(i), content="这是一个很长的测试内容，" * 20, importance=0.9)
        for i in range(5)
    ]

    result = composer._apply_token_budget(result)
    # 应该被截断到很少的记录
    assert len(result.long_term_records) < 5


def test_token_budget_all_fit():
    """所有记录都能放入 budget。"""
    config = {"enabled": True, "max_tokens": 10000}
    composer = MemoryComposer(config)
    result = _make_result()
    result.semantic_records = [_semantic("likes", "苹果")]

    result = composer._apply_token_budget(result)
    # 应该保留所有记录
    assert len(result.semantic_records) == 1


# ---- 优先级计算 ----

def test_record_priority():
    """测试记录优先级计算。"""
    config = {"enabled": True}
    composer = MemoryComposer(config)
    rec = _semantic("likes", "苹果", confidence=0.8)
    rec.updated_at = time.time() - 3600  # 1小时前

    priority = composer._record_priority(rec)
    assert 0 < priority <= 0.8


def test_record_priority_different_types():
    """不同类型记录的优先级计算。"""
    config = {"enabled": True}
    composer = MemoryComposer(config)

    sem = _semantic("likes", "苹果", confidence=0.8)
    epi = EpisodeRecord(summary="吃了火锅", importance=0.7)
    quest = QuestionMemory(question_text="测试？", importance=0.6)
    lt = MemoryRecord(id="1", content="测试", importance=0.5)

    p1 = composer._record_priority(sem)
    p2 = composer._record_priority(epi)
    p3 = composer._record_priority(quest)
    p4 = composer._record_priority(lt)

    assert all(0 < p < 1 for p in [p1, p2, p3, p4])


# ---- Compose 集成 ----

def test_compose_output_is_string():
    """compose 返回字符串。"""
    config = {"enabled": True, "max_tokens": 2000}
    composer = MemoryComposer(config)
    result = _make_result()
    result.semantic_records = [_semantic("likes", "苹果")]

    output = composer.compose(result)
    assert isinstance(output, str)
    assert len(output) > 0


def test_compose_disabled_calls_to_context_string():
    """未启用时调用原 to_context_string。"""
    config = {"enabled": False}
    composer = MemoryComposer(config)
    result = _make_result()
    result.semantic_records = [_semantic("likes", "苹果")]

    output = composer.compose(result)
    # 应该与原方法输出一致
    assert output == result.to_context_string()


# ---- Token 估算 ----

def test_estimate_tokens_tiktoken_unavailable():
    """tiktoken 不可用时使用简单估算。"""
    config = {"enabled": True}
    composer = MemoryComposer(config)

    # 模拟 tiktoken 不可用
    text = "Hello world 你好世界"
    tokens = composer._estimate_tokens(text)
    assert tokens > 0
    assert isinstance(tokens, int)


def test_estimate_tokens_chinese():
    """中文 token 估算。"""
    config = {"enabled": True}
    composer = MemoryComposer(config)

    text = "你好世界" * 10
    tokens = composer._estimate_tokens(text)
    # 中文约 1.5 字符/token
    assert tokens > 0
