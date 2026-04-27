"""用户状态追踪：基于记忆系统构建用户状态快照"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class UserState:
    user_id: str
    last_interaction_ts: float = 0.0
    last_interaction_type: str = "unknown"  # user_message / proactive_message
    daily_message_count: int = 0
    last_message_date: str = ""  # YYYY-MM-DD
    recent_topics: list[str] = field(default_factory=list)
    mood_hint: str = "neutral"  # 基于对话内容的简单推断


class StateTracker:
    """追踪用户状态，基于记忆系统和对话历史"""

    def __init__(self, memory_manager: Any, character_card: Any):
        self._memory_manager = memory_manager
        self._character_card = character_card
        self._states: dict[str, UserState] = {}
        self._global_last_proactive_ts: float = 0.0

    def get_state(self, user_id: str = "default") -> UserState:
        if user_id not in self._states:
            self._states[user_id] = UserState(user_id=user_id)
        return self._states[user_id]

    def update_from_message(
        self, user_id: str, message: str, direction: str = "in"
    ) -> None:
        """从用户消息或主动消息更新状态（同步）"""
        state = self.get_state(user_id)
        now = time.time()
        state.last_interaction_ts = now
        state.last_interaction_type = "user_message" if direction == "in" else "proactive_message"

        # 更新每日计数
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        if state.last_message_date != today:
            state.daily_message_count = 0
            state.last_message_date = today
        if direction == "out":
            state.daily_message_count += 1

        # 简单提取话题（取消息前50字作为话题线索）
        if message and len(message) > 5:
            topic = message[:50].strip()
            if topic not in state.recent_topics:
                state.recent_topics.append(topic)
                state.recent_topics = state.recent_topics[-10:]  # 保留最近10个

    def update_proactive_sent(self, user_id: str = "default") -> None:
        """记录主动消息发送（同步）"""
        state = self.get_state(user_id)
        now = time.time()
        state.last_interaction_ts = now
        state.last_interaction_type = "proactive_message"
        state.daily_message_count += 1
        self._global_last_proactive_ts = now

    def seconds_since_last_interaction(self, user_id: str = "default") -> float:
        state = self.get_state(user_id)
        return time.time() - state.last_interaction_ts

    def can_send_proactive(self, user_id: str, min_cooldown: float, max_daily: int) -> bool:
        """基于冷却和每日上限判断是否可发送"""
        state = self.get_state(user_id)
        if self.seconds_since_last_interaction(user_id) < min_cooldown:
            return False
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        if state.last_message_date == today and state.daily_message_count >= max_daily:
            return False
        return True

    async def get_user_context(self, user_id: str = "default", max_memories: int = 5) -> dict:
        """构建用户上下文，用于牵挂生成"""
        state = self.get_state(user_id)
        context = {
            "user_id": user_id,
            "seconds_since_last": self.seconds_since_last_interaction(user_id),
            "recent_topics": state.recent_topics[-5:],
            "mood_hint": state.mood_hint,
            "daily_proactive_count": state.daily_message_count,
        }

        # 尝试从记忆系统获取相关上下文
        try:
            if self._memory_manager and hasattr(self._memory_manager, "retrieval_router"):
                memories = await self._memory_manager.retrieval_router.retrieve(
                    query="用户最近的状态 情绪 事件", top_k=max_memories
                )
                context["recent_memories"] = [
                    {"content": m.content, "score": m.score, "type": m.type}
                    for m in memories
                ]
            else:
                context["recent_memories"] = []
        except Exception:
            context["recent_memories"] = []

        return context
