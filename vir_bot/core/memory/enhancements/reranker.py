"""Re-Ranker - Cross-Encoder 重排序器。"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from vir_bot.core.memory.retrieval_router import RetrievalResult
from vir_bot.utils.logger import logger

if TYPE_CHECKING:
    from vir_bot.core.memory.episodic_store import EpisodeRecord
    from vir_bot.core.memory.long_term import MemoryRecord
    from vir_bot.core.memory.question_memory import QuestionMemory
    from vir_bot.core.memory.semantic_store import SemanticMemoryRecord


@dataclass
class RecordScore:
    """记录及其相关性分数。"""

    record: object  # SemanticMemoryRecord | EpisodeRecord | QuestionMemory | MemoryRecord
    source_type: str  # "semantic" | "episodic" | "question" | "long_term"
    text_for_ranking: str
    base_score: float  # 原始置信度/重要性
    rerank_score: float = 0.0


class ReRanker:
    """Cross-Encoder 重排序器。

    设计要点：
    1. 懒加载模型（首次使用时加载）
    2. 回退策略（模型加载失败时使用原顺序 + base_score）
    3. 统一不同记录类型的文本表示
    """

    def __init__(self, config: dict | None = None):
        config = config or {}
        self.model_name = config.get("model", "cross-encoder/ms-marco-MiniLM-L-6-v2")
        self.top_k = config.get("top_k", 5)
        self.enabled = config.get("enabled", False)
        self._model = None
        self._load_error = False
        self._load_error_msg = None

    async def _ensure_model_loaded(self) -> bool:
        """懒加载 CrossEncoder 模型。"""
        if self._model is not None:
            return True
        if self._load_error:
            return False

        try:
            from sentence_transformers import CrossEncoder
            import asyncio

            loop = asyncio.get_event_loop()
            self._model = await loop.run_in_executor(
                None,
                lambda: CrossEncoder(self.model_name, max_length=512),
            )
            logger.info(f"ReRanker model loaded: {self.model_name}")
            return True
        except ImportError as e:
            self._load_error = True
            self._load_error_msg = f"sentence_transformers not installed: {e}"
            logger.warning(self._load_error_msg)
            return False
        except Exception as e:
            self._load_error = True
            self._load_error_msg = f"Failed to load ReRanker model: {e}"
            logger.warning(self._load_error_msg)
            return False

    def _collect_and_unify(self, query: str, result: RetrievalResult) -> list[RecordScore]:
        """收集所有记录并统一为 (query, document) 格式。"""
        records = []

        # Semantic records
        for rec in result.semantic_records:
            records.append(RecordScore(
                record=rec,
                source_type="semantic",
                text_for_ranking=self._semantic_to_text(rec),
                base_score=rec.confidence,
            ))

        # Episodic records
        for rec in result.episodic_records:
            records.append(RecordScore(
                record=rec,
                source_type="episodic",
                text_for_ranking=self._episodic_to_text(rec),
                base_score=rec.importance,
            ))

        # Question records
        for rec in result.question_records:
            records.append(RecordScore(
                record=rec,
                source_type="question",
                text_for_ranking=self._question_to_text(rec),
                base_score=rec.importance,
            ))

        # Long-term records
        for rec in result.long_term_records:
            records.append(RecordScore(
                record=rec,
                source_type="long_term",
                text_for_ranking=self._long_term_to_text(rec),
                base_score=rec.importance,
            ))

        return records

    def _semantic_to_text(self, rec: "SemanticMemoryRecord") -> str:
        if rec.source_text:
            return rec.source_text
        return f"用户{rec.predicate}：{rec.object}"

    def _episodic_to_text(self, rec: "EpisodeRecord") -> str:
        return rec.summary

    def _question_to_text(self, rec: "QuestionMemory") -> str:
        parts = [f"问：{rec.question_text}"]
        if rec.answer_summary:
            parts.append(f"答：{rec.answer_summary}")
        return " ".join(parts)

    def _long_term_to_text(self, rec: "MemoryRecord") -> str:
        return rec.content

    async def rerank(self, query: str, result: RetrievalResult) -> RetrievalResult:
        """对检索结果进行重排序。"""
        if not self.enabled:
            return result

        all_records = self._collect_and_unify(query, result)

        if not all_records:
            return result

        model_loaded = await self._ensure_model_loaded()

        if model_loaded and self._model:
            pairs = [(query, r.text_for_ranking) for r in all_records]
            try:
                import asyncio
                loop = asyncio.get_event_loop()
                scores = await loop.run_in_executor(
                    None,
                    lambda: self._model.predict(pairs),
                )
                for rec_score, score in zip(all_records, scores):
                    rec_score.rerank_score = float(score)
            except Exception as e:
                logger.warning(f"ReRanker prediction failed, falling back: {e}")
                for rec_score in all_records:
                    rec_score.rerank_score = rec_score.base_score
        else:
            # 回退：使用 base_score + 关键词匹配
            self._simple_rerank(query, all_records)

        # 按 rerank_score 降序排序
        all_records.sort(key=lambda x: x.rerank_score, reverse=True)

        # 更新 RetrievalResult（取 top_k）
        self._update_result(result, all_records[: self.top_k])

        return result

    def _simple_rerank(self, query: str, records: list[RecordScore]) -> None:
        """基于关键词匹配的简单 reranking（回退方案）。"""
        query_tokens = set(re.findall(r'[\w一-鿿]+', query.lower()))
        for rec in records:
            text_tokens = set(re.findall(r'[\w一-鿿]+', rec.text_for_ranking.lower()))
            if query_tokens and text_tokens:
                overlap = len(query_tokens & text_tokens) / max(len(query_tokens), 1)
                rec.rerank_score = rec.base_score + overlap * 0.5
            else:
                rec.rerank_score = rec.base_score

    def _update_result(self, result: RetrievalResult, ranked: list[RecordScore]) -> None:
        """将重排序后的记录写回 RetrievalResult。"""
        result.semantic_records = []
        result.episodic_records = []
        result.question_records = []
        result.long_term_records = []

        for rec_score in ranked:
            if rec_score.source_type == "semantic":
                result.semantic_records.append(rec_score.record)
            elif rec_score.source_type == "episodic":
                result.episodic_records.append(rec_score.record)
            elif rec_score.source_type == "question":
                result.question_records.append(rec_score.record)
            elif rec_score.source_type == "long_term":
                result.long_term_records.append(rec_score.record)
