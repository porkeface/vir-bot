"""结构化记忆更新器。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from vir_bot.core.memory.memory_writer import MemoryOperation
from vir_bot.core.memory.semantic_store import SemanticMemoryStore

if TYPE_CHECKING:
    from .verifier import WriteVerifier


class MemoryUpdater:
    """根据结构化操作更新 semantic memory。"""

    def __init__(
        self,
        semantic_store: SemanticMemoryStore,
        enable_versioning: bool = False,
        verifier: "WriteVerifier | None" = None,
    ):
        self.semantic_store = semantic_store
        self.enable_versioning = enable_versioning
        self.verifier = verifier

    async def apply(self, *, user_id: str, operations: list[MemoryOperation], source_message_id: str | None = None) -> None:
        # 如果启用了验证器，先验证操作
        if self.verifier:
            verified_ops: list[MemoryOperation] = []
            for op in operations:
                passed, reason, suggestion = await self.verifier.verify(op, user_id)
                if passed:
                    verified_ops.append(op)
                else:
                    logger.info(f"Verifier blocked op: {reason} (suggestion: {suggestion})")
                    if suggestion == "candidate":
                        # 标记为候选，仍然写入但标记
                        op.source_text = f"[CANDIDATE] {op.source_text}"
                        verified_ops.append(op)
            operations = verified_ops

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
                    enable_versioning=self.enable_versioning and operation.op == "UPDATE",
                )
            elif operation.op == "DELETE":
                if self.enable_versioning:
                    # 版本模式：标记旧版本为废弃，而不是物理删除
                    existing = self.semantic_store.find_by_predicate(
                        user_id=user_id,
                        namespace=operation.namespace,
                        predicate=operation.predicate,
                    )
                    if existing:
                        existing.valid_to = time.time()
                        existing.is_active = False
                        existing.is_deprecated = True
                        existing.deprecation_reason = "User requested DELETE"
                        existing.updated_at = time.time()
                        self.semantic_store._save()
                        continue

                self.semantic_store.deactivate(
                    user_id=user_id,
                    namespace=operation.namespace,
                    predicate=operation.predicate,
                    object_value=operation.object,
                )
