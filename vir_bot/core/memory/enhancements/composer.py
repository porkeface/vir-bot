"""Memory Composer - 去重 + 冲突消解 + Token Budget。"""

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING

from vir_bot.core.memory.retrieval_router import RetrievalResult
from vir_bot.utils.logger import logger

if TYPE_CHECKING:
    from vir_bot.core.memory.episodic_store import EpisodeRecord
    from vir_bot.core.memory.long_term import MemoryRecord
    from vir_bot.core.memory.question_memory import QuestionMemory
    from vir_bot.core.memory.semantic_store import SemanticMemoryRecord


class MemoryComposer:
    """记忆组合器。

    功能：
    1. 去重：相似度 > threshold 保留高优先级者
    2. 冲突消解：同一事实有矛盾时，按时间新近择优
    3. Token Budget：按优先级截断，不超过 max_tokens
    """

    def __init__(self, config: dict | None = None):
        config = config or {}
        self.enabled = config.get("enabled", False)
        self.max_tokens = config.get("max_tokens", 2000)
        self.dedup_threshold = config.get("dedup_threshold", 0.95)
        self.conflict_strategy = config.get("conflict_strategy", "newest_first")

    def compose(self, result: RetrievalResult) -> str:
        """将 RetrievalResult 组合为上下文字符串。"""
        if not self.enabled:
            return result.to_context_string()

        # 1. 去重
        result = self._deduplicate(result)

        # 2. 冲突消解
        result = self._resolve_conflicts(result)

        # 3. Token Budget 分配
        result = self._apply_token_budget(result)

        # 4. 格式化
        return result.to_context_string()

    # ---- 去重 ----

    def _deduplicate(self, result: RetrievalResult) -> RetrievalResult:
        """对各类记录分别去重。"""
        result.semantic_records = self._dedup_semantic(result.semantic_records)
        result.episodic_records = self._dedup_by_similarity(
            result.episodic_records,
            key_fn=lambda r: r.summary,
        )
        result.question_records = self._dedup_by_similarity(
            result.question_records,
            key_fn=lambda r: r.question_text,
            extra_key_fn=lambda r: r.answer_summary,
        )
        # long_term_records 交给下游格式化处理，此处不做去重
        return result

    def _dedup_semantic(self, records: list["SemanticMemoryRecord"]) -> list:
        """SemanticMemoryRecord 去重：按 (namespace, predicate, object) 精确匹配。"""
        seen: dict[tuple, object] = {}
        for rec in records:
            key = (rec.namespace, rec.predicate, rec.object)
            if key in seen:
                if self._record_priority(rec) > self._record_priority(seen[key]):
                    seen[key] = rec
            else:
                seen[key] = rec
        return list(seen.values())

    def _dedup_by_similarity(
        self, records: list, key_fn, extra_key_fn=None
    ) -> list:
        """基于文本相似度去重（token 重叠率）。"""
        if not records:
            return records

        def tokenize(text: str) -> set:
            return set(re.findall(r'[\w一-鿿]+', text.lower()))

        keep = []
        for rec in records:
            text = key_fn(rec)
            if extra_key_fn:
                text += " " + extra_key_fn(rec)

            is_dup = False
            for kept_rec in keep:
                kept_text = key_fn(kept_rec)
                if extra_key_fn:
                    kept_text += " " + extra_key_fn(kept_rec)

                tokens_a = tokenize(text)
                tokens_b = tokenize(kept_text)

                if tokens_a and tokens_b:
                    overlap = len(tokens_a & tokens_b) / max(len(tokens_a), 1)
                    if overlap > self.dedup_threshold:
                        is_dup = True
                        if self._record_priority(rec) > self._record_priority(kept_rec):
                            keep.remove(kept_rec)
                            keep.append(rec)
                        break

            if not is_dup:
                keep.append(rec)

        return keep

    # ---- 冲突消解 ----

    def _resolve_conflicts(self, result: RetrievalResult) -> RetrievalResult:
        """对语义记忆做冲突消解。"""
        result.semantic_records = self._resolve_semantic_conflicts(result.semantic_records)
        return result

    def _resolve_semantic_conflicts(self, records: list["SemanticMemoryRecord"]) -> list:
        """相同 (namespace, predicate) 不同 object 视为冲突，保留最优。"""
        groups: dict[tuple, list] = {}
        for rec in records:
            key = (rec.namespace, rec.predicate)
            groups.setdefault(key, []).append(rec)

        result = []
        for key, group in groups.items():
            if len(group) == 1:
                result.append(group[0])
                continue

            if self.conflict_strategy == "newest_first":
                group.sort(key=lambda r: r.updated_at, reverse=True)
            elif self.conflict_strategy == "highest_confidence":
                group.sort(key=lambda r: r.confidence, reverse=True)
            else:
                group.sort(key=lambda r: self._record_priority(r), reverse=True)

            result.append(group[0])
            if len(group) > 1:
                dropped = [r.object for r in group[1:]]
                logger.debug(f"冲突消解 {key}: 保留 {group[0].object}，丢弃 {dropped}")

        return result

    def _record_priority(self, rec) -> float:
        """计算记录优先级 = 置信度/重要性 × 时间衰减。"""
        base = getattr(rec, 'confidence', getattr(rec, 'importance', 0.5))

        now = time.time()
        ts = getattr(
            rec, 'updated_at',
            getattr(rec, 'timestamp', getattr(rec, 'created_at', now))
        )
        age_hours = (now - ts) / 3600
        time_factor = max(0.5, 1.0 - age_hours / (24 * 7))

        return base * time_factor

    # ---- Token Budget ----

    def _apply_token_budget(self, result: RetrievalResult) -> RetrievalResult:
        """按优先级保留记录，不超过 max_tokens。"""
        all_items: list[tuple] = []  # (source_type, record, priority)

        for rec in result.semantic_records:
            all_items.append(("semantic", rec, self._record_priority(rec)))
        for rec in result.episodic_records:
            all_items.append(("episodic", rec, self._record_priority(rec)))
        for rec in result.question_records:
            all_items.append(("question", rec, self._record_priority(rec)))
        for rec in result.long_term_records:
            all_items.append(("long_term", rec, self._record_priority(rec)))

        all_items.sort(key=lambda x: x[2], reverse=True)

        keep_semantic = []
        keep_episodic = []
        keep_question = []
        keep_long_term = []
        estimated_tokens = 0

        for source_type, rec, _ in all_items:
            text = self._record_to_text(rec, source_type)
            tokens = self._estimate_tokens(text)

            if estimated_tokens + tokens > self.max_tokens:
                break

            estimated_tokens += tokens
            if source_type == "semantic":
                keep_semantic.append(rec)
            elif source_type == "episodic":
                keep_episodic.append(rec)
            elif source_type == "question":
                keep_question.append(rec)
            elif source_type == "long_term":
                keep_long_term.append(rec)

        result.semantic_records = keep_semantic
        result.episodic_records = keep_episodic
        result.question_records = keep_question
        result.long_term_records = keep_long_term

        logger.debug(f"Token budget: {estimated_tokens}/{self.max_tokens} tokens used")
        return result

    def _record_to_text(self, rec, source_type: str) -> str:
        if source_type == "semantic":
            return f"用户{rec.predicate}：{rec.object}"
        elif source_type == "episodic":
            return rec.summary
        elif source_type == "question":
            return f"问：{rec.question_text} 答：{rec.answer_summary}"
        elif source_type == "long_term":
            return rec.content
        return ""

    def _estimate_tokens(self, text: str) -> int:
        """估算 token 数，优先使用 tiktoken。"""
        try:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(text))
        except ImportError:
            chinese = sum(1 for c in text if '一' <= c <= '鿿')
            other = len(text) - chinese
            return int(chinese / 1.5 + other / 4)
