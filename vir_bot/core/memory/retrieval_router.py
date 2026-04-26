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
    graph_edges: list["GraphEdge"] = field(default_factory=list)

    query_type: str = "general"
    retrieval_time_ms: float = 0.0

    def has_results(self) -> bool:
        return bool(
            self.semantic_records
            or self.episodic_records
            or self.question_records
            or self.long_term_records
            or self.graph_edges
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

        if self.graph_edges:
            sections.append(self._format_graph())

        if not sections:
            return ""

        return "\n\n".join(sections)

    def _format_graph(self) -> str:
        """格式化图关系结果。"""
        lines = ["【关系记忆】"]
        for edge in self.graph_edges:
            lines.append(f"- {edge.subject} -[{edge.predicate}]-> {edge.object}")
        return "\n".join(lines)

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

必须以纯JSON格式返回，不要有任何其他内容：
{{
    "query_type": "preference",
    "needs_memory_lookup": true,
    "reason": "用户询问偏好"
}}

query_type 可选值（必须选一个）：
- "time_query": 时间查询（现在几点、今天几号、现在什么日期等）
- "preference": 查询用户偏好（喜欢/讨厌什么）
- "identity": 查询用户身份（名字/来自哪里/职业）
- "habit": 查询用户习惯（经常做什么/作息）
- "episodic": 查询时间相关事件（昨天/今天/最近发生了什么）
- "question": 查询之前问过的问题
- "conversation": 查询之前的对话内容
- "general": 普通对话，不需要查记忆

needs_memory_lookup: 布尔值，当用户的问题需要查询记忆库时为 true。

输出要求：只输出一个合法的JSON对象，不要 markdown 代码块，不要解释。"""


class RetrievalRouter:
    """检索路由器 - 使用大模型理解问题意图。"""

    def __init__(
        self,
        semantic_store: "SemanticMemoryStore",
        episodic_store: "EpisodicMemoryStore",
        question_store: "QuestionMemoryStore",
        long_term: "LongTermMemory | None" = None,
        ai_provider: "AIProvider | None" = None,
        features: dict | None = None,
    ):
        self.semantic_store = semantic_store
        self.episodic_store = episodic_store
        self.question_store = question_store
        self.long_term = long_term
        self.ai_provider = ai_provider
        self._features = features or {}

        self._intent_cache: dict[str, dict] = {}
        self._cache_ttl = 300
        self._reranker: "ReRanker | None" = None
        self._composer: "MemoryComposer | None" = None
        self._graph_store: "MemoryGraphStore | None" = None

        self._init_reranker()
        self._init_composer()
        self._init_graph_store()

        logger.info("RetrievalRouter initialized with AI-powered intent classification")

    def _init_graph_store(self) -> None:
        """初始化图存储（如果启用）。"""
        if not self._features.get("graph", {}).get("enabled", False):
            return
        try:
            from .graph_store import MemoryGraphStore

            config = self._features.get("graph", {})
            persist_path = config.get("persist_path", "./data/memory/memory_graph.json")
            self._graph_store = MemoryGraphStore(persist_path=persist_path)
            logger.info("MemoryGraphStore initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize MemoryGraphStore: {e}")

    def _init_reranker(self) -> None:
        """初始化 Re-Ranker（如果启用）。"""
        if not self._features.get("reranker", {}).get("enabled", False):
            return
        try:
            from vir_bot.core.memory.enhancements.reranker import ReRanker
            self._reranker = ReRanker(self._features["reranker"])
            logger.info("ReRanker initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize ReRanker: {e}")

    def _init_composer(self) -> None:
        """初始化 Memory Composer（如果启用）。"""
        if not self._features.get("composer", {}).get("enabled", False):
            return
        try:
            from vir_bot.core.memory.enhancements.composer import MemoryComposer
            self._composer = MemoryComposer(self._features["composer"])
            logger.info("MemoryComposer initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize MemoryComposer: {e}")

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
        """AI 分类失败时的保守回退。
        尽量保守：不添加人类定义的关键词列表，让后续的并行检索处理。
        只处理空查询这种明确情况。"""
        if not query.strip():
            return {"query_type": "general", "needs_memory_lookup": False}
        # 保守回退：交给并行检索处理
        return {"query_type": "general", "needs_memory_lookup": False}
    def classify_query(self, query: str) -> str:
        result = self._classify_with_rules(query)
        return result.get("query_type", "general")

    async def retrieve(
        self,
        query: str,
        user_id: str,
        top_k: int = 5,
        force_multi_search: bool = False,
    ) -> RetrievalResult:
        start_time = time.time()

        classification = await self.classify_query_async(query)
        query_type = classification.get("query_type", "general")
        needs_lookup = classification.get("needs_memory_lookup", False)

        logger.debug(f"Query classified as: {query_type}, needs_lookup: {needs_lookup}")

        result = RetrievalResult(
            query=query,
            user_id=user_id,
            query_type=query_type,
        )

        # 多路并行检索：始终并行查多个记忆层，信任 AI 语义理解
        import asyncio

        tasks = []
        task_names = []

        # 语义记忆：始终查（结构化事实，最快）
        tasks.append(self._search_semantic(query, user_id, top_k))
        task_names.append("semantic")

        # 问题记忆：查用户问过的问题
        tasks.append(self._search_questions(query, user_id, top_k))
        task_names.append("questions")

        # 事件记忆：查时间相关事件
        tasks.append(self._search_episodic(query, user_id, top_k))
        task_names.append("episodic")

        # 长期记忆：向量搜索
        if self.long_term:
            tasks.append(self._search_long_term(query, user_id, top_k))
            task_names.append("long_term")

        # 并行执行
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 合并结果
        for name, res in zip(task_names, results):
            if isinstance(res, Exception):
                logger.warning(f"Search {name} failed: {res}")
                continue
            if name == "semantic":
                result.semantic_records = res
            elif name == "questions":
                result.question_records = res
            elif name == "episodic":
                result.episodic_records = res
            elif name == "long_term":
                result.long_term_records = res

        # 图查询（如果启用）
        if self._graph_store:
            graph_results = self._graph_store.query(subject=f"user:{user_id}")
            result.graph_edges = graph_results

        # Re-Ranker：对检索结果重排序
        if self._reranker:
            result = await self._reranker.rerank(query, result)

        result.retrieval_time_ms = (time.time() - start_time) * 1000
        return result

    async def _search_semantic(self, query, user_id, top_k):
        """搜索语义记忆。"""
        return self.semantic_store.search(
            user_id=user_id,
            query=query,
            top_k=top_k,
        )

    async def _search_questions(self, query, user_id, top_k):
        """搜索问题记忆。"""
        questions = self.question_store.list_by_user(user_id=user_id)
        # 简单的相关性排序（按时间戳倒序）
        scored = [(q.timestamp, q) for q in questions]
        scored.sort(reverse=True)
        return [q for _, q in scored[:top_k]]

    async def _search_episodic(self, query, user_id, top_k):
        """搜索事件记忆。"""
        return self.episodic_store.search(
            user_id=user_id,
            query=query,
            top_k=top_k,
        )

    async def _search_long_term(self, query, user_id, top_k):
        """搜索长期记忆。"""
        if not self.long_term:
            return []
        return await self.long_term.search(
            query=query,
            top_k=top_k,
            filters={"user_id": user_id} if user_id else None,
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

        # 时间查询快速返回 None（AI 会从系统提示词获取时间）
        if query_type == "time_query":
            return None

        # 信任 AI 分类器的判断，不再额外加硬编码规则
        if not force_lookup and not needs_lookup and query_type == "general":
            return None

        # 使用多路检索
        result = await self.retrieve(query, user_id, top_k=6, force_multi_search=True)

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

        # 使用 Composer 或默认格式化
        if self._composer:
            context = self._composer.compose(result)
        else:
            context = result.to_context_string()

        if context:
            type_hints = {
                "preference": "（这是用户偏好相关的记忆）",
                "identity": "（这是用户身份相关的记忆）",
                "habit": "（这是用户习惯相关的记忆）",
                "episodic": "（这是时间相关的事件记忆）",
                "question": "（这是之前问过的问题）",
                "conversation": "（这是之前的对话记录）",
            }
            hint = type_hints.get(query_type, "")
            return (
                f"【记忆检索结果】{hint}\n"
                f"- 以下内容是回答当前问题前刚从记忆系统取回的结果。\n"
                f"- 只能基于这些结果陈述用户事实，不要编造。\n\n"
                f"{context}\n\n"
                f"- 如果以上结果里没有对应信息，就直接说不知道或没查到。"
            )

        return None
