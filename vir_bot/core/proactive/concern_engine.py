"""牵挂引擎 - 核心决策中枢，生成牵挂念头并评估。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

from vir_bot.utils.logger import logger


@dataclass
class ConcernThought:
    """一个牵挂念头。"""

    user_id: str
    thought: str  # 牵挂的内容描述
    motivation: str  # 牵挂动机（为什么想起这个）
    priority: float = 0.5  # 0-1，越高越应该表达
    concern_type: str = "general"  # "care", "reminder", "curiosity", "greeting"
    generated_at: float = field(default_factory=time.time)


class ConcernEngine:
    """牵挂引擎：模拟人类"想起某人近况"的心理过程。

    周期性将用户状态与长期记忆组合，生成牵挂念头。
    通过规则+LLM评估决定是否值得主动表达。
    """

    def __init__(
        self,
        ai_provider: Any,
        memory_manager: Any,
        character_card: Any,
        config: dict | None = None,
    ):
        self.ai = ai_provider
        self.memory = memory_manager
        self.character = character_card
        self.config = config or {}
        self._thoughts: list[ConcernThought] = []
        self._max_thoughts = self.config.get("max_pending_thoughts", 10)
        self._min_priority_threshold = self.config.get("min_priority_threshold", 0.6)

    async def generate_thoughts(self, user_id: str, state: Any) -> list[ConcernThought]:
        """基于用户状态和记忆生成牵挂念头。"""
        thoughts = []

        try:
            # 1. 从语义记忆获取用户相关信息
            if self.memory:
                records = self.memory.list_semantic_memory(user_id=user_id)
                # 按 namespace 分组生成牵挂
                thoughts.extend(self._generate_from_semantic(records, user_id, state))

            # 2. 从事件记忆获取近期事件
            if self.memory and self.memory.episodic_store:
                episodes = self.memory.episodic_store.list_by_user(user_id=user_id)[:5]
                thoughts.extend(self._generate_from_episodic(episodes, user_id, state))

            # 3. 基于时间和习惯生成牵挂
            thoughts.extend(self._generate_from_time_context(user_id, state))

            # 4. 用LLM评估和筛选
            if self.ai and thoughts:
                evaluated = await self._evaluate_with_llm(thoughts, state)
                thoughts = evaluated

            # 按优先级排序，保留top N
            thoughts.sort(key=lambda t: t.priority, reverse=True)
            thoughts = thoughts[: self._max_thoughts]

            self._thoughts = thoughts
            return thoughts

        except Exception as e:
            logger.error(f"牵挂引擎生成念头失败: {e}")
            return []

    def _generate_from_semantic(
        self, records: list, user_id: str, state: Any
    ) -> list[ConcernThought]:
        """从语义记忆生成牵挂。"""
        thoughts = []
        now = time.time()

        # 分组：偏好、习惯、身份
        by_ns: dict[str, list] = {}
        for r in records[:15]:
            by_ns.setdefault(r.namespace, []).append(r)

        # 从偏好生成关心
        prefs = by_ns.get("profile.preference", [])
        for r in prefs[:3]:
            thoughts.append(
                ConcernThought(
                    user_id=user_id,
                    thought=f"用户喜欢{r.object}，可以聊聊这个",
                    motivation=f"用户偏好: {r.object}",
                    priority=0.7 if now - r.updated_at < 86400 else 0.5,
                    concern_type="care",
                )
            )

        # 从习惯生成提醒
        habits = by_ns.get("profile.habit", [])
        for r in habits[:2]:
            if state.is_work_time and "工作" in r.object:
                thoughts.append(
                    ConcernThought(
                        user_id=user_id,
                        thought=f"用户在工作时间有{r.object}的习惯",
                        motivation=f"习惯触发: {r.object}",
                        priority=0.6,
                        concern_type="reminder",
                    )
                )

        return thoughts

    def _generate_from_episodic(
        self, episodes: list, user_id: str, state: Any
    ) -> list[ConcernThought]:
        """从事件记忆生成牵挂。"""
        thoughts = []

        for ep in episodes[:3]:
            # 只关心近期事件
            if time.time() - ep.start_at > 86400 * 3:  # 3天内
                continue
            thoughts.append(
                ConcernThought(
                    user_id=user_id,
                    thought=f"用户之前提到{ep.summary}，可以跟进一下",
                    motivation=f"近期事件: {ep.summary[:30]}",
                    priority=0.8,
                    concern_type="curiosity",
                )
            )

        return thoughts

    def _generate_from_time_context(self, user_id: str, state: Any) -> list[ConcernThought]:
        """基于时间和上下文生成牵挂。"""
        thoughts = []

        # 深夜关心
        if state.is_late_night and state.last_interaction_ago_min > 60:
            thoughts.append(
                ConcernThought(
                    user_id=user_id,
                    thought="这么晚了用户还没睡，关心一下",
                    motivation="深夜时段",
                    priority=0.9,
                    concern_type="care",
                )
            )

        # 长时间没交互
        if state.last_interaction_ago_min > 120:
            thoughts.append(
                ConcernThought(
                    user_id=user_id,
                    thought="好久没和用户交互了，打个招呼",
                    motivation=f"距离上次交互{int(state.last_interaction_ago_min)}分钟",
                    priority=0.85,
                    concern_type="greeting",
                )
            )

        return thoughts

    async def _evaluate_with_llm(
        self, thoughts: list[ConcernThought], state: Any
    ) -> list[ConcernThought]:
        """用LLM评估牵挂念头，调整优先级。"""
        if not thoughts:
            return []

        prompt = self._build_evaluation_prompt(thoughts, state)

        try:
            response = await self.ai.chat(
                messages=[{"role": "user", "content": prompt}],
                system=(
                    "你是一个牵挂评估器。评估每个牵挂念头是否值得表达。"
                    "只输出JSON数组，格式："
                    "[{"index": 0, "priority": 0.8, "should_express": true, "reason": "..."}]"
                ),
                temperature=0.3,
            )

            import json

            content = response.content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]

            evaluated = json.loads(content)
            result = []

            for item in evaluated:
                idx = item.get("index", -1)
                if idx >= 0 and idx < len(thoughts):
                    th = thoughts[idx]
                    th.priority = float(item.get("priority", th.priority))
                    if item.get("should_express", True):
                        result.append(th)
                    else:
                        logger.debug(f"牵挂被LLM否决: {item.get('reason', '')}")

            return result

        except Exception as e:
            logger.warning(f"LLM牵挂评估失败，使用规则结果: {e}")
            return [t for t in thoughts if t.priority >= self._min_priority_threshold]

    def _build_evaluation_prompt(self, thoughts: list[ConcernThought], state: Any) -> str:
        """构建LLM评估提示词。"""
        lines = [
            "当前用户状态：",
            f"- 时间：{state.hour_of_day}:00, 是否深夜={state.is_late_night}",
            f"- 距离上次交互：{int(state.last_interaction_ago_min)}分钟",
            f"- 交互频率：{state.interaction_frequency}",
            "",
            "待评估的牵挂念头：",
        ]

        for i, th in enumerate(thoughts):
            lines.append(f"{i}. [{th.concern_type}] {th.thought}")
            lines.append(f"   动机：{th.motivation}, 当前优先级：{th.priority:.2f}")

        lines.append("")
        lines.append("请评估每个念头是否值得主动表达，输出JSON数组。")
        return "\n".join(lines)

    def get_pending_thoughts(self, min_priority: float | None = None) -> list[ConcernThought]:
        """获取待处理的牵挂念头。"""
        threshold = min_priority or self._min_priority_threshold
        return [t for t in self._thoughts if t.priority >= threshold]

    def clear_thoughts(self) -> None:
        """清空牵挂念头。"""
        self._thoughts.clear()
