"""感知层 - 从记忆系统采集用户状态信号，生成状态标签。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

from vir_bot.utils.logger import logger


@dataclass
class UserState:
    """用户状态快照。"""

    user_id: str
    timestamp: float = field(default_factory=time.time)

    # 时间相关
    hour_of_day: int = 0
    day_of_week: int = 0
    is_late_night: bool = False
    is_work_time: bool = False

    # 活动状态（从记忆推断）
    last_interaction_ago_min: float = 0.0  # 距离上次交互多少分钟
    interaction_frequency: str = "normal"  # "frequent" / "normal" / "rare"
    recent_topics: list[str] = field(default_factory=list)

    # 情绪/状态标签（从记忆抽取）
    mood_tags: list[str] = field(default_factory=list)
    activity_tags: list[str] = field(default_factory=list)

    # 派生的牵挂驱动信号
    should_check_in: bool = False
    check_in_reason: str = ""


class PerceptionLayer:
    """感知层：从记忆系统采集信号，生成用户状态。"""

    def __init__(self, memory_manager: Any, config: dict | None = None):
        self.memory = memory_manager
        self.config = config or {}
        self._state_cache: dict[str, UserState] = {}  # user_id -> state
        self._cache_ttl = 300  # 5分钟缓存

    async def sense(self, user_id: str) -> UserState:
        """采集用户当前状态信号。"""
        now = time.time()

        # 检查缓存
        if user_id in self._state_cache:
            cached = self._state_cache[user_id]
            if now - cached.timestamp < self._cache_ttl:
                return cached

        state = UserState(user_id=user_id)

        # 1. 时间信号
        import datetime

        dt = datetime.datetime.now()
        state.hour_of_day = dt.hour
        state.day_of_week = dt.weekday()
        state.is_late_night = dt.hour >= 23 or dt.hour <= 5
        state.is_work_time = (0 <= dt.weekday() <= 4) and 9 <= dt.hour <= 18

        # 2. 交互频率（从短期记忆推断）
        if self.memory:
            recent = self.memory.get_context_messages(n=20)
            if recent:
                state.last_interaction_ago_min = (now - recent[-1].get("timestamp", now)) / 60.0
                # 简单频率判断
                if len(recent) >= 10:
                    state.interaction_frequency = "frequent"
                elif len(recent) <= 2:
                    state.interaction_frequency = "rare"

            # 3. 话题标签（从语义记忆获取）
            try:
                records = self.memory.list_semantic_memory(user_id=user_id)
                topics = set()
                for r in records[:20]:
                    if r.namespace == "profile.preference":
                        topics.add("preference")
                    elif r.namespace == "profile.habit":
                        topics.add("habit")
                    elif r.namespace == "profile.event":
                        topics.add("event")
                    if "喜欢" in r.predicate or "likes" in r.predicate:
                        topics.add("likes_" + r.object[:10])
                state.recent_topics = list(topics)[:10]
            except Exception as e:
                logger.debug(f"Perception: 获取语义记忆失败: {e}")

        # 4. 生成牵挂驱动信号
        state.should_check_in = self._evaluate_check_in(state)
        state.check_in_reason = self._generate_reason(state)

        # 更新缓存
        self._state_cache[user_id] = state
        return state

    def _evaluate_check_in(self, state: UserState) -> bool:
        """评估是否应该主动关心用户。"""
        # 深夜
        if state.is_late_night and state.last_interaction_ago_min > 60:
            return True
        # 长时间没交互
        if state.last_interaction_ago_min > 120:  # 2小时
            return True
        # 用户习惯时段（如每天早上）
        if state.is_work_time and state.interaction_frequency == "frequent":
            return True
        return False

    def _generate_reason(self, state: UserState) -> str:
        """生成牵挂原因。"""
        reasons = []
        if state.is_late_night:
            reasons.append("深夜时段")
        if state.last_interaction_ago_min > 120:
            reasons.append(f"距离上次交互{int(state.last_interaction_ago_min)}分钟")
        if state.interaction_frequency == "frequent":
            reasons.append("用户交互频繁")
        return "; ".join(reasons) if reasons else "定期关心"

    def clear_cache(self, user_id: str | None = None) -> None:
        """清空状态缓存。"""
        if user_id:
            self._state_cache.pop(user_id, None)
        else:
            self._state_cache.clear()
