"""结构化语义记忆存储。"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from vir_bot.utils.logger import logger


@dataclass
class SemanticMemoryRecord:
    """用户事实型长期记忆。"""

    memory_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str = ""
    namespace: str = ""
    subject: str = "user"
    predicate: str = ""
    object: str = ""
    confidence: float = 0.7
    source_text: str = ""
    source_message_id: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    is_active: bool = True

    @classmethod
    def from_dict(cls, data: dict) -> "SemanticMemoryRecord":
        return cls(**data)

    def to_dict(self) -> dict:
        return asdict(self)


class SemanticMemoryStore:
    """基于本地 JSON 的结构化语义记忆存储。"""

    def __init__(self, persist_path: str = "./data/memory/semantic_memory.json"):
        self.persist_path = Path(persist_path)
        self.persist_path.parent.mkdir(parents=True, exist_ok=True)
        self._records: dict[str, SemanticMemoryRecord] = {}
        self._load()
        logger.info(f"SemanticMemoryStore initialized: path={self.persist_path}")

    def _load(self) -> None:
        if not self.persist_path.exists():
            return

        try:
            data = json.loads(self.persist_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning(f"Semantic memory file is invalid JSON: {self.persist_path}")
            return

        for item in data.get("records", []):
            record = SemanticMemoryRecord.from_dict(item)
            self._records[record.memory_id] = record

    def _save(self) -> None:
        payload = {
            "version": "1.0",
            "updated_at": time.time(),
            "records": [record.to_dict() for record in self._records.values()],
        }
        self.persist_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def upsert(
        self,
        *,
        user_id: str,
        namespace: str,
        subject: str,
        predicate: str,
        object_value: str,
        confidence: float,
        source_text: str,
        source_message_id: str | None = None,
        replace_predicate: bool = False,
    ) -> SemanticMemoryRecord:
        """按 user_id + namespace + predicate + object 执行幂等写入。"""
        normalized_object = object_value.strip()
        if not normalized_object:
            raise ValueError("object_value must not be empty")
        if self._is_invalid_object(normalized_object):
            raise ValueError(f"invalid semantic memory object: {normalized_object}")

        existing = self._find_existing(
            user_id=user_id,
            namespace=namespace,
            predicate=predicate,
            object_value=normalized_object,
        )

        now = time.time()
        if existing is not None:
            existing.confidence = max(existing.confidence, confidence)
            existing.source_text = source_text
            existing.source_message_id = source_message_id
            existing.updated_at = now
            existing.is_active = True
            self._save()
            return existing

        if replace_predicate:
            self.deactivate(
                user_id=user_id,
                namespace=namespace,
                predicate=predicate,
            )

        # 只有完全是疑问词的情况才跳过写入
        if self._is_pure_question_word(normalized_object):
            logger.warning(
                f"Skipping semantic memory write: object is pure question word: {normalized_object}"
            )
            raise ValueError(
                f"invalid semantic memory object (pure question word): {normalized_object}"
            )

        record = SemanticMemoryRecord(
            user_id=user_id,
            namespace=namespace,
            subject=subject,
            predicate=predicate,
            object=normalized_object,
            confidence=confidence,
            source_text=source_text,
            source_message_id=source_message_id,
            created_at=now,
            updated_at=now,
        )
        self._records[record.memory_id] = record
        self._save()
        return record

    def search(
        self,
        *,
        user_id: str,
        query: str,
        top_k: int = 5,
        namespaces: list[str] | None = None,
    ) -> list[SemanticMemoryRecord]:
        """按简单词项匹配搜索结构化记忆。"""
        tokens = self._tokenize(query)
        inferred_namespaces = self._infer_namespaces(query)
        results: list[tuple[float, SemanticMemoryRecord]] = []

        for record in self._records.values():
            if not record.is_active or record.user_id != user_id:
                continue
            if namespaces and record.namespace not in namespaces:
                continue

            haystack = " ".join(
                [
                    record.namespace,
                    record.predicate,
                    record.object,
                    record.source_text,
                ]
            ).lower()

            score = record.confidence
            if inferred_namespaces and record.namespace in inferred_namespaces:
                score += 2.0

            if tokens:
                for token in tokens:
                    if token in haystack:
                        score += 1.0
                if record.object.lower() in query.lower():
                    score += 1.0
            else:
                score += 0.1

            if score > record.confidence:
                results.append((score, record))

        results.sort(key=lambda item: (item[0], item[1].updated_at), reverse=True)
        return [record for _, record in results[:top_k]]

    def list_by_user(
        self,
        user_id: str,
        namespaces: list[str] | None = None,
    ) -> list[SemanticMemoryRecord]:
        records = [
            record
            for record in self._records.values()
            if record.is_active and record.user_id == user_id
        ]
        if namespaces:
            records = [record for record in records if record.namespace in namespaces]
        records.sort(key=lambda item: item.updated_at, reverse=True)
        return records

    def clear(self) -> None:
        self._records.clear()
        self._save()

    def deactivate(
        self,
        *,
        user_id: str,
        namespace: str,
        predicate: str,
        object_value: str | None = None,
    ) -> None:
        changed = False
        for record in self._records.values():
            if not record.is_active:
                continue
            if (
                record.user_id != user_id
                or record.namespace != namespace
                or record.predicate != predicate
            ):
                continue
            if object_value is not None and record.object != object_value:
                continue
            record.is_active = False
            record.updated_at = time.time()
            changed = True

        if changed:
            self._save()

    def count(self, user_id: str | None = None) -> int:
        if user_id is None:
            return len([record for record in self._records.values() if record.is_active])
        return len(
            [
                record
                for record in self._records.values()
                if record.is_active and record.user_id == user_id
            ]
        )

    def _find_existing(
        self,
        *,
        user_id: str,
        namespace: str,
        predicate: str,
        object_value: str,
    ) -> SemanticMemoryRecord | None:
        for record in self._records.values():
            if not record.is_active:
                continue
            if (
                record.user_id == user_id
                and record.namespace == namespace
                and record.predicate == predicate
                and record.object == object_value
            ):
                return record
        return None

    def cleanup_invalid_records(self) -> int:
        """清理明确无效的记录（仅在手动调用时）"""
        removed = 0
        for record in self._records.values():
            if not record.is_active:
                continue
            # 只清理那些完全是疑问词的记录
            if self._is_pure_question_word(record.object):
                record.is_active = False
                record.updated_at = time.time()
                removed += 1
        if removed:
            self._save()
        return removed

    def _tokenize(self, text: str) -> list[str]:
        normalized = text.lower().strip()
        if not normalized:
            return []
        manual_tokens = []
        keyword_groups = [
            "喜欢",
            "讨厌",
            "不喜欢",
            "爱吃",
            "喜欢吃",
            "每天",
            "经常",
            "习惯",
            "名字",
            "叫",
            "来自",
            "哪里",
            "昨天",
            "今天",
            "最近",
        ]
        for keyword in keyword_groups:
            if keyword in normalized:
                manual_tokens.append(keyword)

        split_tokens = [
            token
            for token in normalized.replace("，", " ").replace("。", " ").replace("？", " ").split()
            if token
        ]
        return list(dict.fromkeys(manual_tokens + split_tokens))

    def _infer_namespaces(self, query: str) -> set[str]:
        normalized = query.lower()
        namespaces: set[str] = set()
        if any(keyword in normalized for keyword in ["喜欢", "讨厌", "爱吃", "不喜欢", "吃什么"]):
            namespaces.add("profile.preference")
        if any(keyword in normalized for keyword in ["习惯", "经常", "每天", "平时"]):
            namespaces.add("profile.habit")
        if any(keyword in normalized for keyword in ["名字", "叫", "来自", "哪里人", "是谁"]):
            namespaces.add("profile.identity")
        if any(keyword in normalized for keyword in ["昨天", "今天", "最近", "上次"]):
            namespaces.add("profile.event")
        return namespaces

    def _is_invalid_object(self, value: str) -> bool:
        """检查是否是无效的记忆对象（例如纯问句词）"""
        lowered = value.strip().lower()
        # 只有当 object 完全就是这些疑问词时才认为无效
        pure_question_words = {"什么", "哪些", "哪个", "吗", "呢", "吧", "么", "啥"}
        if lowered in pure_question_words:
            return True
        # 如果含有问号，但不是只有问号，也是无效的
        if value.strip() in ["?", "？"]:
            return True
        return False

    def _is_pure_question_word(self, value: str) -> bool:
        """检查是否是纯疑问词"""
        lowered = value.strip().lower()
        pure_question_words = {"什么", "哪些", "哪个", "吗", "呢", "吧", "么", "啥"}
        return lowered in pure_question_words
