"""长期记忆：ChromaDB 向量检索"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path

import chromadb
from chromadb.config import Settings

from vir_bot.utils.logger import logger


@dataclass
class MemoryRecord:
    id: str
    content: str
    metadata: dict = field(default_factory=dict)


class LongTermMemory:
    """基于 ChromaDB 的长期记忆，向量检索"""

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
            metadata={"description": "vir-bot long-term memory"},
        )
        self._embedding_fn = self._load_embedding_fn()
        logger.info(f"LongTermMemory initialized: collection={collection_name}, model={embedding_model}")

    def _load_embedding_fn(self):
        """懒加载 sentence-transformers"""
        try:
            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer(self.embedding_model)
            return model.encode
        except ImportError:
            logger.warning("sentence-transformers not installed, using dummy embeddings")
            return lambda texts: [[0.0] * 384 for _ in texts]

    async def add(self, content: str, metadata: dict | None = None) -> str:
        """添加一条记忆，返回 ID"""
        record_id = str(uuid.uuid4())
        meta = metadata or {}
        emb = self._embedding_fn([content]).tolist()

        self._collection.add(
            ids=[record_id],
            documents=[content],
            embeddings=emb,
            metadatas=[meta],
        )
        return record_id

    async def search(self, query: str, top_k: int | None = None) -> list[MemoryRecord]:
        """向量相似度检索"""
        k = top_k or self.top_k
        emb = self._embedding_fn([query]).tolist()

        results = self._collection.query(
            query_embeddings=emb,
            n_results=k,
            include=["documents", "metadatas"],
        )

        records = []
        if results["ids"] and results["ids"][0]:
            for i, record_id in enumerate(results["ids"][0]):
                records.append(
                    MemoryRecord(
                        id=record_id,
                        content=results["documents"][0][i],
                        metadata=results["metadatas"][0][i] or {},
                    )
                )
        return records

    async def delete(self, record_id: str) -> None:
        """删除一条记忆"""
        self._collection.delete(ids=[record_id])

    async def clear(self) -> None:
        """清空所有记忆"""
        self._client.delete_collection(self.collection_name)
        self._collection = self._client.get_or_create_collection(name=self.collection_name)

    async def count(self) -> int:
        return self._collection.count()