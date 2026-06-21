"""候选行为选择器 — 多个候选行为竞争，选择最合适的（借鉴 Alice IAUS）。

核心思想：主动消息不是"发不发"的二元选择，而是多个候选行为竞争：
- 发文字消息
- 发语音消息
- 分享一段回忆
- 问一个问题
- 表达一种情绪
- 保持沉默

每个候选根据驱动力、上下文、关系阶段评分，加噪声后选最高分。
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from vir_bot.utils.logger import logger


@dataclass
class ActionCandidate:
    """一个候选行为。"""
    action_type: str       # send_message / send_voice / share_memory / ask_question / express_emotion / silence
    score: float = 0.0     # 基础评分
    reason: str = ""       # 选择原因


class ActionSelector:
    """候选行为选择器。"""

    ACTION_TYPES = [
        "send_message",
        "send_voice",
        "share_memory",
        "ask_question",
        "express_emotion",
        "silence",
    ]

    def select(
        self,
        drives: Any,  # DriveSnapshot
        context: dict | None = None,
        relationship_stage: str = "acquaintance",
        temperature: float = 0.1,
    ) -> ActionCandidate:
        """从候选行为中选择最合适的。

        Args:
            drives: 5D 驱动力快照
            context: 上下文信息（proactive_count_today, silence_hours 等）
            relationship_stage: 关系阶段
            temperature: 噪声温度（越高越随机）
        """
        context = context or {}
        scores: dict[str, float] = {}

        for action_type in self.ACTION_TYPES:
            base_score = self._score_action(action_type, drives, context, relationship_stage)
            # 加入噪声
            noisy_score = base_score + random.gauss(0, temperature)
            scores[action_type] = max(0.0, noisy_score)

        # 选择得分最高的
        best_action = max(scores, key=scores.get)
        best_score = scores[best_action]

        # 如果沉默得分最高，且其他行为得分都不高，选择沉默
        if best_action == "silence" and best_score < 0.5:
            # 检查是否有其他行为值得做
            non_silence = {k: v for k, v in scores.items() if k != "silence"}
            best_non_silence = max(non_silence, key=non_silence.get)
            if non_silence[best_non_silence] > 0.4:
                best_action = best_non_silence
                best_score = non_silence[best_non_silence]

        reason = self._explain_choice(best_action, drives, context)

        logger.debug(
            f"[ActionSelector] 选择: {best_action} (score={best_score:.2f}), "
            f"scores={', '.join(f'{k}={v:.2f}' for k, v in sorted(scores.items(), key=lambda x: -x[1]))}"
        )

        return ActionCandidate(
            action_type=best_action,
            score=best_score,
            reason=reason,
        )

    def _score_action(
        self,
        action_type: str,
        drives: Any,
        context: dict,
        relationship_stage: str,
    ) -> float:
        """为候选行为评分。"""

        proactive_count = context.get("proactive_count_today", 0)
        silence_hours = context.get("silence_hours", 0)
        hour = datetime.now().hour

        if action_type == "send_message":
            # 发文字消息：联结欲 + 关心欲 + 好奇心
            score = (
                drives.loneliness * 0.40
                + drives.care_drive * 0.30
                + drives.curiosity * 0.20
                + drives.expression * 0.10
            )
            # 已经发过很多消息，降低评分
            if proactive_count > 3:
                score *= 0.5
            elif proactive_count > 1:
                score *= 0.8
            return score

        elif action_type == "send_voice":
            # 发语音：深夜或情绪化时更倾向
            score = 0.2
            if 0 <= hour < 6:
                score += 0.3  # 深夜更亲密
            if drives.expression > 0.5:
                score += 0.2  # 表达欲高时
            if relationship_stage in ("close", "friend"):
                score += 0.1  # 关系近时更自然
            return score

        elif action_type == "share_memory":
            # 分享回忆：好奇心 + 关心欲
            score = drives.curiosity * 0.5 + drives.care_drive * 0.3
            # 有沉默时间时更合适
            if silence_hours > 4:
                score += 0.2
            return score

        elif action_type == "ask_question":
            # 问问题：好奇心
            score = drives.curiosity * 0.6 + drives.expression * 0.2
            # 关系浅时更倾向问问题
            if relationship_stage in ("stranger", "acquaintance"):
                score += 0.15
            return score

        elif action_type == "express_emotion":
            # 表达情绪：表达欲 + 玩乐欲
            score = drives.expression * 0.5 + drives.playfulness * 0.3
            # 关系深时更自然
            if relationship_stage in ("close", "friend"):
                score += 0.2
            return score

        elif action_type == "silence":
            # 保持沉默：发过很多消息时得分高
            score = 0.3
            if proactive_count > 3:
                score += 0.5
            elif proactive_count > 1:
                score += 0.2
            # 深夜沉默更合理
            if 0 <= hour < 6:
                score += 0.1
            return score

        return 0.3

    def _explain_choice(
        self, action_type: str, drives: Any, context: dict
    ) -> str:
        """解释选择原因。"""
        dominant = drives.dominant

        explanations = {
            "send_message": f"想聊天（{dominant}最强）",
            "send_voice": "想用声音说话",
            "share_memory": "想分享一段回忆",
            "ask_question": "好奇对方的事",
            "express_emotion": "想表达心情",
            "silence": "先不打扰",
        }
        return explanations.get(action_type, "默认选择")
