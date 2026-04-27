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
        embedding_model: str = "all-MiniLM-L6-v2",
    ):
        self.semantic_store = semantic_store
        self.episodic_store = episodic_store
        self.embedding_model_name = embedding_model
        self._model = None
        self._model_error = False
        self._sim_threshold = 0.85  # 语义相似度阈值

    async def _ensure_model_loaded(self) -> bool:
        """懒加载 embedding 模型。"""
        if self._model is not None:
            return True
        if self._model_error:
            return False
        try:
            from sentence_transformers import SentenceTransformer
            import asyncio
            loop = asyncio.get_event_loop()
            self._model = await loop.run_in_executor(
                None,
                lambda: SentenceTransformer(self.embedding_model_name),
            )
            logger.info(f"Verifier embedding model loaded: {self.embedding_model_name}")
            return True
        except Exception as e:
            self._model_error = True
            logger.warning(f"Failed to load embedding model: {e}")
            return False

    def _cosine_similarity(self, vec1, vec2) -> float:
        """计算余弦相似度。"""
        import numpy as np
        v1 = np.array(vec1)
        v2 = np.array(vec2)
        return float(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-8))

    async def _semantic_similarity(self, text1: str, text2: str) -> float:
        """计算两段文本的语义相似度。"""
        if not await self._ensure_model_loaded():
            return 0.0
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            embeddings = await loop.run_in_executor(
                None,
                lambda: self._model.encode([text1, text2]),
            )
            return self._cosine_similarity(embeddings[0], embeddings[1])
        except Exception as e:
            logger.warning(f"Similarity computation failed: {e}")
            return 0.0

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
        """查找语义相似的现有记忆（基于 embedding 相似度）。"""
        candidates = self.semantic_store.search(
            user_id=user_id,
            query=op.object,
            top_k=5,
        )
        if not candidates:
            return None

        best = None
        best_sim = 0.0
        for rec in candidates:
            sim = await self._semantic_similarity(op.object, rec.object)
            if sim > best_sim and sim >= self._sim_threshold:
                best_sim = sim
                best = rec

        if best:
            logger.info(f"Found similar memory: {best.object} (sim={best_sim:.3f})")
        return best

    async def _check_conflict(
        self,
        op: "MemoryOperation",
        user_id: str,
    ) -> "SemanticMemoryRecord | None":
        """检查是否与现有高置信度记忆冲突（基于语义相似度）。"""
        existing = self.semantic_store.search(
            user_id=user_id,
            query=op.predicate,
            top_k=10,
        )
        for record in existing:
            if record.confidence > 0.8 and record.object != op.object:
                # 使用语义相似度确认是同一谓词的不同值
                sim = await self._semantic_similarity(op.object, record.object)
                if sim >= self._sim_threshold:
                    logger.info(
                        f"Conflict detected: {record.object} vs {op.object} (sim={sim:.3f})"
                    )
                    return record
        return None
