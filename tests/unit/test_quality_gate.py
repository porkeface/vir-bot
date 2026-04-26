"""测试记忆质量门。"""

from __future__ import annotations

import pytest

from vir_bot.core.memory.quality_gate import QualityGate
from vir_bot.core.memory.memory_writer import MemoryOperation


class TestQualityGate:
    """测试 QualityGate。"""

    def test_fuzzy_time_words(self):
        """测试时间性模糊词检测。"""
        gate = QualityGate()

        op = MemoryOperation(
            op="ADD",
            namespace="profile.preference",
            subject="user",
            predicate="likes",
            object="火锅",
            confidence=0.9,
            source_text="我最近喜欢吃火锅",
        )

        passed, reason, conf = gate.check(op)
        assert passed is False
        assert "模糊" in reason
        assert conf == 0.3

    def test_emotion_words(self):
        """测试情绪化表达检测。"""
        gate = QualityGate()

        op = MemoryOperation(
            op="ADD",
            namespace="profile.preference",
            subject="user",
            predicate="likes",
            object="火锅",
            confidence=0.9,
            source_text="我超级喜欢火锅",  # 包含情绪化词汇 "超级喜欢"
        )

        passed, reason, conf = gate.check(op)
        assert passed is False
        assert "情绪化" in reason or "可靠性" in reason

    def test_short_source_text(self):
        """测试来源信息不足。"""
        gate = QualityGate()

        op = MemoryOperation(
            op="ADD",
            namespace="profile.preference",
            subject="user",
            predicate="likes",
            object="火锅",
            confidence=0.9,
            source_text="",  # 空字符串
        )

        passed, reason, conf = gate.check(op)
        assert passed is False
        assert "不足" in reason

    def test_valid_operation(self):
        """测试正常的操作通过质量门。"""
        gate = QualityGate()

        op = MemoryOperation(
            op="ADD",
            namespace="profile.preference",
            subject="user",
            predicate="likes",
            object="火锅",
            confidence=0.9,
            source_text="我喜欢吃火锅",
        )

        passed, reason, conf = gate.check(op)
        assert passed is True
        assert reason == "通过"
        assert conf == 1.0

    def test_empty_object(self):
        """测试空对象值。"""
        gate = QualityGate()

        op = MemoryOperation(
            op="ADD",
            namespace="profile.preference",
            subject="user",
            predicate="likes",
            object="",
            confidence=0.9,
            source_text="我喜欢吃火锅",
        )

        passed, reason, conf = gate.check(op)
        assert passed is False
        assert "空" in reason
