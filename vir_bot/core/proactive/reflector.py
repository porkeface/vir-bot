"""Reflector v4: 质量门控，4 轴评分 + 反模式拒绝 + 时段 LLM 判断"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
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
    """质量门控：LLM 4 轴评分 + 反模式自动拒绝 + 时段适宜性判断"""

    SYSTEM_PROMPT = """你是消息质量评估器。评估一条主动消息是否适合发送。

评分维度（每项 0.0-1.0）：
1. specificity（具体性）：消息是否包含具体信息（事件、时间、人物、细节），而不是泛泛的问候
2. timing（时机）：现在发这条消息是否合适。考虑：
   - 现在几点？如果很晚（23点后），内容是否紧急到必须发？
   - 对方最后说了什么？如果说了"晚安"、"去忙了"，可能不适合打扰
   - 今天已经发了几条？太多会让人烦
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
        context: dict | None = None,
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

        # 3. LLM 4 轴评分（含上下文）
        try:
            result = await self._llm_reflect(message, seed_content, mood_directive, recent_messages, context)
            return result
        except Exception as e:
            logger.warning(f"[Reflector] LLM 评估失败: {e}")
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
        context: dict | None,
    ) -> ReflectResult:
        """LLM 评分"""
        user_prompt = self._build_prompt(message, seed_content, mood_directive, recent_messages, context)

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

        score = specificity * 0.3 + timing * 0.2 + value * 0.35 + freshness * 0.15

        approved = score >= 0.55

        if specificity < 0.3:
            approved = False
            reason = f"具体性太低({specificity:.1f}): {reason}"
        if value < 0.3:
            approved = False
            reason = f"价值太低({value:.1f}): {reason}"
        # v4: timing 维度更严格 — 不再硬编码，但 LLM 给低分时要听
        if timing < 0.25:
            approved = False
            reason = f"时机不合适({timing:.1f}): {reason}"

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
        context: dict | None,
    ) -> str:
        now = datetime.now()
        parts = [f"## 待评估消息\n{message}"]

        # 上下文信息
        if context:
            parts.append("\n## 当前情况")

            # 时间
            hour = now.hour
            if 0 <= hour < 6:
                parts.append(f"- 现在是凌晨 {hour}:{now.minute:02d}，深夜")
            elif 22 <= hour < 24:
                parts.append(f"- 现在是晚上 {hour}:{now.minute:02d}，很晚了")
            else:
                parts.append(f"- 现在是 {hour}:{now.minute:02d}")

            # 用户最后消息
            last_msg = context.get("last_user_msg_content", "")
            last_ts = context.get("last_user_msg_ts", 0)
            if last_msg and last_ts > 0:
                silence_hours = (time.time() - last_ts) / 3600
                if silence_hours < 1:
                    parts.append(f"- 她 {int(silence_hours * 60)} 分钟前说：「{last_msg[:50]}」")
                elif silence_hours < 24:
                    parts.append(f"- 她 {silence_hours:.1f} 小时前说：「{last_msg[:50]}」")
                else:
                    parts.append(f"- 她 {silence_hours / 24:.1f} 天前说：「{last_msg[:50]}」")

            # 已发消息数
            count_today = context.get("proactive_count_today", 0)
            count_unanswered = context.get("proactive_count_unanswered", 0)
            if count_today > 0:
                parts.append(f"- 今天已经主动发了 {count_today} 条消息")
            if count_unanswered > 0:
                parts.append(f"- 有 {count_unanswered} 条消息她没回")

        if seed_content:
            parts.append(f"\n## 内容种子（消息的素材来源）\n{seed_content}")

        if mood_directive:
            parts.append(f"\n## 期望风格\n{mood_directive}")

        if recent_messages:
            parts.append("\n## 最近发送的主动消息（检查重复）")
            for m in recent_messages[-5:]:
                parts.append(f"- {m}")

        parts.append("\n请评分（特别注意 timing 维度）：")
        return "\n".join(parts)
