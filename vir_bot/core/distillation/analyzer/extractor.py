# -*- coding: utf-8 -*-
"""
Persona extractor: provide dataclasses describing a persona and a multi-round
LLM-driven extractor that turns DialogueTurn sequences into a structured
PersonaProfile.

Design notes:
- The extractor drives a multi-round analysis as described in DISTILLATION_PLAN.md:
  1) coarse Big Five + speaking style + keywords
  2) fine-grained emotional patterns, values, quirks
  3) sample dialogues selection
  4) consistency check & annotated role card draft
- The implementation is written to be backend-agnostic: it uses an injected
  `AIProvider` to perform LLM calls. The provider must offer an async `chat`
  method compatible with `vir_bot.core.ai_provider.AIProvider`.
- The extractor attempts to parse machine-readable JSON from the model; when
  that fails it falls back to simpler heuristics (plain text).
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from vir_bot.core.ai_provider import AIProvider, AIResponse
from vir_bot.core.distillation.parser.base import DialogueTurn

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data models (PersonaProfile and supporting structures)
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


# ---------------------------------------------------------------------------
# Prompts (default templates). Implementations can override by passing
# custom prompts via config to PersonaExtractor.
# ---------------------------------------------------------------------------

_DEFAULT_SYSTEM_PROMPT = """You are an expert in personality analysis and writing concise structured profiles.
Given conversational logs, produce structured JSON following the requested schema.
Be precise and conservative: if something cannot be inferred, leave it empty or null.
"""

_ROUND1_USER_PROMPT = """Round 1 - Coarse Extraction.
Input: the conversation logs (plain text). Tasks:
1) Provide Big-Five scores (0.0-1.0) for: openness, conscientiousness, extraversion, agreeableness, neuroticism.
2) Summarize speaking style in 2-3 short sentences.
3) List up to 5 single-word core personality keywords.
4) Output JSON only with keys: big_five, speaking_style_summary, core_keywords.
Conversation:
```
{dialogue_text}
```"""

_ROUND2_USER_PROMPT = """Round 2 - Fine-grained Extraction.
Input: same conversation and previous round results.
Tasks:
1) Extract emotional patterns: dominant emotions, triggers, recovery behaviors, expression style.
2) Extract values: frequent topics, attitudes to typical domains (work, love, family), humor style.
3) Identify special quirks or taboos (up to 10 items).
4) Output JSON only with keys: emotional_patterns, values, taboos, special_quirks.
Conversation:
```
{dialogue_text}
```
Previous round output:
```
{round1_output}
```"""

_ROUND3_USER_PROMPT = """Round 3 - Dialogue Example Selection.
Input: conversation logs.
Tasks:
1) Choose 5-10 representative dialogue snippets. For each provide:
   - context (short explanation when this happens)
   - original (the exact messages involved; keep original text)
   - trigger (what topic or situation leads to this)
   - note (why it's representative)
2) Output JSON: {"examples": [{...}, ...]}
Conversation:
```
{dialogue_text}
```"""

_ROUND4_USER_PROMPT = """Round 4 - Consistency Check.
Input: aggregated persona draft and examples.
Tasks:
1) Verify consistency between persona descriptions and examples.
2) Highlight up to 10 conflicts or uncertain inferences.
3) Output JSON: {"conflicts": [...], "validated_persona": <persona-draft>}
Input persona:
```
{persona_json}
```
Examples:
```
{examples_json}
```"""

# ---------------------------------------------------------------------------
# PersonaExtractor implementation
# ---------------------------------------------------------------------------


class PersonaExtractor:
    """
    PersonaExtractor performs multi-round LLM-based extraction to produce a
    PersonaProfile from a list of DialogueTurn.

    Constructor parameters:
    - ai_provider: instance of AIProvider used to call the LLM.
    - prompts: optional dict to override prompt templates.
    - max_chunk_chars: when the conversation is large, we chunk text to avoid
      sending overly long prompts (the extractor concatenates the first N chars).
    """

    def __init__(
        self,
        ai_provider: AIProvider,
        *,
        prompts: Optional[Dict[str, str]] = None,
        max_chunk_chars: int = 40_000,
        timeout_seconds: int = 60,
    ) -> None:
        self.ai = ai_provider
        self.prompts = prompts or {}
        self.max_chunk_chars = int(max_chunk_chars)
        self.timeout_seconds = int(timeout_seconds)

    async def extract(
        self, turns: List[DialogueTurn], name: Optional[str] = None
    ) -> PersonaProfile:
        """
        Run the full extraction pipeline and return a PersonaProfile.
        The method is resilient: even if LLM outputs cannot be parsed as JSON,
        it will attempt to salvage useful text into the profile.
        """
        logger.info("Starting persona extraction (turns=%d)", len(turns))

        dialogue_text = self._render_dialogue_text(turns)
        if len(dialogue_text) > self.max_chunk_chars:
            logger.debug(
                "Dialogue text too long (%d chars), truncating to %d",
                len(dialogue_text),
                self.max_chunk_chars,
            )
            dialogue_text = dialogue_text[: self.max_chunk_chars]

        # Round 1: coarse extraction
        round1 = await self._call_llm(_ROUND1_USER_PROMPT.format(dialogue_text=dialogue_text))
        round1_json = self._safe_parse_json(round1)
        logger.debug("Round1 parsed: %s", round1_json)

        # Round 2: fine-grained
        round2_input = _ROUND2_USER_PROMPT.format(
            dialogue_text=dialogue_text,
            round1_output=round1 if isinstance(round1, str) else json.dumps(round1),
        )
        round2 = await self._call_llm(round2_input)
        round2_json = self._safe_parse_json(round2)
        logger.debug("Round2 parsed: %s", round2_json)

        # Round 3: select dialogue examples
        round3_input = _ROUND3_USER_PROMPT.format(dialogue_text=dialogue_text)
        round3 = await self._call_llm(round3_input)
        round3_json = self._safe_parse_json(round3)
        logger.debug("Round3 parsed: %s", round3_json)

        # Build initial PersonaProfile from collected outputs
        profile = self._build_profile_from_rounds(name, round1_json, round2_json, round3_json)

        # Round 4: consistency check (ask LLM to validate)
        try:
            persona_json_text = json.dumps(
                self._profile_to_serializable(profile), ensure_ascii=False, indent=2
            )
            examples_json_text = json.dumps(round3_json or {}, ensure_ascii=False, indent=2)
            round4_input = _ROUND4_USER_PROMPT.format(
                persona_json=persona_json_text, examples_json=examples_json_text
            )
            round4 = await self._call_llm(round4_input)
            round4_json = self._safe_parse_json(round4)
            # incorporate conflicts/notes into profile.raw_notes for later review
            if round4_json:
                profile.raw_notes["consistency_check"] = round4_json
        except Exception as e:
            logger.exception("Round 4 consistency check failed: %s", e)
            profile.raw_notes.setdefault("errors", []).append(f"round4_error: {e}")

        logger.info("Extraction complete for persona '%s'", name or profile.name or "<unknown>")
        return profile

    # -------------------------
    # Internal helpers
    # -------------------------

    async def _call_llm(self, user_prompt: str) -> str:
        """
        Call the AI provider with a best-effort time bound. Return the content
        string from the response. Raises on provider errors.
        """
        system = self.prompts.get("system", _DEFAULT_SYSTEM_PROMPT)
        # Build a simple chat message sequence
        messages = [{"role": "user", "content": user_prompt}]
        try:
            coro = self.ai.chat(messages=messages, system=system, stream=False, temperature=0.2)
            # Enforce timeout using asyncio.wait_for
            resp: AIResponse = await asyncio.wait_for(coro, timeout=self.timeout_seconds)
            logger.debug(
                "LLM response model=%s finish=%s",
                getattr(resp, "model", None),
                getattr(resp, "finish_reason", None),
            )
            return resp.content or ""
        except asyncio.TimeoutError:
            logger.exception("LLM call timed out")
            raise
        except Exception:
            logger.exception("LLM call failed")
            raise

    def _render_dialogue_text(self, turns: List[DialogueTurn]) -> str:
        """
        Convert a list of DialogueTurn into a reasonably compact plain text
        representation for the LLM. Preserve original content and basic metadata.
        """
        lines: List[str] = []
        for t in turns:
            ts = t.timestamp.isoformat() if getattr(t, "timestamp", None) else ""
            sender = t.sender or "<unknown>"
            # keep original content without modification
            content = t.content.replace("\n", " \\n ")
            meta = ""
            if t.metadata:
                # include minimal metadata hints
                meta_keys = ", ".join(sorted(t.metadata.keys()))
                meta = f" [{meta_keys}]" if meta_keys else ""
            lines.append(f"{ts} {sender}:{meta} {content}".strip())
        return "\n".join(lines)

    def _safe_parse_json(self, text_or_obj: Any) -> Optional[Dict[str, Any]]:
        """
        Try to parse LLM output as JSON. Accept either a dict-like object
        (already parsed) or a string. Returns dict on success, otherwise None.
        When parsing fails, it will attempt to extract the first JSON object
        substring as a fallback.
        """
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
        # direct parse attempt
        try:
            return json.loads(text)
        except Exception:
            pass
        # fallback: find first {...} or [ ... ] block and parse
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = text[start : end + 1]
            try:
                return json.loads(candidate)
            except Exception:
                pass
        # try array
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1 and end > start:
            candidate = text[start : end + 1]
            try:
                parsed = json.loads(candidate)
                # wrap into dict if appropriate
                return {"_list": parsed}
            except Exception:
                pass
        # parse failure: return None and keep raw text in notes
        logger.debug("Failed to parse JSON from LLM output. Storing raw text.")
        return {"_raw": text}

    def _build_profile_from_rounds(
        self,
        name: Optional[str],
        round1_json: Optional[Dict[str, Any]],
        round2_json: Optional[Dict[str, Any]],
        round3_json: Optional[Dict[str, Any]],
    ) -> PersonaProfile:
        """
        Consolidate the JSON outputs into a PersonaProfile dataclass.
        This function is conservative: it extracts known fields but preserves
        the raw round outputs in profile.raw_notes for human inspection.
        """
        profile = PersonaProfile(name=name or None)
        profile.raw_notes["round1"] = round1_json
        profile.raw_notes["round2"] = round2_json
        profile.raw_notes["round3"] = round3_json

        # Round1 -> big_five, speaking_style_summary, core_keywords
        if round1_json:
            bf = round1_json.get("big_five") or round1_json.get("bigFive") or {}
            # normalize values if possible
            for k in (
                "openness",
                "conscientiousness",
                "extraversion",
                "agreeableness",
                "neuroticism",
            ):
                try:
                    v = float(bf.get(k, profile.big_five.get(k, 0.0)))
                    profile.big_five[k] = max(0.0, min(1.0, v))
                except Exception:
                    # if not numeric, leave default
                    pass
            # speaking style summary
            profile.speaking_style.summary = (
                round1_json.get("speaking_style_summary") or round1_json.get("speaking_style") or ""
            )
            # core keywords
            core = round1_json.get("core_keywords") or round1_json.get("keywords") or []
            try:
                profile.raw_notes["core_keywords"] = list(core)
            except Exception:
                profile.raw_notes["core_keywords"] = core

        # Round2 -> emotional_patterns, values, taboos, special_quirks
        if round2_json:
            ep = round2_json.get("emotional_patterns") or {}
            if isinstance(ep, dict):
                profile.emotional_patterns.dominant_emotions = (
                    ep.get("dominant_emotions") or ep.get("dominant") or []
                )
                profile.emotional_patterns.triggers = ep.get("triggers") or []
                profile.emotional_patterns.recovery_behaviors = ep.get("recovery_behaviors") or []
                profile.emotional_patterns.expression_style = ep.get("expression_style") or ""
            vals = round2_json.get("values") or {}
            if isinstance(vals, dict):
                profile.values.frequent_topics = vals.get("frequent_topics") or []
                profile.values.attitudes = vals.get("attitudes") or {}
                profile.values.life_view = vals.get("life_view") or None
                profile.values.humor_style = vals.get("humor_style") or None
            profile.taboos = round2_json.get("taboos") or []
            profile.special_quirks = round2_json.get("special_quirks") or []

        # Round3 -> examples
        if round3_json:
            examples = (
                round3_json.get("examples")
                or round3_json.get("items")
                or round3_json.get("_list")
                or []
            )
            parsed_examples: List[DialogueExample] = []
            for ex in examples:
                if isinstance(ex, dict):
                    parsed_examples.append(
                        DialogueExample(
                            context=ex.get("context") or "",
                            original=ex.get("original") or ex.get("text") or "",
                            trigger=ex.get("trigger") or None,
                            note=ex.get("note") or None,
                        )
                    )
                else:
                    parsed_examples.append(DialogueExample(context="", original=str(ex)))
            profile.dialogue_examples = parsed_examples

        # If no textual summary provided, craft a minimal summary from available data
        if not profile.summary:
            # prefer speaking style summary, then values.life_view, then keywords
            if profile.speaking_style.summary:
                profile.summary = profile.speaking_style.summary
            else:
                kw = profile.raw_notes.get("core_keywords")
                if kw:
                    profile.summary = " / ".join(kw[:5])
                elif profile.values.life_view:
                    profile.summary = profile.values.life_view
                else:
                    profile.summary = "Persona extracted from conversation logs."

        return profile

    def _profile_to_serializable(self, profile: PersonaProfile) -> Dict[str, Any]:
        """
        Convert PersonaProfile to a JSON-serializable dict for validation or saving.
        """
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
            "raw_notes": profile.raw_notes,
        }
