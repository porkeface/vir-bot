"""写入前验证：重复检测 + 冲突检测。"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from vir_bot.utils.logger import logger

if TYPE_CHECKING:
    from vir_bot.core.memory.memory_writer import MemoryOperation
    from vir_bot.core.memory.semantic_store import SemanticMemoryRecord, SemanticMemoryStore


class WriteVerifier:
    """写入前验证器。"""

    def __init__(
        self,
        semantic_store: "SemanticMemoryStore",
        episodic_store: "EpisodicMemoryStore | None" = None,
    ):
        self.semantic_store = semantic_store
        self.episodic_store = episodic_store

    async def verify(
        self,
        operation: "MemoryOperation",
        user_id: str,
    ) -> tuple[bool, str, str]:
        """
        验证写入操作。
        返回: (通过?, 原因, 建议操作)
        建议操作: 'proceed' | 'candidate' | 'block'
        """
        if operation.op == "ADD":
            # 重复检测：语义相似度比对
            similar = await self._find_similar(operation, user_id)
            if similar and similar.confidence > 0.8:
                return False, f"与现有记忆重复: {similar.object}", "candidate"

            # 冲突检测：与高置信度记忆矛盾
            conflict = await self._check_conflict(operation, user_id)
            if conflict:
                return (
                    False,
                    f"与高置信度记忆冲突: {conflict.object}",
                    "candidate",
                )

        elif operation.op == "UPDATE":
            # 检查是否存在要更新的记录
            existing = self.semantic_store.search(
                user_id=user_id,
                query=operation.predicate,
                top_k=1,
            )
            if not existing:
                return False, "没有找到要更新的记录", "block"

        elif operation.op == "DELETE":
            # 检查是否存在要删除的记录
            existing = self.semantic_store.search(
                user_id=user_id,
                query=operation.predicate,
                top_k=1,
            )
            if not existing:
                return False, "没有找到要删除的记录", "block"

        return True, "通过", "proceed"

    async def _find_similar(
        self,
        op: "MemoryOperation",
        user_id: str,
    ) -> "SemanticMemoryRecord | None":
        """查找语义相似的现有记忆。"""
        results = self.semantic_store.search(
            user_id=user_id,
            query=op.object,
            top_k=1,
        )
        if results:
            return results[0]
        return None

    async def _check_conflict(
        self,
        op: "MemoryOperation",
        user_id: str,
    ) -> "SemanticMemoryRecord | None":
        """检查是否与现有高置信度记忆冲突。"""
        existing = self.semantic_store.search(
            user_id=user_id,
            query=op.predicate,
            top_k=5,
        )
        for record in existing:
            if record.confidence > 0.8 and record.object != op.object:
                return record
        return None
