"""长期记忆：ChromaDB 向量检索 - 增强版

支持多维度存储和检索：
- 记忆类型 (event/preference/personality/conversation/habit)
- 重要性权重 (0.0-1.0)
- 时间戳 (用于时序推理)
- 实体标签 (知识图谱)
- 情感维度 (初级情感分析)
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

import chromadb
from chromadb.config import Settings

from vir_bot.utils.logger import logger

# =============================================================================
# 数据模型
# =============================================================================


@dataclass
class MemoryRecord:
    """增强的记忆记录"""

    id: str
    content: str

    # 记忆分类维度
    type: Literal["event", "preference", "personality", "conversation", "habit"] = "conversation"

    # 重要性权重 (0.0-1.0，用于排序和优先级)
    importance: float = 0.5

    # 时间戳 (用于时序推理和去重)
    timestamp: float = field(default_factory=time.time)

    # 实体标签 (知识图谱初级版，用于关键词扩展检索)
    entities: list[str] = field(default_factory=list)

    # 情感维度 (初级情感分析)
    sentiment: dict = field(default_factory=dict)

    # 其他元数据
    metadata: dict = field(default_factory=dict)

    def to_chroma_metadata(self) -> dict:
        """转换为 ChromaDB 的 metadata 格式"""
        meta = {
            "type": self.type,
            "importance": self.importance,
            "timestamp": self.timestamp,
            "entities": ",".join(self.entities) if self.entities else "",
            "sentiment": str(self.sentiment),
        }
        # 确保 user_id 被存储
        if "user_id" not in meta:
            meta["user_id"] = self.metadata.get("user_id", "")
        meta.update(self.metadata)
        return meta

    @classmethod
    def from_chroma_metadata(cls, record_id: str, content: str, metadata: dict) -> "MemoryRecord":
        """从 ChromaDB 的 metadata 还原"""
        return cls(
            id=record_id,
            content=content,
            type=metadata.get("type", "conversation"),
            importance=float(metadata.get("importance", 0.5)),
            timestamp=float(metadata.get("timestamp", time.time())),
            entities=metadata.get("entities", "").split(",") if metadata.get("entities") else [],
            sentiment=eval(metadata.get("sentiment", "{}")),
            metadata={
                k: v
                for k, v in metadata.items()
                if k not in ["type", "importance", "timestamp", "entities", "sentiment"]
            },
        )


# =============================================================================
# 长期记忆主类
# =============================================================================


class LongTermMemory:
    """基于 ChromaDB 的长期记忆 - 支持多维度查询"""

    def __init__(
        self,
        persist_dir: str = "./data/memory/chroma_db",
        collection_name: str = "persona_memory",
        embedding_model: str = "all-MiniLM-L6-v2",
        top_k: int = 5,
    ):
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.collection_name = collection_name
        self.embedding_model = embedding_model
        self.top_k = top_k

        self._client = chromadb.PersistentClient(
            path=str(self.persist_dir),
            settings=Settings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={
                "description": "vir-bot enhanced long-term memory with multi-dimensional indexing"
            },
        )
        self._embedding_fn = self._load_embedding_fn()
        logger.info(
            f"LongTermMemory initialized: collection={collection_name}, "
            f"model={embedding_model}, top_k={top_k}"
        )

    def _load_embedding_fn(self):
        """懒加载嵌入函数，支持多种回退方案"""
        # 方案1：尝试 SentenceTransformer（如果模型已缓存则离线可用）
        try:
            from sentence_transformers import SentenceTransformer
            # 尝试离线模式
            import os
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
            model = SentenceTransformer(self.embedding_model, local_files_only=True)
            logger.info(f"Loaded embedding model (offline): {self.embedding_model}")
            return model.encode
        except Exception as e:
            logger.warning(f"SentenceTransformer load failed: {e}")

        # 方案2：尝试 Ollama 嵌入 API
        try:
            import requests
            # 从配置读取 Ollama 地址（假设和 AI 配置共享）
            ollama_url = "http://localhost:11434/api/embeddings"
            # 测试连通性
            resp = requests.post(ollama_url, json={"model": "qwen2.5:7b", "prompt": "test"}, timeout=2)
            if resp.status_code == 200:
                def ollama_embed(texts):
                    results = []
                    for text in texts:
                        r = requests.post(ollama_url, json={"model": "qwen2.5:7b", "prompt": text})
                        results.append(r.json()["embedding"])
                    return results
                logger.info("Using Ollama embeddings as fallback")
                return ollama_embed
        except Exception as e:
            logger.warning(f"Ollama embedding not available: {e}")

        # 方案3：简单哈希向量化（回退方案，不依赖网络）
        logger.warning("Using simple hash-based embeddings (low quality, offline)")
        import hashlib
        def simple_embed(texts):
            results = []
            for text in texts:
                vec = []
                for i in range(0, 384, 4):
                    data = text + str(i)
                    data_bytes = data.encode('utf-8')
                    h = hashlib.md5(data_bytes).digest()
                    for b in h[:4]:
                        vec.append((b - 128) / 128.0)
                results.append(vec[:384])
            return results
        return simple_embed

    # =================
    # 基础操作
    # =================

    async def add(
        self,
        content: str,
        type: str = "conversation",
        importance: float = 0.5,
        entities: list[str] | None = None,
        sentiment: dict | None = None,
        metadata: dict | None = None,
        user_id: str | None = None,
    ) -> str:
        """添加一条增强的记忆，返回 ID

        Args:
            content: 记忆内容
            type: 记忆类型 (event/preference/personality/conversation/habit)
            importance: 重要性 (0.0-1.0)
            entities: 实体列表 (如 ["张三", "生日"])
            sentiment: 情感字典 (如 {"joy": 0.8, "sadness": 0.1})
            metadata: 其他元数据

        Returns:
            记忆 ID
        """
        record_id = str(uuid.uuid4())
        meta = metadata or {}
        entities = entities or []
        sentiment = sentiment or {}

        # 确保 user_id 被存储
        if user_id:
            meta["user_id"] = user_id

        # 生成 embedding
        emb = self._embedding_fn([content])

        # 构建 ChromaDB metadata
        chroma_meta = {
            "type": type,
            "importance": importance,
            "timestamp": time.time(),
            "entities": ",".join(entities) if entities else "",
            "sentiment": str(sentiment),
            **meta,
        }

        self._collection.add(
            ids=[record_id],
            documents=[content],
            embeddings=emb,
            metadatas=[chroma_meta],
        )

        logger.debug(f"Memory added: id={record_id}, type={type}, importance={importance}")
        return record_id

    async def search(
        self,
        query: str,
        top_k: int | None = None,
        filters: dict | None = None,
        sort_by: str = "relevance",
    ) -> list[MemoryRecord]:
        """多维度记忆搜索

        Args:
            query: 查询文本
            top_k: 返回数量，None 则用默认值
            filters: 过滤条件，如 {"type": ["personality", "habit"]}
            sort_by: 排序方式 ("relevance" | "importance" | "timestamp")

        Returns:
            记忆记录列表
        """
        k = top_k or self.top_k
        emb = self._embedding_fn([query])

        # 构建 ChromaDB where 子句
        where_clause = None
        if filters:
            conditions = []
            if "user_id" in filters:
                conditions.append({"user_id": filters["user_id"]})
            if "type" in filters:
                types = filters["type"]
                if isinstance(types, str):
                    types = [types]
                conditions.append({"type": {"": types}})
            if len(conditions) == 1:
                where_clause = conditions[0]
            elif len(conditions) > 1:
                where_clause = {"": conditions}

        results = self._collection.query(
            query_embeddings=emb,
            n_results=k * 2,  # 先取 2 倍，后续再排序和过滤
            where=where_clause,  # 传递过滤器
            include=["documents", "metadatas", "distances"],
        )

        records = []
        if results["ids"] and results["ids"][0]:
            for i, record_id in enumerate(results["ids"][0]):
                record = MemoryRecord.from_chroma_metadata(
                    record_id=record_id,
                    content=results["documents"][0][i],
                    metadata=results["metadatas"][0][i] or {},
                )
                records.append(record)

        # 应用过滤
        if filters:
            records = self._apply_filters(records, filters)

        # 排序
        if sort_by == "importance":
            records.sort(key=lambda r: r.importance, reverse=True)
        elif sort_by == "timestamp":
            records.sort(key=lambda r: r.timestamp, reverse=True)
        # else: 保持向量相似度排序

        return records[:k]

    async def search_by_type(
        self,
        query: str,
        types: list[str],
        top_k: int | None = None,
        sort_by: str = "importance",
    ) -> list[MemoryRecord]:
        """按类型搜索记忆

        Example:
            # 搜索所有人设和习惯相关的记忆
            results = await memory.search_by_type(
                query="撒娇 性格",
                types=["personality", "habit"],
                top_k=10
            )
        """
        return await self.search(
            query=query,
            top_k=top_k,
            filters={"type": types},
            sort_by=sort_by,
        )

    async def search_by_entity(
        self,
        entity: str,
        top_k: int | None = None,
    ) -> list[MemoryRecord]:
        """按实体搜索记忆

        Example:
            # 搜索所有关于"生日"的记忆
            results = await memory.search_by_entity("生日", top_k=5)
        """
        k = top_k or self.top_k

        # 查询所有记录并在客户端过滤（因为 ChromaDB 不支持精确的数组匹配）
        results = self._collection.query(
            query_embeddings=self._embedding_fn([entity]),
            n_results=k * 5,
            include=["documents", "metadatas"],
        )

        records = []
        if results["ids"] and results["ids"][0]:
            for i, record_id in enumerate(results["ids"][0]):
                metadata = results["metadatas"][0][i] or {}
                entities = metadata.get("entities", "").split(",")

                # 检查实体是否匹配
                if entity in entities:
                    record = MemoryRecord.from_chroma_metadata(
                        record_id=record_id,
                        content=results["documents"][0][i],
                        metadata=metadata,
                    )
                    records.append(record)

                    if len(records) >= k:
                        break

        return records[:k]

    async def search_by_importance(
        self,
        min_importance: float = 0.7,
        top_k: int | None = None,
    ) -> list[MemoryRecord]:
        """获取高重要性的记忆"""
        k = top_k or self.top_k

        # 查询所有记录
        results = self._collection.query(
            query_embeddings=self._embedding_fn(["important"]),
            n_results=self._collection.count(),
            include=["documents", "metadatas"],
        )

        records = []
        if results["ids"] and results["ids"][0]:
            for i, record_id in enumerate(results["ids"][0]):
                record = MemoryRecord.from_chroma_metadata(
                    record_id=record_id,
                    content=results["documents"][0][i],
                    metadata=results["metadatas"][0][i] or {},
                )

                if record.importance >= min_importance:
                    records.append(record)

        # 按重要性倒序排列
        records.sort(key=lambda r: r.importance, reverse=True)
        return records[:k]

    async def delete(self, record_id: str) -> None:
        """删除一条记忆"""
        self._collection.delete(ids=[record_id])
        logger.debug(f"Memory deleted: id={record_id}")

    async def update(
        self,
        record_id: str,
        importance: float | None = None,
        entities: list[str] | None = None,
        sentiment: dict | None = None,
    ) -> None:
        """更新记忆的元数据（不改变内容）"""
        # ChromaDB 不支持直接更新，需要先查询后删除再添加
        # 这里做一个简化版本
        logger.debug(
            f"Memory update not directly supported; consider delete + re-add: id={record_id}"
        )

    async def clear(self) -> None:
        """清空所有记忆"""
        self._client.delete_collection(self.collection_name)
        self._collection = self._client.get_or_create_collection(
            name=self.collection_name,
            metadata={"description": "vir-bot enhanced long-term memory"},
        )
        logger.info("All memories cleared")

    async def count(self) -> int:
        """获取总记忆数"""
        return self._collection.count()

    # =================
    # 辅助方法
    # =================

    def _apply_filters(self, records: list[MemoryRecord], filters: dict) -> list[MemoryRecord]:
        """应用过滤条件。"""
        filtered = records

        if "type" in filters:
            allowed_types = filters["type"]
            if isinstance(allowed_types, str):
                allowed_types = [allowed_types]
            filtered = [r for r in filtered if r.type in allowed_types]

        if "importance_min" in filters:
            min_imp = filters["importance_min"]
            filtered = [r for r in filtered if r.importance >= min_imp]

        if "importance_max" in filters:
            max_imp = filters["importance_max"]
            filtered = [r for r in filtered if r.importance <= max_imp]

        for key, value in filters.items():
            if key in {"type", "importance_min", "importance_max"}:
                continue
            filtered = [r for r in filtered if r.metadata.get(key) == value]

        return filtered

    def _calculate_sentiment_score(self, text: str) -> dict:
        """简单的情感分析（可后续扩展为 NLP 模型）"""
        # 当前是占位符，返回空字典
        # 实际应用中可以集成专门的情感分析库
        return {}

    # =================
    # 统计和管理
    # =================

    async def get_stats(self) -> dict:
        """获取记忆库统计信息"""
        total = await self.count()

        # 按类型统计
        results = self._collection.query(
            query_embeddings=self._embedding_fn(["memory"]),
            n_results=total,
            include=["metadatas"],
        )

        type_count = {}
        importance_sum = 0.0

        if results["metadatas"] and results["metadatas"][0]:
            for metadata in results["metadatas"][0]:
                mem_type = metadata.get("type", "conversation")
                type_count[mem_type] = type_count.get(mem_type, 0) + 1
                importance_sum += float(metadata.get("importance", 0.5))

        avg_importance = importance_sum / max(total, 1)

        return {
            "total_count": total,
            "type_distribution": type_count,
            "average_importance": avg_importance,
        }

    async def get_recent(self, n: int = 10) -> list[MemoryRecord]:
        """获取最近的记忆"""
        results = self._collection.query(
            query_embeddings=self._embedding_fn(["recent"]),
            n_results=min(n * 2, self._collection.count()),
            include=["documents", "metadatas"],
        )

        records = []
        if results["ids"] and results["ids"][0]:
            for i, record_id in enumerate(results["ids"][0]):
                record = MemoryRecord.from_chroma_metadata(
                    record_id=record_id,
                    content=results["documents"][0][i],
                    metadata=results["metadatas"][0][i] or {},
                )
                records.append(record)

        # 按时间戳排序
        records.sort(key=lambda r: r.timestamp, reverse=True)
        return records[:n]

    async def export_to_dict(self) -> dict:
        """导出所有记忆为字典（备份用）"""
        total = await self.count()
        results = self._collection.query(
            query_embeddings=self._embedding_fn(["export"]),
            n_results=total,
            include=["documents", "metadatas"],
        )

        export_data = {
            "version": "1.0",
            "timestamp": time.time(),
            "total": total,
            "memories": [],
        }

        if results["ids"] and results["ids"][0]:
            for i, record_id in enumerate(results["ids"][0]):
                record = MemoryRecord.from_chroma_metadata(
                    record_id=record_id,
                    content=results["documents"][0][i],
                    metadata=results["metadatas"][0][i] or {},
                )
                export_data["memories"].append(
                    {
                        "id": record.id,
                        "content": record.content,
                        "type": record.type,
                        "importance": record.importance,
                        "timestamp": record.timestamp,
                        "entities": record.entities,
                        "sentiment": record.sentiment,
                    }
                )

        return export_data

