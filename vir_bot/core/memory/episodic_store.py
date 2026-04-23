"""事件记忆存储 - 用于记住"昨天/今天/最近发生了什么"。"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from vir_bot.utils.logger import logger


@dataclass
class EpisodeRecord:
    """事件记忆记录。"""

    episode_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str = ""

    summary: str = ""
    entities: list[str] = field(default_factory=list)

    start_at: float = field(default_factory=time.time)
    end_at: float = field(default_factory=time.time)

    importance: float = 0.5

    source_message_ids: list[str] = field(default_factory=list)

    episode_type: Literal["daily", "weekly", "session", "event"] = "session"

    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    is_active: bool = True

    @classmethod
    def from_dict(cls, data: dict) -> "EpisodeRecord":
        return cls(**data)

    def to_dict(self) -> dict:
        return asdict(self)


class EpisodicMemoryStore:
    """基于本地 JSON 的事件记忆存储。"""

    def __init__(self, persist_path: str = "./data/memory/episodic_memory.json"):
        self.persist_path = Path(persist_path)
        self.persist_path.parent.mkdir(parents=True, exist_ok=True)
        self._records: dict[str, EpisodeRecord] = {}
        self._load()
        logger.info(f"EpisodicMemoryStore initialized: path={self.persist_path}")

    def _load(self) -> None:
        if not self.persist_path.exists():
            return

        try:
            data = json.loads(self.persist_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning(f"Episodic memory file is invalid JSON: {self.persist_path}")
            return

        for item in data.get("records", []):
            record = EpisodeRecord.from_dict(item)
            self._records[record.episode_id] = record

    def _save(self) -> None:
        payload = {
            "version": "1.0",
            "updated_at": time.time(),
            "records": [record.to_dict() for record in self._records.values()],
        }
        self.persist_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add(
        self,
        *,
        user_id: str,
        summary: str,
        entities: list[str] | None = None,
        start_at: float | None = None,
        end_at: float | None = None,
        importance: float = 0.5,
        source_message_ids: list[str] | None = None,
        episode_type: str = "session",
    ) -> EpisodeRecord:
        now = time.time()
        record = EpisodeRecord(
            user_id=user_id,
            summary=summary.strip(),
            entities=entities or [],
            start_at=start_at or now,
            end_at=end_at or now,
            importance=max(0.0, min(1.0, importance)),
            source_message_ids=source_message_ids or [],
            episode_type=episode_type,
            created_at=now,
            updated_at=now,
        )
        self._records[record.episode_id] = record
        self._save()
        return record

    def get(self, episode_id: str) -> EpisodeRecord | None:
        return self._records.get(episode_id)

    def list_by_user(
        self,
        user_id: str,
        episode_type: str | None = None,
        since: float | None = None,
        until: float | None = None,
    ) -> list[EpisodeRecord]:
        records = [
            record
            for record in self._records.values()
            if record.is_active and record.user_id == user_id
        ]

        if episode_type:
            records = [record for record in records if record.episode_type == episode_type]

        if since is not None:
            records = [record for record in records if record.start_at >= since]

        if until is not None:
            records = [record for record in records if record.end_at <= until]

        records.sort(key=lambda item: item.start_at, reverse=True)
        return records

    def search(
        self,
        *,
        user_id: str,
        query: str,
        top_k: int = 5,
        since: float | None = None,
        until: float | None = None,
    ) -> list[EpisodeRecord]:
        query_lower = query.lower()
        results: list[tuple[float, EpisodeRecord]] = []

        for record in self._records.values():
            if not record.is_active or record.user_id != user_id:
                continue

            if since is not None and record.start_at < since:
                continue
            if until is not None and record.end_at > until:
                continue

            score = record.importance

            if query_lower in record.summary.lower():
                score += 3.0

            for entity in record.entities:
                if entity.lower() in query_lower or query_lower in entity.lower():
                    score += 1.0

            results.append((score, record))

        results.sort(key=lambda item: (item[0], item[1].start_at), reverse=True)
        return [record for _, record in results[:top_k]]

    def get_recent(
        self,
        user_id: str,
        hours: int = 24,
        top_k: int = 10,
    ) -> list[EpisodeRecord]:
        since = time.time() - hours * 3600
        return self.list_by_user(user_id=user_id, since=since)[:top_k]

    def get_today(self, user_id: str) -> list[EpisodeRecord]:
        import datetime

        today_start = datetime.datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        ).timestamp()
        return self.list_by_user(user_id=user_id, since=today_start)

    def get_yesterday(self, user_id: str) -> list[EpisodeRecord]:
        import datetime

        now = datetime.datetime.now()
        yesterday_start = (now - datetime.timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        yesterday_end = yesterday_start.replace(hour=23, minute=59, second=59)
        return self.list_by_user(
            user_id=user_id,
            since=yesterday_start.timestamp(),
            until=yesterday_end.timestamp(),
        )

    def deactivate(self, episode_id: str) -> None:
        record = self._records.get(episode_id)
        if record:
            record.is_active = False
            record.updated_at = time.time()
            self._save()

    def count(self, user_id: str | None = None) -> int:
        if user_id is None:
            return len([record for record in self._records.values() if record.is_active])
        return len(
            [
                record
                for record in self._records.values()
                if record.is_active and record.user_id == user_id
            ]
        )

    def clear(self) -> None:
        self._records.clear()
        self._save()
