"""测试记忆生命周期管理器。"""

from __future__ import annotations

import pytest
import time

from vir_bot.core.memory.lifecycle.janitor import MemoryJanitor
from vir_bot.core.memory.lifecycle.decay import DecayConfig, MemoryDecay
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
def janitor(store: SemanticMemoryStore) -> MemoryJanitor:
    """创建一个生命周期管理器。"""
    config = {"interval_hours": 24}
    decay = MemoryDecay(config=DecayConfig())
    merger = MemoryMerger(semantic_store=store)
    return MemoryJanitor(
        config=config,
        semantic_store=store,
        decay=decay,
        merger=merger,
    )


class TestMemoryJanitor:
    """测试 MemoryJanitor。"""

    def test_get_all_users(self, janitor, store):
        """测试获取所有用户。"""
        r1 = SemanticMemoryRecord(user_id="user1")
        r2 = SemanticMemoryRecord(user_id="user2")
        store._records[r1.memory_id] = r1
        store._records[r2.memory_id] = r2

        users = janitor._get_all_users()
        assert "user1" in users
        assert "user2" in users

    def test_apply_decay(self, janitor, store):
        """测试应用衰减。"""
        record = SemanticMemoryRecord(
            user_id="user1",
            confidence=0.05,  # 非常低
            updated_at=time.time() - 86400 * 100,  # 很久以前
        )
        store._records[record.memory_id] = record

        janitor._apply_decay()
        # 记录应该被标记为不活跃
        assert record.is_active is False

    def test_archive_low_confidence(self, janitor, store):
        """测试归档低置信度记忆。"""
        record = SemanticMemoryRecord(
            user_id="user1",
            confidence=0.05,
            updated_at=time.time() - 86400 * 100,
        )
        store._records[record.memory_id] = record

        janitor._archive_low_confidence()
        # 记录应该被标记为不活跃
        assert record.is_active is False
