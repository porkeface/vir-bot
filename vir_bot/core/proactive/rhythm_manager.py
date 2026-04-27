"""节奏管理器 - 动态调整主动消息频率，避免过度打扰。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class InteractionRecord:
    """一次交互记录。"""

    timestamp: float
    initiator: str  # "user" | "bot"
    channel: str = "default"


class RhythmManager:
    """节奏管理器：根据用户回复率、互动热度动态调整主动消息频次。"""

    def __init__(self, config: Any = None):
        self._config = config or {}
        self._history: list[InteractionRecord] = []
        self._max_history = self._get_config("max_history", 200)
        self._cooldown_seconds = self._get_config("cooldown_seconds", 1800)  # 30分钟
        self._last_proactive_time: dict[str, float] = {}  # user_id -> timestamp
        self._daily_limit = self._get_config("daily_limit", 10)  # 每天最多主动N次
        self._daily_counts: dict[str, tuple[float, int]] = {}  # user_id -> (date, count)

    def _get_config(self, key: str, default: Any) -> Any:
        """获取配置值，兼容字典和对象两种格式。"""
        if isinstance(self._config, dict):
            return self._config.get(key, default)
        return getattr(self._config, key, default)

    def record_interaction(
        self,
        user_id: str,
        initiator: str,
        channel: str = "default",
    ) -> None:
        """记录一次交互。"""
        record = InteractionRecord(
            timestamp=time.time(),
            initiator=initiator,
            channel=channel,
        )
        self._history.append(record)
        if len(self._history) > self._max_history:
            self._history.pop(0)

    def can_send(self, user_id: str) -> tuple[bool, str]:
        """
        综合判断：是否应该发送主动消息。
        返回：(是否允许, 原因)
        """
        now = time.time()

        # 1. 冷却期检查
        if user_id in self._last_proactive_time:
            elapsed = now - self._last_proactive_time[user_id]
            if elapsed < self._cooldown_seconds:
                return False, f"冷却期，还剩{int((self._cooldown_seconds - elapsed) / 60)}分钟"

        # 2. 每日限额检查
        today = now // 86400  # 日期整数
        if user_id in self._daily_counts:
            last_date, count = self._daily_counts[user_id]
            if last_date == today and count >= self._daily_limit:
                return False, f"今日主动消息已达限额({self._daily_limit})"
            if last_date != today:
                self._daily_counts[user_id] = (today, 0)
        else:
            self._daily_counts[user_id] = (today, 0)

        # 3. 用户互动热度检查（用户最近回复积极吗？）
        if not self._is_user_responsive(user_id):
            return False, "用户近期互动不积极，暂缓主动消息"

        # 4. 深夜更保守（22:00 - 06:00）
        if self._is_late_night() and self._get_recent_proactive_count(user_id, 3600) > 0:
            return False, "深夜已发送过主动消息"

        return True, "通过节奏检查"

    def _is_late_night(self) -> bool:
        """判断当前是否深夜（22:00 - 06:00）"""
        from datetime import datetime
        hour = datetime.now().hour
        return hour >= 22 or hour < 6

    def on_proactive_sent(self, user_id: str) -> None:
        """记录一次主动消息发送。"""
        now = time.time()
        self._last_proactive_time[user_id] = now

        # 更新每日计数
        if user_id in self._daily_counts:
            last_date, count = self._daily_counts[user_id]
            self._daily_counts[user_id] = (last_date, count + 1)

    def _is_user_responsive(self, user_id: str) -> bool:
        """检查用户近期是否积极回复。"""
        now = time.time()
        recent = [
            r for r in self._history
            if r.timestamp > now - 86400 and r.initiator == "user"
        ]
        if not recent:
            return True  # 没有近期记录，默认允许

        # 检查最近10条用户消息后，是否有bot回复
        bot_replies = [
            r for r in self._history
            if r.timestamp > now - 86400 and r.initiator == "bot"
        ]
        # 如果bot主动发了3条以上，用户都没回，就暂缓
        if len(bot_replies) >= 3 and len(recent) == 0:
            return False

        return True

    def _get_recent_proactive_count(self, user_id: str, window_seconds: float) -> int:
        """获取近期主动消息数量。"""
        now = time.time()
        return sum(
            1 for r in self._history
            if r.initiator == "bot"
            and r.timestamp > now - window_seconds
        )

    def get_stats(self, user_id: str = "default") -> dict:
        """获取用户的节奏统计。"""
        now = time.time()
        today = now // 86400

        daily_count = 0
        if user_id in self._daily_counts:
            last_date, count = self._daily_counts[user_id]
            if last_date == today:
                daily_count = count

        return {
            "daily_sent": daily_count,
            "daily_limit": self._daily_limit,
            "cooldown_remaining": max(
                0,
                self._cooldown_seconds
                - (now - self._last_proactive_time.get(user_id, 0)),
            ),
            "recent_proactive_24h": self._get_recent_proactive_count(user_id, 86400),
        }
