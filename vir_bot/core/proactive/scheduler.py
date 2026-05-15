"""动态调度器：替代固定 60 秒轮询，只在有意义的时刻唤醒"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from vir_bot.utils.logger import logger


# =============================================================================
# 唤醒源
# =============================================================================


class WakeSource(ABC):
    @abstractmethod
    def next_wake(self, ctx: dict) -> float | None:
        """返回下次唤醒的 Unix 时间戳，None 表示不需要唤醒"""
        ...


class DailyRhythm(WakeSource):
    """每天固定时间段窗口"""

    def __init__(self, windows: list[tuple[int, int]] | None = None):
        # 默认窗口：早9点、午12点、晚6点、晚9点
        self._windows = windows or [(9, 10), (12, 13), (18, 19), (21, 22)]

    def next_wake(self, ctx: dict) -> float | None:
        now = datetime.now()
        today = now.date()
        for start_h, end_h in self._windows:
            candidate = datetime(today.year, today.month, today.day, start_h, 0)
            if candidate.timestamp() > now.timestamp():
                return candidate.timestamp()
        # 今天的窗口都过了，返回明天第一个
        tomorrow = today + timedelta(days=1)
        first = self._windows[0]
        return datetime(tomorrow.year, tomorrow.month, tomorrow.day, first[0], 0).timestamp()


class SilenceDetector(WakeSource):
    """用户沉默超过阈值时唤醒"""

    def __init__(self, thresholds: dict[str, int] | None = None):
        self._thresholds = thresholds or {
            "IDLE": 7200,       # 2 小时
            "WAITING": 1800,    # 30 分钟
            "CONCERNED": 3600,  # 1 小时
            "WORRIED": 14400,   # 4 小时
            "BACK_OFF": 86400,  # 24 小时
        }

    def next_wake(self, ctx: dict) -> float | None:
        last_user_ts = ctx.get("last_user_msg_ts", 0)
        conv_state = ctx.get("conv_state", "IDLE")
        threshold = self._thresholds.get(conv_state, 7200)
        wake_time = last_user_ts + threshold
        if wake_time > time.time():
            return wake_time
        return None


class StateDeadline(WakeSource):
    """状态转移超时唤醒（BACK_OFF 重置等）"""

    def __init__(self, backoff_reset_seconds: int = 7200):
        self._backoff_reset = backoff_reset_seconds

    def next_wake(self, ctx: dict) -> float | None:
        conv_state = ctx.get("conv_state", "IDLE")
        first_unanswered_ts = ctx.get("first_unanswered_ts", 0)

        if conv_state == "BACK_OFF" and first_unanswered_ts > 0:
            return first_unanswered_ts + 75 * 60 + self._backoff_reset
        if conv_state == "WAITING" and first_unanswered_ts > 0:
            return first_unanswered_ts + 15 * 60  # WAITING → CONCERNED
        if conv_state == "CONCERNED" and first_unanswered_ts > 0:
            return first_unanswered_ts + 45 * 60  # CONCERNED → WORRIED
        return None


# =============================================================================
# 预过滤器
# =============================================================================


@dataclass
class FilterContext:
    user_id: str = "default"
    conv_state: str = "IDLE"
    last_proactive_ts: float = 0.0
    last_user_msg_ts: float = 0.0
    daily_sent: int = 0
    daily_limit: int = 5
    cooldown_seconds: int = 7200
    hour: int = 0
    has_content_seed: bool = True  # Phase 2 之前默认 True
    unanswered_count: int = 0


class PreFilter(ABC):
    @abstractmethod
    def should_fire(self, ctx: FilterContext) -> tuple[bool, str]:
        """返回 (是否通过, 原因)"""
        ...


class DailyLimitFilter(PreFilter):
    """每日发送上限"""
    def should_fire(self, ctx: FilterContext) -> tuple[bool, str]:
        if ctx.daily_sent >= ctx.daily_limit:
            return False, f"今日已发 {ctx.daily_sent} 条，达到上限 {ctx.daily_limit}"
        return True, "每日限额 OK"


class CooldownFilter(PreFilter):
    """冷却期检查"""
    def should_fire(self, ctx: FilterContext) -> tuple[bool, str]:
        if ctx.last_proactive_ts <= 0:
            return True, "首次发送，无冷却"
        elapsed = time.time() - ctx.last_proactive_ts
        if elapsed < ctx.cooldown_seconds:
            remaining = int((ctx.cooldown_seconds - elapsed) / 60)
            return False, f"冷却中，还剩 {remaining} 分钟"
        return True, "冷却期已过"


class QuietHoursFilter(PreFilter):
    """深夜时段不发送（23:00-07:00）"""
    QUIET_START = 23
    QUIET_END = 7

    def should_fire(self, ctx: FilterContext) -> tuple[bool, str]:
        hour = ctx.hour
        if hour >= self.QUIET_START or hour < self.QUIET_END:
            return False, f"深夜时段 ({hour}:00)，不打扰"
        return True, "非深夜时段"


class EngagementFilter(PreFilter):
    """用户互动检查：用户没回消息时提高门槛"""
    def should_fire(self, ctx: FilterContext) -> tuple[bool, str]:
        if ctx.unanswered_count >= 3:
            return False, f"已发 {ctx.unanswered_count} 条未回复，停止打扰"
        return True, "互动检查通过"


class ContentFilter(PreFilter):
    """内容种子检查：没有新内容可说时不发（Phase 2 实现）"""
    def should_fire(self, ctx: FilterContext) -> tuple[bool, str]:
        if not ctx.has_content_seed:
            return False, "没有可用的内容种子"
        return True, "有内容种子"


# =============================================================================
# 动态调度器
# =============================================================================


class ProactiveScheduler:
    """动态调度器：计算下次唤醒时间，预过滤，只在有意义时调 LLM"""

    # 状态对应的每日限额和冷却
    STATE_LIMITS = {
        "IDLE":      (5, 7200),    # 5 条/天，2h 冷却
        "WAITING":   (3, 1800),    # 3 条/天，30m 冷却
        "CONCERNED": (2, 3600),    # 2 条/天，1h 冷却
        "WORRIED":   (1, 14400),   # 1 条/天，4h 冷却
        "BACK_OFF":  (0, 86400),   # 0 条/天，24h 冷却
    }

    def __init__(self, config: Any = None):
        self._wake_sources: list[WakeSource] = [
            DailyRhythm(),
            SilenceDetector(),
            StateDeadline(),
        ]
        self._pre_filters: list[PreFilter] = [
            DailyLimitFilter(),
            CooldownFilter(),
            QuietHoursFilter(),
            EngagementFilter(),
            ContentFilter(),
        ]

    def calculate_next_wake(self, ctx: dict) -> float:
        """计算下次唤醒时间，返回 Unix 时间戳"""
        now = time.time()
        candidates = []
        for source in self._wake_sources:
            try:
                ts = source.next_wake(ctx)
                if ts is not None and ts > now:
                    candidates.append(ts)
            except Exception as e:
                logger.debug(f"唤醒源 {source.__class__.__name__} 计算失败: {e}")

        if not candidates:
            # 兜底：10 分钟后检查
            return now + 600

        return min(candidates)

    def run_pre_filters(self, ctx: FilterContext) -> tuple[bool, str]:
        """运行所有预过滤器，返回 (全部通过, 最后一个失败原因)"""
        for f in self._pre_filters:
            passed, reason = f.should_fire(ctx)
            if not passed:
                return False, reason
        return True, "全部通过"

    def get_state_limits(self, conv_state: str) -> tuple[int, int]:
        """返回 (daily_limit, cooldown_seconds)"""
        return self.STATE_LIMITS.get(conv_state, (5, 7200))

    def build_filter_context(
        self,
        user_id: str,
        conv_state: str,
        last_proactive_ts: float,
        last_user_msg_ts: float,
        daily_sent: int,
        unanswered_count: int,
        has_content_seed: bool = True,
    ) -> FilterContext:
        daily_limit, cooldown = self.get_state_limits(conv_state)
        return FilterContext(
            user_id=user_id,
            conv_state=conv_state,
            last_proactive_ts=last_proactive_ts,
            last_user_msg_ts=last_user_msg_ts,
            daily_sent=daily_sent,
            daily_limit=daily_limit,
            cooldown_seconds=cooldown,
            hour=datetime.now().hour,
            has_content_seed=has_content_seed,
            unanswered_count=unanswered_count,
        )
