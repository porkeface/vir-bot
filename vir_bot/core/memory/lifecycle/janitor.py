"""记忆生命周期管理器（后台任务）。"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

from vir_bot.utils.logger import logger

if TYPE_CHECKING:
    from vir_bot.core.memory.semantic_store import SemanticMemoryStore
    from vir_bot.core.memory.episodic_store import EpisodicMemoryStore
    from .decay import MemoryDecay
    from .merge import MemoryMerger


class MemoryJanitor:
    """记忆生命周期管理器（后台任务）。"""

    def __init__(
        self,
        config: dict,
        semantic_store: "SemanticMemoryStore",
        episodic_store: "EpisodicMemoryStore | None" = None,
        decay: "MemoryDecay | None" = None,
        merger: "MemoryMerger | None" = None,
    ):
        self.config = config
        self.semantic_store = semantic_store
        self.episodic_store = episodic_store
        self.decay = decay or MemoryDecay()
        self.merger = merger or MemoryMerger(semantic_store)
        self._running = False

    async def start(self) -> None:
        """启动后台生命周期管理。"""
        self._running = True
        logger.info("MemoryJanitor: starting background task")

        while self._running:
            try:
                await self.run_once()
            except Exception as e:
                logger.error(f"Janitor error: {e}")

            # 等待下次运行（默认每天一次）
            interval = self.config.get("interval_hours", 24) * 3600
            await time.sleep(interval)

    def stop(self) -> None:
        """停止。"""
        self._running = False
        logger.info("MemoryJanitor: stopped")

    async def run_once(self) -> None:
        """执行一次生命周期维护。"""
        logger.info("Janitor: starting maintenance...")

        # 1. 衰减降权
        self._apply_decay()

        # 2. 合并相似记忆
        users = self._get_all_users()
        for user_id in users:
            await self.merger.merge_similar(user_id)

        # 3. 归档低置信度记忆
        self._archive_low_confidence()

        logger.info("Janitor: maintenance complete")

    def _apply_decay(self) -> None:
        """应用衰减。"""
        changed = False
        for record in self.semantic_store._records.values():
            if not record.is_active:
                continue

            action = self.decay.apply_decay(record)
            if action == "delete":
                record.is_active = False
                changed = True
            elif action == "archive":
                if not hasattr(record, "metadata") or record.metadata is None:
                    record.metadata = {}
                record.metadata["archived"] = True
                changed = True

        if changed:
            self.semantic_store._save()

    def _archive_low_confidence(self) -> None:
        """归档低置信度记忆。"""
        import os
        from pathlib import Path

        archive_dir = Path("data/memory/archive")
        archive_dir.mkdir(parents=True, exist_ok=True)

        to_archive = []
        for record in self.semantic_store._records.values():
            if (
                record.confidence < 0.1
                and time.time() - record.updated_at > 86400 * 90  # 90天未访问
            ):
                to_archive.append(record)

        if not to_archive:
            return

        archive_file = archive_dir / f"archive_{int(time.time())}.json"
        data = [r.to_dict() for r in to_archive]
        archive_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        for record in to_archive:
            record.is_active = False

        self.semantic_store._save()
        logger.info(f"Archived {len(to_archive)} low-confidence memories")

    def _get_all_users(self) -> list[str]:
        """获取所有用户 ID。"""
        users = set()
        for r in self.semantic_store._records.values():
            if r.user_id:
                users.add(r.user_id)
        return list(users)
