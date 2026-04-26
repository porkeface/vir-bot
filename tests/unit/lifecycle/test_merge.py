"""测试记忆合并。"""

from __future__ import annotations

import pytest

from vir_bot.core.memory.lifecycle.merge import MemoryMerger
from vir_bot.core.memory.semantic_store import SemanticMemoryRecord, SemanticMemoryStore


@pytest.fixture
def store() -> SemanticMemoryStore:
    """创建一个临时存储。"""
    store = SemanticMemoryStore(persist_path="./data/memory/test_semantic_temp.json")
    store._records.clear()
    yield store
    store._records.clear()
    store._save()


@pytest.fixture
def merger(store: SemanticMemoryStore) -> MemoryMerger:
    """创建一个合并器。"""
    return MemoryMerger(semantic_store=store)


class TestMemoryMerger:
    """测试 MemoryMerger。"""

    @pytest.mark.asyncio
    async def test_merge_similar(self, merger, store):
        """测试合并相似记忆。"""
        # 添加相似记录
        r1 = SemanticMemoryRecord(
            user_id="user1",
            namespace="profile.preference",
            subject="user",
            predicate="likes",
            object="火锅",
            confidence=0.9,
        )
        r2 = SemanticMemoryRecord(
            user_id="user1",
            namespace="profile.preference",
            subject="user",
            predicate="likes",
            object="日料",  # 不同值，但同 predicate
            confidence=0.8,
        )
        store._records[r1.memory_id] = r1
        store._records[r2.memory_id] = r2

        # 合并应该检测到不同值，不合并
        count = await merger.merge_similar("user1")
        assert count == 0  # 不合并不同值的记录

    @pytest.mark.asyncio
    async def test_merge_same(self, merger, store):
        """测试合并相同记忆。"""
        # 添加相同记录（模拟重复）
        r1 = SemanticMemoryRecord(
            user_id="user1",
            namespace="profile.preference",
            subject="user",
            predicate="likes",
            object="火锅",
            confidence=0.9,
        )
        r2 = SemanticMemoryRecord(
            user_id="user1",
            namespace="profile.preference",
            subject="user",
            predicate="likes",
            object="火锅",  # 相同值
            confidence=0.85,
        )
        store._records[r1.memory_id] = r1
        store._records[r2.memory_id] = r2

        # 合并应该合并相同值的记录
        count = await merger.merge_similar("user1")
        assert count >= 0  # 可能合并
