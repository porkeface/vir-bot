"""测试记忆衰减算法。"""

from __future__ import annotations

import pytest
import time

from vir_bot.core.memory.lifecycle.decay import DecayConfig, MemoryDecay
from vir_bot.core.memory.semantic_store import SemanticMemoryRecord


class TestDecayConfig:
    """测试 DecayConfig。"""

    def test_defaults(self):
        """测试默认配置。"""
        config = DecayConfig()
        assert config.base_decay_rate == 0.01
        assert config.importance_factor == 0.5
        assert config.access_factor == 0.3
        assert config.min_confidence == 0.1
        assert config.archive_threshold == 0.1
        assert config.delete_threshold == 0.05


class TestMemoryDecay:
    """测试 MemoryDecay。"""

    def test_calculate_retention_score(self):
        """测试计算留存分数。"""
        config = DecayConfig()
        decay = MemoryDecay(config=config)

        record = SemanticMemoryRecord(
            confidence=0.8,
            updated_at=time.time() - 86400,  # 1天前
        )

        score = decay.calculate_retention_score(record)
        assert 0 < score <= 0.8  # 应该衰减

    def test_apply_decay_keep(self):
        """测试应用衰减 - 保持。"""
        config = DecayConfig()
        decay = MemoryDecay(config=config)

        record = SemanticMemoryRecord(
            confidence=0.8,
            updated_at=time.time() - 86400 * 2,  # 2天前
        )

        action = decay.apply_decay(record)
        assert action == "keep"
        assert record.confidence < 0.8  # 置信度降低

    def test_apply_decay_archive(self):
        """测试应用衰减 - 归档。"""
        config = DecayConfig()
        decay = MemoryDecay(config=config)

        record = SemanticMemoryRecord(
            confidence=0.1,  # 低置信度
            updated_at=time.time() - 86400 * 2,
        )

        action = decay.apply_decay(record)
        assert action == "archive"

    def test_apply_decay_delete(self):
        """测试应用衰减 - 删除。"""
        config = DecayConfig()
        decay = MemoryDecay(config=config)

        record = SemanticMemoryRecord(
            confidence=0.03,  # 非常低置信度
            updated_at=time.time() - 86400 * 2,
        )

        action = decay.apply_decay(record)
        assert action == "delete"
