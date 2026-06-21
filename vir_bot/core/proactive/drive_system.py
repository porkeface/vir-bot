"""DriveSystem: 内驱力系统 — 模拟 AI 的内在需求，替代硬编码定时器"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from vir_bot.utils.logger import logger


@dataclass
class DriveState:
    """单条驱动力的状态"""
    name: str
    value: float = 0.0           # 当前值 0.0-1.0
    last_update_ts: float = 0.0  # 上次更新时间
    last_trigger_ts: float = 0.0 # 上次被触发的时间


@dataclass
class DriveSnapshot:
    """驱动力快照，用于传递给其他组件（5D）"""
    loneliness: float = 0.0      # 联结欲
    curiosity: float = 0.0       # 好奇心
    care_drive: float = 0.0      # 关心欲
    expression: float = 0.0      # 表达欲
    playfulness: float = 0.0     # 玩乐欲
    timestamp: float = 0.0

    @property
    def max_drive(self) -> float:
        return max(self.loneliness, self.curiosity, self.care_drive, self.expression, self.playfulness)

    @property
    def dominant(self) -> str:
        d = {
            "loneliness": self.loneliness,
            "curiosity": self.curiosity,
            "care_drive": self.care_drive,
            "expression": self.expression,
            "playfulness": self.playfulness,
        }
        return max(d, key=d.get)

    def to_dict(self) -> dict:
        return {
            "loneliness": round(self.loneliness, 3),
            "curiosity": round(self.curiosity, 3),
            "care_drive": round(self.care_drive, 3),
            "expression": round(self.expression, 3),
            "playfulness": round(self.playfulness, 3),
        }


class DriveSystem:
    """内驱力系统：5 条驱动力随时间自然积累，概率触发灵感（借鉴 OpenHer）"""

    # 孤独感：指数增长，越久越强烈
    LONELINESS_BASE_RATE = 0.018     # 每小时基础增长
    LONELINESS_DECAY_REPLY = 0.55    # 用户回复时下降
    LONELINESS_DECAY_SEND = 0.15     # 自己发消息时下降

    # 好奇心：线性增长，有新事实时快速上升
    CURIOSITY_BASE_RATE = 0.012
    CURIOSITY_FACT_BOOST = 0.35      # 有新事实时增长
    CURIOSITY_DECAY_USE = 0.45       # 用过种子后下降

    # 关心欲：事件驱动，不自动增长
    CARE_DRIVE_DECAY_MENTION = 0.7   # 提到事件后下降
    CARE_DRIVE_EVENT_BOOST = 0.4     # 关心事件提升
    EXPRESSION_INTEREST_BOOST = 0.2  # 用户感兴趣时提升

    # 表达欲：线性增长，发消息后下降
    EXPRESSION_BASE_RATE = 0.008     # 每小时基础增长
    EXPRESSION_DECAY_SEND = 0.3      # 发消息后下降

    # 玩乐欲：缓慢增长，互动后下降
    PLAYFULNESS_BASE_RATE = 0.005    # 每小时基础增长
    PLAYFULNESS_DECAY_PLAY = 0.5     # 玩乐互动后下降

    # 值域
    MIN_VALUE = 0.0
    MAX_VALUE = 1.0

    def __init__(self):
        self._drives: dict[str, DriveState] = {
            "loneliness": DriveState(name="loneliness", value=0.3, last_update_ts=time.time()),
            "curiosity": DriveState(name="curiosity", value=0.2, last_update_ts=time.time()),
            "care_drive": DriveState(name="care_drive", value=0.1, last_update_ts=time.time()),
            "expression": DriveState(name="expression", value=0.15, last_update_ts=time.time()),
            "playfulness": DriveState(name="playfulness", value=0.1, last_update_ts=time.time()),
        }
        self._has_new_facts: bool = False

    def snapshot(self) -> DriveSnapshot:
        """获取当前驱动力快照（只读，不触发衰减）"""
        return DriveSnapshot(
            loneliness=self._drives["loneliness"].value,
            curiosity=self._drives["curiosity"].value,
            care_drive=self._drives["care_drive"].value,
            expression=self._drives["expression"].value,
            playfulness=self._drives["playfulness"].value,
            timestamp=time.time(),
        )

    def on_user_reply(self) -> None:
        """用户回复消息时调用"""
        now = time.time()
        self._drives["loneliness"].value = max(
            self.MIN_VALUE,
            self._drives["loneliness"].value - self.LONELINESS_DECAY_REPLY,
        )
        self._drives["loneliness"].last_update_ts = now
        logger.debug(f"[DriveSystem] 用户回复，loneliness → {self._drives['loneliness'].value:.2f}")

    def on_proactive_sent(self) -> None:
        """自己发出主动消息时调用"""
        now = time.time()
        self._drives["loneliness"].value = max(
            self.MIN_VALUE,
            self._drives["loneliness"].value - self.LONELINESS_DECAY_SEND,
        )
        self._drives["expression"].value = max(
            self.MIN_VALUE,
            self._drives["expression"].value - self.EXPRESSION_DECAY_SEND,
        )
        self._drives["loneliness"].last_update_ts = now
        self._drives["loneliness"].last_trigger_ts = now
        self._drives["expression"].last_update_ts = now
        logger.debug(f"[DriveSystem] 已发送，loneliness → {self._drives['loneliness'].value:.2f}, expression → {self._drives['expression'].value:.2f}")

    def on_seed_used(self, seed_type: str) -> None:
        """内容种子被使用时调用"""
        now = time.time()
        if seed_type in ("interest", "shared_memory"):
            self._drives["curiosity"].value = max(
                self.MIN_VALUE,
                self._drives["curiosity"].value - self.CURIOSITY_DECAY_USE,
            )
        elif seed_type == "callback":
            self._drives["care_drive"].value = max(
                self.MIN_VALUE,
                self._drives["care_drive"].value - self.CARE_DRIVE_DECAY_MENTION,
            )
        self._drives["curiosity"].last_update_ts = now
        logger.debug(f"[DriveSystem] 种子使用 [{seed_type}], curiosity={self._drives['curiosity'].value:.2f}")

    def on_new_facts_available(self) -> None:
        """有新的事实可用来调用"""
        self._has_new_facts = True
        self._drives["curiosity"].value = min(
            self.MAX_VALUE,
            self._drives["curiosity"].value + self.CURIOSITY_FACT_BOOST,
        )
        logger.debug(f"[DriveSystem] 新事实可用，curiosity → {self._drives['curiosity'].value:.2f}")

    def on_care_event(self, event_description: str = "") -> None:
        """关心事件触发（用户提到考试、面试、生日等）"""
        now = time.time()
        self._drives["care_drive"].value = min(
            self.MAX_VALUE,
            self._drives["care_drive"].value + self.CARE_DRIVE_EVENT_BOOST,
        )
        self._drives["care_drive"].last_update_ts = now
        logger.info(f"[DriveSystem] 关心事件: {event_description[:30]}, care_drive → {self._drives['care_drive'].value:.2f}")

    def on_playful_interaction(self) -> None:
        """玩乐互动后调用（开玩笑、斗图、玩游戏等）"""
        self._drives["playfulness"].value = max(
            self.MIN_VALUE,
            self._drives["playfulness"].value - self.PLAYFULNESS_DECAY_PLAY,
        )
        self._drives["playfulness"].last_update_ts = time.time()
        logger.debug(f"[DriveSystem] 玩乐互动，playfulness → {self._drives['playfulness'].value:.2f}")

    def on_user_express_interest(self) -> None:
        """用户表现出兴趣时调用"""
        now = time.time()
        self._drives["expression"].value = min(
            self.MAX_VALUE,
            self._drives["expression"].value + self.EXPRESSION_INTEREST_BOOST,
        )
        self._drives["expression"].last_update_ts = now
        logger.debug(f"[DriveSystem] 用户感兴趣，expression → {self._drives['expression'].value:.2f}")

    def drive_to_probability(self, drives: DriveSnapshot) -> float:
        """将驱动力转化为发送概率（0.0-1.0）"""
        # 加权组合（5D）
        raw = (
            drives.loneliness * 0.35
            + drives.curiosity * 0.20
            + drives.care_drive * 0.25
            + drives.expression * 0.10
            + drives.playfulness * 0.10
        )
        # sigmoid 映射：0.3 → ~0.15, 0.5 → ~0.35, 0.7 → ~0.6, 0.9 → ~0.82
        prob = 1 / (1 + math.exp(-6 * (raw - 0.45)))
        return prob

    def should_consider_sending(self, drives: DriveSnapshot) -> tuple[bool, float]:
        """概率判断：是否应该考虑发送（0 LLM 成本的快速过滤）"""
        prob = self.drive_to_probability(drives)
        roll = random.random()
        should = roll < prob
        logger.debug(
            f"[DriveSystem] 概率判断: prob={prob:.2f} roll={roll:.2f} "
            f"→ {'触发' if should else '跳过'}"
        )
        return should, prob

    def tick(self) -> None:
        """更新驱动力到当前时间"""
        now = time.time()
        for drive in self._drives.values():
            if drive.last_update_ts <= 0:
                drive.last_update_ts = now
                continue

            elapsed_hours = (now - drive.last_update_ts) / 3600
            if elapsed_hours <= 0:
                continue

            if drive.name == "loneliness":
                # 指数增长：每小时 base_rate，但随值增大加速
                growth = self.LONELINESS_BASE_RATE * elapsed_hours
                # 额外加速：值越高增长越快（指数特性）
                growth *= (1 + drive.value * 0.8)
                drive.value = min(self.MAX_VALUE, drive.value + growth)

            elif drive.name == "curiosity":
                # 线性增长
                growth = self.CURIOSITY_BASE_RATE * elapsed_hours
                drive.value = min(self.MAX_VALUE, drive.value + growth)

            elif drive.name == "care_drive":
                # 不自动增长（事件驱动）
                pass

            elif drive.name == "expression":
                # 线性增长
                growth = self.EXPRESSION_BASE_RATE * elapsed_hours
                drive.value = min(self.MAX_VALUE, drive.value + growth)

            elif drive.name == "playfulness":
                # 缓慢线性增长
                growth = self.PLAYFULNESS_BASE_RATE * elapsed_hours
                drive.value = min(self.MAX_VALUE, drive.value + growth)

            drive.last_update_ts = now

    def get_state_summary(self) -> str:
        """获取可读的状态摘要（用于 prompt）"""
        s = self.snapshot()
        parts = []
        if s.loneliness > 0.6:
            parts.append(f"孤独感很强({s.loneliness:.1f})")
        elif s.loneliness > 0.3:
            parts.append(f"有点想她({s.loneliness:.1f})")
        else:
            parts.append(f"孤独感低({s.loneliness:.1f})")

        if s.curiosity > 0.5:
            parts.append(f"好奇({s.curiosity:.1f})")
        if s.care_drive > 0.5:
            parts.append(f"很想关心她({s.care_drive:.1f})")
        if s.expression > 0.5:
            parts.append(f"想说话({s.expression:.1f})")
        if s.playfulness > 0.5:
            parts.append(f"想玩({s.playfulness:.1f})")

        return "，".join(parts)
