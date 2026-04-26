"""测试语义记忆的版本管理功能。"""

from __future__ import annotations

import pytest
import time

from vir_bot.core.memory.semantic_store import SemanticMemoryRecord, SemanticMemoryStore


@pytest.fixture
def store() -> SemanticMemoryStore:
    """创建一个临时存储。"""
    store = SemanticMemoryStore(persist_path="./data/memory/test_semantic_temp.json")
    store._records.clear()
    yield store
    # 清理
    store._records.clear()
    store._save()


@pytest.fixture
def sample_record() -> SemanticMemoryRecord:
    """创建一个示例记录。"""
    return SemanticMemoryRecord(
        user_id="test_user",
        namespace="profile.preference",
        subject="user",
        predicate="likes",
        object="火锅",
        confidence=0.9,
        source_text="我喜欢吃火锅",
    )


class TestSemanticMemoryRecordVersioning:
    """测试 SemanticMemoryRecord 的版本字段。"""

    def test_default_version_fields(self, sample_record):
        """测试默认版本字段。"""
        assert sample_record.valid_from > 0
        assert sample_record.valid_to is None
        assert sample_record.previous_version_id is None
        assert sample_record.version_number == 1
        assert sample_record.confidence_history == []
        assert sample_record.is_deprecated is False
        assert sample_record.deprecation_reason is None

    def test_from_dict_backward_compatible(self):
        """测试从旧格式字典加载（向后兼容）。"""
        old_data = {
            "memory_id": "test-id",
            "user_id": "user1",
            "namespace": "profile.identity",
            "subject": "user",
            "predicate": "name_is",
            "object": "张三",
            "confidence": 0.8,
            "source_text": "我叫张三",
            "source_message_id": None,
            "created_at": 1234567890.0,
            "updated_at": 1234567890.0,
            "is_active": True,
            # 没有版本字段
        }

        record = SemanticMemoryRecord.from_dict(old_data)
        assert record.memory_id == "test-id"
        assert record.user_id == "user1"
        # 版本字段应该有默认值
        assert record.valid_from > 0
        assert record.version_number == 1


class TestSemanticMemoryStoreVersioning:
    """测试 SemanticMemoryStore 的版本管理功能。"""

    def test_create_new_version(self, store):
        """测试创建新版本。"""
        # 创建初始版本
        v1 = store.upsert(
            user_id="user1",
            namespace="profile.preference",
            subject="user",
            predicate="likes",
            object_value="火锅",
            confidence=0.9,
            source_text="我喜欢火锅",
        )

        assert v1.version_number == 1
        assert v1.valid_to is None
        assert v1.is_active is True

        # 创建新版本（通过 _create_new_version）
        v2 = store._create_new_version(
            old_record=v1,
            new_object="日料",
            confidence=0.8,
            source_text="我现在喜欢日料",
            source_message_id=None,
        )

        # 检查新版本
        assert v2.version_number == 2
        assert v2.previous_version_id == v1.memory_id
        assert v2.object == "日料"
        assert v2.is_active is True

        # 检查旧版本
        assert v1.valid_to is not None
        assert v1.is_active is False

    def test_upsert_with_versioning(self, store):
        """测试启用版本管理时的 upsert。"""
        # 第一次写入
        r1 = store.upsert(
            user_id="user1",
            namespace="profile.preference",
            subject="user",
            predicate="likes",
            object_value="火锅",
            confidence=0.9,
            source_text="我喜欢火锅",
        )

        # 第二次写入相同 predicate 但不同值，应该创建新版本
        r2 = store.upsert(
            user_id="user1",
            namespace="profile.preference",
            subject="user",
            predicate="likes",
            object_value="日料",
            confidence=0.8,
            source_text="我现在喜欢日料",
            enable_versioning=True,
        )

        # 应该创建新版本
        assert r2.memory_id != r1.memory_id
        assert r2.version_number == 2
        assert r2.previous_version_id == r1.memory_id
        assert r2.object == "日料"

        # 旧版本应该被关闭
        assert r1.valid_to is not None
        assert r1.is_active is False

    def test_get_version_chain(self, store):
        """测试获取版本链。"""
        # 创建多个版本
        v1 = store.upsert(
            user_id="user1",
            namespace="profile.preference",
            subject="user",
            predicate="likes",
            object_value="火锅",
            confidence=0.9,
            source_text="我喜欢火锅",
        )

        v2 = store._create_new_version(v1, "日料", 0.8, "现在喜欢日料", None)
        v3 = store._create_new_version(v2, "西餐", 0.85, "最近喜欢西餐", None)

        # 获取版本链（从最新开始）
        chain = store.get_version_chain(v3.memory_id)
        assert len(chain) == 3
        assert chain[0].memory_id == v3.memory_id
        assert chain[1].memory_id == v2.memory_id
        assert chain[2].memory_id == v1.memory_id

    def test_get_valid_at(self, store):
        """测试在特定时间点查询有效版本。"""
        # 创建版本1
        v1 = store.upsert(
            user_id="user1",
            namespace="profile.preference",
            subject="user",
            predicate="likes",
            object_value="火锅",
            confidence=0.9,
            source_text="我喜欢火锅",
        )
        time1 = v1.valid_from

        # 等待一小段时间
        time.sleep(0.01)

        # 创建版本2
        v2 = store._create_new_version(v1, "日料", 0.8, "现在喜欢日料", None)
        time2 = v2.valid_from

        # 查询 time1 时的有效版本
        result = store.get_valid_at("user1", "likes", time1)
        assert result is not None
        assert result.object == "火锅"

        # 查询 time2 时的有效版本
        result = store.get_valid_at("user1", "likes", time2)
        assert result is not None
        assert result.object == "日料"

    def test_deprecate(self, store):
        """测试标记记忆为废弃。"""
        v1 = store.upsert(
            user_id="user1",
            namespace="profile.preference",
            subject="user",
            predicate="likes",
            object_value="火锅",
            confidence=0.9,
            source_text="我喜欢火锅",
        )

        assert v1.is_deprecated is False

        result = store.deprecate(v1.memory_id, "用户纠正")
        assert result is True
        assert v1.is_deprecated is True
        assert v1.deprecation_reason == "用户纠正"

    def test_deprecate_nonexistent(self, store):
        """测试标记不存在的记忆为废弃。"""
        result = store.deprecate("nonexistent-id", "reason")
        assert result is False
