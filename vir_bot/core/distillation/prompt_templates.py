# -*- coding: utf-8 -*-
"""
Distillation prompt templates

This module centralizes the LLM prompt templates used by the distillation
PersonaExtractor. Prompts are written to be clear, conservative, and to request
machine-parsable (JSON) outputs where possible. The extractor uses these
templates to run the multi-round extraction described in DISTILLATION_PLAN.md.

Guidelines encoded in prompts:
- Ask the model to be explicit about what is inferred vs. unknown.
- Prefer numeric ranges for Big Five (0.0 - 1.0).
- Request strict JSON output and provide schema examples.
- Provide fallback instructions to produce a compact raw text when JSON fails.
"""

from __future__ import annotations

from typing import Any, Dict

# -----------------------------------------------------------------------------
# System-level prompt (intent & behavior)
# -----------------------------------------------------------------------------
SYSTEM_PROMPT = """You are an expert analyst specialized in extracting stable personality
profiles and speaking style from conversational logs. Your job is to read chat
turns and produce structured, conservative, and human-readable persona data
that can be interpreted by downstream tooling.

Rules:
- Respond primarily in JSON when asked for structured output.
- If you are not certain about an inference, prefer null or empty lists instead
  of fabricating details.
- Keep answers concise and machine-parseable.
- When asked for example dialogues, preserve the original text exactly (do not
  rewrite messages) and provide a short contextual note for each snippet.
- Always avoid revealing or fabricating personally-identifying information.
"""


# -----------------------------------------------------------------------------
# JSON schemas / examples to include in prompts
# These are not formal JSON Schema files, but compact "expected output" examples
# to encourage LLM to produce machine-readable replies.
# -----------------------------------------------------------------------------
_BIG_FIVE_SCHEMA_EXAMPLE = r"""
Example expected JSON (Round 1):
{
  "big_five": {
    "openness": 0.72,
    "conscientiousness": 0.35,
    "extraversion": 0.60,
    "agreeableness": 0.80,
    "neuroticism": 0.22
  },
  "speaking_style_summary": "Short, playful sentences; frequent use of emojis and laughter tokens.",
  "core_keywords": ["playful", "curious", "warm", "impulsive", "supportive"]
}
"""

_ROUND2_SCHEMA_EXAMPLE = r"""
Example expected JSON (Round 2):
{
  "emotional_patterns": {
    "dominant_emotions": ["joy", "anxiety"],
    "triggers": ["work criticism", "misunderstandings about care"],
    "recovery_behaviors": ["self-deprecating humor", "distraction by hobbies"],
    "expression_style": "expressive, uses exclamation and emojis to convey warmth"
  },
  "values": {
    "frequent_topics": ["music", "relationships", "personal growth"],
    "attitudes": {"work": "pragmatic", "love": "romantic", "family": "protective"},
    "life_view": "optimistic with occasional worry about status",
    "humor_style": "self-deprecating and meme-aware"
  },
  "taboos": ["jokes about family", "dismissive comments about mental health"],
  "special_quirks": ["adds '哈哈' after uncomfortable statements", "uses ~ to soften sentences"]
}
"""

_ROUND3_SCHEMA_EXAMPLE = r"""
Example expected JSON (Round 3):
{
  "examples": [
    {
      "context": "Reassuring a friend who is upset",
      "original": "A: 我懂你为什么生气。B: 谢谢你... 我现在好多了。",
      "trigger": "friend shares sadness",
      "note": "Shows comforting and empathic tone"
    }
  ]
}
"""

_ROUND4_SCHEMA_EXAMPLE = r"""
Example expected JSON (Round 4):
{
  "conflicts": [
    {"field": "extraversion", "issue": "Round1 suggests high extraversion but examples show long introspective messages"}
  ],
  "validated_persona": { /* persona draft validated or with clarifying notes */ }
}
"""

# -----------------------------------------------------------------------------
# Multi-round user prompts
# - Round 1: Coarse extraction (Big Five, style, keywords)
# - Round 2: Fine-grained (emotions, values, taboos, quirks)
# - Round 3: Dialogue examples selection (representative snippets)
# - Round 4: Consistency check (validate, highlight conflicts)
# -----------------------------------------------------------------------------

ROUND1_PROMPT = """Round 1 — Coarse Persona Extraction

Task:
1) Read the conversation below and provide:
   - A Big Five score for each trait in the range 0.0 - 1.0:
     - openness, conscientiousness, extraversion, agreeableness, neuroticism
   - A concise (1-3 sentences) `speaking_style_summary`
   - Up to 5 `core_keywords` (single words) that capture the person's core personality

Requirements:
- Output JSON only. No additional commentary.
- Follow the structure in the example exactly when possible.
- If a trait cannot be inferred, set its value to null.

Schema hint:
{schema_example}

Conversation:
```
{dialogue_text}
```
"""

ROUND2_PROMPT = """Round 2 — Fine-grained Analysis

Input:
- Conversation (same as Round 1)
- Round1 JSON output (below) — use it as context

Tasks:
1) Extract `emotional_patterns`:
   - `dominant_emotions`: list of short emotion words (max 8)
   - `triggers`: situations/topics causing strong emotions
   - `recovery_behaviors`: how the person calms down / self-soothes
   - `expression_style`: brief phrase describing emotional expression

2) Extract `values`:
   - `frequent_topics`: list of topics they frequently discuss
   - `attitudes`: short mapping for domains like work/love/family (2-5 keys)
   - `life_view`: 1-2 sentence summary if inferrable
   - `humor_style`: short phrase (if present)

3) Identify `taboos` and `special_quirks` (lists).

Requirements:
- Output JSON only, using the structure in the example below.
- Be conservative: prefer empty lists or null rather than guessing.
- Keep lists compact and focused.

Schema hint:
{schema_example}

Conversation:
```
{dialogue_text}
```

Round1 output:
```
{round1_output}
```
"""

ROUND3_PROMPT = """Round 3 — Representative Dialogue Examples

Task:
1) From the conversation select 5-10 representative snippets that illustrate the person's:
   - speaking style
   - emotional reactions
   - values or typical behaviors
2) For each snippet include:
   - `context`: short note when/why this happens
   - `original`: the exact original messages (do NOT paraphrase; preserve punctuation and emojis)
   - `trigger`: what topic/situation led to this exchange
   - `note`: one-sentence reason why this snippet is representative

Requirements:
- Output JSON only in the format shown in the example.
- Preserve original text verbatim.

Schema hint:
{schema_example}

Conversation:
```
{dialogue_text}
```
"""

ROUND4_PROMPT = """Round 4 — Consistency & Conflict Check

Input:
- Persona draft JSON (combined from previous rounds)
- The selected examples JSON

Tasks:
1) Verify whether the described persona attributes are consistent with the examples.
2) If any inconsistencies or overconfident inferences exist, list up to 10 `conflicts` with:
   - `field` (e.g., 'extraversion', 'taboos')
   - `issue` short description
   - `evidence` pointing to where the conflict comes from (line references or example indices)
3) Produce `validated_persona`: the persona draft with clarifying notes or corrections where needed.

Requirements:
- Output JSON only, matching the example.
- Be explicit about uncertainty (use "uncertain" flags or nulls as needed).

Schema hint:
{schema_example}

Persona draft:
```
{persona_json}
```

Examples:
```
{examples_json}
```
"""

# -----------------------------------------------------------------------------
# Utility mapping and helper
# -----------------------------------------------------------------------------
_PROMPTS: Dict[str, str] = {
    "system": SYSTEM_PROMPT,
    "round1": ROUND1_PROMPT,
    "round2": ROUND2_PROMPT,
    "round3": ROUND3_PROMPT,
    "round4": ROUND4_PROMPT,
}

_SCHEMA_EXAMPLES: Dict[str, str] = {
    "round1": _BIG_FIVE_SCHEMA_EXAMPLE,
    "round2": _ROUND2_SCHEMA_EXAMPLE,
    "round3": _ROUND3_SCHEMA_EXAMPLE,
    "round4": _ROUND4_SCHEMA_EXAMPLE,
}


def render_prompt(name: str, **kwargs: Any) -> str:
    """
    Render a named prompt with provided keyword replacements.

    Args:
        name: one of "system", "round1", "round2", "round3", "round4".
        kwargs: variables referenced in the template, e.g. dialogue_text,
                round1_output, persona_json, examples_json, etc.

    Returns:
        A fully formatted prompt string ready to pass to the LLM.

    Notes:
    - Templates expect `dialogue_text` in most rounds.
    - The helper will automatically inject the schema hint for the round when available.
    """
    key = name.lower()
    if key not in _PROMPTS:
        raise KeyError(f"Unknown prompt name: {name!r}")

    template = _PROMPTS[key]
    # Inject schema example into kwargs if not present and available
    if key in _SCHEMA_EXAMPLES and "schema_example" not in kwargs:
        kwargs["schema_example"] = _SCHEMA_EXAMPLES[key]

    try:
        return template.format(**kwargs)
    except KeyError as e:
        missing = e.args[0] if e.args else "<unknown>"
        raise KeyError(f"Missing template variable: {missing} for prompt '{name}'") from e


# -----------------------------------------------------------------------------
# Convenience small helper for composing multi-message sequences used by the
# extractor: return (system, user_message) pair for each round.
# -----------------------------------------------------------------------------
def prepare_round_messages(round_name: str, **kwargs: Any) -> Dict[str, str]:
    """
    Return a dict with keys 'system' and 'user' containing the formatted
    system and user prompts for a given round name.
    """
    system = _PROMPTS["system"]
    user = render_prompt(round_name, **kwargs)
    return {"system": system, "user": user}


# -----------------------------------------------------------------------------
# Module-level exported names
# -----------------------------------------------------------------------------
__all__ = [
    "SYSTEM_PROMPT",
    "ROUND1_PROMPT",
    "ROUND2_PROMPT",
    "ROUND3_PROMPT",
    "ROUND4_PROMPT",
    "render_prompt",
    "prepare_round_messages",
]
