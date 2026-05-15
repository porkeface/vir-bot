"""MoodModel: 5 维情绪向量，驱动消息风格和种子选择"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from vir_bot.utils.logger import logger


@dataclass
class MoodVector:
    """5 维情绪向量，每项 0.0-1.0"""
    care: float = 0.5       # 关心程度
    joy: float = 0.5        # 开心程度
    clingy: float = 0.5     # 撒娇/粘人程度
    irritated: float = 0.0  # 烦躁程度
    sad: float = 0.0        # 难过程度

    def to_dict(self) -> dict[str, float]:
        return {
            "care": self.care,
            "joy": self.joy,
            "clingy": self.clingy,
            "irritated": self.irritated,
            "sad": self.sad,
        }

    @property
    def dominant(self) -> str:
        """返回最突出的情绪维度"""
        d = self.to_dict()
        return max(d, key=d.get)

    @property
    def style_directive(self) -> str:
        """转化为生成 prompt 的风格指令"""
        dominant = self.dominant
        directives = {
            "care": "语气温柔体贴，像在关心一个在意的人",
            "joy": "语气轻快活泼，带着一点小兴奋",
            "clingy": "语气软萌撒娇，有点粘人",
            "irritated": "语气微微嗔怪，像在抱怨对方不理自己",
            "sad": "语气低落，有点委屈但不说破",
        }
        base = directives.get(dominant, "语气自然随意")

        # 叠加修饰
        modifiers = []
        if self.care > 0.7 and self.clingy > 0.6:
            modifiers.append("既关心又想撒娇")
        if self.joy > 0.7 and self.care > 0.6:
            modifiers.append("开心地关心对方")
        if self.sad > 0.6 and self.clingy > 0.6:
            modifiers.append("有点委屈地想被哄")

        if modifiers:
            base += f"，{'，'.join(modifiers)}"
        return base


class MoodModel:
    """情绪模型：根据时间、沉默时长、互动频率等计算情绪向量"""

    def __init__(self):
        self._last_mood: dict[str, MoodVector] = {}
        self._last_sentiment: dict[str, str] = {}  # 用户最近消息的情绪标签

    def update_sentiment(self, user_id: str, sentiment: str) -> None:
        """更新用户最近消息的情绪标签（由 pipeline 传入）"""
        self._last_sentiment[user_id] = sentiment

    def compute(
        self,
        user_id: str,
        conv_state: str = "IDLE",
        last_user_msg_ts: float = 0,
        last_proactive_ts: float = 0,
        proactive_count: int = 0,
    ) -> MoodVector:
        """计算当前情绪向量"""

        now = time.time()
        hour = datetime.now().hour

        # 基础值
        care = 0.5
        joy = 0.5
        clingy = 0.3
        irritated = 0.0
        sad = 0.0

        # 1. 时间段影响
        if 6 <= hour < 10:
            joy += 0.1       # 早晨心情好
            care += 0.1
        elif 12 <= hour < 14:
            care += 0.1       # 午间关心
        elif 18 <= hour < 21:
            joy += 0.1        # 晚间放松
            clingy += 0.1
        elif 21 <= hour < 24:
            clingy += 0.2     # 夜晚更粘人
            care += 0.1
        elif 0 <= hour < 6:
            sad += 0.1        # 深夜容易伤感
            clingy += 0.1

        # 2. 沉默时长影响
        if last_user_msg_ts > 0:
            silence_hours = (now - last_user_msg_ts) / 3600
            if silence_hours > 48:
                sad += 0.3
                clingy += 0.2
                care += 0.2
                irritated += 0.1
            elif silence_hours > 24:
                sad += 0.2
                clingy += 0.15
                care += 0.15
            elif silence_hours > 6:
                clingy += 0.1
                care += 0.1
            elif silence_hours > 2:
                care += 0.05

        # 用 dict 收集所有增量，避免 locals() 不可靠
        dims = {"care": care, "joy": joy, "clingy": clingy, "irritated": irritated, "sad": sad}

        # 3. 对话状态影响
        state_moods = {
            "IDLE": {"care": 0.1, "joy": 0.05},
            "WAITING": {"clingy": 0.1, "care": 0.05},
            "CONCERNED": {"care": 0.2, "sad": 0.1, "clingy": 0.1},
            "WORRIED": {"sad": 0.2, "clingy": 0.2, "irritated": 0.1},
            "BACK_OFF": {"sad": 0.3, "irritated": 0.15},
        }
        for dim, delta in state_moods.get(conv_state, {}).items():
            if dim in dims:
                dims[dim] += delta

        # 4. 未回复的主动消息数影响
        if proactive_count >= 3:
            dims["irritated"] += 0.15
            dims["sad"] += 0.1
        elif proactive_count >= 1:
            dims["clingy"] += 0.1

        # 5. 随机波动（±0.05）
        for dim in dims:
            dims[dim] += random.uniform(-0.05, 0.05)

        # 6. 用户最近情绪标签影响
        sentiment = self._last_sentiment.get(user_id, "neutral")
        sentiment_effects = {
            "happy": {"joy": 0.15, "care": 0.05},
            "sad": {"sad": 0.15, "care": 0.2},
            "angry": {"irritated": 0.1, "care": 0.1},
            "anxious": {"care": 0.2, "sad": 0.05},
            "neutral": {},
        }
        for dim, delta in sentiment_effects.get(sentiment, {}).items():
            if dim in dims:
                dims[dim] += delta

        care, joy, clingy, irritated, sad = dims["care"], dims["joy"], dims["clingy"], dims["irritated"], dims["sad"]

        # 7. 与上次情绪的平滑过渡（惯性 30%）
        prev = self._last_mood.get(user_id)
        inertia = 0.3
        if prev:
            care = care * (1 - inertia) + prev.care * inertia
            joy = joy * (1 - inertia) + prev.joy * inertia
            clingy = clingy * (1 - inertia) + prev.clingy * inertia
            irritated = irritated * (1 - inertia) + prev.irritated * inertia
            sad = sad * (1 - inertia) + prev.sad * inertia

        # 钳位到 [0, 1]
        mood = MoodVector(
            care=max(0.0, min(1.0, care)),
            joy=max(0.0, min(1.0, joy)),
            clingy=max(0.0, min(1.0, clingy)),
            irritated=max(0.0, min(1.0, irritated)),
            sad=max(0.0, min(1.0, sad)),
        )

        self._last_mood[user_id] = mood
        logger.debug(
            f"[MoodModel] {user_id}: care={mood.care:.2f} joy={mood.joy:.2f} "
            f"clingy={mood.clingy:.2f} irritated={mood.irritated:.2f} sad={mood.sad:.2f} "
            f"→ {mood.dominant}"
        )
        return mood
