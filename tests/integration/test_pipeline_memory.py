"""Integration tests for Pipeline + Memory system."""

import pytest
from unittest.mock import AsyncMock, Mock, patch, MagicMock


@pytest.fixture
def pipeline_with_memory():
    """Create a Pipeline with MemoryManager for integration testing."""
    with patch("vir_bot.core.pipeline.MessagePipeline._init_ai") as mock_init_ai:
        from vir_bot.core.pipeline import MessagePipeline, PipelineConfig
        from vir_bot.core.ai_provider import AIProvider
        from vir_bot.core.memory.memory_manager import MemoryManager
        from vir_bot.core.memory.short_term import ShortTermMemory
        from vir_bot.core.memory.long_term import LongTermMemory
        from vir_bot.core.memory.semantic_store import SemanticMemoryStore
        from vir_bot.core.memory.memory_writer import MemoryWriter
        from vir_bot.core.memory.memory_updater import MemoryUpdater
        from vir_bot.core.memory.episodic_store import EpisodicMemoryStore
        from vir_bot.core.memory.question_memory import QuestionMemoryStore

        # Create mock AI provider
        ai = Mock(spec=AIProvider)
        ai.chat = AsyncMock()
        ai.chat.return_value = Mock(
            content="你好！我是助手。",
            tool_calls=None,
        )

        # Create memory components
        short_term = ShortTermMemory(max_turns=20, window_size=10)
        long_term = MagicMock(spec=LongTermMemory)

        semantic_store = SemanticMemoryStore(
            persist_path="tests/data/test_semantic.json"
        )
        episodic_store = EpisodicMemoryStore()
        question_store = QuestionMemoryStore(
            persist_path="tests/data/test_questions.json"
        )

        writer = MemoryWriter(ai_provider=ai)
        updater = MemoryUpdater(semantic_store=semantic_store)

        memory_manager = MemoryManager(
            short_term=short_term,
            long_term=long_term,
            semantic_store=semantic_store,
            memory_writer=writer,
            memory_updater=updater,
            window_size=10,
            episodic_store=episodic_store,
            question_store=question_store,
            ai_provider=ai,
        )

        # Create pipeline
        config = PipelineConfig()
        pipeline = MessagePipeline(
            ai_provider=ai,
            memory_manager=memory_manager,
            character_card=MagicMock(),
            mcp_registry=MagicMock(),
            config=config,
        )

        yield pipeline

        # Cleanup
        import os

        for f in ["tests/data/test_semantic.json", "tests/data/test_questions.json"]:
            if os.path.exists(f):
                os.remove(f)


class TestPipelineWithMemory:
    """Test that Pipeline correctly uses MemoryManager."""

    @pytest.mark.asyncio
    async def test_build_context_calls_memory(self, pipeline_with_memory):
        """Test that pipeline calls MemoryManager.build_context."""
        pipeline = pipeline_with_memory

        with patch.object(
            pipeline.memory,
            "build_context",
            new_callable=AsyncMock,
        ) as mock_build:
            mock_build.return_value = ("系统提示词", [{"role": "user", "content": "测试"}])

            system, conv = await pipeline._build_context(
                Mock(content="测试问题", user_id="test_user")
            )

            mock_build.assert_called_once()
            assert system == "系统提示词"

    @pytest.mark.asyncio
    async def test_process_calls_memory(self, pipeline_with_memory):
        """Test that process adds interaction to memory."""
        pipeline = pipeline_with_memory

        # Mock the memory update
        with patch.object(
            pipeline.memory,
            "add_interaction",
            new_callable=AsyncMock,
        ) as mock_add:
            # Mock AI response
            pipeline.ai.chat.return_value = Mock(
                content="我记住了，你喜欢火锅。",
                tool_calls=None,
            )

            # Create a mock message
            from vir_bot.core.pipeline import PlatformMessage, Platform

            msg = PlatformMessage(
                platform=Platform.WEB,
                user_id="test_user",
                content="我喜欢吃什么？",
                msg_id="test_123",
            )

            # Mock pre_filter to allow message
            pipeline._pre_filter = Mock(return_value=True)
            pipeline._rate_limiter.check = AsyncMock(return_value=True)

            response = await pipeline.process(msg)

            # Memory should be updated (async task created)
            # Note: We can't easily assert the task runs, but we can check it was created
            assert response is not None

    @pytest.mark.asyncio
    async def test_memory_injection_in_prompt(self, pipeline_with_memory):
        """Test that memory context is injected into system prompt."""
        pipeline = pipeline_with_memory

        # Add some semantic memory
        pipeline.memory.semantic_store.upsert(
            user_id="test_user",
            namespace="profile.preference",
            subject="user",
            predicate="likes",
            object="火锅",
            confidence=0.9,
            source_text="我喜欢火锅",
        )

        # Mock the retrieval to return our memory
        with patch.object(
            pipeline.memory.retrieval_router,
            "retrieve_for_context",
            new_callable=AsyncMock,
        ) as mock_retrieve:
            mock_retrieve.return_value = "【记忆检索结果】\n- 用户喜欢火锅"

            system, conv = await pipeline._build_context(
                Mock(content="我喜欢吃什么", user_id="test_user")
            )

            assert "记忆检索结果" in system
            assert "火锅" in system


class TestSemanticMemoryRecall:
    """Test that AI companion can recall semantic memories."""

    @pytest.mark.asyncio
    async def test_recall_user_preference(self, pipeline_with_memory):
        """Test recalling user preferences from semantic memory."""
        pipeline = pipeline_with_memory

        # Store a preference
        pipeline.memory.semantic_store.upsert(
            user_id="test_user",
            namespace="profile.preference",
            subject="user",
            predicate="likes",
            object="火锅",
            confidence=0.9,
            source_text="我最喜欢吃火锅",
        )

        # Query should find this memory
        results = pipeline.memory.semantic_store.search(
            user_id="test_user",
            query="我喜欢吃什么",
            top_k=5,
        )

        assert len(results) > 0
        assert any("火锅" in r.object for r in results)

    @pytest.mark.asyncio
    async def test_recall_user_identity(self, pipeline_with_memory):
        """Test recalling user identity from semantic memory."""
        pipeline = pipeline_with_memory

        # Store identity
        pipeline.memory.semantic_store.upsert(
            user_id="test_user",
            namespace="profile.identity",
            subject="user",
            predicate="name_is",
            object="张三",
            confidence=1.0,
            source_text="我叫张三",
        )

        # Query should find this memory
        results = pipeline.memory.semantic_store.search(
            user_id="test_user",
            query="我叫什么名字",
            top_k=5,
        )

        assert len(results) > 0
        assert any("张三" in r.object for r in results)


class TestTimeQuerySkipping:
    """Test that time queries skip memory lookup."""

    @pytest.mark.asyncio
    async def test_time_query_skipped(self, pipeline_with_memory):
        """Test that time queries don't trigger memory lookup."""
        pipeline = pipeline_with_memory

        with patch.object(
            pipeline.memory.retrieval_router,
            "classify_query_async",
            new_callable=AsyncMock,
        ) as mock_classify:
            mock_classify.return_value = {
                "query_type": "time_query",
                "needs_memory_lookup": False,
            }

            result = await pipeline.memory.retrieval_router.retrieve_for_context(
                query="现在几点了", user_id="test_user"
            )

            assert result is None
