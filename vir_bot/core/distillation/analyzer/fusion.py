# -*- coding: utf-8 -*-
"""
FusionEngine — 统计结果与 LLM 分析结果的融合

职责：
1. 将 StyleAnalyzer 的精确统计数据注入 PersonaProfile
2. 检测 LLM 输出与统计数据之间的矛盾
3. 生成最终的融合人格描述
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from vir_bot.core.distillation.analyzer.extractor import PersonaProfile, SpeakingStyle
from vir_bot.core.distillation.analyzer.style_analyzer import StyleStats

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 矛盾检测结果
# ---------------------------------------------------------------------------


@dataclass
class Contradiction:
    """一个矛盾点。"""
    field: str
    llm_claim: str
    stats_evidence: str
    severity: str  # "high", "medium", "low"
    resolution: str  # "use_stats", "use_llm", "flagged"


@dataclass
class FusionResult:
    """融合结果。"""
    profile: PersonaProfile
    contradictions: List[Contradiction] = field(default_factory=list)
    stats_injected: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# FusionEngine
# ---------------------------------------------------------------------------


class FusionEngine:
    """
    融合统计结果与 LLM 分析结果。

    策略：
    - 精确数据（句长、语气词频率、emoji 等）：直接使用统计数据
    - 推断数据（人格、情绪、价值观）：使用 LLM 输出
    - 矛盾检测：当 LLM 描述与统计事实不符时标记
    """

    def fuse(
        self,
        profile: PersonaProfile,
        style_stats: Optional[StyleStats] = None,
    ) -> FusionResult:
        """
        融合统计结果到人格描述中。

        Args:
            profile: LLM 提取的人格描述
            style_stats: StyleAnalyzer 的统计结果

        Returns:
            FusionResult 包含融合后的 profile 和矛盾列表
        """
        result = FusionResult(profile=profile)
        contradictions = []

        if style_stats is None:
            return result

        # Step 1: 注入统计数据到 SpeakingStyle
        injected = self._inject_style_stats(profile, style_stats)
        result.stats_injected = injected

        # Step 2: 矛盾检测
        contradictions = self._detect_contradictions(profile, style_stats)
        result.contradictions = contradictions

        if contradictions:
            logger.info("发现 %d 个统计-LLM 矛盾", len(contradictions))
            for c in contradictions:
                logger.info("  [%s] %s: LLM说'%s'，统计显示'%s'", c.severity, c.field, c.llm_claim, c.stats_evidence)

        return result

    # ------------------------------------------------------------------
    # 注入统计数据
    # ------------------------------------------------------------------

    def _inject_style_stats(self, profile: PersonaProfile, stats: StyleStats) -> List[str]:
        """将统计结果注入 SpeakingStyle。"""
        injected = []

        # 句子长度
        profile.speaking_style.sentence_length_avg = stats.sentence_length_mean
        profile.speaking_style.short_sentence_ratio = stats.short_sentence_ratio
        injected.append("sentence_length")

        # 语气词
        if stats.filler_words:
            profile.speaking_style.filler_words = list(stats.filler_words.keys())[:15]
            injected.append("filler_words")

        # 标点习惯
        if stats.punctuation_stats:
            profile.speaking_style.punctuation_habits = stats.punctuation_stats
            injected.append("punctuation")

        # emoji
        if stats.emoji_total > 0:
            profile.speaking_style.emoji_stats = {
                "total": stats.emoji_total,
                "per_message": round(stats.emoji_per_message, 2),
                "unique": stats.emoji_unique,
                "top": stats.emoji_top[:10],
            }
            injected.append("emoji")

        # 称呼
        if stats.self_references or stats.other_references:
            calling = {}
            if stats.self_references:
                calling["self"] = stats.self_references[0][0]  # 最常用的自称
            if stats.other_references:
                calling["other"] = stats.other_references[0][0]  # 最常用的称呼
            profile.speaking_style.calling_conventions = calling
            injected.append("calling")

        # 更新 summary（如果 LLM 给的太模糊，补充统计信息）
        if not profile.speaking_style.summary or len(profile.speaking_style.summary) < 20:
            summary_parts = []
            if stats.short_sentence_ratio > 0.6:
                summary_parts.append("说话简短")
            elif stats.short_sentence_ratio < 0.3:
                summary_parts.append("倾向长句")

            if stats.filler_word_rate > 0.5:
                top_filler = list(stats.filler_words.keys())[:3]
                summary_parts.append(f"常用语气词：{'、'.join(top_filler)}")

            if stats.emoji_per_message > 0.3:
                summary_parts.append("频繁使用表情符号")

            if stats.punctuation_stats.get("exclamation_rate", 0) > 0.02:
                summary_parts.append("喜欢用感叹号")

            if summary_parts:
                profile.speaking_style.summary = "；".join(summary_parts) + "。"
                injected.append("summary")

        return injected

    # ------------------------------------------------------------------
    # 矛盾检测
    # ------------------------------------------------------------------

    def _detect_contradictions(
        self,
        profile: PersonaProfile,
        stats: StyleStats,
    ) -> List[Contradiction]:
        """检测 LLM 描述与统计数据的矛盾。"""
        contradictions = []

        # 检查 1：说话长度
        if profile.speaking_style.summary:
            summary = profile.speaking_style.summary.lower()
            if ("简短" in summary or "短句" in summary or "简洁" in summary):
                if stats.short_sentence_ratio < 0.3 and stats.sentence_length_mean > 20:
                    contradictions.append(Contradiction(
                        field="speaking_style.length",
                        llm_claim="说话简短",
                        stats_evidence=f"平均句长 {stats.sentence_length_mean:.1f} 字，短句比例仅 {stats.short_sentence_ratio:.1%}",
                        severity="medium",
                        resolution="use_stats",
                    ))
            elif ("长句" in summary or "详细" in summary or "啰嗦" in summary or "话多" in summary):
                if stats.short_sentence_ratio > 0.7 and stats.sentence_length_mean < 10:
                    contradictions.append(Contradiction(
                        field="speaking_style.length",
                        llm_claim="说话详细/话多",
                        stats_evidence=f"平均句长仅 {stats.sentence_length_mean:.1f} 字，短句比例 {stats.short_sentence_ratio:.1%}",
                        severity="medium",
                        resolution="use_stats",
                    ))

        # 检查 2：emoji 使用
        if profile.speaking_style.summary:
            summary = profile.speaking_style.summary.lower()
            if ("emoji" in summary or "表情" in summary or "频繁" in summary):
                if stats.emoji_per_message < 0.05:
                    contradictions.append(Contradiction(
                        field="speaking_style.emoji",
                        llm_claim="频繁使用表情",
                        stats_evidence=f"每条消息平均仅 {stats.emoji_per_message:.2f} 个 emoji",
                        severity="low",
                        resolution="use_stats",
                    ))
            elif ("少用" in summary or "不用" in summary or "很少" in summary):
                if stats.emoji_per_message > 0.5:
                    contradictions.append(Contradiction(
                        field="speaking_style.emoji",
                        llm_claim="很少使用表情",
                        stats_evidence=f"每条消息平均 {stats.emoji_per_message:.2f} 个 emoji",
                        severity="low",
                        resolution="use_stats",
                    ))

        # 检查 3：语气词
        if profile.speaking_style.filler_words:
            llm_fillers = set(profile.speaking_style.filler_words)
            stats_fillers = set(list(stats.filler_words.keys())[:10])
            overlap = llm_fillers & stats_fillers
            if llm_fillers and not overlap:
                contradictions.append(Contradiction(
                    field="speaking_style.filler_words",
                    llm_claim=f"LLM 提到的语气词：{llm_fillers}",
                    stats_evidence=f"实际高频语气词：{stats_fillers}",
                    severity="low",
                    resolution="use_stats",
                ))

        # 检查 4：回复速度与性格
        if stats.avg_reply_seconds and profile.big_five:
            if profile.big_five.get("extraversion", 0) and profile.big_five["extraversion"] > 0.7:
                if stats.avg_reply_seconds > 600:  # 超过10分钟
                    contradictions.append(Contradiction(
                        field="extraversion_vs_reply_speed",
                        llm_claim="高外向性（>0.7）",
                        stats_evidence=f"平均回复速度 {stats.avg_reply_seconds / 60:.1f} 分钟，较慢",
                        severity="medium",
                        resolution="flagged",
                    ))

        return contradictions

    def to_dict(self, result: FusionResult) -> Dict[str, Any]:
        """转为可序列化的字典。"""
        return {
            "stats_injected": result.stats_injected,
            "contradictions": [
                {
                    "field": c.field,
                    "llm_claim": c.llm_claim,
                    "stats_evidence": c.stats_evidence,
                    "severity": c.severity,
                    "resolution": c.resolution,
                }
                for c in result.contradictions
            ],
            "contradiction_count": len(result.contradictions),
        }
