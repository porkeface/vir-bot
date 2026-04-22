"""结构化问题记忆 - 用于精准记住和检索用户问过的问题"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Literal

from vir_bot.utils.logger import logger


@dataclass
class QuestionMemory:
    """用户问题的结构化记忆 - 相比通用 conversation，这里对问题进行了语义分解"""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # ==================== 问题维度 ====================
    question_text: str = ""
    question_type: Literal["how", "what", "why", "example", "opinion", "other"] = "other"
    topic: str = ""  # 问题主题，如 "时间管理", "OKR", "Python装饰器"
    entities: list[str] = field(default_factory=list)  # 实体列表：["张三", "生日", "OKR"]
    intent: str = ""  # 用户意图：learn/debug/opinion/confirm/explore

    # ==================== 回答维度 ====================
    answer_text: str = ""  # 原始完整答案
    answer_summary: str = ""  # 答案摘要（50-100字核心内容）
    key_points: list[str] = field(default_factory=list)  # 关键要点列表 (3-5条)

    # ==================== 元数据 ====================
    timestamp: float = field(default_factory=time.time)
    importance: float = 0.7  # 默认0.7（用户主动问的问题通常很重要）
    user_id: str = ""

    # ==================== 关联维度 ====================
    related_question_ids: list[str] = field(default_factory=list)  # 相关问题ID
    follow_up_count: int = 0  # 用户后续追问次数（越多说明越重要）


@dataclass
class QuestionIndexEntry:
    """问题索引条目 - 用于快速查询"""

    question_memory_id: str
    question_text: str
    topic: str
    entities: list[str]
    question_type: str
    timestamp: float


class QuestionMemoryIndex:
    """问题倒排索引 - O(1) 查询相关问题"""

    def __init__(self):
        # topic -> set of question_ids
        self.topic_index: dict[str, set[str]] = {}

        # entity -> set of question_ids
        self.entity_index: dict[str, set[str]] = {}

        # question_type -> set of question_ids
        self.type_index: dict[str, set[str]] = {}

        # 所有问题ID，按时间排序（用于最近问题查询）
        self.all_question_ids: list[str] = []

        logger.info("QuestionMemoryIndex initialized")

    def add(self, question: QuestionMemory) -> None:
        """添加问题到索引"""
        qid = question.id

        # 添加到主列表
        if qid not in self.all_question_ids:
            self.all_question_ids.append(qid)

        # 按主题索引
        if question.topic:
            if question.topic not in self.topic_index:
                self.topic_index[question.topic] = set()
            self.topic_index[question.topic].add(qid)

        # 按实体索引
        for entity in question.entities:
            if entity not in self.entity_index:
                self.entity_index[entity] = set()
            self.entity_index[entity].add(qid)

        # 按类型索引
        if question.question_type not in self.type_index:
            self.type_index[question.question_type] = set()
        self.type_index[question.question_type].add(qid)

    def find_by_topic(self, topic: str, limit: int = 10) -> list[str]:
        """按主题查询相关问题"""
        if topic not in self.topic_index:
            return []
        return list(self.topic_index[topic])[-limit:]

    def find_by_entity(self, entity: str, limit: int = 10) -> list[str]:
        """按实体查询相关问题"""
        if entity not in self.entity_index:
            return []
        return list(self.entity_index[entity])[-limit:]

    def find_by_type(self, qtype: str, limit: int = 10) -> list[str]:
        """按问题类型查询"""
        if qtype not in self.type_index:
            return []
        return list(self.type_index[qtype])[-limit:]

    def find_recent(self, limit: int = 10) -> list[str]:
        """获取最近问过的问题"""
        return self.all_question_ids[-limit:]

    def clear(self) -> None:
        """清空索引"""
        self.topic_index.clear()
        self.entity_index.clear()
        self.type_index.clear()
        self.all_question_ids.clear()
        logger.info("QuestionMemoryIndex cleared")
