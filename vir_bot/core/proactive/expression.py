"""表达层 - 将牵挂念头转化为符合角色人设的自然语言消息。"""

from __future__ import annotations

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
            system = self._build_system_prompt(thought)

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

        # 回退：基于规则的简单消息
        return self._fallback_message(thought, state)

    def _build_system_prompt(self, thought: Any) -> str:
        """构建系统提示词，注入角色人设。"""
        parts = []

        if self.character:
            # 核心人设
            if self.character.personality:
                parts.append(f"你的性格：{self.character.personality}")
            if self.character.description:
                parts.append(f"你的描述：{self.character.description}")
            # 风格要求
            parts.append(
                "你是用户的AI伴侣，现在要主动发一条关心的消息。"
                "语气要符合你的人设，自然、不突兀。"
                "不要说'系统通知'之类的话，就用你平时的说话方式。"
            )
        else:
            parts.append("你是一个关心用户的AI伴侣，现在要主动发一条关心的消息。")

        # 牵挂类型约束
        type_hints = {
            "care": "表达关心和在意，不要显得太正式。",
            "reminder": "温和地提醒，不要像闹钟那样生硬。",
            "curiosity": "带着好奇和兴趣询问，不要像审问。",
            "greeting": "轻松打个招呼，不要长篇大论。",
        }
        hint = type_hints.get(thought.concern_type, "自然表达你的牵挂。")
        parts.append(hint)

        return "\n".join(parts)

    def _build_prompt(self, thought: Any, user_id: str, state: Any) -> str:
        """构建用户消息部分。"""
        lines = [
            f"牵挂类型：{thought.concern_type}",
            f"牵挂内容：{thought.thought}",
            f"动机：{thought.motivation}",
            "",
        ]

        # 添加上下文记忆
        if self.memory and user_id:
            try:
                records = self.memory.search_semantic_memory(
                    user_id=user_id,
                    query=thought.thought,
                    top_k=3,
                )
                if records:
                    lines.append("相关记忆：")
                    for r in records:
                        lines.append(f"- {r.predicate}: {r.object}")
                    lines.append("")
            except Exception as e:
                logger.debug(f"获取语义记忆失败: {e}")

        # 当前状态信息
        lines.extend([
            f"当前时间：{state.hour_of_day}:00",
            f"是否深夜：{state.is_late_night}",
            f"交互频率：{state.interaction_frequency}",
            "",
            "请生成一条简短自然的主动消息（30字以内），直接输出消息内容，不要解释。",
        ])

        return "\n".join(lines)

    def _fallback_message(self, thought: Any, state: Any) -> str:
        """规则回退的简单消息。"""
        type_messages = {
            "care": [
                "还没睡呢？注意休息哦～",
                "最近怎么样？有空聊聊吗？",
                "刚刚想到你啦，最近还好吗？",
            ],
            "reminder": [
                "提醒一下，你之前说要做的那件事～",
                "别忘了之前提到的事情哦～",
            ],
            "curiosity": [
                "好奇你最近在忙什么～",
                "突然想起你啦，最近有什么新鲜事吗？",
            ],
            "greeting": [
                "嗨～好久不见啦！",
                "嘿，最近怎么样？",
            ],
        }

        import random
        messages = type_messages.get(thought.concern_type, ["想你啦～"])
        return random.choice(messages)
