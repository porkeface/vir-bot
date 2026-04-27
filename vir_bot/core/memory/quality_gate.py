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

    def __init__(self, config: dict | None = None, ai_provider=None):
        self.config = config or {}
        self._ai_provider = ai_provider

    async def check(
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

        # 规则检查通过，检查是否需要 LLM 二次检查
        if self._needs_llm_check(operation) and self._ai_provider:
            passed, reason, adj = await self._llm_check(operation)
            if not passed:
                return False, f"LLM质量检查未通过: {reason}", adj
            return True, f"LLM检查通过: {reason}", adj

        # 通过所有检查
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
        if not self._ai_provider:
            return True, "LLM client not available, passing", 1.0

        prompt = f"""请判断以下记忆操作是否可靠，给出判断和置信度调整建议。

操作类型: {op.op}
谓词: {op.predicate}
对象: {op.object}
来源文本: {op.source_text}
当前置信度: {op.confidence}

请考虑：
1. 来源文本是否清晰明确？
2. 是否有情绪化表达？
3. 是否包含模糊时间词？
4. 内容是否自相矛盾？

返回格式（只返回JSON）:
{{"passed": true/false, "reason": "原因", "confidence_adjustment": 0.0-1.0}}"""

        try:
            response = await self._ai_provider.chat(
                messages=[{"role": "user", "content": prompt}],
                system="你是一个记忆质量审查员，只返回JSON格式，不要其他内容。",
            )
            import json

            content = response.content.strip()
            # 提取JSON（可能包含在```json 块中）
            if "```" in content:
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            result = json.loads(content)
            return (
                result.get("passed", True),
                result.get("reason", "LLM检查通过"),
                float(result.get("confidence_adjustment", 1.0)),
            )
        except Exception as e:
            logger.warning(f"LLM check failed: {e}")
            return True, f"LLM检查失败: {e}", 1.0
