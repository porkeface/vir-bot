"""结构化记忆更新器。"""

from __future__ import annotations

from vir_bot.core.memory.memory_writer import MemoryOperation
from vir_bot.core.memory.semantic_store import SemanticMemoryStore


class MemoryUpdater:
    """根据结构化操作更新 semantic memory。"""

    def __init__(self, semantic_store: SemanticMemoryStore):
        self.semantic_store = semantic_store

    def apply(self, *, user_id: str, operations: list[MemoryOperation], source_message_id: str | None = None) -> None:
        for operation in operations:
            if operation.op in {"ADD", "UPDATE"}:
                self.semantic_store.upsert(
                    user_id=user_id,
                    namespace=operation.namespace,
                    subject=operation.subject,
                    predicate=operation.predicate,
                    object_value=operation.object,
                    confidence=operation.confidence,
                    source_text=operation.source_text,
                    source_message_id=source_message_id,
                    replace_predicate=(operation.op == "UPDATE"),
                )
            elif operation.op == "DELETE":
                self.semantic_store.deactivate(
                    user_id=user_id,
                    namespace=operation.namespace,
                    predicate=operation.predicate,
                    object_value=operation.object,
                )
