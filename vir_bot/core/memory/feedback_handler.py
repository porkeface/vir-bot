"""用户反馈处理器。"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from vir_bot.utils.logger import logger

if TYPE_CHECKING:
    from .semantic_store import SemanticMemoryRecord, SemanticMemoryStore


class FeedbackHandler:
    """处理用户纠正反馈，调整记忆置信度或触发更新。"""

    def __init__(self, semantic_store: SemanticMemoryStore):
        self.semantic_store = semantic_store
        self._correction_history: dict[str, list[float]] = {}

    async def handle_correction(
        self,
        user_id: str,
        predicate: str,
        new_value: str | None,
        reason: str,
    ) -> str:
        """
        处理用户纠正。
        返回操作类型：'confidence_reduced' | 'updated' | 'noop'
        """
        existing = self.semantic_store.search(
            user_id=user_id,
            query=predicate,
            top_k=1,
        )

        if not existing:
            logger.info(f"No existing memory found for predicate: {predicate}")
            return "noop"

        # 记录纠正历史
        key = f"{user_id}:{predicate}"
        if key not in self._correction_history:
            self._correction_history[key] = []
        self._correction_history[key].append(time.time())

        # 连续两次纠正 → 自动 UPDATE
        recent = [
            t for t in self._correction_history[key]
            if time.time() - t < 86400  # 24小时内
        ]

        if len(recent) >= 2 and new_value:
            old = existing[0]
            try:
                self.semantic_store.upsert(
                    user_id=user_id,
                    namespace=old.namespace,
                    subject=old.subject,
                    predicate=predicate,
                    object_value=new_value,
                    confidence=0.8,
                    source_text=f"User correction: {reason}",
                    enable_versioning=True,
                )
                logger.info(f"Auto-updated predicate {predicate} to {new_value}")
                return "updated"
            except ValueError as e:
                logger.error(f"Failed to auto-update: {e}")
                return "noop"

        # 单次纠正 → 降低置信度
        for record in existing:
            record.confidence *= 0.3
            record.is_deprecated = True
            record.deprecation_reason = reason
            if not record.confidence_history:
                record.confidence_history = [record.confidence]
            record.confidence_history.append(record.confidence)
            record.updated_at = time.time()

        self.semantic_store._save()
        logger.info(f"Reduced confidence for predicate {predicate}: {reason}")
        return "confidence_reduced"

    def get_correction_count(self, user_id: str, predicate: str) -> int:
        """获取纠正次数（24小时内）。"""
        key = f"{user_id}:{predicate}"
        if key not in self._correction_history:
            return 0
        recent = [
            t for t in self._correction_history[key]
            if time.time() - t < 86400
        ]
        return len(recent)
