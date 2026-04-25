"""Tests for MemoryManager - context building and memory injection."""

import pytest
from unittest.mock import AsyncMock, Mock, patch, MagicMock


class TestMemoryManagerInit:
    """Test MemoryManager initialization."""

    def test_init_with_defaults(self, memory_manager):
        """Test basic initialization."""
        assert memory_manager is not None
        assert memory_manager.window_size == 10
        assert memory_manager.retrieval_router is not None

    def test_init_with_features(self):
        """Test initialization with features config."""
        from vir_bot.core.memory.memory_manager import MemoryManager
        from vir_bot.core.memory.short_term import ShortTermMemory
        from vir_bot.core.memory.long_term import LongTermMemory
        from vir_bot.core.memory.semantic_store import SemanticMemoryStore
        from vir_bot.core.memory.memory_writer import MemoryWriter
        from vir_bot.core.memory.memory_updater import MemoryUpdater
        from vir_bot.core.memory.episodic_store import EpisodicMemoryStore
        from vir_bot.core.memory.question_memory import QuestionMemoryStore
        import tempfile
        import os

        with tempfile.TemporaryDirectory() as tmp:
            semantic = SemanticMemoryStore(persist_path=os.path.join(tmp, "semantic.json"))
            episodic = EpisodicMemoryStore()
            question = QuestionMemoryStore(persist_path=os.path.join(tmp, "question.json"))
            short_term = ShortTermMemory(max_turns=20)
            long_term = MagicMock()
            writer = MemoryWriter(ai_provider=Mock())
            updater = MemoryUpdater(semantic_store=semantic)

            mm = MemoryManager(
                short_term=short_term,
                long_term=long_term,
                semantic_store=semantic,
                memory_writer=writer,
                memory_updater=updater,
                episodic_store=episodic,
                question_store=question,
                features={"reranker": {"enabled": True}},
            )

            assert mm._is_feature_enabled("reranker") is True
            assert mm._is_feature_enabled("nonexistent") is False


class TestBuildEnhancedSystemPrompt:
    """Test system prompt building with memory injection."""

    @pytest.mark.asyncio
    async def test_includes_time_constraint(self, memory_manager):
        """Test that system prompt includes current time."""
        with patch("vir_bot.core.memory.memory_manager.datetime") as mock_dt:
            import datetime

            mock_dt.now.return_value = datetime.datetime(2025, 4, 25, 14, 30, 0)

            result = await memory_manager.build_enhanced_system_prompt(
                current_query="现在几点了",
                base_system_prompt="你是一个助手",
                user_id="test_user",
            )

            assert "2025年04月25日 14:30:00" in result
            assert "绝对行为准则" in result

    @pytest.mark.asyncio
    async def test_no_memory_context_when_none(self, memory_manager):
        """Test that prompt works without memory context."""
        with patch.object(
            memory_manager,
            "_build_query_specific_memory_context",
            new_callable=AsyncMock,
        ) as mock_ctx:
            mock_ctx.return_value = None

            result = await memory_manager.build_enhanced_system_prompt(
                current_query="你好",
                base_system_prompt="你是一个助手",
                user_id="test_user",
            )

            # 绝对行为准则中包含"【记忆检索结果】"作为示例，这里只检查基础提示词
            assert "你是一个助手" in result


class TestBuildContext:
    """Test build_context method used by Pipeline."""

    @pytest.mark.asyncio
    async def test_returns_system_and_conversation(self, memory_manager):
        """Test that build_context returns correct tuple."""
        with patch.object(
            memory_manager,
            "build_enhanced_system_prompt",
            new_callable=AsyncMock,
        ) as mock_build:
            mock_build.return_value = "系统提示词"

            system, conv = await memory_manager.build_context(
                current_query="测试",
                system_prompt="基础提示词",
                user_id="test_user",
            )

            assert system == "系统提示词"
            assert isinstance(conv, list)


class TestIsFeatureEnabled:
    """Test _is_feature_enabled helper."""

    def test_enabled_feature(self):
        """Test that enabled feature returns True."""
        from vir_bot.core.memory.memory_manager import MemoryManager
        import tempfile
        import os

        with tempfile.TemporaryDirectory() as tmp:
            from vir_bot.core.memory.semantic_store import SemanticMemoryStore
            from vir_bot.core.memory.short_term import ShortTermMemory
            from vir_bot.core.memory.memory_writer import MemoryWriter
            from vir_bot.core.memory.memory_updater import MemoryUpdater

            semantic = SemanticMemoryStore(persist_path=os.path.join(tmp, "s.json"))
            writer = MemoryWriter(ai_provider=Mock())
            mm = MemoryManager(
                short_term=ShortTermMemory(max_turns=20),
                long_term=MagicMock(),
                semantic_store=semantic,
                memory_writer=writer,
                memory_updater=MemoryUpdater(semantic_store=semantic),
                features={"test_feature": {"enabled": True}},
            )

            assert mm._is_feature_enabled("test_feature") is True
            assert mm._is_feature_enabled("nonexistent") is False
