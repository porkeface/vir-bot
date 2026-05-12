"""表达层 - 将牵挂念头转化为符合角色人设的自然语言消息。"""

from __future__ import annotations

import random
import time
from typing import Any, Optional

from vir_bot.utils.logger import logger


class ExpressionLayer:
    """表达层：组合角色人设 + 牵挂内容 + 记忆上下文，生成自然消息。"""

    def __init__(self, ai_provider: Any, character_card: Any, memory_manager: Any):
        self.ai = ai_provider
        self.character = character_card
        self.memory = memory_manager

    async def generate_message(
        self,
        thought: Any,  # ConcernThought
        user_id: str,
        state: Any,  # UserState
    ) -> str:
        """将牵挂念头转化为一条自然消息。"""

        try:
            prompt = self._build_prompt(thought, user_id, state)
            system = self._build_system_prompt()

            response = await self.ai.chat(
                messages=[{"role": "user", "content": prompt}],
                system=system,
                temperature=0.7,
            )

            message = response.content.strip()
            if message:
                logger.info(f"生成主动消息: {message[:50]}...")
                return message

        except Exception as e:
            logger.warning(f"表达层生成消息失败: {e}")

        return self._fallback_message()

    def _build_system_prompt(self) -> str:
        """构建系统提示词，完全从角色卡读取，不硬编码行为。"""
        parts = []

        if self.character:
            if self.character.name:
                parts.append(f"你是{self.character.name}。")
            if self.character.personality:
                parts.append(f"你的性格：{self.character.personality}")
            if self.character.description:
                parts.append(f"关于你：{self.character.description}")

            # 从角色卡读取主动行为指引
            proactive = self.character.extensions.get("proactive_behavior", {})
            tone = proactive.get("说话的语气", "")
            if tone:
                parts.append(f"说话方式：{tone}")

            ways = proactive.get("关心的方式", [])
            if ways:
                parts.append(f"你可以这样表达关心：{'、'.join(ways)}")

            # 从角色卡读取要避免的表达
            avoid = proactive.get("避免的表达", [])
            if avoid:
                parts.append(f"绝不要说：{'、'.join(avoid)}")

            # 从角色卡读取情绪模式
            emotions = self.character.extensions.get("emotional_patterns", {})
            if emotions:
                emotion_examples = []
                for emotion, phrases in emotions.items():
                    emotion_examples.append(f"{emotion}时用：{'、'.join(phrases[:3])}")
                parts.append("情绪表达参考：" + "；".join(emotion_examples))

            # 从角色卡读取说话风格
            style = self.character.extensions.get("response_style", {})
            if style:
                for k, v in style.items():
                    if isinstance(v, str):
                        parts.append(f"{k}：{v}")

        else:
            parts.append("你是一个关心对方的人，现在想主动发一条消息。")

        parts.append("直接用你平时的说话方式发消息，不要解释，不要用系统通知的语气。")

        return "\n".join(parts)

    def _build_prompt(self, thought: Any, user_id: str, state: Any) -> str:
        """构建用户消息部分。"""
        lines = [
            f"你想到了：{thought.content}",
            f"为什么想到这个：{thought.motivation}",
            "",
        ]

        # 添加上下文记忆
        if self.memory and user_id:
            try:
                records = self.memory.search_semantic_memory(
                    user_id=user_id,
                    query=thought.content,
                    top_k=3,
                )
                if records:
                    lines.append("你记得关于对方的事：")
                    for r in records:
                        lines.append(f"- {r.predicate}: {r.object}")
                    lines.append("")
            except Exception as e:
                logger.debug(f"获取语义记忆失败: {e}")

        # 当前状态
        from datetime import datetime
        hour = datetime.now().hour
        if 0 <= hour < 6:
            time_hint = "现在是深夜"
        elif 6 <= hour < 12:
            time_hint = "现在是上午"
        elif 12 <= hour < 14:
            time_hint = "现在是中午"
        elif 14 <= hour < 18:
            time_hint = "现在是下午"
        elif 18 <= hour < 22:
            time_hint = "现在是晚上"
        else:
            time_hint = "现在是深夜"

        lines.append(f"{time_hint}，距离上次聊天已经过了很久。")
        lines.append("")
        lines.append("现在发一条消息给对方，30字以内，直接输出消息内容：")

        return "\n".join(lines)

    def _fallback_message(self) -> str:
        """从角色卡读取 fallback 消息，没有则用通用的。"""
        if self.character:
            # 从情绪模式中组合自然的 fallback
            emotions = self.character.extensions.get("emotional_patterns", {})
            care_phrases = emotions.get("关心", [])
            if care_phrases:
                return random.choice(care_phrases)

            # 用角色卡的 greeting
            greeting = self.character.extensions.get("greeting", "")
            if greeting:
                return greeting

        return "想你啦～"
