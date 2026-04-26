"""测试写入前验证器。"""

from __future__ import annotations

import pytest
import time

from vir_bot.core.memory.semantic_store import SemanticMemoryRecord, SemanticMemoryStore
from vir_bot.core.memory.verifier import WriteVerifier
from vir_bot.core.memory.memory_writer import MemoryOperation


@pytest.fixture
def store() -> SemanticMemoryStore:
    """创建一个临时存储。"""
    store = SemanticMemoryStore(persist_path="./data/memory/test_semantic_temp.json")
    store._records.clear()
    yield store
    store._records.clear()
    store._save()


@pytest.fixture
def verifier(store: SemanticMemoryStore) -> WriteVerifier:
    """创建一个验证器。"""
    return WriteVerifier(semantic_store=store)


class TestWriteVerifier:
    """测试 WriteVerifier。"""

    @pytest.mark.asyncio
    async def test_verify_add_no_conflict(self, verifier, store):
        """测试 ADD 操作无冲突（空存储）。"""
        # 不添加任何记录，应该无冲突
        op = MemoryOperation(
            op="ADD",
            namespace="profile.preference",
            subject="user",
            predicate="likes",
            object="日料",
            confidence=0.8,
            source_text="我喜欢吃日料",
        )

        passed, reason, suggestion = await verifier.verify(op, "user1")
        assert passed is True
        assert suggestion == "proceed"

    @pytest.mark.asyncio
    async def test_verify_add_duplicate(self, verifier, store):
        """测试 ADD 操作检测到重复。"""
        # 添加一条记录
        record = SemanticMemoryRecord(
            user_id="user1",
            namespace="profile.preference",
            subject="user",
            predicate="likes",
            object="火锅",
            confidence=0.9,
        )
        store._records[record.memory_id] = record

        op = MemoryOperation(
            op="ADD",
            namespace="profile.preference",
            subject="user",
            predicate="likes",
            object="火锅",  # 相同的值
            confidence=0.9,
            source_text="我喜欢吃火锅",
        )

        passed, reason, suggestion = await verifier.verify(op, "user1")
        assert passed is False
        assert "重复" in reason
        assert suggestion == "candidate"

    @pytest.mark.asyncio
    async def test_verify_update_exists(self, verifier, store):
        """测试 UPDATE 操作存在记录。"""
        op = MemoryOperation(
            op="UPDATE",
            namespace="profile.preference",
            subject="user",
            predicate="likes",
            object="日料",
            confidence=0.8,
            source_text="我喜欢吃日料",
        )

        # 没有记录，应该失败
        passed, reason, suggestion = await verifier.verify(op, "user1")
        assert passed is False
        assert "没有找到" in reason
        assert suggestion == "block"

    @pytest.mark.asyncio
    async def test_verify_delete_exists(self, verifier, store):
        """测试 DELETE 操作存在记录。"""
        op = MemoryOperation(
            op="DELETE",
            namespace="profile.preference",
            subject="user",
            predicate="likes",
            object="火锅",
            confidence=0.9,
            source_text="",
        )

        # 没有记录，应该失败
        passed, reason, suggestion = await verifier.verify(op, "user1")
        assert passed is False
        assert "没有找到" in reason
        assert suggestion == "block"
