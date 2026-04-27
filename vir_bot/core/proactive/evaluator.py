"""牵挂评估器：评估牵挂念头是否值得发送"""
from __future__ import annotations

import time
from typing import Any

from vir_bot.utils.logger import logger


class ConcernEvaluator:
    """评估牵挂念头的价值，决定是否发送"""

    def __init__(self, ai_provider: Any, config: Any):
        self._ai = ai_provider
        self._config = config

    async def evaluate(
        self, thought: Any, user_context: dict
    ) -> tuple[bool, float, str]:
        """评估牵挂念头，返回 (是否发送, 分数, 原因)"""
        if not thought or not thought.content:
            return False, 0.0, "牵挂内容为空"

        # 规则检查：冷却时间
        if user_context.get("seconds_since_last", 0) < self._config.min_cooldown_seconds:
            return False, 0.0, "冷却时间未到"

        # 规则检查：每日上限
        if user_context.get("daily_proactive_count", 0) >= self._config.max_daily_messages:
            return False, 0.0, "每日主动消息已达上限"

        # LLM 评估
        if self._config.concern.llm_evaluate:
            return await self._llm_evaluate(thought, user_context)
        else:
            # 规则评估：简单基于牵挂内容长度
            score = min(len(thought.content) / 100, 1.0)
            return score >= self._config.concern.threshold, score, "规则评估"

    async def _llm_evaluate(
        self, thought: Any, user_context: dict
    ) -> tuple[bool, float, str]:
        """使用 LLM 评估牵挂价值"""
        system_prompt = """你是牵挂评估系统。评估一个牵挂念头是否值得发送给用户。

评估维度：
1. 相关性：是否和用户的历史记忆、话题相关
2. 时机：现在发送是否合适（考虑距离上次交互的时间）
3. 价值：是否能给用户带来温暖、关心，而不是打扰

输出格式（严格 JSON）：
{"send": true/false, "score": 0.0-1.0, "reason": "简短原因"}"""

        user_prompt = self._build_evaluation_prompt(thought, user_context)

        try:
            response = await self._ai.chat(
                messages=[{"role": "user", "content": user_prompt}],
                system=system_prompt,
                stream=False,
            )
            import json
            result = json.loads(response.content.strip())
            send = result.get("send", False)
            score = float(result.get("score", 0.0))
            reason = result.get("reason", "")
            return send, score, reason
        except Exception as e:
            logger.error(f"LLM 评估失败: {e}")
            # 失败时保守处理：不发送
            return False, 0.0, f"评估失败: {e}"

    def _build_evaluation_prompt(self, thought: Any, user_context: dict) -> str:
        parts = ["## 牵挂念头", f"{thought.content}", "\n## 用户状态"]
        parts.append(f"- 距离上次交互: {user_context['seconds_since_last']:.0f} 秒")
        parts.append(f"- 今日已发主动消息: {user_context['daily_proactive_count']} 条")
        if user_context.get("recent_topics"):
            parts.append(f"- 最近话题: {', '.join(user_context['recent_topics'])}")
        parts.append("\n请评估是否值得发送：")
        return "\n".join(parts)
