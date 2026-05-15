# -*- coding: utf-8 -*-
"""
TopicClusterer — 基于 embedding 的对话话题聚类

用 sentence-transformers 对对话做 embedding，K-Means 聚类，
每个聚类生成话题标签和统计信息。

输出：话题-情绪关联矩阵，比 LLM 一句话概括更精确。
"""

from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass
class TopicCluster:
    """单个话题聚类。"""
    topic_id: int
    topic_label: str = ""
    count: int = 0
    keywords: List[str] = field(default_factory=list)
    example_messages: List[str] = field(default_factory=list)
    avg_message_length: float = 0.0
    sentiment_hint: str = ""  # 粗略情绪倾向


@dataclass
class TopicAnalysis:
    """话题分析结果。"""
    clusters: List[TopicCluster] = field(default_factory=list)
    topic_distribution: Dict[str, float] = field(default_factory=dict)
    total_messages: int = 0


# ---------------------------------------------------------------------------
# TopicClusterer
# ---------------------------------------------------------------------------


class TopicClusterer:
    """
    基于 embedding 的对话话题聚类。

    流程：
    1. 对每条消息做 embedding
    2. K-Means 聚类
    3. 提取每个聚类的关键词和代表消息
    4. 用 LLM 生成话题标签（可选）
    """

    def __init__(
        self,
        *,
        embedding_model: str = "all-MiniLM-L6-v2",
        n_clusters: int = 8,
        max_examples_per_cluster: int = 5,
        llm_provider: Optional[Any] = None,
    ) -> None:
        self.embedding_model_name = embedding_model
        self.n_clusters = n_clusters
        self.max_examples_per_cluster = max_examples_per_cluster
        self.llm = llm_provider
        self._encoder = None

    def analyze(
        self,
        turns: List[Any],
        target_sender: Optional[str] = None,
        n_clusters: Optional[int] = None,
    ) -> TopicAnalysis:
        """
        对对话做话题聚类分析。

        Args:
            turns: DialogueTurn 列表
            target_sender: 只分析特定发送者的消息
            n_clusters: 聚类数量（覆盖默认值）

        Returns:
            TopicAnalysis 结果
        """
        # 过滤消息
        if target_sender:
            messages = [t for t in turns if t.sender == target_sender and t.content.strip()]
        else:
            messages = [t for t in turns if t.content.strip()]

        if len(messages) < 5:
            logger.warning("消息数量不足（%d），跳过话题聚类", len(messages))
            return TopicAnalysis(total_messages=len(messages))

        k = min(n_clusters or self.n_clusters, len(messages) // 3, 15)
        k = max(k, 2)  # 至少 2 个聚类

        logger.info("话题聚类：%d 条消息，%d 个聚类", len(messages), k)

        # Step 1: 生成 embedding
        texts = [t.content for t in messages]
        embeddings = self._get_embeddings(texts)

        if not embeddings:
            logger.warning("Embedding 生成失败")
            return TopicAnalysis(total_messages=len(messages))

        # Step 2: K-Means 聚类
        labels = self._cluster(embeddings, k)

        # Step 3: 分析每个聚类
        clusters = self._analyze_clusters(messages, labels, k)

        # Step 4: 话题分布
        label_counts = Counter(labels)
        topic_distribution = {
            clusters[i].topic_label or f"话题{i}": label_counts.get(i, 0) / len(messages)
            for i in range(k)
            if i < len(clusters)
        }

        return TopicAnalysis(
            clusters=clusters,
            topic_distribution=topic_distribution,
            total_messages=len(messages),
        )

    # ------------------------------------------------------------------
    # Embedding
    # ------------------------------------------------------------------

    def _get_encoder(self):
        """懒加载 embedding 模型。"""
        if self._encoder is not None:
            return self._encoder

        try:
            from sentence_transformers import SentenceTransformer
            import os
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
            self._encoder = SentenceTransformer(self.embedding_model_name, local_files_only=True)
            logger.info("加载 embedding 模型: %s", self.embedding_model_name)
            return self._encoder
        except Exception as e:
            logger.warning("SentenceTransformer 加载失败: %s，尝试在线模式", e)
            try:
                from sentence_transformers import SentenceTransformer
                self._encoder = SentenceTransformer(self.embedding_model_name)
                return self._encoder
            except Exception as e2:
                logger.error("Embedding 模型加载失败: %s", e2)
                return None

    def _get_embeddings(self, texts: List[str]) -> Optional[List[List[float]]]:
        """生成文本 embedding。"""
        encoder = self._get_encoder()
        if encoder is None:
            return None

        try:
            # 分批处理，避免内存溢出
            batch_size = 256
            all_embeddings = []
            for i in range(0, len(texts), batch_size):
                batch = texts[i : i + batch_size]
                embs = encoder.encode(batch, show_progress_bar=False, convert_to_numpy=True)
                all_embeddings.extend(embs.tolist())
            return all_embeddings
        except Exception as e:
            logger.error("Embedding 生成失败: %s", e)
            return None

    # ------------------------------------------------------------------
    # 聚类
    # ------------------------------------------------------------------

    def _cluster(self, embeddings: List[List[float]], k: int) -> List[int]:
        """K-Means 聚类。"""
        try:
            from sklearn.cluster import KMeans
            import numpy as np

            X = np.array(embeddings)
            kmeans = KMeans(n_clusters=k, random_state=42, n_init=10, max_iter=300)
            labels = kmeans.fit_predict(X)
            return labels.tolist()
        except Exception as e:
            logger.error("K-Means 聚类失败: %s", e)
            # fallback: 均匀分配
            return [i % k for i in range(len(embeddings))]

    # ------------------------------------------------------------------
    # 聚类分析
    # ------------------------------------------------------------------

    def _analyze_clusters(
        self,
        messages: List[Any],
        labels: List[int],
        k: int,
    ) -> List[TopicCluster]:
        """分析每个聚类的内容。"""
        clusters = []

        for cluster_id in range(k):
            cluster_msgs = [messages[i] for i in range(len(messages)) if i < len(labels) and labels[i] == cluster_id]

            if not cluster_msgs:
                clusters.append(TopicCluster(topic_id=cluster_id, topic_label=f"话题{cluster_id}"))
                continue

            # 提取关键词
            keywords = self._extract_keywords(cluster_msgs)

            # 选择代表消息（最长的几条）
            sorted_msgs = sorted(cluster_msgs, key=lambda m: len(m.content), reverse=True)
            examples = [m.content[:100] for m in sorted_msgs[:self.max_examples_per_cluster]]

            # 平均消息长度
            avg_len = sum(len(m.content) for m in cluster_msgs) / len(cluster_msgs)

            # 生成话题标签
            topic_label = self._generate_topic_label(keywords, examples)

            # 粗略情绪
            sentiment = self._guess_sentiment(cluster_msgs)

            clusters.append(TopicCluster(
                topic_id=cluster_id,
                topic_label=topic_label,
                count=len(cluster_msgs),
                keywords=keywords[:10],
                example_messages=examples,
                avg_message_length=round(avg_len, 1),
                sentiment_hint=sentiment,
            ))

        return clusters

    def _extract_keywords(self, messages: List[Any]) -> List[str]:
        """提取聚类中的高频关键词。"""
        all_text = " ".join(m.content for m in messages)

        # 简单分词
        words = re.findall(r'[一-鿿]{2,}|[a-zA-Z]{3,}', all_text)

        # 停用词
        stopwords = {
            "的", "了", "是", "在", "我", "你", "他", "她", "它",
            "吗", "吧", "呢", "啊", "哦", "嗯", "好", "不", "也",
            "就", "都", "还", "这", "那", "有", "没", "什么", "怎么",
            "可以", "一个", "没有", "知道", "觉得", "还是", "如果",
            "但是", "因为", "所以", "然后", "或者", "这样", "那样",
            "这个", "那个", "他们", "我们", "你们", "自己", "一下",
            "真的", "应该", "可能", "已经", "现在", "今天", "明天",
        }

        counter = Counter(w for w in words if w not in stopwords and len(w) >= 2)
        return [w for w, _ in counter.most_common(10)]

    def _generate_topic_label(self, keywords: List[str], examples: List[str]) -> str:
        """根据关键词和示例生成话题标签。"""
        if not keywords:
            return "其他"

        # 简单规则：取前 2~3 个关键词组合
        top_kw = keywords[:3]
        return "、".join(top_kw)

    def _guess_sentiment(self, messages: List[Any]) -> str:
        """粗略猜测聚类的情绪倾向。"""
        all_text = " ".join(m.content for m in messages)

        positive_words = ["开心", "高兴", "喜欢", "爱", "好", "棒", "厉害", "哈哈", "嘿嘿", "太好了", "不错"]
        negative_words = ["难过", "伤心", "生气", "烦", "讨厌", "累", "难受", "焦虑", "担心", "害怕", "糟糕"]
        neutral_words = ["嗯", "好的", "知道了", "行", "可以"]

        pos = sum(all_text.count(w) for w in positive_words)
        neg = sum(all_text.count(w) for w in negative_words)
        neu = sum(all_text.count(w) for w in neutral_words)

        if pos > neg and pos > neu:
            return "积极"
        elif neg > pos and neg > neu:
            return "消极"
        elif neu > 0:
            return "中性"
        return "混合"

    def to_dict(self, analysis: TopicAnalysis) -> Dict[str, Any]:
        """转为可序列化的字典。"""
        return {
            "total_messages": analysis.total_messages,
            "num_clusters": len(analysis.clusters),
            "topic_distribution": analysis.topic_distribution,
            "clusters": [
                {
                    "id": c.topic_id,
                    "label": c.topic_label,
                    "count": c.count,
                    "keywords": c.keywords,
                    "examples": c.example_messages[:3],
                    "avg_length": c.avg_message_length,
                    "sentiment": c.sentiment_hint,
                }
                for c in analysis.clusters
            ],
        }
