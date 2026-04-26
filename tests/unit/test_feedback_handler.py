"""测试用户反馈处理器。"""

from __future__ import annotations

import pytest
import time

from vir_bot.core.memory.feedback_handler import FeedbackHandler
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
def handler(store: SemanticMemoryStore) -> FeedbackHandler:
    """创建一个反馈处理器。"""
    return FeedbackHandler(store)


class TestFeedbackHandler:
    """测试 FeedbackHandler。"""

    @pytest.mark.asyncio
    async def test_handle_correction_no_memory(self, handler, store):
        """测试纠正不存在的记忆。"""
        result = await handler.handle_correction(
            user_id="user1",
            predicate="likes",
            new_value="日料",
            reason="用户说不喜欢火锅",
        )
        assert result == "noop"

    @pytest.mark.asyncio
    async def test_handle_correction_first_time(self, handler, store):
        """测试第一次纠正：降低置信度。"""
        # 创建记忆
        record = SemanticMemoryRecord(
            user_id="user1",
            namespace="profile.preference",
            subject="user",
            predicate="likes",
            object="火锅",
            confidence=0.9,
            source_text="我喜欢火锅",
        )
        store._records[record.memory_id] = record

        # 第一次纠正
        result = await handler.handle_correction(
            user_id="user1",
            predicate="likes",
            new_value="日料",
            reason="用户说不喜欢火锅",
        )

        assert result == "confidence_reduced"
        assert record.confidence < 0.9  # 置信度应该降低
        assert record.confidence == pytest.approx(0.27, rel=0.01)  # 0.9 * 0.3
        assert record.is_deprecated is True
        assert record.deprecation_reason == "用户说不喜欢火锅"

    @pytest.mark.asyncio
    async def test_handle_correction_second_time(self, handler, store):
        """测试第二次纠正（24小时内）：自动更新。"""
        # 创建记忆
        record = SemanticMemoryRecord(
            user_id="user1",
            namespace="profile.preference",
            subject="user",
            predicate="likes",
            object="火锅",
            confidence=0.9,
            source_text="我喜欢火锅",
        )
        store._records[record.memory_id] = record

        # 第一次纠正
        await handler.handle_correction(
            user_id="user1",
            predicate="likes",
            new_value=None,  # 不提供新值
            reason="第一次纠正",
        )

        # 第二次纠正（立即，在24小时内）
        result = await handler.handle_correction(
            user_id="user1",
            predicate="likes",
            new_value="日料",
            reason="第二次纠正",
        )

        # 应该触发自动更新
        assert result == "updated"

        # 应该创建新版本
        active = store.list_by_user("user1")
        assert len(active) == 1
        assert active[0].object == "日料"
        assert active[0].version_number == 2

    @pytest.mark.asyncio
    async def test_handle_correction_across_time(self, handler, store):
        """测试跨时间的纠正（超过24小时不算连续）。"""
        # 创建记忆
        record = SemanticMemoryRecord(
            user_id="user1",
            namespace="profile.preference",
            subject="user",
            predicate="likes",
            object="火锅",
            confidence=0.9,
            source_text="我喜欢火锅",
        )
        store._records[record.memory_id] = record

        # 模拟第一次纠正在很久以前
        key = "user1:likes"
        handler._correction_history[key] = [time.time() - 86400 * 2]  # 2天前

        # 现在的纠正应该不算连续
        result = await handler.handle_correction(
            user_id="user1",
            predicate="likes",
            new_value=None,
            reason="现在的纠正",
        )

        assert result == "confidence_reduced"

    def test_get_correction_count(self, handler):
        """测试获取纠正次数。"""
        # 初始为0
        count = handler.get_correction_count("user1", "likes")
        assert count == 0

        # 记录一次纠正
        handler._correction_history["user1:likes"] = [time.time()]
        count = handler.get_correction_count("user1", "likes")
        assert count == 1

        # 记录多次纠正
        handler._correction_history["user1:likes"].append(time.time())
        count = handler.get_correction_count("user1", "likes")
        assert count == 2
