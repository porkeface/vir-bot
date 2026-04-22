"""
GenericParser for simple JSON / NDJSON / TXT chat exports.

This parser is intentionally lightweight and defensive: it supports common
export formats such as:

- JSON array of message objects:
  [
    {"sender": "Alice", "content": "Hi", "timestamp": "2023-01-01T12:00:00Z"},
    ...
  ]

- NDJSON (newline-delimited JSON): one JSON object per line

- Plain text: one message per line, common patterns:
    2023-01-01 12:00:00 Alice: Hello world
    Alice: Hello world
    [12:00] Alice: Hello
  The TXT parser will attempt to extract a sender, optional timestamp and the
  remaining content. If it cannot detect a timestamp it will leave it as None.

The parser returns a list of DialogueTurn objects (see base.ChatParser) and
tries to preserve chronological order. If timestamps are available they will be
used for sorting; otherwise original file order is preserved.

Note: This module depends on the abstract base and models in parser.base.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .base import ChatParser, DialogueTurn, parse_timestamp

# Simple regexes for text parsing
# Examples matched:
#   2023-01-01 12:00:00 Alice: message...
#   [12:00] Alice: message...
#   12:00 Alice: message...
#   Alice: message...
_TIMESTAMP_SENDER_RE = re.compile(
    r"""^\s*
    (?:
        (?P<iso>\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)    # ISO-ish
      |
        (?P<bracket>\[\s*\d{1,2}:\d{2}(?::\d{2})?\s*\])                                       # [12:34] style
      |
        (?P<time>\d{1,2}:\d{2}(?::\d{2})?)                                                   # 12:34 or 12:34:56
    )?
    \s*
    (?P<sender>[^\:\n]{1,80}?)\s*:\s*(?P<content>.*)$
    """,
    re.VERBOSE,
)


class GenericParser(ChatParser):
    """
    Generic parser for JSON/NDJSON/TXT chat records.

    Args:
        encoding: file encoding (defaults to value from ChatParser base)
        min_msg_length: discard empty or very short messages (optional)
    """

    def __init__(self, *, encoding: str | None = None, min_msg_length: int = 0) -> None:
        super().__init__(encoding=encoding or "utf-8")
        self.min_msg_length = int(min_msg_length)

    def parse(self, path: str | Path) -> List[DialogueTurn]:
        """
        Parse the file at `path` and return a list of `DialogueTurn`.

        The method autodetects file type by extension and by content:
        - .json -> try JSON array parse
        - .ndjson or other -> try NDJSON then fallback to TXT parsing
        - .txt -> text line parser

        Raises:
            FileNotFoundError if file does not exist.
            ValueError on irrecoverable parse errors.
        """
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Chat file not found: {p}")

        text = self.read_text(p)

        # Heuristics based on extension first
        suffix = p.suffix.lower()
        try_parsers: List[str] = []
        if suffix == ".json":
            try_parsers = ["json_array", "ndjson", "txt_lines"]
        elif suffix in (".ndjson", ".jsonl"):
            try_parsers = ["ndjson", "json_array", "txt_lines"]
        elif suffix in (".txt", ".log", ".chat"):
            try_parsers = ["txt_lines", "ndjson", "json_array"]
        else:
            # Unknown extension: try structured parsers first if it looks like JSON
            stripped = text.lstrip()
            if stripped.startswith("[") or stripped.startswith("{"):
                try_parsers = ["json_array", "ndjson", "txt_lines"]
            else:
                try_parsers = ["ndjson", "txt_lines", "json_array"]

        # Attempt parsers in order until one yields turns
        last_error: Optional[Exception] = None
        for parser in try_parsers:
            try:
                if parser == "json_array":
                    turns = self._parse_json_array(text)
                elif parser == "ndjson":
                    turns = self._parse_ndjson(text)
                elif parser == "txt_lines":
                    turns = self._parse_txt_lines(text)
                else:
                    continue

                # Filter out very short messages if requested
                turns = [t for t in turns if len(t.content.strip()) >= self.min_msg_length]

                # Assign stable turn_ids if missing and ensure chronological order
                self._normalize_turn_ids_and_sort(turns)
                return turns
            except Exception as e:
                last_error = e
                # try next parser
                continue

        # If all parsers failed, raise a helpful error
        raise ValueError(f"Failed to parse chat file '{p}': {last_error!r}")

    # ---------- Parser implementations ----------

    def _parse_json_array(self, text: str) -> List[DialogueTurn]:
        """
        Parse a JSON array of message objects.
        Each object is expected to be a mapping with keys similar to:
        'sender', 'content', 'timestamp' etc.

        Returns list of DialogueTurn.
        """
        data = json.loads(text)
        if not isinstance(data, list):
            # Sometimes exports wrap in an envelope like {"messages": [...]}
            if isinstance(data, dict) and "messages" in data and isinstance(data["messages"], list):
                data = data["messages"]
            else:
                raise ValueError("JSON content is not an array of messages")
        return self._turns_from_dicts(data)

    def _parse_ndjson(self, text: str) -> List[DialogueTurn]:
        """
        Parse newline-delimited JSON: one JSON object per non-empty line.
        Ignores blank lines. Returns list of DialogueTurn.
        """
        turns: List[DialogueTurn] = []
        for lineno, line in enumerate(text.splitlines(), start=1):
            s = line.strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
            except json.JSONDecodeError:
                # If a single line isn't valid JSON this format may not apply
                raise ValueError(f"NDJSON parse failed at line {lineno}")
            if not isinstance(obj, dict):
                # Only dict-like messages are supported
                continue
            turns.extend(self._turns_from_dicts([obj]))
        return turns

    def _parse_txt_lines(self, text: str) -> List[DialogueTurn]:
        """
        Parse plain text where each line typically contains a message.
        Uses a forgiving regex to extract optional timestamp, sender and content.
        Falls back to treating the entire line as content with an unknown sender.
        """
        turns: List[DialogueTurn] = []
        for idx, raw_line in enumerate(text.splitlines()):
            line = raw_line.strip()
            if not line:
                continue
            m = _TIMESTAMP_SENDER_RE.match(line)
            if m:
                sender = (m.group("sender") or "").strip()
                content = (m.group("content") or "").strip()
                # Combine any detected timestamp groups into a string to parse
                ts_candidate = m.group("iso") or m.group("bracket") or m.group("time") or None
                # If bracket style like [12:34] keep inner text
                if ts_candidate and ts_candidate.startswith("[") and ts_candidate.endswith("]"):
                    ts_candidate = ts_candidate[1:-1].strip()
                ts = parse_timestamp(ts_candidate) if ts_candidate else None
                dt = DialogueTurn(
                    turn_id=idx,
                    sender=sender or "",
                    recipient=None,
                    content=content,
                    timestamp=ts,
                    metadata={"raw_line": raw_line},
                )
                turns.append(dt)
            else:
                # No sender detected; treat entire line as content, unknown sender
                dt = DialogueTurn(
                    turn_id=idx,
                    sender="",
                    recipient=None,
                    content=line,
                    timestamp=None,
                    metadata={"raw_line": raw_line},
                )
                turns.append(dt)
        return turns

    # ---------- Helpers ----------

    def _turns_from_dicts(self, items: Iterable[Dict[str, Any]]) -> List[DialogueTurn]:
        """
        Convert iterable of mapping-like message objects into DialogueTurn using
        the base class utility where possible.
        """
        # Re-use base.build_turns_from_dicts by passing a list
        # But build_turns_from_dicts is an instance method on ChatParser
        # Accept both list of dicts or generator
        items_list = list(items)
        # The base method already parses timestamp and maps common keys
        return self.build_turns_from_dicts(items_list)

    def _normalize_turn_ids_and_sort(self, turns: List[DialogueTurn]) -> None:
        """
        Ensure turn_id is monotonically increasing and sort by timestamp if
        available. This mutates the provided list in-place.
        """
        # If any timestamp exists, attempt to sort by timestamp (None go last
        # while preserving original order among None timestamps).
        has_ts = any(t.timestamp is not None for t in turns)
        if has_ts:
            # Preserve stable ordering among equal keys by using enumerate index
            for idx, t in enumerate(turns):
                # attach original index for tie-breaking
                t.metadata.setdefault("_original_index", idx)
            turns.sort(
                key=lambda t: (
                    t.timestamp
                    if t.timestamp is not None
                    else parse_timestamp(0),  # epoch for None -> keep before others? see below
                    t.metadata.get("_original_index", 0),
                )
            )
            # After sort, if any had timestamp None we might prefer them to be in file order.
            # The above puts None as epoch (1970) so they would come first — that's not ideal.
            # Better: use a very large sentinel for None so they come last.
            # We'll re-sort using a correction:
            sentinel = None
            try:
                from datetime import datetime, timezone

                sentinel = datetime.max.replace(tzinfo=timezone.utc)
            except Exception:
                sentinel = None

            def _ts_key(t):
                return (
                    t.timestamp if t.timestamp is not None else sentinel,
                    t.metadata.get("_original_index", 0),
                )

            turns.sort(key=_ts_key)

        # Assign monotonic turn_id based on current ordering
        for i, t in enumerate(turns):
            t.turn_id = i

        # Remove internal metadata helper if present
        for t in turns:
            t.metadata.pop("_original_index", None)
