"""牵挂引擎：生成牵挂念头，评估是否值得发送"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from vir_bot.utils.logger import logger


@dataclass
class ConcernThought:
    """牵挂念头"""
    content: str
    concern_type: str = "care"  # care / reminder / curiosity / greeting
    motivation: str = ""
    score: float = 0.0
    reason: str = ""
    related_memories: list[dict] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)


class ConcernEngine:
    """牵挂引擎：定期生成牵挂念头"""

    def __init__(
        self,
        ai_provider: Any,
        memory_manager: Any,
        character_card: Any,
        state_tracker: Any,
        config: Any,
    ):
        self._ai = ai_provider
        self._memory = memory_manager
        self._character = character_card
        self._tracker = state_tracker
        self._config = config
        self._running = False
        self._task = None

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.get_event_loop().create_task(self._loop())
        logger.info("牵挂引擎已启动")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("牵挂引擎已停止")

    async def _loop(self) -> None:
        """完整的牵挂→评估→生成→发送循环"""
        while self._running:
            try:
                await self._check_once()
            except Exception as e:
                logger.error(f"牵挂引擎循环错误: {e}")
            await asyncio.sleep(self._config.check_interval_seconds)

    async def _check_once(self) -> None:
        """执行一次牵挂检查"""
        context = await self._tracker.get_user_context(
            max_memories=self._config.expression.max_context_memories
        )
        if not context.get("recent_memories"):
            return
        thought = await self._generate_thought(context)
        return thought

    async def _generate_thought(self, context: dict) -> ConcernThought:
        """基于上下文生成牵挂念头"""
        system_prompt = self._build_concern_system_prompt()
        user_prompt = self._build_concern_user_prompt(context)

        try:
            response = await self._ai.chat(
                messages=[{"role": "user", "content": user_prompt}],
                system=system_prompt,
                stream=False,
            )
            content = response.content.strip()
            thought = ConcernThought(
                content=content,
                related_memories=context.get("recent_memories", []),
            )
            return thought
        except Exception as e:
            logger.error(f"生成牵挂念头失败: {e}")
            return ConcernThought(content="", reason=f"生成失败: {e}")

    def _build_concern_system_prompt(self) -> str:
        char_name = self._character.name if self._character else "助手"
        return (
            f"你是{char_name}的内在牵挂系统。基于用户的最近记忆和状态，生成一个牵挂念头。\n\n"
            f"牵挂念头是你「想起用户」时的内心想法，例如：\n"
            f"- 「他昨晚说今天要面试，现在应该结束了吧？不知道结果怎么样。」\n"
            f"- 「她最近总提到加班，今天是不是又熬夜了？」\n"
            f"- 「他之前说想去看那部电影，周末到了，会不会去了？」\n\n"
            f"规则：\n"
            f"1. 只输出牵挂念头本身，不要额外解释\n"
            f"2. 念头要基于已有记忆，不要编造\n"
            f"3. 如果没有值得牵挂的内容，输出空字符串\n"
            f"4. 语气要符合{char_name}的角色人设"
        )

    def _build_concern_user_prompt(self, context: dict) -> str:
        parts = ["## 用户当前状态"]
        parts.append(f"- 距离上次交互: {context['seconds_since_last']:.0f} 秒")
        parts.append(f"- 今日已发主动消息: {context['daily_proactive_count']} 条")
        if context.get("recent_topics"):
            parts.append(f"- 最近话题: {', '.join(context['recent_topics'])}")

        if context.get("recent_memories"):
            parts.append("\n## 相关记忆")
            for i, mem in enumerate(context["recent_memories"][:5], 1):
                content = mem.get("content", "")[:100]
                parts.append(f"{i}. {content}")

        parts.append("\n请生成牵挂念头（无则留空）：")
        return "\n".join(parts)
