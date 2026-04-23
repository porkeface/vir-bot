"""检索路由器 - 使用大模型理解问题意图，路由到不同记忆层。"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from vir_bot.utils.logger import logger

if TYPE_CHECKING:
    from vir_bot.core.ai_provider import AIProvider
    from vir_bot.core.memory.episodic_store import EpisodicMemoryStore, EpisodeRecord
    from vir_bot.core.memory.long_term import LongTermMemory, MemoryRecord
    from vir_bot.core.memory.question_memory import QuestionMemory, QuestionMemoryStore
    from vir_bot.core.memory.semantic_store import SemanticMemoryRecord, SemanticMemoryStore


@dataclass
class RetrievalResult:
    """检索结果。"""

    query: str
    user_id: str

    semantic_records: list["SemanticMemoryRecord"] = field(default_factory=list)
    episodic_records: list["EpisodeRecord"] = field(default_factory=list)
    question_records: list["QuestionMemory"] = field(default_factory=list)
    long_term_records: list["MemoryRecord"] = field(default_factory=list)

    query_type: str = "general"
    retrieval_time_ms: float = 0.0

    def has_results(self) -> bool:
        return bool(
            self.semantic_records
            or self.episodic_records
            or self.question_records
            or self.long_term_records
        )

    def to_context_string(self) -> str:
        sections = []

        if self.semantic_records:
            sections.append(self._format_semantic())

        if self.episodic_records:
            sections.append(self._format_episodic())

        if self.question_records:
            sections.append(self._format_questions())

        if self.long_term_records:
            sections.append(self._format_long_term())

        if not sections:
            return ""

        return "\n\n".join(sections)

    def _format_semantic(self) -> str:
        lines = ["【用户事实记忆】"]

        ns_labels = {
            "profile.identity": "身份信息",
            "profile.preference": "偏好",
            "profile.habit": "习惯",
            "profile.event": "事件",
        }
        pred_map = {
            "name_is": "名字",
            "from": "来自",
            "is": "身份",
            "likes": "喜欢",
            "dislikes": "讨厌",
            "often_does": "经常做",
            "daily_does": "每天做",
            "mentioned_event": "提到过",
        }

        grouped: dict[str, list[str]] = {}
        for record in self.semantic_records:
            label = ns_labels.get(record.namespace, record.namespace)
            grouped.setdefault(label, []).append(
                f"- 用户{pred_map.get(record.predicate, record.predicate)}：{record.object}"
            )

        for label in ["身份信息", "偏好", "习惯", "事件"]:
            entries = grouped.pop(label, None)
            if entries:
                lines.append(f"【{label}】")
                lines.extend(entries)

        return "\n".join(lines)

    def _format_episodic(self) -> str:
        lines = ["【事件记忆】"]

        for record in self.episodic_records:
            time_str = self._format_time(record.start_at)
            lines.append(f"- [{time_str}] {record.summary}")

        return "\n".join(lines)

    def _format_questions(self) -> str:
        lines = ["【问题记忆】"]

        for question in self.question_records:
            time_str = self._format_time(question.timestamp)
            lines.append(f"- [{time_str}] 问：{question.question_text}")
            if question.answer_summary:
                lines.append(f"  答：{question.answer_summary[:100]}")

        return "\n".join(lines)

    def _format_long_term(self) -> str:
        lines = ["【对话记忆】"]

        for record in self.long_term_records:
            content = record.content.replace("\n", " ").strip()
            if len(content) > 150:
                content = content[:147] + "..."
            lines.append(f"- {content}")

        return "\n".join(lines)

    def _format_time(self, timestamp: float) -> str:
        import datetime

        dt = datetime.datetime.fromtimestamp(timestamp)
        now = datetime.datetime.now()

        if dt.date() == now.date():
            return f"今天 {dt.strftime('%H:%M')}"
        elif (now - dt).days == 1:
            return f"昨天 {dt.strftime('%H:%M')}"
        elif (now - dt).days < 7:
            return f"{(now - dt).days}天前 {dt.strftime('%H:%M')}"
        else:
            return dt.strftime("%m-%d %H:%M")


CLASSIFY_PROMPT = """你是一个意图分类器。分析用户问题，判断需要查询哪种记忆。

用户问题：{query}

请返回JSON格式：
{{
    "query_type": "preference|identity|habit|episodic|question|conversation|general",
    "needs_memory_lookup": true/false,
    "reason": "简短理由"
}}

query_type 说明：
- preference: 查询用户偏好（喜欢/讨厌什么）
- identity: 查询用户身份（名字/来自哪里/职业）
- habit: 查询用户习惯（经常做什么/作息）
- episodic: 查询时间相关事件（昨天/今天/最近发生了什么）
- question: 查询之前问过的问题
- conversation: 查询之前的对话内容
- general: 普通对话，不需要查记忆

needs_memory_lookup: 是否需要查询记忆库（当用户问"记不记得""我之前说过"等时为true）

只返回JSON，不要其他内容。"""


class RetrievalRouter:
    """检索路由器 - 使用大模型理解问题意图。"""

    def __init__(
        self,
        semantic_store: "SemanticMemoryStore",
        episodic_store: "EpisodicMemoryStore",
        question_store: "QuestionMemoryStore",
        long_term: "LongTermMemory | None" = None,
        ai_provider: "AIProvider | None" = None,
    ):
        self.semantic_store = semantic_store
        self.episodic_store = episodic_store
        self.question_store = question_store
        self.long_term = long_term
        self.ai_provider = ai_provider

        self._intent_cache: dict[str, dict] = {}
        self._cache_ttl = 300

        logger.info("RetrievalRouter initialized with AI-powered intent classification")

    def set_ai_provider(self, ai_provider: "AIProvider") -> None:
        self.ai_provider = ai_provider

    async def classify_query_async(self, query: str) -> dict:
        if query in self._intent_cache:
            cached = self._intent_cache[query]
            if time.time() - cached.get("_timestamp", 0) < self._cache_ttl:
                return cached

        if self.ai_provider:
            try:
                result = await self._classify_with_ai(query)
                if result:
                    result["_timestamp"] = time.time()
                    self._intent_cache[query] = result
                    if len(self._intent_cache) > 1000:
                        self._intent_cache.pop(next(iter(self._intent_cache)))
                    return result
            except Exception as e:
                logger.warning(f"AI classification failed, fallback to rules: {e}")

        return self._classify_with_rules(query)

    async def _classify_with_ai(self, query: str) -> dict | None:
        if not self.ai_provider:
            return None

        try:
            prompt = CLASSIFY_PROMPT.format(query=query)
            response = await self.ai_provider.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
            )

            content = response.content.strip()
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

            result = json.loads(content)

            if "query_type" not in result:
                result["query_type"] = "general"
            if "needs_memory_lookup" not in result:
                result["needs_memory_lookup"] = result["query_type"] != "general"

            logger.debug(f"AI classified query '{query[:30]}...' as {result['query_type']}")
            return result

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse AI response: {e}")
            return None
        except Exception as e:
            logger.warning(f"AI classification error: {e}")
            return None

    def _classify_with_rules(self, query: str) -> dict:
        """AI 分类失败时的保守回退（删除所有硬编码关键词短路）。
        回退策略：检测到任何个人相关语义信号 → 认为需要查记忆，
        由后续检索层面的向量匹配决定相关性。"""
        query_lower = query.lower().strip()

        if not query_lower:
            return {"query_type": "general", "needs_memory_lookup": False}

        # 宽泛的个人/话题触发：几乎所有涉及「我」「你」「什么」「哪里」的都查记忆
        broad_signals = [
            "我", "你", "他", "她",
            "什么", "哪些", "哪个", "谁", "怎", "哪", "为",
            "喜欢", "讨厌", "爱好", "习惯", "每天", "平时", "经常",
            "名字", "叫", "来自", "哪里", "人", "身份", "职业",
            "昨天", "今天", "明天", "最近", "做", "去", "来", "会",
            "记得", "记得吗", "还记得", "不记得", "忘了", "说过",
            "之前", "上次", "以前", "聊过", "提过", "发生过",
            "能", "要", "想", "觉得",
        ]
        if any(s in query_lower for s in broad_signals):
            return {"query_type": "general", "needs_memory_lookup": True}

        return {"query_type": "general", "needs_memory_lookup": False}
    def classify_query(self, query: str) -> str:
        result = self._classify_with_rules(query)
        return result.get("query_type", "general")

    async def retrieve(
        self,
        query: str,
        user_id: str,
        top_k: int = 5,
    ) -> RetrievalResult:
        start_time = time.time()

        classification = await self.classify_query_async(query)
        query_type = classification.get("query_type", "general")

        logger.debug(f"Query classified as: {query_type}")

        result = RetrievalResult(
            query=query,
            user_id=user_id,
            query_type=query_type,
        )

        if query_type == "preference":
            result.semantic_records = self.semantic_store.list_by_user(
                user_id=user_id,
                namespaces=["profile.preference"],
            )[:top_k]

        elif query_type == "identity":
            result.semantic_records = self.semantic_store.list_by_user(
                user_id=user_id,
                namespaces=["profile.identity"],
            )[:top_k]

        elif query_type == "habit":
            result.semantic_records = self.semantic_store.list_by_user(
                user_id=user_id,
                namespaces=["profile.habit"],
            )[:top_k]

        elif query_type == "episodic":
            result.episodic_records = self._retrieve_episodic(query, user_id, top_k)

        elif query_type == "question":
            result.question_records = self._retrieve_questions(query, user_id, top_k)

        elif query_type == "conversation":
            result.long_term_records = await self._retrieve_long_term(
                query, user_id, top_k
            )

        else:
            result.semantic_records = self.semantic_store.search(
                user_id=user_id,
                query=query,
                top_k=top_k,
            )

            if self.long_term:
                result.long_term_records = await self.long_term.search(
                    query=query,
                    top_k=max(2, top_k // 2),
                    filters={"user_id": user_id},
                )

        result.retrieval_time_ms = (time.time() - start_time) * 1000
        return result

    def _retrieve_episodic(
        self,
        query: str,
        user_id: str,
        top_k: int,
    ) -> list["EpisodeRecord"]:
        query_lower = query.lower()

        if "今天" in query_lower:
            return self.episodic_store.get_today(user_id)[:top_k]

        if "昨天" in query_lower:
            return self.episodic_store.get_yesterday(user_id)[:top_k]

        if "最近" in query_lower:
            return self.episodic_store.get_recent(user_id, hours=72, top_k=top_k)

        return self.episodic_store.search(
            user_id=user_id,
            query=query,
            top_k=top_k,
        )

    def _retrieve_questions(
        self,
        query: str,
        user_id: str,
        top_k: int,
    ) -> list["QuestionMemory"]:
        questions = self.question_store.list_by_user(user_id=user_id)

        query_lower = query.lower()
        if "今天" in query_lower:
            import datetime

            today_start = datetime.datetime.now().replace(
                hour=0, minute=0, second=0, microsecond=0
            ).timestamp()
            questions = [q for q in questions if q.timestamp >= today_start]

        return questions[:top_k]

    async def _retrieve_long_term(
        self,
        query: str,
        user_id: str,
        top_k: int,
    ) -> list["MemoryRecord"]:
        if not self.long_term:
            return []

        return await self.long_term.search(
            query=query,
            top_k=top_k,
            filters={"user_id": user_id},
        )

    async def retrieve_for_context(
        self,
        query: str,
        user_id: str,
        force_lookup: bool = False,
    ) -> str | None:
        classification = await self.classify_query_async(query)
        query_type = classification.get("query_type", "general")
        needs_lookup = classification.get("needs_memory_lookup", False)

        if not force_lookup and not needs_lookup and query_type == "general":
            return None

        result = await self.retrieve(query, user_id, top_k=6)

        if not result.has_results():
            if force_lookup or needs_lookup:
                return (
                    "【记忆检索结果】\n"
                    "- 已查询记忆库，但没有找到相关记录。\n"
                    "- 如果用户在问\"记不记得\"\"有没有发生过\"或某项个人事实，"
                    "请直接回答不知道、还没记住，或目前没有这条记录。\n"
                    "- 不要补全细节，不要猜测。"
                )
            return None

        context = result.to_context_string()
        if context:
            return (
                f"【记忆检索结果】\n"
                f"- 以下内容是回答当前问题前刚从记忆系统取回的结果。\n"
                f"- 只能基于这些结果陈述用户事实，不要编造。\n\n"
                f"{context}\n\n"
                f"- 如果以上结果里没有对应信息，就直接说不知道或没查到。"
            )

        return None
