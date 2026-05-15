# -*- coding: utf-8 -*-
"""
PersonaExtractor — 多轮 LLM 人格提取器（v2）

核心改进：
1. 分块提取：长对话按轮数分块，每块独立提取，最后合并
2. Round 4 回流：一致性校验发现冲突后自动修正
3. 中文 prompt：提升中文聊天记录的提取质量
4. 增量更新：支持已有角色卡 + 新对话 → 更新角色卡
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from vir_bot.core.ai_provider import AIProvider, AIResponse
from vir_bot.core.distillation.parser.base import DialogueTurn
from vir_bot.core.distillation.prompt_templates import render_prompt

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 配置常量
# ---------------------------------------------------------------------------
DEFAULT_CHUNK_SIZE = 400  # 每块对话轮数
DEFAULT_MAX_CHUNK_CHARS = 40_000  # 每块最大字符数（安全阀）
DEFAULT_TIMEOUT_SECONDS = 120  # 单次 LLM 调用超时
MAX_CONFLICTS_TO_CORRECT = 5  # 最多修正几个冲突字段

# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass
class SpeakingStyle:
    sentence_length_avg: Optional[float] = None
    short_sentence_ratio: Optional[float] = None
    filler_words: List[str] = field(default_factory=list)
    punctuation_habits: Dict[str, float] = field(default_factory=dict)
    emoji_stats: Dict[str, Any] = field(default_factory=dict)
    calling_conventions: Dict[str, str] = field(default_factory=dict)
    summary: str = ""


@dataclass
class EmotionalPatterns:
    dominant_emotions: List[str] = field(default_factory=list)
    triggers: List[str] = field(default_factory=list)
    recovery_behaviors: List[str] = field(default_factory=list)
    expression_style: str = ""


@dataclass
class ValueProfile:
    frequent_topics: List[str] = field(default_factory=list)
    attitudes: Dict[str, str] = field(default_factory=dict)
    life_view: Optional[str] = None
    humor_style: Optional[str] = None


@dataclass
class DialogueExample:
    context: str
    original: str
    trigger: Optional[str] = None
    note: Optional[str] = None


@dataclass
class PersonaProfile:
    name: Optional[str] = None
    summary: str = ""
    big_five: Dict[str, float] = field(
        default_factory=lambda: {
            "openness": 0.0,
            "conscientiousness": 0.0,
            "extraversion": 0.0,
            "agreeableness": 0.0,
            "neuroticism": 0.0,
        }
    )
    speaking_style: SpeakingStyle = field(default_factory=SpeakingStyle)
    emotional_patterns: EmotionalPatterns = field(default_factory=EmotionalPatterns)
    values: ValueProfile = field(default_factory=ValueProfile)
    dialogue_examples: List[DialogueExample] = field(default_factory=list)
    taboos: List[str] = field(default_factory=list)
    special_quirks: List[str] = field(default_factory=list)
    raw_notes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ChunkResult:
    """单个对话块的提取结果。"""
    chunk_index: int
    turn_range: tuple  # (start, end)
    round1: Optional[Dict[str, Any]] = None
    round2: Optional[Dict[str, Any]] = None
    round3: Optional[Dict[str, Any]] = None
    profile: Optional[PersonaProfile] = None


# ---------------------------------------------------------------------------
# PersonaExtractor
# ---------------------------------------------------------------------------


class PersonaExtractor:
    """
    多轮 LLM 人格提取器。

    改进点：
    - 分块提取：长对话按 chunk_size 轮分块，每块独立提取
    - Merge Round：合并多块结果，处理矛盾
    - Round 4 回流：校验冲突后自动修正
    - 增量更新：已有角色卡 + 新对话 → 更新
    """

    def __init__(
        self,
        ai_provider: AIProvider,
        *,
        prompts: Optional[Dict[str, str]] = None,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        max_chunk_chars: int = DEFAULT_MAX_CHUNK_CHARS,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.ai = ai_provider
        self.prompts = prompts or {}
        self.chunk_size = chunk_size
        self.max_chunk_chars = max_chunk_chars
        self.timeout_seconds = timeout_seconds

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    async def extract(
        self,
        turns: List[DialogueTurn],
        name: Optional[str] = None,
    ) -> PersonaProfile:
        """
        执行完整的提取流水线。

        流程：
        1. 分块
        2. 每块跑 Round 1~3
        3. Merge Round 合并
        4. Round 4 一致性校验
        5. 如果有冲突，执行修正轮
        """
        logger.info("开始人格提取（共 %d 轮对话，每块 %d 轮）", len(turns), self.chunk_size)

        # Step 1: 分块
        chunks = self._split_into_chunks(turns)
        logger.info("分为 %d 个块", len(chunks))

        # Step 2: 每块独立提取
        chunk_results: List[ChunkResult] = []
        for i, chunk_turns in enumerate(chunks):
            logger.info("提取第 %d/%d 块（%d 轮）", i + 1, len(chunks), len(chunk_turns))
            result = await self._extract_chunk(chunk_turns, chunk_index=i)
            chunk_results.append(result)

        # Step 3: 合并
        if len(chunk_results) == 1:
            profile = chunk_results[0].profile or PersonaProfile(name=name)
        else:
            profile = await self._merge_chunks(chunk_results, name=name)

        # Step 4: Round 4 一致性校验 + 回流修正
        profile = await self._consistency_check_and_correct(profile, turns)

        logger.info("人格提取完成：%s", name or profile.name or "<unknown>")
        return profile

    async def extract_incremental(
        self,
        existing_persona: str,
        new_turns: List[DialogueTurn],
        name: Optional[str] = None,
    ) -> PersonaProfile:
        """
        增量更新：已有角色描述 + 新对话 → 更新后的人格。

        Args:
            existing_persona: 现有角色描述（Markdown 或 JSON 字符串）
            new_turns: 新的对话记录
            name: 角色名称
        """
        logger.info("增量更新：%d 轮新对话", len(new_turns))
        dialogue_text = self._render_dialogue_text(new_turns)

        # 裁剪到安全长度
        if len(dialogue_text) > self.max_chunk_chars:
            dialogue_text = dialogue_text[:self.max_chunk_chars]

        prompt = render_prompt(
            "incremental",
            existing_persona=existing_persona,
            dialogue_text=dialogue_text,
        )
        response = await self._call_llm(prompt)
        result_json = self._safe_parse_json(response) or {}

        # 构建 profile
        updated = result_json.get("updated_persona", result_json)
        profile = self._dict_to_profile(updated, name=name)
        profile.raw_notes["incremental_changes"] = result_json.get("changes", [])
        profile.raw_notes["extraction_mode"] = "incremental"

        return profile

    # ------------------------------------------------------------------
    # 分块
    # ------------------------------------------------------------------

    def _split_into_chunks(self, turns: List[DialogueTurn]) -> List[List[DialogueTurn]]:
        """按轮数分块，每块 chunk_size 轮。"""
        if len(turns) <= self.chunk_size:
            return [turns]

        chunks = []
        for i in range(0, len(turns), self.chunk_size):
            chunk = turns[i : i + self.chunk_size]
            if chunk:
                chunks.append(chunk)
        return chunks

    # ------------------------------------------------------------------
    # 单块提取
    # ------------------------------------------------------------------

    async def _extract_chunk(
        self,
        turns: List[DialogueTurn],
        chunk_index: int = 0,
    ) -> ChunkResult:
        """对单个对话块执行 Round 1~3 提取。"""
        dialogue_text = self._render_dialogue_text(turns)

        # 安全截断
        if len(dialogue_text) > self.max_chunk_chars:
            logger.debug("块 %d 字符过多（%d），截断到 %d", chunk_index, len(dialogue_text), self.max_chunk_chars)
            dialogue_text = dialogue_text[:self.max_chunk_chars]

        result = ChunkResult(
            chunk_index=chunk_index,
            turn_range=(0, len(turns)),
        )

        # Round 1
        round1_prompt = render_prompt("round1", dialogue_text=dialogue_text)
        round1_raw = await self._call_llm(round1_prompt)
        result.round1 = self._safe_parse_json(round1_raw)
        logger.debug("块 %d Round1: %s", chunk_index, list(result.round1.keys()) if result.round1 else "None")

        # Round 2
        round2_prompt = render_prompt(
            "round2",
            dialogue_text=dialogue_text,
            round1_output=json.dumps(result.round1, ensure_ascii=False) if result.round1 else "{}",
        )
        round2_raw = await self._call_llm(round2_prompt)
        result.round2 = self._safe_parse_json(round2_raw)

        # Round 3
        round3_prompt = render_prompt("round3", dialogue_text=dialogue_text)
        round3_raw = await self._call_llm(round3_prompt)
        result.round3 = self._safe_parse_json(round3_raw)

        # 构建单块 profile
        result.profile = self._build_profile_from_rounds(
            name=None,
            round1_json=result.round1,
            round2_json=result.round2,
            round3_json=result.round3,
        )

        return result

    # ------------------------------------------------------------------
    # 合并多块结果
    # ------------------------------------------------------------------

    async def _merge_chunks(
        self,
        chunk_results: List[ChunkResult],
        name: Optional[str] = None,
    ) -> PersonaProfile:
        """用 Merge Round 合并多块提取结果。"""
        logger.info("合并 %d 个块的提取结果", len(chunk_results))

        # 构建合并输入
        chunk_summaries = []
        for cr in chunk_results:
            summary = {
                "chunk_index": cr.chunk_index,
                "round1": cr.round1,
                "round2": cr.round2,
                "examples_count": len(cr.profile.dialogue_examples) if cr.profile else 0,
            }
            chunk_summaries.append(summary)

        chunk_results_text = json.dumps(chunk_summaries, ensure_ascii=False, indent=2)

        # 如果太长，只传摘要
        if len(chunk_results_text) > self.max_chunk_chars:
            # 只传 Round1 + Round2 的核心字段
            condensed = []
            for cr in chunk_results:
                condensed.append({
                    "chunk": cr.chunk_index,
                    "big_five": cr.round1.get("big_five") if cr.round1 else None,
                    "keywords": cr.round1.get("core_keywords") if cr.round1 else None,
                    "style": cr.round1.get("speaking_style_summary") if cr.round1 else None,
                    "emotions": (cr.round2.get("emotional_patterns", {}).get("dominant_emotions") if cr.round2 else None),
                    "taboos": cr.round2.get("taboos") if cr.round2 else None,
                    "quirks": cr.round2.get("special_quirks") if cr.round2 else None,
                })
            chunk_results_text = json.dumps(condensed, ensure_ascii=False, indent=2)

        merge_prompt = render_prompt("merge", chunk_results=chunk_results_text)
        merge_raw = await self._call_llm(merge_prompt)
        merge_json = self._safe_parse_json(merge_raw)

        if merge_json:
            profile = self._build_profile_from_rounds(
                name=name,
                round1_json=merge_json,
                round2_json=merge_json,
                round3_json=None,
            )
        else:
            # fallback：取第一个块的结果
            profile = chunk_results[0].profile or PersonaProfile(name=name)

        # 合并所有块的对话示例
        all_examples = []
        for cr in chunk_results:
            if cr.profile and cr.profile.dialogue_examples:
                all_examples.extend(cr.profile.dialogue_examples)
        # 去重（按 original 文本）
        seen = set()
        unique_examples = []
        for ex in all_examples:
            if ex.original not in seen:
                seen.add(ex.original)
                unique_examples.append(ex)
        # 最多保留 10 个
        profile.dialogue_examples = unique_examples[:10]

        profile.raw_notes["merge_chunks"] = len(chunk_results)
        profile.raw_notes["total_examples_merged"] = len(all_examples)

        return profile

    # ------------------------------------------------------------------
    # Round 4 一致性校验 + 回流修正
    # ------------------------------------------------------------------

    async def _consistency_check_and_correct(
        self,
        profile: PersonaProfile,
        turns: List[DialogueTurn],
    ) -> PersonaProfile:
        """执行 Round 4 一致性校验，如果有冲突则修正。"""
        logger.info("执行一致性校验")

        persona_json = json.dumps(
            self._profile_to_serializable(profile), ensure_ascii=False, indent=2
        )
        examples_json = json.dumps(
            [asdict(e) for e in profile.dialogue_examples],
            ensure_ascii=False,
            indent=2,
        )

        round4_prompt = render_prompt(
            "round4",
            persona_json=persona_json,
            examples_json=examples_json,
        )
        round4_raw = await self._call_llm(round4_prompt)
        round4_json = self._safe_parse_json(round4_raw)

        if not round4_json:
            logger.warning("Round 4 输出解析失败，跳过校验")
            return profile

        conflicts = round4_json.get("conflicts", [])
        validated = round4_json.get("validated_persona", {})

        profile.raw_notes["consistency_check"] = round4_json
        logger.info("一致性校验完成，发现 %d 个冲突", len(conflicts))

        if not conflicts:
            # 无冲突，用 validated_persona 更新
            if validated:
                profile = self._apply_validated_persona(profile, validated)
            return profile

        # 有冲突 → 执行修正轮
        if len(conflicts) > MAX_CONFLICTS_TO_CORRECT:
            conflicts = conflicts[:MAX_CONFLICTS_TO_CORRECT]

        logger.info("执行修正轮（%d 个冲突）", len(conflicts))
        return await self._correct_conflicts(profile, turns, conflicts, examples_json)

    async def _correct_conflicts(
        self,
        profile: PersonaProfile,
        turns: List[DialogueTurn],
        conflicts: List[Dict],
        examples_json: str,
    ) -> PersonaProfile:
        """根据冲突修正人格特征。"""
        dialogue_text = self._render_dialogue_text(turns)
        if len(dialogue_text) > self.max_chunk_chars:
            dialogue_text = dialogue_text[:self.max_chunk_chars]

        persona_json = json.dumps(
            self._profile_to_serializable(profile), ensure_ascii=False, indent=2
        )
        conflicts_json = json.dumps(conflicts, ensure_ascii=False, indent=2)

        correction_prompt = render_prompt(
            "correction",
            conflicts_json=conflicts_json,
            dialogue_text=dialogue_text,
            examples_json=examples_json,
            persona_json=persona_json,
        )
        correction_raw = await self._call_llm(correction_prompt)
        correction_json = self._safe_parse_json(correction_raw)

        if correction_json:
            corrected_profile = self._build_profile_from_rounds(
                name=profile.name,
                round1_json=correction_json,
                round2_json=correction_json,
                round3_json=None,
            )
            # 保留原始对话示例
            corrected_profile.dialogue_examples = profile.dialogue_examples
            corrected_profile.raw_notes["correction_applied"] = True
            corrected_profile.raw_notes["original_conflicts"] = conflicts
            logger.info("修正完成")
            return corrected_profile

        logger.warning("修正轮输出解析失败，保留原始结果")
        return profile

    def _apply_validated_persona(
        self, profile: PersonaProfile, validated: Dict[str, Any]
    ) -> PersonaProfile:
        """将 Round 4 的 validated_persona 合并到 profile 中。"""
        if "big_five" in validated:
            for k, v in validated["big_five"].items():
                if v is not None:
                    try:
                        profile.big_five[k] = max(0.0, min(1.0, float(v)))
                    except (ValueError, TypeError):
                        pass

        if "speaking_style_summary" in validated:
            profile.speaking_style.summary = validated["speaking_style_summary"]

        if "core_keywords" in validated:
            profile.raw_notes["core_keywords"] = validated["core_keywords"]

        if "emotional_patterns" in validated:
            ep = validated["emotional_patterns"]
            if isinstance(ep, dict):
                profile.emotional_patterns.dominant_emotions = ep.get("dominant_emotions", [])
                profile.emotional_patterns.triggers = ep.get("triggers", [])
                profile.emotional_patterns.recovery_behaviors = ep.get("recovery_behaviors", [])
                profile.emotional_patterns.expression_style = ep.get("expression_style", "")

        if "values" in validated:
            vals = validated["values"]
            if isinstance(vals, dict):
                profile.values.frequent_topics = vals.get("frequent_topics", [])
                profile.values.attitudes = vals.get("attitudes", {})
                profile.values.life_view = vals.get("life_view")
                profile.values.humor_style = vals.get("humor_style")

        if "taboos" in validated:
            profile.taboos = validated["taboos"]

        if "special_quirks" in validated:
            profile.special_quirks = validated["special_quirks"]

        return profile

    # ------------------------------------------------------------------
    # LLM 调用
    # ------------------------------------------------------------------

    async def _call_llm(self, user_prompt: str) -> str:
        """调用 AI Provider，带超时保护。"""
        system = self.prompts.get("system", render_prompt("system"))
        messages = [{"role": "user", "content": user_prompt}]
        try:
            coro = self.ai.chat(
                messages=messages, system=system, stream=False, temperature=0.2
            )
            resp: AIResponse = await asyncio.wait_for(coro, timeout=self.timeout_seconds)
            return resp.content or ""
        except asyncio.TimeoutError:
            logger.error("LLM 调用超时（%ds）", self.timeout_seconds)
            raise
        except Exception:
            logger.exception("LLM 调用失败")
            raise

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    def _render_dialogue_text(self, turns: List[DialogueTurn]) -> str:
        """将对话轮次转换为纯文本。"""
        lines: List[str] = []
        for t in turns:
            ts = t.timestamp.isoformat() if getattr(t, "timestamp", None) else ""
            sender = t.sender or "<unknown>"
            content = t.content.replace("\n", " \\n ")
            meta = ""
            if t.metadata:
                meta_keys = ", ".join(sorted(t.metadata.keys()))
                meta = f" [{meta_keys}]" if meta_keys else ""
            lines.append(f"{ts} {sender}:{meta} {content}".strip())
        return "\n".join(lines)

    def _safe_parse_json(self, text_or_obj: Any) -> Optional[Dict[str, Any]]:
        """解析 LLM 输出的 JSON，带多重 fallback。"""
        if text_or_obj is None:
            return None
        if isinstance(text_or_obj, dict):
            return text_or_obj
        if not isinstance(text_or_obj, str):
            try:
                return json.loads(str(text_or_obj))
            except Exception:
                return None

        text = text_or_obj.strip()

        # 直接解析
        try:
            return json.loads(text)
        except Exception:
            pass

        # 提取第一个 {...}
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except Exception:
                pass

        # 提取第一个 [...]
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1 and end > start:
            try:
                return {"_list": json.loads(text[start : end + 1])}
            except Exception:
                pass

        logger.debug("JSON 解析失败，保留原始文本")
        return {"_raw": text}

    def _build_profile_from_rounds(
        self,
        name: Optional[str],
        round1_json: Optional[Dict[str, Any]],
        round2_json: Optional[Dict[str, Any]],
        round3_json: Optional[Dict[str, Any]],
    ) -> PersonaProfile:
        """将多轮 JSON 输出合并为 PersonaProfile。"""
        profile = PersonaProfile(name=name)
        profile.raw_notes["round1"] = round1_json
        profile.raw_notes["round2"] = round2_json
        profile.raw_notes["round3"] = round3_json

        # Round 1 → big_five, speaking_style, keywords
        if round1_json:
            bf = round1_json.get("big_five") or round1_json.get("bigFive") or {}
            for k in ("openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism"):
                v = bf.get(k)
                if v is not None:
                    try:
                        profile.big_five[k] = max(0.0, min(1.0, float(v)))
                    except (ValueError, TypeError):
                        pass

            profile.speaking_style.summary = (
                round1_json.get("speaking_style_summary")
                or round1_json.get("speaking_style")
                or ""
            )
            core = round1_json.get("core_keywords") or round1_json.get("keywords") or []
            profile.raw_notes["core_keywords"] = list(core) if isinstance(core, list) else core

        # Round 2 → emotional_patterns, values, taboos, quirks
        if round2_json:
            ep = round2_json.get("emotional_patterns") or {}
            if isinstance(ep, dict):
                profile.emotional_patterns.dominant_emotions = ep.get("dominant_emotions") or ep.get("dominant") or []
                profile.emotional_patterns.triggers = ep.get("triggers") or []
                profile.emotional_patterns.recovery_behaviors = ep.get("recovery_behaviors") or []
                profile.emotional_patterns.expression_style = ep.get("expression_style") or ""

            vals = round2_json.get("values") or {}
            if isinstance(vals, dict):
                profile.values.frequent_topics = vals.get("frequent_topics") or []
                profile.values.attitudes = vals.get("attitudes") or {}
                profile.values.life_view = vals.get("life_view")
                profile.values.humor_style = vals.get("humor_style")

            profile.taboos = round2_json.get("taboos") or []
            profile.special_quirks = round2_json.get("special_quirks") or []

        # Round 3 → dialogue examples
        if round3_json:
            examples = (
                round3_json.get("examples")
                or round3_json.get("items")
                or round3_json.get("_list")
                or []
            )
            for ex in examples:
                if isinstance(ex, dict):
                    profile.dialogue_examples.append(DialogueExample(
                        context=ex.get("context") or "",
                        original=ex.get("original") or ex.get("text") or "",
                        trigger=ex.get("trigger"),
                        note=ex.get("note"),
                    ))
                else:
                    profile.dialogue_examples.append(DialogueExample(context="", original=str(ex)))

        # 生成 summary
        if not profile.summary:
            if profile.speaking_style.summary:
                profile.summary = profile.speaking_style.summary
            else:
                kw = profile.raw_notes.get("core_keywords")
                if kw and isinstance(kw, list):
                    profile.summary = " / ".join(kw[:5])
                elif profile.values.life_view:
                    profile.summary = profile.values.life_view
                else:
                    profile.summary = "从对话记录中提取的人格特征。"

        return profile

    def _dict_to_profile(self, data: Dict[str, Any], name: Optional[str] = None) -> PersonaProfile:
        """将字典转换为 PersonaProfile。"""
        if not data:
            return PersonaProfile(name=name)
        return self._build_profile_from_rounds(
            name=name or data.get("name"),
            round1_json=data,
            round2_json=data,
            round3_json={"examples": data.get("dialogue_examples", [])} if "dialogue_examples" in data else None,
        )

    def _profile_to_serializable(self, profile: PersonaProfile) -> Dict[str, Any]:
        """将 PersonaProfile 转为可序列化的字典。"""
        return {
            "name": profile.name,
            "summary": profile.summary,
            "big_five": profile.big_five,
            "speaking_style": {
                "sentence_length_avg": profile.speaking_style.sentence_length_avg,
                "short_sentence_ratio": profile.speaking_style.short_sentence_ratio,
                "filler_words": profile.speaking_style.filler_words,
                "punctuation_habits": profile.speaking_style.punctuation_habits,
                "emoji_stats": profile.speaking_style.emoji_stats,
                "calling_conventions": profile.speaking_style.calling_conventions,
                "summary": profile.speaking_style.summary,
            },
            "emotional_patterns": {
                "dominant_emotions": profile.emotional_patterns.dominant_emotions,
                "triggers": profile.emotional_patterns.triggers,
                "recovery_behaviors": profile.emotional_patterns.recovery_behaviors,
                "expression_style": profile.emotional_patterns.expression_style,
            },
            "values": {
                "frequent_topics": profile.values.frequent_topics,
                "attitudes": profile.values.attitudes,
                "life_view": profile.values.life_view,
                "humor_style": profile.values.humor_style,
            },
            "dialogue_examples": [
                {"context": e.context, "original": e.original, "trigger": e.trigger, "note": e.note}
                for e in profile.dialogue_examples
            ],
            "taboos": profile.taboos,
            "special_quirks": profile.special_quirks,
        }
