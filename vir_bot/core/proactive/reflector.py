"""Reflector: 质量门控，4 轴评分 + 反模式拒绝"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from vir_bot.utils.logger import logger


@dataclass
class ReflectResult:
    """反思结果"""
    approved: bool
    score: float           # 综合分 0.0-1.0
    specificity: float     # 具体性：是否有具体信息
    timing: float          # 时机：是否适合现在发
    value: float           # 价值：是否能带来温暖
    freshness: float       # 新鲜感：是否和之前的消息重复
    reason: str            # 原因
    anti_pattern: str = "" # 命中的反模式（空=未命中）


# 反模式关键词列表（命中任一则自动拒绝）
ANTI_PATTERNS = [
    "在干嘛",
    "在干嘛呀",
    "在忙吗",
    "吃了吗",
    "你好",
    "睡了吗",
    "今天怎么样",
    "最近怎么样",
    "忙不忙",
    "无聊",
    "没什么事",
    "就是想问问",
]


class Reflector:
    """质量门控：LLM 4 轴评分 + 反模式自动拒绝"""

    SYSTEM_PROMPT = """你是消息质量评估器。评估一条主动消息是否适合发送。

评分维度（每项 0.0-1.0）：
1. specificity（具体性）：消息是否包含具体信息（事件、时间、人物、细节），而不是泛泛的问候
2. timing（时机）：现在发这条消息是否合适（考虑时间和状态）
3. value（价值）：这条消息能否给对方带来温暖、关心、有趣的感觉
4. freshness（新鲜感）：是否和最近的消息内容重复

输出严格 JSON：
{"specificity": 0.0-1.0, "timing": 0.0-1.0, "value": 0.0-1.0, "freshness": 0.0-1.0, "reason": "简短原因"}"""

    def __init__(self, ai_provider: Any):
        self._ai = ai_provider

    async def reflect(
        self,
        message: str,
        seed_content: str = "",
        mood_directive: str = "",
        recent_messages: list[str] | None = None,
    ) -> ReflectResult:
        """评估消息质量"""

        # 1. 反模式自动拒绝（0 LLM 成本）
        for pattern in ANTI_PATTERNS:
            if pattern in message:
                logger.info(f"[Reflector] 反模式拒绝: '{pattern}' in '{message[:30]}'")
                return ReflectResult(
                    approved=False,
                    score=0.0,
                    specificity=0.0,
                    timing=0.5,
                    value=0.0,
                    freshness=0.0,
                    reason=f"命中反模式: {pattern}",
                    anti_pattern=pattern,
                )

        # 2. 消息太短或太长
        if len(message) < 4:
            return ReflectResult(
                approved=False, score=0.0,
                specificity=0.0, timing=0.5, value=0.0, freshness=0.5,
                reason="消息太短",
            )
        if len(message) > 200:
            return ReflectResult(
                approved=False, score=0.0,
                specificity=0.3, timing=0.5, value=0.3, freshness=0.5,
                reason="消息太长",
            )

        # 3. LLM 4 轴评分
        try:
            result = await self._llm_reflect(message, seed_content, mood_directive, recent_messages)
            return result
        except Exception as e:
            logger.warning(f"[Reflector] LLM 评估失败: {e}")
            # 失败时放行（保守策略：宁可多发不可不发）
            return ReflectResult(
                approved=True, score=0.5,
                specificity=0.5, timing=0.5, value=0.5, freshness=0.5,
                reason=f"评估失败，放行: {e}",
            )

    async def _llm_reflect(
        self,
        message: str,
        seed_content: str,
        mood_directive: str,
        recent_messages: list[str] | None,
    ) -> ReflectResult:
        """LLM 评分"""
        user_prompt = self._build_prompt(message, seed_content, mood_directive, recent_messages)

        response = await self._ai.chat(
            messages=[{"role": "user", "content": user_prompt}],
            system=self.SYSTEM_PROMPT,
            stream=False,
        )

        content = response.content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        data = json.loads(content)

        specificity = float(data.get("specificity", 0.5))
        timing = float(data.get("timing", 0.5))
        value = float(data.get("value", 0.5))
        freshness = float(data.get("freshness", 0.5))
        reason = data.get("reason", "")

        # 综合分：加权平均
        score = specificity * 0.3 + timing * 0.2 + value * 0.35 + freshness * 0.15

        # 阈值：0.55 以上通过
        approved = score >= 0.55

        # 任一维度过低也拒绝
        if specificity < 0.3:
            approved = False
            reason = f"具体性太低({specificity:.1f}): {reason}"
        if value < 0.3:
            approved = False
            reason = f"价值太低({value:.1f}): {reason}"

        result = ReflectResult(
            approved=approved,
            score=score,
            specificity=specificity,
            timing=timing,
            value=value,
            freshness=freshness,
            reason=reason,
        )

        logger.info(
            f"[Reflector] {'通过' if approved else '拒绝'}: "
            f"score={score:.2f} spec={specificity:.2f} timing={timing:.2f} "
            f"value={value:.2f} fresh={freshness:.2f} — {reason}"
        )
        return result

    def _build_prompt(
        self,
        message: str,
        seed_content: str,
        mood_directive: str,
        recent_messages: list[str] | None,
    ) -> str:
        parts = [f"## 待评估消息\n{message}"]

        if seed_content:
            parts.append(f"\n## 内容种子（消息的素材来源）\n{seed_content}")

        if mood_directive:
            parts.append(f"\n## 期望风格\n{mood_directive}")

        if recent_messages:
            parts.append("\n## 最近发送的主动消息（检查重复）")
            for m in recent_messages[-5:]:
                parts.append(f"- {m}")

        parts.append("\n请评分：")
        return "\n".join(parts)
