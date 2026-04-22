# -*- coding: utf-8 -*-
"""
Distillation pipeline orchestration.

Provides `DistillationPipeline` that wires together:
- parser (platform-specific) -> produces list[DialogueTurn]
- analyzer (PersonaExtractor) -> produces PersonaProfile
- generator (WikiGenerator) -> renders and saves markdown
- (optional) lightweight evaluation that checks basic overlap/consistency

The implementation is backend-agnostic and uses factory helpers from the
distillation subpackages to create components lazily.

Usage example:
    from vir_bot.core.ai_provider import AIProvider
    from vir_bot.core.distillation import create_pipeline
    pipeline = create_pipeline(ai_provider, config=some_config)
    result = await pipeline.run("./data/chat_records/sample.json", name="小雅", evaluate=True)

This module avoids heavy external dependencies and provides reasonable defaults.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from vir_bot.core.ai_provider import AIProvider
from vir_bot.core.distillation.analyzer import create_extractor
from vir_bot.core.distillation.generator import create_wiki_generator
from vir_bot.core.distillation.parser import create_parser

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------
@dataclass
class DistillationResult:
    name: str
    profile: Dict[str, Any]
    markdown: Optional[str] = None
    markdown_path: Optional[str] = None
    metrics: Dict[str, float] = None
    raw_notes: Dict[str, Any] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "profile": self.profile,
            "markdown_path": self.markdown_path,
            "metrics": self.metrics or {},
            "raw_notes": self.raw_notes or {},
        }


# ---------------------------------------------------------------------------
# DistillationPipeline
# ---------------------------------------------------------------------------
class DistillationPipeline:
    """
    Orchestrates the distillation process.

    Parameters
    - ai_provider: an instance implementing `AIProvider` used by analyzers.
    - config: optional configuration object or mapping (pipeline-specific params)
    - parser_name: default parser to use (e.g., "generic", "wechat"). The pipeline
      will attempt to auto-detect parser based on file extension unless parser_name is provided.
    - wiki_output_dir: default directory to save generated wiki markdown.
    """

    def __init__(
        self,
        ai_provider: AIProvider,
        *,
        config: Optional[Any] = None,
        parser_name: Optional[str] = None,
        wiki_output_dir: str = "./data/wiki/characters",
    ) -> None:
        self.ai = ai_provider
        self.config = config
        self.parser_name = parser_name or "generic"
        self.wiki_output_dir = wiki_output_dir

    async def run(
        self,
        input_path: str,
        name: str,
        *,
        evaluate: bool = False,
        dry_run: bool = False,
        incremental: bool = False,
        existing: Optional[str] = None,
        timeout_seconds: int = 120,
    ) -> DistillationResult:
        """
        Execute the full distillation pipeline.

        Steps:
        1. Parse chat exports into DialogueTurn list
        2. Run multi-round LLM analysis (PersonaExtractor)
        3. Generate Markdown (WikiGenerator) and optionally save to disk
        4. (Optional) Evaluate simple similarity metrics between source and distilled persona

        Args:
            input_path: path to chat export file
            name: persona display name
            evaluate: whether to run evaluation step
            dry_run: if True, do not write files to disk
            incremental: reserved for future use (e.g. merging with existing persona)
            existing: path to existing persona file for incremental updates
            timeout_seconds: per-LLM-call timeout (passed to extractor)

        Returns:
            DistillationResult
        """
        logger.info("Starting distillation for '%s' from '%s'", name, input_path)
        # Step 0: validate input file
        p = Path(input_path)
        if not p.exists():
            raise FileNotFoundError(f"Input chat file not found: {input_path}")

        # Step 1: choose/create parser
        parser_name = self._choose_parser_name(p)
        logger.debug("Using parser '%s' for file '%s'", parser_name, input_path)
        parser = create_parser(parser_name)

        # Parsing may be IO-bound; run in thread if parser.parse is blocking.
        turns = await self._maybe_blocking_call(parser.parse, input_path)
        logger.info("Parsed %d dialogue turns", len(turns))

        # Step 2: create extractor and run extraction
        extractor = create_extractor(
            self.ai, prompts=getattr(self.config, "prompts", None), timeout_seconds=timeout_seconds
        )
        profile_obj = await extractor.extract(turns, name=name)
        # Convert to serializable dict
        try:
            profile = (
                profile_obj
                if isinstance(profile_obj, dict)
                else getattr(profile_obj, "__dict__", None) or asdict(profile_obj)
            )
        except Exception:
            # Best-effort fallback
            profile = json.loads(
                json.dumps(
                    profile_obj,
                    default=lambda o: getattr(o, "__dict__", str(o)),
                    ensure_ascii=False,
                )
            )

        # Step 3: generate wiki markdown
        wiki_gen = create_wiki_generator(author=None, include_raw_notes=True)
        md = wiki_gen.generate(profile_obj, name=name)

        md_path = None
        if not dry_run:
            os.makedirs(self.wiki_output_dir, exist_ok=True)
            out_path = Path(self.wiki_output_dir) / f"{self._safe_filename(name)}.md"
            written = wiki_gen.save(profile_obj, name=name, output_dir=self.wiki_output_dir)
            md_path = str(written)
            logger.info("Saved wiki to %s", md_path)
        else:
            logger.info("Dry-run enabled; skipping file write")

        # Step 4: optional evaluation
        metrics: Dict[str, float] = {}
        raw_notes: Dict[str, Any] = (
            profile.get("raw_notes", {}) if isinstance(profile, dict) else {}
        )

        if evaluate:
            try:
                sim = self._evaluate_overlap_similarity(profile_obj, turns)
                metrics["overlap_similarity"] = sim
                # Heuristic pass/fail
                metrics["pass"] = 1.0 if sim >= 0.7 else 0.0
                logger.info("Evaluation complete: similarity=%.3f", sim)
            except Exception as e:
                logger.exception("Evaluation failed: %s", e)
                raw_notes.setdefault("_eval_error", str(e))

        result = DistillationResult(
            name=name,
            profile=profile,
            markdown=md,
            markdown_path=md_path,
            metrics=metrics,
            raw_notes=raw_notes,
        )

        logger.info("Distillation finished for '%s'", name)
        return result

    # ---------------------------
    # Helpers
    # ---------------------------
    def _choose_parser_name(self, path_obj: Path) -> str:
        """
        Choose parser name based on provided parser_name or file extension heuristics.
        """
        if self.parser_name and self.parser_name != "auto":
            return self.parser_name
        # auto heuristics
        ext = path_obj.suffix.lower()
        if ext in (".json", ".ndjson", ".jsonl", ".txt", ".log", ".chat"):
            return "generic"
        # fallback
        return "generic"

    async def _maybe_blocking_call(self, func, *args, **kwargs):
        """
        Run `func` either directly (if coroutine) or in threadpool (if blocking sync).
        """
        if asyncio.iscoroutinefunction(func):
            return await func(*args, **kwargs)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))

    def _safe_filename(self, name: str) -> str:
        # reuse simple sanitizer similar to generator
        s = (name or "persona").strip()
        safe = "".join(ch for ch in s if ch.isalnum() or ch in " -_.")
        safe = safe.replace(" ", "_")
        return safe[:200] or "persona"

    def _tokenize(self, text: str) -> List[str]:
        # very small tokenizer: split on non-alphanumeric and lowercase
        if not text:
            return []
        import re

        toks = [t.lower() for t in re.split(r"[^0-9A-Za-z\u4e00-\u9fff]+", text) if t]
        return toks

    def _evaluate_overlap_similarity(self, profile_obj: Any, turns: List[Any]) -> float:
        """
        Lightweight evaluation: compute Jaccard-like overlap between most frequent
        words in source conversation and the distilled persona (summary + examples).

        Returns a float in [0.0, 1.0], higher means more overlap.
        """
        # Extract source text from turns
        texts = []
        for t in turns:
            try:
                texts.append(getattr(t, "content", "") or str(t))
            except Exception:
                texts.append(str(t))
        source_text = "\n".join(texts)

        # Compose distilled text from profile summary + examples
        parts = []
        try:
            summary = getattr(profile_obj, "summary", None) or (
                profile_obj.get("summary") if isinstance(profile_obj, dict) else None
            )
            if summary:
                parts.append(summary)
        except Exception:
            pass

        try:
            examples = (
                getattr(profile_obj, "dialogue_examples", None)
                or (profile_obj.get("dialogue_examples") if isinstance(profile_obj, dict) else None)
                or []
            )
            for ex in examples:
                if isinstance(ex, dict):
                    parts.append(ex.get("original") or ex.get("text") or "")
                else:
                    parts.append(getattr(ex, "original", "") or str(ex))
        except Exception:
            pass

        distilled_text = "\n".join(parts)

        # Token sets
        src_tokens = set(self._tokenize(source_text))
        dst_tokens = set(self._tokenize(distilled_text))

        if not src_tokens or not dst_tokens:
            return 0.0

        inter = src_tokens.intersection(dst_tokens)
        union = src_tokens.union(dst_tokens)
        jaccard = len(inter) / len(union) if union else 0.0

        # Also compute a weighted overlap by focusing on top-k frequency words
        src_freq = {}
        for t in self._tokenize(source_text):
            src_freq[t] = src_freq.get(t, 0) + 1
        dst_freq = {}
        for t in self._tokenize(distilled_text):
            dst_freq[t] = dst_freq.get(t, 0) + 1

        # pick top 50 tokens from source
        top_src = set(sorted(src_freq.keys(), key=lambda k: -src_freq[k])[:50])
        top_dst = set(sorted(dst_freq.keys(), key=lambda k: -dst_freq[k])[:50])

        if not top_src or not top_dst:
            weighted = jaccard
        else:
            weighted = len(top_src.intersection(top_dst)) / max(1, len(top_src.union(top_dst)))

        # combine jaccard and weighted with a soft balance
        score = 0.5 * jaccard + 0.5 * weighted
        # clamp and return
        return max(0.0, min(1.0, float(score)))
