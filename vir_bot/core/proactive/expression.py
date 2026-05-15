"""表达层 - 将内容种子 + 情绪向量转化为自然语言消息。"""
from __future__ import annotations

import random
from typing import Any

from vir_bot.utils.logger import logger


class ExpressionLayer:
    """表达层：内容种子 + 情绪风格 + 角色人设 → 自然消息"""

    def __init__(self, ai_provider: Any, character_card: Any, memory_manager: Any):
        self.ai = ai_provider
        self.character = character_card
        self.memory = memory_manager

    async def generate_message(
        self,
        seed_content: str,
        seed_context: str = "",
        mood_directive: str = "",
        state_hint: str = "",
        user_id: str = "default",
    ) -> str:
        """基于内容种子和情绪风格生成一条自然消息"""

        try:
            prompt = self._build_prompt(seed_content, seed_context, mood_directive, state_hint, user_id)
            system = self._build_system_prompt(mood_directive)

            response = await self.ai.chat(
                messages=[{"role": "user", "content": prompt}],
                system=system,
                temperature=0.75,
            )

            message = response.content.strip()
            # 清理引号包裹
            if message.startswith('"') and message.endswith('"'):
                message = message[1:-1]
            if message.startswith("「") and message.endswith("」"):
                message = message[1:-1]

            if message:
                logger.info(f"[Expression] 生成消息: {message[:60]}...")
                return message

        except Exception as e:
            logger.warning(f"[Expression] 生成失败: {e}")

        return self._fallback_message()

    def _build_system_prompt(self, mood_directive: str = "") -> str:
        """系统提示词：角色人设 + 情绪风格"""
        parts = []

        if self.character:
            if self.character.name:
                parts.append(f"你是{self.character.name}。")
            if self.character.personality:
                parts.append(f"你的性格：{self.character.personality}")
            if self.character.description:
                parts.append(f"关于你：{self.character.description}")

            # 角色卡的主动行为指引
            proactive = self.character.extensions.get("proactive_behavior", {})
            tone = proactive.get("说话的语气", "")
            if tone:
                parts.append(f"说话方式：{tone}")

            ways = proactive.get("关心的方式", [])
            if ways:
                parts.append(f"你可以这样表达关心：{'、'.join(ways)}")

            avoid = proactive.get("避免的表达", [])
            if avoid:
                parts.append(f"绝不要说：{'、'.join(avoid)}")

            # 情绪表达参考
            emotions = self.character.extensions.get("emotional_patterns", {})
            if emotions:
                emotion_examples = []
                for emotion, phrases in emotions.items():
                    emotion_examples.append(f"{emotion}时用：{'、'.join(phrases[:3])}")
                parts.append("情绪表达参考：" + "；".join(emotion_examples))
        else:
            parts.append("你是一个关心对方的人，现在想主动发一条消息。")

        # 情绪风格指令
        if mood_directive:
            parts.append(f"当前情绪风格：{mood_directive}")

        parts.append("")
        parts.append("规则：")
        parts.append("1. 直接发消息，像平时聊天一样自然")
        parts.append("2. 不要解释你为什么发这条消息")
        parts.append("3. 不要用系统通知的语气")
        parts.append("4. 30 字以内，最多不超过 50 字")
        parts.append("5. 要有具体内容，不要泛泛问候")

        return "\n".join(parts)

    def _build_prompt(
        self,
        seed_content: str,
        seed_context: str,
        mood_directive: str,
        state_hint: str,
        user_id: str,
    ) -> str:
        """构建用户提示词"""
        lines = []

        # 内容种子
        lines.append(f"你想到了这件事：{seed_content}")
        if seed_context:
            lines.append(f"背景：{seed_context}")

        # 状态提示
        if state_hint:
            lines.append(f"当前情况：{state_hint}")

        # 从记忆系统补充上下文
        if self.memory and user_id:
            try:
                records = self.memory.search_semantic_memory(
                    user_id=user_id,
                    query=seed_content,
                    top_k=2,
                )
                if records:
                    lines.append("你记得关于对方的事：")
                    for r in records:
                        lines.append(f"- {r.predicate}: {r.object}")
            except Exception:
                pass

        # 时间感知
        from datetime import datetime
        hour = datetime.now().hour
        if 0 <= hour < 6:
            time_hint = "深夜"
        elif 6 <= hour < 12:
            time_hint = "上午"
        elif 12 <= hour < 14:
            time_hint = "中午"
        elif 14 <= hour < 18:
            time_hint = "下午"
        elif 18 <= hour < 22:
            time_hint = "晚上"
        else:
            time_hint = "深夜"
        lines.append(f"现在是{time_hint}。")

        lines.append("")
        lines.append("用你平时的语气发一条消息给对方，30字以内：")

        return "\n".join(lines)

    def _fallback_message(self) -> str:
        """降级消息：从角色卡的情绪模式中随机选取"""
        if self.character:
            emotions = self.character.extensions.get("emotional_patterns", {})
            care_phrases = emotions.get("关心", [])
            if care_phrases:
                return random.choice(care_phrases)

            greeting = self.character.extensions.get("greeting", "")
            if greeting:
                return greeting

        return "想你啦～"
