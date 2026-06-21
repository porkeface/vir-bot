"""基于 SQLite 的语义记忆存储 — 替代 JSON 文件存储。

优势：
- 支持并发读写（asyncio.Lock 保护）
- 更好的查询性能（索引）
- 支持事务
- 更小的存储开销

用法：
    store = SqliteSemanticMemoryStore("./data/memory/semantic.db")
    await store.upsert(user_id="u1", namespace="profile.preference", ...)
    results = await store.search(user_id="u1", query="喜欢什么", top_k=5)
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from vir_bot.utils.logger import logger

if TYPE_CHECKING:
    from vir_bot.core.memory.semantic_store import SemanticMemoryRecord


class SqliteSemanticMemoryStore:
    """基于 SQLite 的语义记忆存储。

    替代 SemanticMemoryStore（JSON 文件），提供更好的性能和并发支持。
    所有写操作通过 asyncio.Lock 串行化，避免 SQLite 并发写入问题。
    """

    def __init__(self, db_path: str = "./data/memory/semantic.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()
        self._init_db()
        logger.info(f"SqliteSemanticMemoryStore initialized: {self.db_path}")

    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接（延迟初始化）。"""
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        return self._conn

    def _init_db(self) -> None:
        """初始化数据库表。"""
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS semantic_memory (
                memory_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                namespace TEXT NOT NULL,
                subject TEXT NOT NULL DEFAULT 'user',
                predicate TEXT NOT NULL,
                object TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0.7,
                source_text TEXT DEFAULT '',
                source_message_id TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                valid_from REAL NOT NULL,
                valid_to REAL,
                previous_version_id TEXT,
                version_number INTEGER NOT NULL DEFAULT 1,
                confidence_history TEXT DEFAULT '[]',
                is_deprecated INTEGER NOT NULL DEFAULT 0,
                deprecation_reason TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_user_id ON semantic_memory(user_id);
            CREATE INDEX IF NOT EXISTS idx_namespace ON semantic_memory(namespace);
            CREATE INDEX IF NOT EXISTS idx_predicate ON semantic_memory(predicate);
            CREATE INDEX IF NOT EXISTS idx_is_active ON semantic_memory(is_active);
            CREATE INDEX IF NOT EXISTS idx_user_active ON semantic_memory(user_id, is_active);
        """)
        conn.commit()

    async def upsert(
        self,
        user_id: str,
        namespace: str,
        subject: str,
        predicate: str,
        object_value: str,
        confidence: float = 0.7,
        source_text: str = "",
        source_message_id: str | None = None,
        replace_predicate: bool = False,
        enable_versioning: bool = False,
    ) -> str:
        """插入或更新记忆。返回 memory_id。所有写操作通过 Lock 串行化。"""
        async with self._lock:
            conn = self._get_conn()
            now = time.time()

            # 查找已有记录
            existing = self._find_by_predicate_sync(
                user_id=user_id, namespace=namespace, predicate=predicate
            )

            if existing and replace_predicate:
                # 更新模式
                if enable_versioning:
                    # 版本管理：标记旧版本（事务保护）
                    old_id = existing.memory_id
                    new_id = str(uuid.uuid4())
                    conn.execute("BEGIN")
                    try:
                        conn.execute(
                            """INSERT INTO semantic_memory
                            (memory_id, user_id, namespace, subject, predicate, object,
                             confidence, source_text, source_message_id,
                             created_at, updated_at, is_active,
                             valid_from, valid_to, previous_version_id, version_number,
                             confidence_history, is_deprecated)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (
                                new_id, user_id, namespace, subject, predicate, object_value,
                                confidence, source_text, source_message_id,
                                now, now, 1,
                                now, None, old_id, (existing.version_number or 1) + 1,
                                json.dumps(existing.confidence_history or []),
                                0,
                            ),
                        )
                        conn.execute(
                            "UPDATE semantic_memory SET valid_to=?, is_active=0 WHERE memory_id=?",
                            (now, old_id),
                        )
                        conn.execute("COMMIT")
                    except Exception:
                        conn.execute("ROLLBACK")
                        raise
                    return new_id
                else:
                    # 直接更新
                    conn.execute(
                        """UPDATE semantic_memory
                        SET object=?, confidence=?, source_text=?, source_message_id=?,
                            updated_at=?
                        WHERE memory_id=?""",
                        (object_value, confidence, source_text, source_message_id, now, existing.memory_id),
                    )
                    conn.commit()
                    return existing.memory_id
            elif existing:
                # 已存在相同 predicate，追加或合并
                return existing.memory_id
            else:
                # 新增
                memory_id = str(uuid.uuid4())
                conn.execute(
                    """INSERT INTO semantic_memory
                    (memory_id, user_id, namespace, subject, predicate, object,
                     confidence, source_text, source_message_id,
                     created_at, updated_at, is_active,
                     valid_from, valid_to, previous_version_id, version_number,
                     confidence_history, is_deprecated)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        memory_id, user_id, namespace, subject, predicate, object_value,
                        confidence, source_text, source_message_id,
                        now, now, 1,
                        now, None, None, 1,
                        json.dumps([]),
                        0,
                    ),
                )
                conn.commit()
                return memory_id

    def _find_by_predicate_sync(
        self,
        user_id: str,
        namespace: str,
        predicate: str,
    ) -> "SemanticMemoryRecord | None":
        """查找指定 predicate 的活跃记忆（内部方法，不加锁）。"""
        conn = self._get_conn()
        row = conn.execute(
            """SELECT * FROM semantic_memory
            WHERE user_id=? AND namespace=? AND predicate=? AND is_active=1
            ORDER BY updated_at DESC LIMIT 1""",
            (user_id, namespace, predicate),
        ).fetchone()

        if not row:
            return None
        return self._row_to_record(row)

    async def find_by_predicate(
        self,
        user_id: str,
        namespace: str,
        predicate: str,
    ) -> "SemanticMemoryRecord | None":
        """查找指定 predicate 的活跃记忆。"""
        async with self._lock:
            return self._find_by_predicate_sync(user_id, namespace, predicate)

    def search(
        self,
        user_id: str,
        query: str,
        top_k: int = 5,
    ) -> list["SemanticMemoryRecord"]:
        """搜索记忆（简单文本匹配，可后续升级为向量搜索）。

        注意：SQLite WAL 模式支持并发读，此方法安全。
        如果需要 async 版本，使用 search_async。
        """
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT * FROM semantic_memory
            WHERE user_id=? AND is_active=1 AND (object LIKE ? OR source_text LIKE ?)
            ORDER BY updated_at DESC LIMIT ?""",
            (user_id, f"%{query}%", f"%{query}%", top_k),
        ).fetchall()

        return [self._row_to_record(row) for row in rows]

    async def search_async(
        self,
        user_id: str,
        query: str,
        top_k: int = 5,
    ) -> list["SemanticMemoryRecord"]:
        """异步搜索记忆（带 Lock 保护）。"""
        async with self._lock:
            return self.search(user_id, query, top_k)

    def list_by_user(
        self,
        user_id: str,
        namespace: str | None = None,
        limit: int = 100,
    ) -> list["SemanticMemoryRecord"]:
        """列出用户的所有活跃记忆。

        注意：SQLite WAL 模式支持并发读，此方法安全。
        如果需要 async 版本，使用 list_by_user_async。
        """
        conn = self._get_conn()
        if namespace:
            rows = conn.execute(
                """SELECT * FROM semantic_memory
                WHERE user_id=? AND namespace=? AND is_active=1
                ORDER BY updated_at DESC LIMIT ?""",
                (user_id, namespace, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM semantic_memory
                WHERE user_id=? AND is_active=1
                ORDER BY updated_at DESC LIMIT ?""",
                (user_id, limit),
            ).fetchall()

        return [self._row_to_record(row) for row in rows]

    async def list_by_user_async(
        self,
        user_id: str,
        namespace: str | None = None,
        limit: int = 100,
    ) -> list["SemanticMemoryRecord"]:
        """异步列出用户记忆（带 Lock 保护）。"""
        async with self._lock:
            return self.list_by_user(user_id, namespace, limit)

    async def deactivate(
        self,
        user_id: str,
        namespace: str,
        predicate: str,
        object_value: str | None = None,
    ) -> None:
        """停用记忆。"""
        async with self._lock:
            conn = self._get_conn()
            if object_value:
                conn.execute(
                    """UPDATE semantic_memory SET is_active=0, updated_at=?
                    WHERE user_id=? AND namespace=? AND predicate=? AND object=?""",
                    (time.time(), user_id, namespace, predicate, object_value),
                )
            else:
                conn.execute(
                    """UPDATE semantic_memory SET is_active=0, updated_at=?
                    WHERE user_id=? AND namespace=? AND predicate=?""",
                    (time.time(), user_id, namespace, predicate),
                )
            conn.commit()

    def _row_to_record(self, row: sqlite3.Row) -> "SemanticMemoryRecord":
        """将数据库行转换为 SemanticMemoryRecord。"""
        from vir_bot.core.memory.semantic_store import SemanticMemoryRecord

        return SemanticMemoryRecord(
            memory_id=row["memory_id"],
            user_id=row["user_id"],
            namespace=row["namespace"],
            subject=row["subject"],
            predicate=row["predicate"],
            object=row["object"],
            confidence=row["confidence"],
            source_text=row["source_text"] or "",
            source_message_id=row["source_message_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            is_active=bool(row["is_active"]),
            valid_from=row["valid_from"],
            valid_to=row["valid_to"],
            previous_version_id=row["previous_version_id"],
            version_number=row["version_number"],
            confidence_history=json.loads(row["confidence_history"] or "[]"),
            is_deprecated=bool(row["is_deprecated"]),
            deprecation_reason=row["deprecation_reason"],
        )

    def close(self) -> None:
        """关闭数据库连接。"""
        if self._conn:
            self._conn.close()
            self._conn = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
