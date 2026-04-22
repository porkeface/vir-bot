"""
Base classes and data models for chat record parsers used in the distillation pipeline.

This module defines:
- `DialogueTurn`: a small dataclass representing a single conversational turn.
- `ChatParser`: an abstract base class that all platform-specific parsers should inherit
  from. The parser must implement `parse(path: str) -> list[DialogueTurn]`.

Design goals:
- Keep the data model minimal and serializable.
- Provide a few helpful utility methods for common parsing tasks (timestamp normalization,
  simple file reading) so implementations can reuse them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# Public API
__all__ = [
    "DialogueTurn",
    "ChatParser",
    "parse_timestamp",
    "DialogueTurns",
]


DialogueTurns = List["DialogueTurn"]


@dataclass
class DialogueTurn:
    """
    Represents a single conversational turn in the chat logs.

    Fields:
    - `turn_id`: monotonically increasing integer (optional, may be 0 if unknown)
    - `sender`: display id or name of the message sender
    - `recipient`: optional recipient (conversation-level or direct recipient)
    - `content`: raw text content of the message (preserve original text)
    - `timestamp`: optional timezone-aware datetime when the message was sent
    - `metadata`: free-form dict to store platform-specific fields (message_id, reactions, raw_html, etc.)
    """

    turn_id: int = 0
    sender: str = ""
    recipient: Optional[str] = None
    content: str = ""
    timestamp: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dict (datetimes converted to ISO strings)."""
        d = asdict(self)
        if self.timestamp:
            # Ensure ISO 8601 with timezone information if available
            d["timestamp"] = self.timestamp.isoformat()
        else:
            d["timestamp"] = None
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DialogueTurn":
        """Create a DialogueTurn from a dictionary, parsing timestamps if necessary."""
        ts = data.get("timestamp")
        if isinstance(ts, str):
            ts_parsed = parse_timestamp(ts)
        else:
            ts_parsed = ts  # could be None or already a datetime
        return cls(
            turn_id=int(data.get("turn_id", 0) or 0),
            sender=str(data.get("sender", "") or ""),
            recipient=data.get("recipient"),
            content=str(data.get("content", "") or ""),
            timestamp=ts_parsed,
            metadata=dict(data.get("metadata") or {}),
        )


def parse_timestamp(value: Union[str, int, float, datetime, None]) -> Optional[datetime]:
    """
    Normalize common timestamp representations into a timezone-aware UTC `datetime`.

    Supported inputs:
    - ISO 8601 string (with or without timezone)
    - Unix timestamp (int/float) seconds since epoch
    - datetime object (naive -> treated as UTC)

    Returns None if input is falsy or cannot be parsed.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            # Treat naive datetimes as UTC to keep downstream logic consistent
            return dt.replace(tzinfo=timezone.utc)
        return dt
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except Exception:
            return None
    if isinstance(value, str):
        s = value.strip()
        # Try numeric unix timestamp in string form
        if s.isdigit() or (s.replace(".", "", 1).isdigit() and s.count(".") <= 1):
            try:
                return datetime.fromtimestamp(float(s), tz=timezone.utc)
            except Exception:
                pass
        # Try ISO format
        try:
            # datetime.fromisoformat supports offsets like "+08:00" (py3.11+)
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            # Fallback: try a few common formats
            from datetime import datetime as _dt

            fmts = [
                "%Y-%m-%d %H:%M:%S%z",
                "%Y-%m-%d %H:%M:%S",
                "%Y/%m/%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%S",
            ]
            for fmt in fmts:
                try:
                    dt = _dt.strptime(s, fmt)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    return dt
                except Exception:
                    continue
    return None


class ChatParser(ABC):
    """
    Abstract base class for chat record parsers.

    Implementations must override `parse(path: str) -> list[DialogueTurn]`.

    Notes:
    - Parsers should preserve original message text in `DialogueTurn.content`.
    - Platform-specific fields should be stored in `DialogueTurn.metadata`.
    - Parsers are allowed to be simple (file-level parsing) or more advanced
      (extracting threads, group messages, mentions) as long as they return a
      linear list of `DialogueTurn` objects for downstream processing.
    """

    def __init__(self, *, encoding: str = "utf-8") -> None:
        self.encoding = encoding

    @abstractmethod
    def parse(self, path: Union[str, Path]) -> DialogueTurns:
        """
        Parse the chat record file at `path` and return a list of `DialogueTurn`.

        Args:
            path: path to the chat export file (platform-specific format).

        Returns:
            A list of DialogueTurn in chronological order (oldest first) if possible.
        """
        raise NotImplementedError

    def read_text(self, path: Union[str, Path]) -> str:
        """
        Convenience helper to read a file as text using the parser's encoding.

        Implementations can call this to get raw content before custom parsing.
        """
        p = Path(path)
        # For safety, raise a readable exception if file missing
        if not p.exists():
            raise FileNotFoundError(f"Chat file not found: {p}")
        # Read in binary then decode to avoid issues with unknown encodings
        with p.open("rb") as f:
            b = f.read()
        try:
            return b.decode(self.encoding)
        except Exception:
            # Fallback: try utf-8 and latin-1
            try:
                return b.decode("utf-8")
            except Exception:
                return b.decode("latin-1", errors="ignore")

    # Optional helper: many parsers might want to extract basic turn records from a
    # JSON-like list. Provide a small utility to convert a list of dict-like messages.
    def build_turns_from_dicts(self, items: List[Dict[str, Any]]) -> DialogueTurns:
        """
        Convert a list of mapping-like message objects into DialogueTurn records.

        Expected keys in each item (not strictly required):
            - sender / from / user
            - recipient / to
            - content / text / message
            - timestamp / ts / time (various formats accepted)

        The function attempts to be flexible and will populate metadata with any
        remaining fields.
        """
        turns: DialogueTurns = []
        for idx, item in enumerate(items):
            sender = (
                item.get("sender")
                or item.get("from")
                or item.get("user")
                or item.get("author")
                or ""
            )
            recipient = item.get("recipient") or item.get("to") or None
            content = item.get("content") or item.get("text") or item.get("message") or ""
            ts = (
                item.get("timestamp")
                or item.get("ts")
                or item.get("time")
                or item.get("date")
                or None
            )
            parsed_ts = parse_timestamp(ts)
            # Collect metadata: everything except the core fields
            metadata = {
                k: v
                for k, v in item.items()
                if k
                not in (
                    "sender",
                    "from",
                    "user",
                    "author",
                    "recipient",
                    "to",
                    "content",
                    "text",
                    "message",
                    "timestamp",
                    "ts",
                    "time",
                    "date",
                )
            }
            turn = DialogueTurn(
                turn_id=int(item.get("turn_id", idx)) if item.get("turn_id") is not None else idx,
                sender=str(sender),
                recipient=recipient,
                content=str(content),
                timestamp=parsed_ts,
                metadata=metadata,
            )
            turns.append(turn)
        return turns
