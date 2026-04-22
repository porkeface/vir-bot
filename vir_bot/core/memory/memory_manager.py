"""记忆管理器：融合 Wiki + 短期 + 长期记忆"""

from __future__ import annotations

import re
from typing import Optional

from vir_bot.core.memory.long_term import LongTermMemory, MemoryRecord
from vir_bot.core.memory.memory_updater import MemoryUpdater
from vir_bot.core.memory.memory_writer import MemoryWriter
from vir_bot.core.memory.question_memory import QuestionMemory, QuestionMemoryIndex
from vir_bot.core.memory.semantic_store import SemanticMemoryRecord, SemanticMemoryStore
from vir_bot.core.memory.short_term import ShortTermMemory
from vir_bot.core.wiki import CharacterProfile, WikiKnowledgeBase
from vir_bot.utils.logger import logger


class MemoryManager:
    """统一管理 Wiki + 短期 + 长期记忆

    优先级顺序：
    1. Wiki 人设库（最高优先级，是"宪法"）
    2. 长期记忆（根据重要性排序）
    3. 短期记忆（最近的对话）
    """

    def __init__(
        self,
        short_term: ShortTermMemory,
        long_term: LongTermMemory,
        semantic_store: SemanticMemoryStore,
        memory_writer: MemoryWriter,
        memory_updater: MemoryUpdater,
        window_size: int = 10,
        wiki_dir: str = "./data/wiki",
    ):
        self.short_term = short_term
        self.long_term = long_term
        self.semantic_store = semantic_store
        self.memory_writer = memory_writer
        self.memory_updater = memory_updater
        self.window_size = window_size
        self.wiki = WikiKnowledgeBase(wiki_dir=wiki_dir)
        self.current_character: Optional[CharacterProfile] = None

        self.question_index = QuestionMemoryIndex()
        self.questions: dict[str, QuestionMemory] = {}

        logger.info("MemoryManager initialized with Wiki + RAG hybrid system")

    async def set_character(self, character_name: str) -> bool:
        """设置当前角色"""
        char_profile = await self.wiki.load_character(character_name)
        if char_profile:
            self.current_character = char_profile
            logger.info(f"Current character set to: {character_name}")
            return True

        logger.warning(f"Character not found: {character_name}")
        return False

    async def add_interaction(
        self,
        user_msg: str,
        assistant_msg: str,
        memory_type: str = "conversation",
        importance: float = 0.5,
        entities: list[str] | None = None,
        metadata: dict | None = None,
    ) -> None:
        """添加一轮对话到记忆。"""
        metadata = metadata or {}

        if memory_type == "conversation":
            q_info = self._classify_question(user_msg)
            question_mem = QuestionMemory(
                question_text=user_msg,
                question_type=q_info["question_type"],
                topic=q_info["topic"],
                entities=q_info["entities"],
                answer_text=assistant_msg,
                answer_summary=assistant_msg[:150],
                key_points=[],
                importance=importance,
                user_id=metadata.get("user_id", ""),
            )
            self.questions[question_mem.id] = question_mem
            self.question_index.add(question_mem)
            logger.debug(
                f"Question classified: topic={q_info['topic']}, type={q_info['question_type']}"
            )

        self.short_term.add_user(user_msg, metadata)
        self.short_term.add_assistant(assistant_msg, metadata)

        if self.long_term and metadata.get("index_long_term", True):
            if entities is None:
                entities = self._extract_entities(user_msg)

            combined_content = f"用户说：{user_msg}\n助手回复：{assistant_msg}"
            await self.long_term.add(
                content=combined_content,
                type=memory_type,
                importance=importance,
                entities=entities,
                metadata={
                    "memory_source": "conversation",
                    "user_preview": user_msg[:100],
                    "assistant_preview": assistant_msg[:100],
                    **metadata,
                },
            )

        await self._write_semantic_memory(
            user_msg=user_msg,
            assistant_msg=assistant_msg,
            metadata=metadata,
        )

    async def _write_semantic_memory(
        self,
        *,
        user_msg: str,
        assistant_msg: str,
        metadata: dict,
    ) -> None:
        user_id = metadata.get("user_id")
        if not user_id:
            return

        operations = await self.memory_writer.extract(
            user_msg=user_msg,
            assistant_msg=assistant_msg,
            user_id=user_id,
        )
        if not operations:
            operations = self._fallback_fact_operations(user_msg)

        if not operations:
            return

        self.memory_updater.apply(
            user_id=user_id,
            operations=operations,
            source_message_id=metadata.get("msg_id"),
        )

    def _extract_entities(self, text: str) -> list[str]:
        """从文本中提取简单实体。"""
        entities = []

        if "生日" in text or "纪念日" in text:
            entities.append("生日")
        if "工作" in text or "项目" in text:
            entities.append("工作")
        if "喜欢" in text or "爱" in text:
            entities.append("喜好")
        if "难过" in text or "伤心" in text or "失落" in text:
            entities.append("情绪")

        return entities

    def _extract_fact_memories(self, user_msg: str) -> list[dict]:
        """从用户消息中抽取可复用的长期事实记忆。"""
        text = user_msg.strip()
        if not text:
            return []

        extracted: list[dict] = []
        pattern_groups = [
            (
                "preference",
                [
                    (
                        r"我(?:最)?喜欢(?:吃|喝|玩|看|听|用)?(?P<value>[^，。！？；\n]+)",
                        "用户喜欢{value}",
                        0.88,
                        ["喜好"],
                    ),
                    (
                        r"我(?:不喜欢|不爱|讨厌)(?P<value>[^，。！？；\n]+)",
                        "用户不喜欢{value}",
                        0.92,
                        ["喜好", "厌恶"],
                    ),
                ],
            ),
            (
                "habit",
                [
                    (
                        r"我(?:经常|总是|平时会|通常会)(?P<value>[^，。！？；\n]+)",
                        "用户经常{value}",
                        0.75,
                        ["习惯"],
                    ),
                    (
                        r"我每天(?P<value>[^，。！？；\n]+)",
                        "用户每天{value}",
                        0.82,
                        ["习惯"],
                    ),
                ],
            ),
            (
                "personality",
                [
                    (
                        r"我叫(?P<value>[^，。！？；\n]+)",
                        "用户的名字是{value}",
                        0.95,
                        ["身份"],
                    ),
                    (
                        r"我来自(?P<value>[^，。！？；\n]+)",
                        "用户来自{value}",
                        0.90,
                        ["身份", "地点"],
                    ),
                    (
                        r"我是(?P<value>[^，。！？；\n]{1,20})",
                        "用户是{value}",
                        0.72,
                        ["身份"],
                    ),
                ],
            ),
            (
                "event",
                [
                    (
                        r"(?P<value>今天[^。！？\n]{2,40})",
                        "用户提到近况：{value}",
                        0.68,
                        ["事件", "今天"],
                    ),
                    (
                        r"(?P<value>昨天[^。！？\n]{2,40})",
                        "用户提到近况：{value}",
                        0.70,
                        ["事件", "昨天"],
                    ),
                    (
                        r"(?P<value>最近[^。！？\n]{2,40})",
                        "用户提到近况：{value}",
                        0.66,
                        ["事件", "最近"],
                    ),
                ],
            ),
        ]

        for memory_type, patterns in pattern_groups:
            for pattern, template, score, extra_entities in patterns:
                for match in re.finditer(pattern, text):
                    value = self._normalize_fact_value(match.group("value"))
                    if not value:
                        continue
                    extracted.append(
                        {
                            "content": template.format(value=value),
                            "type": memory_type,
                            "importance": score,
                            "entities": sorted(set(extra_entities + self._extract_entities(value))),
                            "namespace": self._semantic_namespace(memory_type, template),
                            "predicate": self._semantic_predicate(memory_type, template),
                            "object": value,
                        }
                    )

        deduped: list[dict] = []
        seen_contents: set[str] = set()
        for item in extracted:
            if item["content"] in seen_contents:
                continue
            seen_contents.add(item["content"])
            deduped.append(item)

        return deduped

    def _fallback_fact_operations(self, user_msg: str):
        """LLM writer 失败时的保底抽取，仅接受明显陈述句。"""
        if self._looks_like_question(user_msg):
            return []

        from vir_bot.core.memory.memory_writer import MemoryOperation

        operations = []
        for fact_memory in self._extract_fact_memories(user_msg):
            operations.append(
                MemoryOperation(
                    op="ADD",
                    namespace=fact_memory["namespace"],
                    subject="user",
                    predicate=fact_memory["predicate"],
                    object=fact_memory["object"],
                    confidence=fact_memory["importance"],
                    source_text=user_msg,
                )
            )
        return operations

    def _normalize_fact_value(self, value: str) -> str:
        value = value.strip(" ，。！？；,.!?;:")
        value = re.sub(r"\s+", "", value)
        if len(value) < 2:
            return ""
        if value in {"这个", "那个", "这些", "那些"}:
            return ""
        return value

    def _looks_like_question(self, text: str) -> bool:
        normalized = text.strip()
        question_signals = [
            "？",
            "?",
            "吗",
            "呢",
            "什么",
            "哪些",
            "哪个",
            "记得",
            "还记不记得",
            "能不能",
            "是不是",
        ]
        return any(signal in normalized for signal in question_signals)

    def _semantic_namespace(self, memory_type: str, template: str) -> str:
        if memory_type == "preference":
            return "profile.preference"
        if memory_type == "habit":
            return "profile.habit"
        if memory_type == "personality":
            return "profile.identity"
        if memory_type == "event":
            return "profile.event"
        return f"profile.{memory_type}"

    def _semantic_predicate(self, memory_type: str, template: str) -> str:
        mapping = {
            ("preference", "用户喜欢{value}"): "likes",
            ("preference", "用户不喜欢{value}"): "dislikes",
            ("habit", "用户经常{value}"): "often_does",
            ("habit", "用户每天{value}"): "daily_does",
            ("personality", "用户的名字是{value}"): "name_is",
            ("personality", "用户来自{value}"): "from",
            ("personality", "用户是{value}"): "is",
            ("event", "用户提到近况：{value}"): "mentioned_event",
        }
        return mapping.get((memory_type, template), memory_type)

    def _classify_question(self, user_msg: str) -> dict:
        """简单的基于规则的问题分类。"""
        question_type = "other"

        if any(prefix in user_msg for prefix in ["什么是", "是什么", "什么叫"]):
            question_type = "what"
        elif any(prefix in user_msg for prefix in ["如何", "怎么", "怎样"]):
            question_type = "how"
        elif "为什么" in user_msg:
            question_type = "why"
        elif any(word in user_msg for word in ["举例", "例子", "比如", "例如"]):
            question_type = "example"

        topic_keywords = {
            "时间管理": ["时间", "日程", "规划", "效率", "番茄", "时间块"],
            "OKR": ["OKR", "目标", "关键结果", "KPI", "KR"],
            "Python": ["Python", "编程", "代码", "脚本", "函数", "类"],
            "项目管理": ["项目", "管理", "团队", "协作", "敏捷"],
            "阅读": ["书", "阅读", "文章", "笔记"],
        }

        topic = "general"
        for potential_topic, keywords in topic_keywords.items():
            if any(kw in user_msg for kw in keywords):
                topic = potential_topic
                break

        entities = []
        if "我" in user_msg or "你" in user_msg:
            entities.append("对话")
        if topic != "general":
            entities.append(topic)

        return {
            "question_type": question_type,
            "topic": topic,
            "entities": entities,
        }

    async def search_questions(
        self,
        query: str,
        top_k: int = 5,
        user_id: str | None = None,
    ) -> list[QuestionMemory]:
        """搜索相关问题（倒排索引 + 最近记录回退）。"""
        q_info = self._classify_question(query)
        indexed_ids: set[str] = set()

        if q_info["topic"] != "general":
            indexed_ids.update(self.question_index.find_by_topic(q_info["topic"], limit=10))
        for entity in q_info["entities"]:
            indexed_ids.update(self.question_index.find_by_entity(entity, limit=10))
        if q_info["question_type"] != "other":
            indexed_ids.update(self.question_index.find_by_type(q_info["question_type"], limit=10))
        if not indexed_ids:
            indexed_ids.update(self.question_index.find_recent(limit=top_k * 2))

        results = []
        for qid in indexed_ids:
            question = self.questions.get(qid)
            if question is None:
                continue
            if user_id and question.user_id and question.user_id != user_id:
                continue
            results.append(question)

        results.sort(key=lambda q: (q.importance, q.timestamp), reverse=True)
        return results[:top_k]

    async def get_question(self, question_id: str) -> QuestionMemory | None:
        """获取单个问题记忆。"""
        return self.questions.get(question_id)

    async def search_long_term(
        self,
        query: str,
        top_k: int | None = None,
        memory_types: list[str] | None = None,
        min_importance: float = 0.0,
        user_id: str | None = None,
    ) -> list[MemoryRecord]:
        """多维度搜索长期记忆。"""
        if not self.long_term:
            return []

        filters: dict = {}
        if memory_types:
            filters["type"] = memory_types
        if min_importance > 0:
            filters["importance_min"] = min_importance
        if user_id:
            filters["user_id"] = user_id

        return await self.long_term.search(
            query=query,
            top_k=top_k,
            filters=filters if filters else None,
            sort_by="importance",
        )

    def search_semantic_memory(
        self,
        user_id: str,
        query: str,
        top_k: int = 5,
        namespaces: list[str] | None = None,
    ) -> list[SemanticMemoryRecord]:
        return self.semantic_store.search(
            user_id=user_id,
            query=query,
            top_k=top_k,
            namespaces=namespaces,
        )

    def list_semantic_memory(
        self,
        user_id: str,
        namespaces: list[str] | None = None,
    ) -> list[SemanticMemoryRecord]:
        return self.semantic_store.list_by_user(user_id=user_id, namespaces=namespaces)

    def get_context_messages(self, n: int | None = None) -> list[dict]:
        """获取当前上下文消息（短期记忆窗口）。"""
        return self.short_term.to_messages(n=n or self.window_size)

    async def build_enhanced_system_prompt(
        self,
        current_query: str,
        base_system_prompt: str,
        character_name: str | None = None,
        include_wiki: bool = True,
        include_personality_memory: bool = True,
        include_habit_memory: bool = True,
        long_term_top_k: int = 5,
        user_id: str | None = None,
    ) -> str:
        """构建增强系统提示词，默认主动检索相关记忆。"""
        if character_name and character_name != getattr(self.current_character, "name", None):
            await self.set_character(character_name)

        sections = []

        if include_wiki and self.current_character:
            sections.append(self.current_character.get_system_prompt_injection())
        sections.append(base_system_prompt)

        proactive_memories = await self._gather_proactive_memories(
            current_query=current_query,
            long_term_top_k=long_term_top_k,
            include_personality_memory=include_personality_memory,
            include_habit_memory=include_habit_memory,
            user_id=user_id,
        )
        semantic_memories: list[SemanticMemoryRecord] = []
        if user_id:
            semantic_memories = self.search_semantic_memory(
                user_id=user_id,
                query=current_query,
                top_k=4,
            )
        if semantic_memories:
            semantic_lines = "\n".join(
                f"- [{record.namespace}] {record.object}"
                for record in semantic_memories
            )
            sections.append(f"【用户事实记忆】\n{semantic_lines}")
        if proactive_memories:
            memory_lines = "\n".join(
                f"- [{record.type}] {self._format_memory_content(record.content)}"
                for record in proactive_memories
            )
            sections.append(f"【已检索到的记忆】\n{memory_lines}")

        if self.questions:
            related_questions = await self.search_questions(
                query=current_query,
                top_k=2,
                user_id=user_id,
            )
            if related_questions:
                qa_lines = []
                for q in related_questions:
                    qa_lines.append(f"- 用户之前问过：{q.question_text}")
                    qa_lines.append(f"  回答概要：{q.answer_summary}")
                sections.append("【相关历史问答】\n" + "\n".join(qa_lines))

        sections.append(
            "【重要提醒】\n"
            "- 你必须始终保持上述人设\n"
            "- 在对话中自然地展现这些特点，不要生硬\n"
            "- 回答涉及用户事实、偏好、过往事件时，优先依据已检索到的记忆\n"
            "- 如果记忆里没有明确依据，直接说你现在没有记住，不要编造"
        )

        return "\n\n".join(section for section in sections if section)

    async def _gather_proactive_memories(
        self,
        current_query: str,
        long_term_top_k: int,
        include_personality_memory: bool,
        include_habit_memory: bool,
        user_id: str | None = None,
    ) -> list[MemoryRecord]:
        if not self.long_term:
            return []

        fact_types = ["preference", "event", "conversation"]
        if include_personality_memory:
            fact_types.append("personality")
        if include_habit_memory:
            fact_types.append("habit")

        memory_groups = [
            await self.search_long_term(
                query=current_query,
                top_k=long_term_top_k,
                memory_types=fact_types,
                min_importance=0.25,
                user_id=user_id,
            ),
            await self.search_long_term(
                query=current_query,
                top_k=max(2, long_term_top_k // 2),
                memory_types=["preference", "habit"],
                min_importance=0.5,
                user_id=user_id,
            ),
            await self.get_recent_memories(n=min(3, long_term_top_k), user_id=user_id),
        ]

        merged: list[MemoryRecord] = []
        seen_ids: set[str] = set()
        for group in memory_groups:
            for record in group:
                if record.id in seen_ids:
                    continue
                seen_ids.add(record.id)
                merged.append(record)

        merged.sort(key=lambda item: (item.importance, item.timestamp), reverse=True)
        return merged[:long_term_top_k]

    def _format_memory_content(self, content: str) -> str:
        compact = content.replace("\n", " ").strip()
        if len(compact) <= 180:
            return compact
        return compact[:177] + "..."

    async def build_context(
        self,
        current_query: str,
        system_prompt: str,
        character_name: str | None = None,
        long_term_top_k: int = 5,
        user_id: str | None = None,
    ) -> tuple[str, list[dict]]:
        """构建完整 AI 上下文。"""
        if character_name and character_name != getattr(self.current_character, "name", None):
            await self.set_character(character_name)

        enhanced_system = await self.build_enhanced_system_prompt(
            current_query=current_query,
            base_system_prompt=system_prompt,
            character_name=character_name,
            long_term_top_k=long_term_top_k,
            user_id=user_id,
        )
        conversation = self.get_context_messages()
        return enhanced_system, conversation

    async def get_personality_keywords(self) -> list[str]:
        """获取当前角色的性格关键词。"""
        if not self.current_character:
            return []
        return self.current_character.get_personality_keywords()

    async def search_related_memories(
        self,
        query: str,
        top_k: int = 5,
        user_id: str | None = None,
    ) -> dict:
        """搜索相关的所有记忆并分类。"""
        result = {}
        types = ["personality", "habit", "preference", "event", "conversation"]

        for mem_type in types:
            result[mem_type] = await self.search_long_term(
                query=query,
                top_k=top_k,
                memory_types=[mem_type],
                user_id=user_id,
            )

        return result

    async def get_high_importance_memories(
        self,
        min_importance: float = 0.7,
        top_k: int = 10,
    ) -> list[MemoryRecord]:
        """获取高重要性的记忆。"""
        if not self.long_term:
            return []

        return await self.long_term.search_by_importance(
            min_importance=min_importance,
            top_k=top_k,
        )

    async def get_recent_memories(
        self,
        n: int = 10,
        user_id: str | None = None,
    ) -> list[MemoryRecord]:
        """获取最近的记忆。"""
        if not self.long_term:
            return []

        records = await self.long_term.get_recent(n=max(n * 2, n))
        if user_id:
            records = [r for r in records if r.metadata.get("user_id") == user_id]
        return records[:n]

    async def clear_all(self) -> None:
        """清空所有记忆。"""
        self.short_term.clear()
        if self.long_term:
            await self.long_term.clear()
        self.semantic_store.clear()
        self.wiki.clear_cache()
        self.question_index.clear()
        self.questions.clear()
        logger.info("All memories cleared")

    @property
    def short_term_count(self) -> int:
        """短期记忆数量。"""
        return len(self.short_term)

    async def long_term_count(self) -> int:
        """长期记忆数量。"""
        if not self.long_term:
            return 0
        return await self.long_term.count()

    async def get_memory_stats(self) -> dict:
        """获取记忆系统统计信息。"""
        short_count = self.short_term_count
        long_count = await self.long_term_count()

        long_term_stats = {}
        if self.long_term:
            long_term_stats = await self.long_term.get_stats()

        return {
            "short_term": {
                "count": short_count,
            },
            "long_term": long_term_stats,
            "semantic_count": self.semantic_store.count(),
            "question_count": len(self.questions),
            "character": self.current_character.name if self.current_character else None,
        }

    async def export_memory_backup(self) -> dict:
        """导出记忆备份。"""
        backup = {
            "short_term": self.short_term.to_messages(),
            "long_term": {},
            "character": self.current_character.name if self.current_character else None,
        }

        if self.long_term:
            backup["long_term"] = await self.long_term.export_to_dict()

        return backup
