# -*- coding: utf-8 -*-
"""
StyleAnalyzer — 程序化说话风格统计

不依赖 LLM，直接从对话数据计算说话风格特征：
- 句子长度分布
- 语气词频率
- emoji 使用统计
- 标点习惯
- 称呼方式
- 活跃时间段
- 回复速度
- 话题关键词
"""

from __future__ import annotations

import re
import math
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from vir_bot.core.distillation.parser.base import DialogueTurn

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 中文语气词
FILLER_WORDS = [
    "哈哈", "嘿嘿", "嘻嘻", "呵呵", "哈哈哈", "呜", "嗯", "啊", "呀",
    "啦", "嘛", "呢", "吧", "哦", "噢", "喔", "额", "emmm", "emm",
    "em", "hmm", "啊这", "好家伙", "哇", "哎呀", "哎", "我去",
    "天哪", "救命", "绝了", "离谱", "笑死", "草", "尬",
]

# 称呼词
CALLING_PATTERNS = {
    "self": ["我", "本人", "人家", "俺", "偶"],
    "other": [
        "你", "您", "宝贝", "亲爱的", "老公", "老婆", "宝", "亲",
        "哥", "姐", "兄弟", "姐妹", "老铁", "老哥", "大佬",
    ],
}

# Emoji 正则（只匹配真正的 emoji，不匹配 CJK 字符）
EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U00002702-\U000027B0"  # dingbats
    "\U0000FE00-\U0000FE0F"  # variation selectors
    "\U0000200D"             # zero width joiner
    "\U00002600-\U000026FF"  # misc symbols
    "\U00002300-\U000023FF"  # misc technical
    "\U00002B50-\U00002B55"  # stars
    "\U0001f900-\U0001f9FF"  # supplemental symbols
    "\U0001FA00-\U0001FA6F"  # chess symbols
    "\U0001FA70-\U0001FAFF"  # symbols extended
    "]+",
    flags=re.UNICODE,
)

# 标点符号
PUNCTUATION = {
    "exclamation": "！!?",
    "question": "？?",
    "ellipsis": "…~～",
    "period": "。.",
    "comma": "，,",
}

# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass
class StyleStats:
    """说话风格统计结果。"""
    # 句子长度
    sentence_count: int = 0
    sentence_length_mean: float = 0.0
    sentence_length_median: float = 0.0
    sentence_length_std: float = 0.0
    short_sentence_ratio: float = 0.0  # <10字的比例
    long_sentence_ratio: float = 0.0   # >30字的比例

    # 语气词
    filler_words: Dict[str, int] = field(default_factory=dict)
    filler_word_total: int = 0
    filler_word_rate: float = 0.0  # 每条消息平均语气词数

    # 标点
    punctuation_stats: Dict[str, float] = field(default_factory=dict)
    # exclamation_rate, question_rate, ellipsis_rate, period_rate

    # emoji
    emoji_total: int = 0
    emoji_per_message: float = 0.0
    emoji_top: List[Tuple[str, int]] = field(default_factory=list)  # (emoji, count)
    emoji_unique: int = 0

    # 称呼
    self_references: List[Tuple[str, int]] = field(default_factory=list)
    other_references: List[Tuple[str, int]] = field(default_factory=list)

    # 活跃时间
    active_hours: Dict[int, int] = field(default_factory=dict)  # hour -> count
    peak_hours: List[int] = field(default_factory=list)
    quiet_hours: List[int] = field(default_factory=list)

    # 回复速度
    avg_reply_seconds: Optional[float] = None
    median_reply_seconds: Optional[float] = None

    # 消息长度分布
    message_length_mean: float = 0.0
    message_length_median: float = 0.0

    # 词汇丰富度
    vocabulary_size: int = 0
    vocabulary_richness: float = 0.0  # unique words / total words


# ---------------------------------------------------------------------------
# StyleAnalyzer
# ---------------------------------------------------------------------------


class StyleAnalyzer:
    """从对话记录中统计说话风格特征。"""

    def analyze(self, turns: List[DialogueTurn], target_sender: Optional[str] = None) -> StyleStats:
        """
        分析说话风格。

        Args:
            turns: 对话轮次列表
            target_sender: 目标分析对象的发送者名称。如果为 None，分析所有发送者。

        Returns:
            StyleStats 统计结果
        """
        if target_sender:
            target_turns = [t for t in turns if t.sender == target_sender]
        else:
            target_turns = turns

        if not target_turns:
            logger.warning("没有找到目标发送者的对话")
            return StyleStats()

        stats = StyleStats()
        stats.sentence_count = len(target_turns)

        # 句子长度
        self._analyze_sentence_lengths(target_turns, stats)

        # 语气词
        self._analyze_filler_words(target_turns, stats)

        # 标点
        self._analyze_punctuation(target_turns, stats)

        # emoji
        self._analyze_emojis(target_turns, stats)

        # 称呼
        self._analyze_calling(target_turns, stats)

        # 活跃时间
        self._analyze_active_hours(target_turns, stats)

        # 回复速度
        self._analyze_reply_speed(turns, target_sender, stats)

        # 词汇丰富度
        self._analyze_vocabulary(target_turns, stats)

        return stats

    # ------------------------------------------------------------------
    # 句子长度
    # ------------------------------------------------------------------

    def _analyze_sentence_lengths(self, turns: List[DialogueTurn], stats: StyleStats) -> None:
        lengths = []
        for t in turns:
            content = t.content.strip()
            if content:
                lengths.append(len(content))

        if not lengths:
            return

        stats.message_length_mean = sum(lengths) / len(lengths)
        stats.message_length_median = self._median(lengths)

        # 按标点分句
        all_sentence_lengths = []
        for t in turns:
            sentences = re.split(r'[。！？!?\n]', t.content)
            for s in sentences:
                s = s.strip()
                if s:
                    all_sentence_lengths.append(len(s))

        if all_sentence_lengths:
            stats.sentence_length_mean = sum(all_sentence_lengths) / len(all_sentence_lengths)
            stats.sentence_length_median = self._median(all_sentence_lengths)
            stats.sentence_length_std = self._std(all_sentence_lengths)
            stats.short_sentence_ratio = sum(1 for l in all_sentence_lengths if l < 10) / len(all_sentence_lengths)
            stats.long_sentence_ratio = sum(1 for l in all_sentence_lengths if l > 30) / len(all_sentence_lengths)

    # ------------------------------------------------------------------
    # 语气词
    # ------------------------------------------------------------------

    def _analyze_filler_words(self, turns: List[DialogueTurn], stats: StyleStats) -> None:
        counter: Counter = Counter()
        total_count = 0

        for t in turns:
            content = t.content
            for word in FILLER_WORDS:
                count = content.count(word)
                if count > 0:
                    counter[word] += count
                    total_count += count

        stats.filler_words = dict(counter.most_common(30))
        stats.filler_word_total = total_count
        stats.filler_word_rate = total_count / max(1, len(turns))

    # ------------------------------------------------------------------
    # 标点
    # ------------------------------------------------------------------

    def _analyze_punctuation(self, turns: List[DialogueTurn], stats: StyleStats) -> None:
        total_chars = 0
        punct_counts = {k: 0 for k in PUNCTUATION}

        for t in turns:
            content = t.content
            total_chars += len(content)
            for punct_name, punct_chars in PUNCTUATION.items():
                for ch in punct_chars:
                    punct_counts[punct_name] += content.count(ch)

        if total_chars > 0:
            stats.punctuation_stats = {
                f"{k}_rate": round(v / total_chars, 4)
                for k, v in punct_counts.items()
            }
        else:
            stats.punctuation_stats = {}

    # ------------------------------------------------------------------
    # Emoji
    # ------------------------------------------------------------------

    def _analyze_emojis(self, turns: List[DialogueTurn], stats: StyleStats) -> None:
        emoji_counter: Counter = Counter()

        for t in turns:
            emojis = EMOJI_PATTERN.findall(t.content)
            for e in emojis:
                emoji_counter[e] += 1

        stats.emoji_total = sum(emoji_counter.values())
        stats.emoji_per_message = stats.emoji_total / max(1, len(turns))
        stats.emoji_top = emoji_counter.most_common(20)
        stats.emoji_unique = len(emoji_counter)

    # ------------------------------------------------------------------
    # 称呼
    # ------------------------------------------------------------------

    def _analyze_calling(self, turns: List[DialogueTurn], stats: StyleStats) -> None:
        self_counter: Counter = Counter()
        other_counter: Counter = Counter()

        for t in turns:
            content = t.content
            for word in CALLING_PATTERNS["self"]:
                count = content.count(word)
                if count > 0:
                    self_counter[word] += count
            for word in CALLING_PATTERNS["other"]:
                count = content.count(word)
                if count > 0:
                    other_counter[word] += count

        stats.self_references = self_counter.most_common(10)
        stats.other_references = other_counter.most_common(10)

    # ------------------------------------------------------------------
    # 活跃时间
    # ------------------------------------------------------------------

    def _analyze_active_hours(self, turns: List[DialogueTurn], stats: StyleStats) -> None:
        hour_counter: Dict[int, int] = {}

        for t in turns:
            if t.timestamp:
                hour = t.timestamp.hour
                hour_counter[hour] = hour_counter.get(hour, 0) + 1

        stats.active_hours = hour_counter

        if hour_counter:
            sorted_hours = sorted(hour_counter.items(), key=lambda x: -x[1])
            stats.peak_hours = [h for h, _ in sorted_hours[:3]]
            stats.quiet_hours = [h for h, _ in sorted_hours[-3:]]

    # ------------------------------------------------------------------
    # 回复速度
    # ------------------------------------------------------------------

    def _analyze_reply_speed(
        self,
        all_turns: List[DialogueTurn],
        target_sender: Optional[str],
        stats: StyleStats,
    ) -> None:
        """计算回复速度（从对方发消息到目标回复的时间差）。"""
        if not target_sender:
            return

        reply_times = []
        prev_turn = None

        for t in all_turns:
            if prev_turn and t.sender == target_sender and prev_turn.sender != target_sender:
                if t.timestamp and prev_turn.timestamp:
                    diff = (t.timestamp - prev_turn.timestamp).total_seconds()
                    if 0 < diff < 3600:  # 忽略超过1小时的间隔
                        reply_times.append(diff)
            prev_turn = t

        if reply_times:
            stats.avg_reply_seconds = sum(reply_times) / len(reply_times)
            stats.median_reply_seconds = self._median(reply_times)

    # ------------------------------------------------------------------
    # 词汇丰富度
    # ------------------------------------------------------------------

    def _analyze_vocabulary(self, turns: List[DialogueTurn], stats: StyleStats) -> None:
        """计算词汇丰富度（去重词数 / 总词数）。"""
        all_text = " ".join(t.content for t in turns)

        # 简单分词：按非中文非字母数字分割
        words = re.findall(r'[一-鿿]+|[a-zA-Z]+|[0-9]+', all_text)
        if not words:
            return

        stats.vocabulary_size = len(set(words))
        stats.vocabulary_richness = len(set(words)) / len(words)

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    @staticmethod
    def _median(values: List[float]) -> float:
        if not values:
            return 0.0
        sorted_vals = sorted(values)
        n = len(sorted_vals)
        if n % 2 == 0:
            return (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2
        return sorted_vals[n // 2]

    @staticmethod
    def _std(values: List[float]) -> float:
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
        return math.sqrt(variance)

    def to_dict(self, stats: StyleStats) -> Dict[str, Any]:
        """将 StyleStats 转为可序列化的字典。"""
        return {
            "sentence_count": stats.sentence_count,
            "sentence_length": {
                "mean": round(stats.sentence_length_mean, 1),
                "median": round(stats.sentence_length_median, 1),
                "std": round(stats.sentence_length_std, 1),
                "short_ratio": round(stats.short_sentence_ratio, 3),
                "long_ratio": round(stats.long_sentence_ratio, 3),
            },
            "message_length": {
                "mean": round(stats.message_length_mean, 1),
                "median": round(stats.message_length_median, 1),
            },
            "filler_words": stats.filler_words,
            "filler_word_rate": round(stats.filler_word_rate, 2),
            "punctuation": stats.punctuation_stats,
            "emoji": {
                "total": stats.emoji_total,
                "per_message": round(stats.emoji_per_message, 2),
                "unique": stats.emoji_unique,
                "top": stats.emoji_top,
            },
            "calling": {
                "self": stats.self_references,
                "other": stats.other_references,
            },
            "active_hours": stats.active_hours,
            "peak_hours": stats.peak_hours,
            "quiet_hours": stats.quiet_hours,
            "reply_speed": {
                "avg_seconds": round(stats.avg_reply_seconds, 1) if stats.avg_reply_seconds else None,
                "median_seconds": round(stats.median_reply_seconds, 1) if stats.median_reply_seconds else None,
            },
            "vocabulary": {
                "size": stats.vocabulary_size,
                "richness": round(stats.vocabulary_richness, 3),
            },
        }
