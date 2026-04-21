"""短期记忆：asyncio Ring Buffer"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import AsyncIterator

import time


@dataclass
class MemoryEntry:
    role: str  # "user" | "assistant"
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)


class ShortTermMemory:
    """基于 deque 的短期记忆，仅保留最近 N 轮对话"""

    def __init__(self, max_turns: int = 20):
        self.max_turns = max_turns
        self._buffer: deque[MemoryEntry] = deque(maxlen=max_turns)

    def add(self, role: str, content: str, metadata: dict | None = None) -> None:
        entry = MemoryEntry(role=role, content=content, metadata=metadata or {})
        self._buffer.append(entry)

    def add_user(self, content: str, metadata: dict | None = None) -> None:
        self.add("user", content, metadata)

    def add_assistant(self, content: str, metadata: dict | None = None) -> None:
        self.add("assistant", content, metadata)

    def get_recent(self, n: int | None = None) -> list[MemoryEntry]:
        """获取最近 n 条记忆，默认全部"""
        n = n or len(self._buffer)
        return list(self._buffer)[-n:]

    def to_messages(self, n: int | None = None) -> list[dict]:
        """转换为 OpenAI 格式 messages"""
        entries = self.get_recent(n)
        return [{"role": e.role, "content": e.content} for e in entries]

    def clear(self) -> None:
        self._buffer.clear()

    def __len__(self) -> int:
        return len(self._buffer)

    def __iter__(self):
        return iter(self._buffer)