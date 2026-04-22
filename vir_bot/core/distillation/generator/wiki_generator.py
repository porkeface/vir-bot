# -*- coding: utf-8 -*-
"""
WikiGenerator

Generates human-readable Markdown "wiki" files for a PersonaProfile produced
by the distillation pipeline and saves them to disk.

Responsibilities:
- Convert a PersonaProfile into a clear, structured Markdown document.
- Provide a `save` helper that writes the Markdown file to disk and creates
  parent directories as needed.
- Keep output deterministic and safe for filenames.

This module aims to be lightweight and dependency-free (stdlib only).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

# Import PersonaProfile and DialogueExample from the analyzer module.
# The analyzer module is part of this package and is expected to exist.
try:
    from vir_bot.core.distillation.analyzer.extractor import (
        DialogueExample,
        PersonaProfile,
    )
except Exception:  # pragma: no cover - defensive import for different contexts
    # Provide lightweight fallback types to keep type hints valid in editors
    PersonaProfile = Any  # type: ignore
    DialogueExample = Any  # type: ignore


# Simple filename sanitizer
_FILENAME_SAFE_RE = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff\-_\. ]+")


def _safe_filename(name: str) -> str:
    """
    Make a filesystem-safe filename from a display name.
    Keeps Chinese/Japanese characters, ASCII letters/numbers, dash, underscore, dot and space.
    Trims and replaces multiple spaces with single underscore.
    """
    if not name:
        name = "persona"
    s = str(name).strip()
    # Remove unsafe chars
    s = _FILENAME_SAFE_RE.sub("", s)
    # Replace spaces with underscores
    s = re.sub(r"\s+", "_", s)
    # Limit length
    return s[:200]


def _maybe_serializable(obj: Any) -> Any:
    """
    Convert dataclasses and common container types into JSON-serializable structures.
    """
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, dict):
        return {k: _maybe_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_maybe_serializable(x) for x in obj]
    try:
        json.dumps(obj)
        return obj
    except Exception:
        return str(obj)


class WikiGenerator:
    """
    WikiGenerator produces Markdown and saves it to disk.

    Usage:
        gen = WikiGenerator()
        md = gen.generate(profile, name="小雅")
        gen.save(profile, name="小雅", output_dir="./data/wiki/characters")

    Options (constructor):
        - author: optional string to include in front-matter/footer
        - include_raw_notes: whether to append raw_notes JSON to the end of the doc
        - template: optional callable(template_str) to further post-process generated markdown
    """

    def __init__(
        self,
        *,
        author: Optional[str] = None,
        include_raw_notes: bool = False,
        template: Optional[Any] = None,
    ) -> None:
        self.author = author
        self.include_raw_notes = include_raw_notes
        # template can be a callable that accepts (md:str, profile:PersonaProfile, name:str) -> str
        self.template = template

    def generate(self, profile: PersonaProfile, name: Optional[str] = None) -> str:
        """
        Generate a Markdown representation for the provided PersonaProfile.

        Returns:
            A UTF-8 string containing the Markdown document.
        """
        title = name or (getattr(profile, "name", None) or "Unknown Persona")
        lines: List[str] = []

        # Front matter (simple)
        lines.append(f"# {title}")
        meta_items: List[str] = []
        if self.author:
            meta_items.append(f"Author: {self.author}")
        meta_items.append(f"Generated: {datetime.utcnow().isoformat()}Z")
        # model or source hints if present in raw_notes
        if getattr(profile, "raw_notes", None):
            rn = profile.raw_notes
            src = None
            if isinstance(rn, dict):
                src = rn.get("source") or rn.get("model") or rn.get("provider")
            if src:
                meta_items.append(f"Source: {src}")
        if meta_items:
            lines.append("")
            for m in meta_items:
                lines.append(f"*{m}*")
        lines.append("")

        # Summary / short description
        summary = getattr(profile, "summary", "") or ""
        if summary:
            lines.append("## Summary")
            lines.append("")
            lines.append(summary.strip())
            lines.append("")

        # Big Five
        big_five = getattr(profile, "big_five", None) or {}
        if big_five:
            lines.append("## Big Five (估计)")
            lines.append("")
            # order explicitly
            for k in (
                "openness",
                "conscientiousness",
                "extraversion",
                "agreeableness",
                "neuroticism",
            ):
                v = big_five.get(k)
                if v is None:
                    display = "N/A"
                else:
                    try:
                        display = f"{float(v):.2f}"
                    except Exception:
                        display = str(v)
                lines.append(f"- **{k.capitalize()}**: {display}")
            lines.append("")

        # Speaking style
        ss = getattr(profile, "speaking_style", None)
        if ss:
            lines.append("## Speaking Style")
            lines.append("")
            # Attempt to render fields that commonly exist
            if getattr(ss, "summary", None):
                lines.append(ss.summary.strip())
                lines.append("")
            # filler words
            filler = getattr(ss, "filler_words", None)
            if filler:
                lines.append("- Filler words / common tokens: " + ", ".join(map(str, filler)))
            # punctuation habits
            punc = getattr(ss, "punctuation_habits", None) or {}
            if punc:
                punc_items = ", ".join(f"{k}:{v}" for k, v in punc.items())
                lines.append(f"- Punctuation habits: {punc_items}")
            # emoji stats
            emoji = getattr(ss, "emoji_stats", None) or {}
            if emoji:
                lines.append(f"- Emoji usage (sample): {json.dumps(emoji, ensure_ascii=False)}")
            lines.append("")

        # Emotional patterns
        ep = getattr(profile, "emotional_patterns", None)
        if ep:
            lines.append("## Emotional Patterns")
            lines.append("")
            dom = getattr(ep, "dominant_emotions", None) or []
            if dom:
                lines.append("- Dominant emotions: " + ", ".join(map(str, dom)))
            triggers = getattr(ep, "triggers", None) or []
            if triggers:
                lines.append("- Triggers: " + ", ".join(map(str, triggers)))
            rec = getattr(ep, "recovery_behaviors", None) or []
            if rec:
                lines.append("- Recovery / calming behaviors: " + ", ".join(map(str, rec)))
            expr = getattr(ep, "expression_style", None)
            if expr:
                lines.append("- Expression style: " + str(expr))
            lines.append("")

        # Values and knowledge
        vals = getattr(profile, "values", None)
        if vals:
            lines.append("## Values & Interests")
            lines.append("")
            freq = getattr(vals, "frequent_topics", None) or []
            if freq:
                lines.append("- Frequent topics: " + ", ".join(map(str, freq)))
            attitudes = getattr(vals, "attitudes", None) or {}
            if attitudes:
                lines.append("- Attitudes:")
                for k, v in attitudes.items():
                    lines.append(f"  - **{k}**: {v}")
            life_view = getattr(vals, "life_view", None)
            if life_view:
                lines.append("- Life view: " + str(life_view))
            humor = getattr(vals, "humor_style", None)
            if humor:
                lines.append("- Humor style: " + str(humor))
            lines.append("")

        # Taboos and quirks
        taboos = getattr(profile, "taboos", None) or []
        quirks = getattr(profile, "special_quirks", None) or []
        if taboos:
            lines.append("## Taboos / Avoid")
            lines.append("")
            for t in taboos:
                lines.append(f"- {t}")
            lines.append("")
        if quirks:
            lines.append("## Special Habits / Quirks")
            lines.append("")
            for q in quirks:
                lines.append(f"- {q}")
            lines.append("")

        # Dialogue examples
        examples = getattr(profile, "dialogue_examples", None) or []
        if examples:
            lines.append("## Representative Dialogue Examples")
            lines.append("")
            for i, ex in enumerate(self._ensure_examples_iterable(examples), start=1):
                ctx = getattr(ex, "context", "") or ""
                orig = getattr(ex, "original", "") or ""
                trig = getattr(ex, "trigger", None)
                note = getattr(ex, "note", None)
                lines.append(f"### Example {i}")
                if ctx:
                    lines.append(f"- Context: {ctx}")
                if trig:
                    lines.append(f"- Trigger: {trig}")
                lines.append("")
                # Preserve original text verbatim in a code block style fence for clarity
                lines.append("```text")
                lines.append(orig)
                lines.append("```")
                if note:
                    lines.append("")
                    lines.append(f"- Note: {note}")
                lines.append("")

        # Footer / raw notes
        if self.include_raw_notes and getattr(profile, "raw_notes", None):
            lines.append("----")
            lines.append("## Raw Notes (for reviewers)")
            lines.append("")
            try:
                serial = json.dumps(
                    _maybe_serializable(profile.raw_notes), ensure_ascii=False, indent=2
                )
            except Exception:
                serial = str(profile.raw_notes)
            lines.append("```json")
            lines.append(serial)
            lines.append("```")
            lines.append("")

        # Optionally attach a machine-readable JSON block of the persona
        try:
            persona_json = json.dumps(
                _maybe_serializable(self._profile_to_dict(profile)), ensure_ascii=False, indent=2
            )
            lines.append("----")
            lines.append("### Machine-readable Persona (JSON)")
            lines.append("")
            lines.append("```json")
            lines.append(persona_json)
            lines.append("```")
            lines.append("")
        except Exception:
            # ignore serialization errors but continue
            pass

        md = "\n".join(lines).rstrip() + "\n"

        # Give template a chance to post-process
        if callable(self.template):
            try:
                md = self.template(md, profile, title)
            except Exception:
                # don't fail generation if template crashes
                pass

        return md

    def save(self, profile: PersonaProfile, name: Optional[str], output_dir: str) -> Path:
        """
        Save the generated markdown to `output_dir/{safe_name}.md`.

        Returns:
            Path object of the written file.
        """
        safe_name = _safe_filename(name or getattr(profile, "name", "") or "persona")
        out_dir = Path(output_dir).expanduser().resolve()
        out_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{safe_name}.md"
        target = out_dir / filename

        md = self.generate(profile, name=name)
        # Write file with UTF-8
        with target.open("w", encoding="utf-8") as f:
            f.write(md)
        return target

    # ------------------------
    # Internal helpers
    # ------------------------

    def _ensure_examples_iterable(
        self, examples: Iterable[DialogueExample]
    ) -> Iterable[DialogueExample]:
        """
        Normalize examples to an iterable of DialogueExample-like objects/dicts.
        Accepts either list-of-dataclass objects or list-of-dicts.
        """
        if not examples:
            return []
        # If first element is a dict, yield lightweight wrappers
        first = None
        try:
            first = next(iter(examples))
        except Exception:
            return []
        # If elements are dicts, create a simple object-like wrapper
        if isinstance(first, dict):

            class _D:
                def __init__(self, d: Dict[str, Any]):
                    self.context = d.get("context") or d.get("ctx") or ""
                    self.original = d.get("original") or d.get("text") or d.get("utterance") or ""
                    self.trigger = d.get("trigger")
                    self.note = d.get("note")

            return (_D(d) for d in examples)  # type: ignore
        # Otherwise assume they are objects with attributes
        return examples  # type: ignore

    def _profile_to_dict(self, profile: PersonaProfile) -> Dict[str, Any]:
        """
        Convert the PersonaProfile into a plain dict suitable for JSON serialization.
        Conservative: only include known attributes if present.
        """
        # If it's already a dataclass, prefer asdict
        try:
            if is_dataclass(profile):
                return asdict(profile)
        except Exception:
            pass

        # Generic mapping fallback
        d: Dict[str, Any] = {}
        for key in (
            "name",
            "summary",
            "big_five",
            "speaking_style",
            "emotional_patterns",
            "values",
            "dialogue_examples",
            "taboos",
            "special_quirks",
            "raw_notes",
        ):
            val = getattr(profile, key, None)
            if val is None:
                continue
            # Ensure serializable shape
            d[key] = _maybe_serializable(val)
        return d
