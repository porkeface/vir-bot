"""记忆衰减算法。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from vir_bot.utils.logger import logger

if TYPE_CHECKING:
    from vir_bot.core.memory.semantic_store import SemanticMemoryRecord


@dataclass
class DecayConfig:
    """衰减配置。"""
    base_decay_rate: float = 0.01  # 每天衰减率
    importance_factor: float = 0.5  # 重要性影响因子
    access_factor: float = 0.3  # 访问时间影响因子
    min_confidence: float = 0.1  # 最低置信度阈值
    archive_threshold: float = 0.1  # 归档阈值
    delete_threshold: float = 0.05  # 删除阈值


class MemoryDecay:
    """记忆衰减算法。"""

    def __init__(self, config: DecayConfig | None = None):
        self.config = config or DecayConfig()

    def calculate_retention_score(self, record: "SemanticMemoryRecord") -> float:
        """计算留存分数。"""
        score = record.confidence

        days_since_access = (time.time() - record.updated_at) / 86400

        # 基础衰减
        decay = self.config.base_decay_rate * days_since_access

        # 重要性减缓衰减
        if hasattr(record, "importance") and record.importance:
            decay *= max(0, 1 - self.config.importance_factor * record.importance)

        score = max(0, score - decay)
        return min(1, score)

    def apply_decay(self, record: "SemanticMemoryRecord") -> str:
        """
        应用衰减，返回是否需要归档/删除。
        返回: 'keep' | 'archive' | 'delete'
        """
        if not record.is_active:
            return "keep"  # 已经不活跃，跳过

        score = self.calculate_retention_score(record)
        record.confidence = score

        if score <= self.config.delete_threshold:
            return "delete"
        elif score <= self.config.archive_threshold:
            return "archive"
        return "keep"
