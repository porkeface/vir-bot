#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Command-line interface for the distillation pipeline.

Provides a lightweight CLI that:
- Loads configuration (config.yaml or env overrides)
- Instantiates an AI provider from the project's AI config
- Runs the distillation pipeline (parse -> analyze -> generate)
- Optionally evaluates and writes the wiki markdown to disk

Example usages (see DISTILLATION_PLAN.md):
  python -m vir_bot.core.distillation.cli \
      --input ./data/chat_records/myfriend.json \
      --name "小雅" \
      --output ./data/wiki/characters/

  python -m vir_bot.core.distillation.cli \
      --input ./data/chat_records/myfriend.json \
      --name "小雅" \
      --output ./data/wiki/characters/ \
      --evaluate

  python -m vir_bot.core.distillation.cli \
      --input ./data/chat_records/myfriend.json \
      --name "小雅" \
      --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from vir_bot.config import get_config, load_config
from vir_bot.core.ai_provider import AIProviderFactory
from vir_bot.core.distillation import create_pipeline

logger = logging.getLogger("vir_bot.distillation.cli")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="vir-bot-distill",
        description="Persona distillation CLI — parse chat logs, extract persona, generate wiki card.",
    )

    p.add_argument(
        "--config",
        "-c",
        help="Path to config.yaml (optional). If omitted, environment/default is used.",
        default=None,
    )
    p.add_argument(
        "--input", "-i", required=True, help="Path to chat export file (json/ndjson/txt...)."
    )
    p.add_argument(
        "--name",
        "-n",
        required=True,
        help="Display name for the persona (used for filenames and title).",
    )
    p.add_argument(
        "--output",
        "-o",
        help="Directory to write generated wiki markdown. Defaults to './data/wiki/characters/'.",
        default="./data/wiki/characters/",
    )
    p.add_argument(
        "--evaluate", action="store_true", help="Run lightweight evaluation after generation."
    )
    p.add_argument(
        "--dry-run", action="store_true", help="Do not write files to disk; only print a summary."
    )
    p.add_argument(
        "--incremental",
        action="store_true",
        help="(reserved) run incremental update based on existing persona file.",
    )
    p.add_argument(
        "--existing", help="Path to existing persona file when using --incremental.", default=None
    )
    p.add_argument(
        "--parser",
        help="Force parser name (generic/wechat/qq/discord). Default: auto-detect/generic.",
        default="auto",
    )
    p.add_argument(
        "--timeout", type=int, help="Per-LLM-call timeout (seconds). Default: 120", default=120
    )
    p.add_argument("--verbose", "-v", action="count", help="Increase verbosity (use -v, -vv).")

    return p


async def _run_distillation_async(args: argparse.Namespace) -> int:
    # Load configuration
    if args.config:
        cfg = load_config(args.config)
    else:
        # load default config (reads VIRBOT_CONFIG env or config.yaml)
        cfg = get_config()

    # Create AI provider from config.ai
    try:
        ai_provider = AIProviderFactory.create(cfg.ai)
    except Exception as e:
        logger.exception("Failed to create AI provider from configuration: %s", e)
        return 2

    # Build pipeline
    pipeline = create_pipeline(
        ai_provider,
        config=cfg,
        parser_name=(args.parser if args.parser != "auto" else None),
        wiki_output_dir=args.output,
    )

    # Run pipeline
    try:
        result = await pipeline.run(
            input_path=args.input,
            name=args.name,
            evaluate=args.evaluate,
            dry_run=args.dry_run,
            incremental=args.incremental,
            existing=args.existing,
            timeout_seconds=args.timeout,
        )
    except FileNotFoundError as e:
        logger.error("Input error: %s", e)
        return 3
    except Exception as e:
        logger.exception("Distillation failed: %s", e)
        return 4
    finally:
        # Best-effort provider cleanup if it offers close()
        try:
            close_coro = getattr(ai_provider, "close", None)
            if close_coro:
                maybe = close_coro()
                if asyncio.iscoroutine(maybe):
                    await maybe
        except Exception:
            logger.debug("Error while closing AI provider", exc_info=True)

    # Print summary and optionally write result details
    try:
        print_summary(result, args)
    except Exception:
        logger.exception("Failed to print result summary")

    return 0


def print_summary(result: Any, args: argparse.Namespace) -> None:
    """
    Print a user-friendly summary of the DistillationResult.
    The structure of result is expected to have simple attributes or dict-like fields.
    """
    print("\n== Distillation Summary ==")
    name = (
        getattr(result, "name", None) or result.get("name")
        if isinstance(result, dict)
        else "<unknown>"
    )
    print(f"Persona: {name}")
    md_path = getattr(result, "markdown_path", None) or (
        result.get("markdown_path") if isinstance(result, dict) else None
    )
    if args.dry_run:
        print("Dry run: no file was written.")
    else:
        print(f"Markdown output: {md_path or 'N/A'}")

    metrics: Optional[Dict[str, float]] = getattr(result, "metrics", None) or (
        result.get("metrics") if isinstance(result, dict) else None
    )
    if metrics:
        print("\nMetrics:")
        try:
            for k, v in metrics.items():
                # print floats nicely
                if isinstance(v, float):
                    print(f"  - {k}: {v:.3f}")
                else:
                    print(f"  - {k}: {v}")
        except Exception:
            print(f"  - {metrics}")

    # Try to show summary text and a small preview of the generated markdown
    profile = getattr(result, "profile", None) or (
        result.get("profile") if isinstance(result, dict) else None
    )
    if profile:
        summary = None
        if isinstance(profile, dict):
            summary = profile.get("summary")
        else:
            summary = getattr(profile, "summary", None)
        if summary:
            print("\nPersona Summary:")
            print("  " + summary.replace("\n", "\n  "))

    markdown = getattr(result, "markdown", None) or (
        result.get("markdown") if isinstance(result, dict) else None
    )
    if markdown:
        print("\nGenerated markdown preview (first 30 lines):\n")
        lines = markdown.splitlines()
        preview = "\n".join(lines[:30])
        print(preview)
        if len(lines) > 30:
            print("\n... (truncated)\n")

    # Raw notes if verbose
    if args.verbose and getattr(result, "raw_notes", None):
        raw = getattr(result, "raw_notes", None) or (
            result.get("raw_notes") if isinstance(result, dict) else None
        )
        print("\nRaw notes:")
        try:
            print(json.dumps(raw, ensure_ascii=False, indent=2))
        except Exception:
            print(str(raw))


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    ns = parser.parse_args(argv)
    # adjust logging level based on verbose flags
    if ns.verbose:
        if ns.verbose >= 2:
            logging.getLogger().setLevel(logging.DEBUG)
        else:
            logging.getLogger().setLevel(logging.INFO)

    try:
        return asyncio.run(_run_distillation_async(ns))
    except KeyboardInterrupt:
        logger.warning("Interrupted by user")
        return 130
    except Exception:
        logger.exception("Unexpected error in CLI")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
