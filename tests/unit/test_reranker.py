"""测试 Re-Ranker。"""

import pytest
import time

from vir_bot.core.memory.enhancements.reranker import ReRanker, RecordScore
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
    )


# ---- 基础行为 ----

def test_reranker_disabled_returns_original():
    """未启用时返回原结果。"""
    config = {"enabled": False}
    reranker = ReRanker(config)
    result = _make_result()
    result.semantic_records = [_semantic("likes", "苹果", confidence=0.9)]

    # 同步方式测试 disabled 状态
    assert reranker.enabled is False
    # 未启用时 rerank 应该返回原结果
    import asyncio
    reranked = asyncio.run(reranker.rerank("水果", result))
    assert len(reranked.semantic_records) == 1
    assert reranked.semantic_records[0].object == "苹果"


def test_reranker_enabled_flag():
    """启用标志正确读取。"""
    config = {"enabled": True, "model": "cross-encoder/ms-marco-MiniLM-L-6-v2", "top_k": 3}
    reranker = ReRanker(config)
    assert reranker.enabled is True
    assert reranker.top_k == 3


# ---- 记录格式统一 ----

def test_collect_and_unify_semantic():
    """SemanticMemoryRecord 统一格式。"""
    config = {"enabled": False}
    reranker = ReRanker(config)
    result = _make_result()
    result.semantic_records = [
        _semantic("likes", "苹果", confidence=0.9, namespace="profile.preference"),
    ]

    records = reranker._collect_and_unify("测试", result)
    assert len(records) == 1
    assert records[0].source_type == "semantic"
    assert "苹果" in records[0].text_for_ranking
    assert records[0].base_score == 0.9


def test_collect_and_unify_episodic():
    """EpisodeRecord 统一格式。"""
    config = {"enabled": False}
    reranker = ReRanker(config)
    result = _make_result()
    result.episodic_records = [
        EpisodeRecord(summary="用户吃了火锅", importance=0.7),
    ]

    records = reranker._collect_and_unify("测试", result)
    assert len(records) == 1
    assert records[0].source_type == "episodic"
    assert "火锅" in records[0].text_for_ranking


def test_collect_and_unify_question():
    """QuestionMemory 统一格式。"""
    config = {"enabled": False}
    reranker = ReRanker(config)
    result = _make_result()
    result.question_records = [
        QuestionMemory(
            question_text="我喜欢吃什么？",
            answer_summary="火锅",
            importance=0.8,
        ),
    ]

    records = reranker._collect_and_unify("测试", result)
    assert len(records) == 1
    assert records[0].source_type == "question"
    assert "喜欢" in records[0].text_for_ranking


def test_collect_and_unify_long_term():
    """MemoryRecord 统一格式。"""
    config = {"enabled": False}
    reranker = ReRanker(config)
    result = _make_result()
    result.long_term_records = [
        MemoryRecord(id="1", content="用户说喜欢火锅", importance=0.6),
    ]

    records = reranker._collect_and_unify("测试", result)
    assert len(records) == 1
    assert records[0].source_type == "long_term"
    assert "火锅" in records[0].text_for_ranking


def test_collect_all_record_types():
    """收集所有四种记录类型。"""
    config = {"enabled": False}
    reranker = ReRanker(config)
    result = _make_result()
    result.semantic_records = [_semantic("likes", "苹果")]
    result.episodic_records = [EpisodeRecord(summary="吃了火锅")]
    result.question_records = [QuestionMemory(question_text="测试")]
    result.long_term_records = [MemoryRecord(id="1", content="测试内容")]

    records = reranker._collect_and_unify("测试", result)
    assert len(records) == 4
    types = {r.source_type for r in records}
    assert types == {"semantic", "episodic", "question", "long_term"}


# ---- 文本转换 ----

def test_semantic_to_text_with_source():
    """有 source_text 时优先使用。"""
    config = {"enabled": False}
    reranker = ReRanker(config)
    rec = _semantic("likes", "苹果")
    rec.source_text = "用户说：我最喜欢苹果"
    text = reranker._semantic_to_text(rec)
    assert "用户说" in text


def test_semantic_to_text_without_source():
    """无 source_text 时组合 predicate + object。"""
    config = {"enabled": False}
    reranker = ReRanker(config)
    rec = _semantic("likes", "苹果")
    text = reranker._semantic_to_text(rec)
    assert "喜欢" in text or "likes" in text


# ---- 简单重排序（回退方案） ----

def test_simple_rerank():
    """测试关键词回退排序。"""
    config = {"enabled": False}
    reranker = ReRanker(config)
    result = _make_result()
    # 苹果 confidence 更高，且查询命中苹果
    result.semantic_records = [
        _semantic("likes", "苹果", confidence=0.9),
        _semantic("likes", "香蕉", confidence=0.5),
    ]

    records = reranker._collect_and_unify("苹果很好吃", result)
    reranker._simple_rerank("苹果很好吃", records)

    # 包含"苹果"的记录应该得到更高分数（有 overlap 加成）
    apple_rec = [r for r in records if "苹果" in r.text_for_ranking][0]
    banana_rec = [r for r in records if "香蕉" in r.text_for_ranking][0]
    assert apple_rec.rerank_score > banana_rec.rerank_score


# ---- 更新结果 ----

def test_update_result():
    """测试将重排序结果写回 RetrievalResult。"""
    config = {"enabled": False}
    reranker = ReRanker(config)
    result = _make_result()

    records = [
        RecordScore(_semantic("likes", "苹果"), "semantic", "用户喜欢苹果", 0.9, 0.95),
        RecordScore(_semantic("likes", "香蕉"), "semantic", "用户喜欢香蕉", 0.8, 0.85),
        RecordScore(EpisodeRecord(summary="吃了火锅"), "episodic", "吃了火锅", 0.7, 0.75),
    ]

    reranker._update_result(result, records)

    assert len(result.semantic_records) == 2
    assert len(result.episodic_records) == 1
    assert len(result.question_records) == 0
    assert len(result.long_term_records) == 0


def test_update_result_empty():
    """空记录列表清空所有结果。"""
    config = {"enabled": False}
    reranker = ReRanker(config)
    result = _make_result()
    result.semantic_records = [_semantic("likes", "苹果")]

    reranker._update_result(result, [])

    assert len(result.semantic_records) == 0


# ---- 异步重排序 ----

@pytest.mark.asyncio
async def test_rerank_disabled_returns_same_result():
    """未启用时 rerank 返回原结果。"""
    config = {"enabled": False}
    reranker = ReRanker(config)
    result = _make_result()
    result.semantic_records = [_semantic("likes", "苹果", confidence=0.9)]

    reranked = await reranker.rerank("水果", result)
    assert len(reranked.semantic_records) == 1
    assert reranked.semantic_records[0].object == "苹果"


@pytest.mark.asyncio
async def test_rerank_empty_result():
    """空结果不报错。"""
    config = {"enabled": True}
    reranker = ReRanker(config)
    result = _make_result()

    reranked = await reranker.rerank("查询", result)
    assert reranked.has_results() is False


@pytest.mark.asyncio
async def test_rerank_fallback_on_error(monkeypatch):
    """模型加载失败时回退到 base_score。"""
    config = {"enabled": True, "model": "nonexistent-model", "top_k": 3}
    reranker = ReRanker(config)

    # 模拟模型加载失败
    reranker._load_error = True
    reranker._model = None

    result = _make_result()
    result.semantic_records = [
        _semantic("likes", "苹果", confidence=0.9),
        _semantic("likes", "香蕉", confidence=0.7),
    ]

    reranked = await reranker.rerank("水果", result)
    # 应该不报错，返回结果
    assert len(reranked.semantic_records) == 2
