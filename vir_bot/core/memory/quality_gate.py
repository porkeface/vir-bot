"""记忆质量门：规则引擎 + LLM 二次判断。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from vir_bot.utils.logger import logger

if TYPE_CHECKING:
    from vir_bot.core.memory.memory_writer import MemoryOperation


class QualityGate:
    """记忆质量门：规则引擎先行，LLM 二次判断。"""

    # 时间性模糊词
    FUZZY_TIME_WORDS = ["最近", "经常", "总是", "从来", "刚刚", "马上", "一直", "随时"]

    # 情绪化表达
    EMOTION_WORDS = ["最讨厌", "超级喜欢", "恨死", "爱死", "绝对", "无比", "特别讨厌", "特别喜欢"]

    # 来源可靠性检查：最小长度
    MIN_SOURCE_LENGTH = 5

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self._llm_client = None

    def check(
        self,
        operation: "MemoryOperation",
        context: str = "",
    ) -> tuple[bool, str, float]:
        """
        检查记忆操作是否应通过质量门。
        返回: (通过?, 原因, 置信度调整系数)
        """
        # 规则1：时间性模糊词检测
        if self._has_fuzzy_time_words(operation.source_text):
            return False, "包含时间性模糊词", 0.3

        # 规则2：情绪化表达检测
        if self._has_emotion_words(operation.source_text):
            return False, "情绪化表达，可靠性低", 0.5

        # 规则3：来源可靠性检查
        if not operation.source_text or len(operation.source_text) < self.MIN_SOURCE_LENGTH:
            return False, "来源信息不足", 0.0

        # 规则4：空值检查
        if not operation.object or operation.object.strip() == "":
            return False, "记忆对象为空", 0.0

        # 通过所有规则检查
        return True, "通过", 1.0

    def _has_fuzzy_time_words(self, text: str) -> bool:
        """检查是否包含时间性模糊词。"""
        if not text:
            return False
        return any(word in text for word in self.FUZZY_TIME_WORDS)

    def _has_emotion_words(self, text: str) -> bool:
        """检查是否包含情绪化表达。"""
        if not text:
            return False
        return any(word in text for word in self.EMOTION_WORDS)

    def _needs_llm_check(self, op: "MemoryOperation") -> bool:
        """判断是否需要 LLM 二次检查（置信度在临界区域）。"""
        return 0.5 <= op.confidence <= 0.7

    async def _llm_check(self, op: "MemoryOperation") -> tuple[bool, str, float]:
        """使用 LLM 判断记忆质量（灰色地带）。"""
        # TODO: 实现 LLM 二次检查
        # 暂时返回通过
        return True, "LLM检查通过", 1.0
