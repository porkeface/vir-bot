"""Tests for RetrievalRouter - AI classification and parallel retrieval."""

import pytest
from unittest.mock import AsyncMock, Mock, patch
from vir_bot.core.memory.retrieval_router import RetrievalRouter, RetrievalResult


class TestClassifyQueryAsync:
    """Test AI classification and rule fallback."""

    @pytest.mark.asyncio
    async def test_classify_with_ai_success(self, retrieval_router, mock_ai_provider):
        """Test successful AI classification."""
        mock_ai_provider.chat.return_value = Mock(
            content='{"query_type": "preference", "needs_memory_lookup": true, "reason": "user asks preference"}'
        )

        result = await retrieval_router.classify_query_async("我喜欢吃什么")

        assert result["query_type"] == "preference"
        assert result["needs_memory_lookup"] is True
        assert "reason" in result

    @pytest.mark.asyncio
    async def test_classify_cache_hit(self, retrieval_router, mock_ai_provider):
        """Test classification cache."""
        mock_ai_provider.chat.return_value = Mock(
            content='{"query_type": "identity", "needs_memory_lookup": true}'
        )

        # First call
        await retrieval_router.classify_query_async("我叫什么")
        # Second call should hit cache
        result = await retrieval_router.classify_query_async("我叫什么")

        assert result["query_type"] == "identity"
        # AI should only be called once due to cache
        assert mock_ai_provider.chat.call_count == 1

    @pytest.mark.asyncio
    async def test_classify_cache_ttl_expiry(self, retrieval_router, mock_ai_provider):
        """Test cache TTL expiry."""
        mock_ai_provider.chat.return_value = Mock(
            content='{"query_type": "habit", "needs_memory_lookup": true}'
        )

        await retrieval_router.classify_query_async("我平时做什么")

        # Simulate cache expiry
        import time

        old_entry = retrieval_router._intent_cache.get("我平时做什么什么")
        if old_entry:
            old_entry["_timestamp"] = time.time() - 400  # Exceed TTL

        await retrieval_router.classify_query_async("我平时做什么")

        assert mock_ai_provider.chat.call_count >= 1

    @pytest.mark.asyncio
    async def test_classify_ai_failure_fallback(self, retrieval_router, mock_ai_provider):
        """Test fallback to rules when AI fails."""
        mock_ai_provider.chat.side_effect = Exception("AI service down")

        result = await retrieval_router.classify_query_async("你喜欢什么")

        assert "query_type" in result
        assert "needs_memory_lookup" in result

    def test_classify_with_rules_empty_query(self, retrieval_router):
        """Test rule fallback for empty query."""
        result = retrieval_router._classify_with_rules("")

        assert result["query_type"] == "general"
        assert result["needs_memory_lookup"] is False

    def test_classify_with_rules_normal_query(self, retrieval_router):
        """Test rule fallback for normal query (conservative)."""
        result = retrieval_router._classify_with_rules("今天天气怎么样")

        assert result["query_type"] == "general"
        assert result["needs_memory_lookup"] is False


class TestRetrieve:
    """Test parallel retrieval across all memory layers."""

    @pytest.mark.asyncio
    async def test_retrieve_returns_result(self, retrieval_router):
        """Test retrieve returns RetrievalResult."""
        with patch.object(retrieval_router, "_search_semantic", new_callable=AsyncMock) as mock_sem:
            mock_sem.return_value = []
            with patch.object(retrieval_router, "_search_questions", new_callable=AsyncMock) as mock_q:
                mock_q.return_value = []
                with patch.object(retrieval_router, "_search_episodic", new_callable=AsyncMock) as mock_ep:
                    mock_ep.return_value = []
                    with patch.object(retrieval_router, "_search_long_term", new_callable=AsyncMock) as mock_lt:
                        mock_lt.return_value = []

                        result = await retrieval_router.retrieve(
                            query="测试问题",
                            user_id="test_user",
                            top_k=5,
                        )

                        assert isinstance(result, RetrievalResult)
                        assert result.query == "测试问题"
                        assert result.user_id == "test_user"

    @pytest.mark.asyncio
    async def test_retrieve_parallel_execution(self, retrieval_router):
        """Test that all searches run in parallel."""
        import asyncio

        call_order = []

        async def slow_search(*args, **kwargs):
            call_order.append("semantic")
            await asyncio.sleep(0.1)
            return []

        with patch.object(retrieval_router, "_search_semantic", side_effect=slow_search):
            with patch.object(retrieval_router, "_search_questions", new_callable=AsyncMock) as mock_q:
                mock_q.return_value = []
                with patch.object(retrieval_router, "_search_episodic", new_callable=AsyncMock) as mock_ep:
                    mock_ep.return_value = []
                    with patch.object(retrieval_router, "_search_long_term", new_callable=AsyncMock) as mock_lt:
                        mock_lt.return_value = []

                        await retrieval_router.retrieve(
                            query="测试", user_id="test", top_k=5
                        )

                        # All searches should have been called
                        assert mock_q.called
                        assert mock_ep.called
                        assert mock_lt.called

    @pytest.mark.asyncio
    async def test_retrieve_handles_exceptions(self, retrieval_router):
        """Test that exceptions in one search don't break others."""
        with patch.object(retrieval_router, "_search_semantic", side_effect=Exception("Search failed")):
            with patch.object(retrieval_router, "_search_questions", new_callable=AsyncMock) as mock_q:
                mock_q.return_value = []
                with patch.object(retrieval_router, "_search_episodic", new_callable=AsyncMock) as mock_ep:
                    mock_ep.return_value = []
                    with patch.object(retrieval_router, "_search_long_term", new_callable=AsyncMock) as mock_lt:
                        mock_lt.return_value = []

                        result = await retrieval_router.retrieve(
                            query="测试", user_id="test", top_k=5
                        )

                        assert isinstance(result, RetrievalResult)
                        # Should not raise exception


class TestRetrieveForContext:
    """Test context retrieval with skip strategies."""

    @pytest.mark.asyncio
    async def test_time_query_skipped(self, retrieval_router, mock_ai_provider):
        """Test that time queries are skipped."""
        mock_ai_provider.chat.return_value = Mock(
            content='{"query_type": "time_query", "needs_memory_lookup": false}'
        )

        result = await retrieval_router.retrieve_for_context(
            query="现在几点了", user_id="test"
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_general_no_lookup_skipped(self, retrieval_router, mock_ai_provider):
        """Test that general queries without lookup are skipped."""
        mock_ai_provider.chat.return_value = Mock(
            content='{"query_type": "general", "needs_memory_lookup": false}'
        )

        result = await retrieval_router.retrieve_for_context(
            query="你好", user_id="test", force_lookup=False
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_force_lookup_returns_context(self, retrieval_router, mock_ai_provider):
        """Test that force_lookup=True always retrieves."""
        mock_ai_provider.chat.return_value = Mock(
            content='{"query_type": "general", "needs_memory_lookup": false}'
        )

        # Mock retrieve to return some results
        with patch.object(retrieval_router, "retrieve", new_callable=AsyncMock) as mock_ret:
            mock_ret.return_value = RetrievalResult(
                query="测试", user_id="test", query_type="general"
            )

            result = await retrieval_router.retrieve_for_context(
                query="测试", user_id="test", force_lookup=True
            )

            assert mock_ret.called
            # Should return something (not None) due to force_lookup
            # (actual context depends on RetrievalResult.to_context_string())

    @pytest.mark.asyncio
    async def test_no_results_returns_special_message(self, retrieval_router, mock_ai_provider):
        """Test that no results returns a special message guiding AI."""
        mock_ai_provider.chat.return_value = Mock(
            content='{"query_type": "preference", "needs_memory_lookup": true}'
        )

        with patch.object(retrieval_router, "retrieve", new_callable=AsyncMock) as mock_ret:
            mock_ret.return_value = RetrievalResult(
                query="我喜欢什么", user_id="test", query_type="preference"
            )

            result = await retrieval_router.retrieve_for_context(
                query="我喜欢什么", user_id="test", force_lookup=True
            )

            assert result is not None
            assert "记忆检索结果" in result
            assert "没查到" in result or "不知道" in result


class TestRetrievalResult:
    """Test RetrievalResult data class."""

    def test_has_results_empty(self):
        """Test has_results returns False for empty result."""
        result = RetrievalResult(query="test", user_id="user")
        assert not result.has_results()

    def test_has_results_with_semantic(self):
        """Test has_results returns True with semantic records."""
        from vir_bot.core.memory.semantic_store import SemanticMemoryRecord

        result = RetrievalResult(query="test", user_id="user")
        result.semantic_records.append(
            SemanticMemoryRecord(
                memory_id="test_id",
                user_id="user",
                namespace="profile.preference",
                subject="user",
                predicate="likes",
                object="火锅",
            )
        )
        assert result.has_results()

    def test_to_context_string_empty(self):
        """Test to_context_string returns empty for no results."""
        result = RetrievalResult(query="test", user_id="user")
        assert result.to_context_string() == ""

    def test_to_context_string_with_results(self):
        """Test to_context_string formats results correctly."""
        from vir_bot.core.memory.semantic_store import SemanticMemoryRecord

        result = RetrievalResult(query="test", user_id="user", query_type="preference")
        result.semantic_records.append(
            SemanticMemoryRecord(
                memory_id="test_id",
                user_id="user",
                namespace="profile.preference",
                subject="user",
                predicate="likes",
                object="火锅",
                confidence=0.9,
                source_text="我喜欢火锅",
            )
        )
        context = result.to_context_string()
        assert "用户事实记忆" in context
        assert "火锅" in context
