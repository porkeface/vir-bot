"""相似记忆合并。"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from vir_bot.utils.logger import logger

if TYPE_CHECKING:
    from vir_bot.core.memory.semantic_store import SemanticMemoryRecord, SemanticMemoryStore


class MemoryMerger:
    """相似记忆合并。"""

    def __init__(
        self,
        semantic_store: "SemanticMemoryStore",
        similarity_threshold: float = 0.95,
    ):
        self.store = semantic_store
        self.threshold = similarity_threshold

    async def merge_similar(
        self,
        user_id: str,
        namespace: str | None = None,
    ) -> int:
        """合并相似记忆，返回合并数量。"""
        records = self.store.list_by_user(user_id)
        if namespace:
            records = [r for r in records if r.namespace == namespace]

        if not records:
            return 0

        merged_count = 0
        # 按 predicate:namespace:object 分组，只合并完全相同的记录
        grouped: dict[str, list["SemanticMemoryRecord"]] = {}
        for r in records:
            key = f"{r.predicate}:{r.namespace}:{r.object}"
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(r)

        for key, group in grouped.items():
            if len(group) <= 1:
                continue

            # 简单去重：保留置信度最高的，合并其他信息
            primary = max(group, key=lambda r: r.confidence)
            for other in group:
                if other.memory_id == primary.memory_id:
                    continue

                # 合并 source_text
                if other.source_text not in primary.source_text:
                    primary.source_text += f" | {other.source_text}"

                # 合并置信度历史
                if other.confidence_history:
                    primary.confidence_history.extend(other.confidence_history)

                # 标记旧记录为不活跃
                other.is_active = False
                other.updated_at = time.time()
                merged_count += 1

        if merged_count > 0:
            self.store.save()
            logger.info(f"Merged {merged_count} similar records for {user_id}")

        return merged_count
