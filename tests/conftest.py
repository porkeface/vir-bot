"""pytest configuration and shared fixtures."""

import pytest
from unittest.mock import Mock, AsyncMock, MagicMock
from pathlib import Path
import tempfile


@pytest.fixture
def temp_data_dir():
    """临时数据目录 fixture。"""
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.fixture
def semantic_store(temp_data_dir):
    """SemanticMemoryStore fixture。"""
    from vir_bot.core.memory.semantic_store import SemanticMemoryStore

    path = temp_data_dir / "semantic_memory.json"
    return SemanticMemoryStore(persist_path=str(path))


@pytest.fixture
def episodic_store():
    """EpisodicMemoryStore fixture。"""
    from vir_bot.core.memory.episodic_store import EpisodicMemoryStore

    return EpisodicMemoryStore()


@pytest.fixture
def question_store(temp_data_dir):
    """QuestionMemoryStore fixture。"""
    from vir_bot.core.memory.question_memory import QuestionMemoryStore

    path = temp_data_dir / "question_memory.json"
    return QuestionMemoryStore(persist_path=str(path))


@pytest.fixture
def short_term():
    """ShortTermMemory fixture。"""
    from vir_bot.core.memory.short_term import ShortTermMemory

    return ShortTermMemory(max_turns=20)


@pytest.fixture
def long_term_mock():
    """Mock LongTermMemory fixture (avoid ChromaDB dependency in tests)."""
    mock = MagicMock()
    mock.search = AsyncMock(return_value=[])
    mock.add = AsyncMock()
    return mock


@pytest.fixture
def mock_ai_provider():
    """Mock AI Provider for testing。"""
    provider = Mock()
    provider.chat = AsyncMock()
    provider.chat.return_value = Mock(
        content='{"query_type": "general", "needs_memory_lookup": False, "reason": "test"}'
    )
    return provider


@pytest.fixture
def retrieval_router(semantic_store, episodic_store, question_store, long_term_mock, mock_ai_provider):
    """RetrievalRouter fixture。"""
    from vir_bot.core.memory.retrieval_router import RetrievalRouter

    router = RetrievalRouter(
        semantic_store=semantic_store,
        episodic_store=episodic_store,
        question_store=question_store,
        long_term=long_term_mock,
        ai_provider=mock_ai_provider,
    )
    return router


@pytest.fixture
def memory_manager(short_term, long_term_mock, semantic_store, mock_ai_provider):
    """MemoryManager fixture。"""
    from vir_bot.core.memory.memory_manager import MemoryManager
    from vir_bot.core.memory.memory_writer import MemoryWriter
    from vir_bot.core.memory.memory_updater import MemoryUpdater

    writer = MemoryWriter(ai_provider=mock_ai_provider)
    updater = MemoryUpdater(semantic_store=semantic_store)

    return MemoryManager(
        short_term=short_term,
        long_term=long_term_mock,
        semantic_store=semantic_store,
        memory_writer=writer,
        memory_updater=updater,
        window_size=10,
        episodic_store=episodic_store,
        ai_provider=mock_ai_provider,
    )
