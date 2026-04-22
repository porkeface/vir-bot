"""记忆管理器：融合 Wiki + 短期 + 长期记忆"""

from __future__ import annotations

import asyncio
from typing import Optional

from vir_bot.core.memory.long_term import LongTermMemory, MemoryRecord
from vir_bot.core.memory.short_term import MemoryEntry, ShortTermMemory
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
        window_size: int = 10,
        wiki_dir: str = "./data/wiki",
    ):
        self.short_term = short_term
        self.long_term = long_term
        self.window_size = window_size
        self.wiki = WikiKnowledgeBase(wiki_dir=wiki_dir)
        self.current_character: Optional[CharacterProfile] = None

        logger.info("MemoryManager initialized with Wiki + RAG hybrid system")

    async def set_character(self, character_name: str) -> bool:
        """设置当前角色"""
        char_profile = await self.wiki.load_character(character_name)
        if char_profile:
            self.current_character = char_profile
            logger.info(f"Current character set to: {character_name}")
            return True
        else:
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
        """添加一轮对话到记忆

        Args:
            user_msg: 用户消息
            assistant_msg: 助手回复
            memory_type: 记忆类型 (event/preference/personality/conversation/habit)
            importance: 重要性 (0.0-1.0)
            entities: 相关实体 (如 ["张三", "生日"])
            metadata: 其他元数据
        """
        # 添加到短期记忆
        self.short_term.add_user(user_msg, metadata)
        self.short_term.add_assistant(assistant_msg, metadata)

        # 添加到长期记忆
        if self.long_term and metadata is None or metadata.get("index_long_term", True):
            combined_content = f"用户说：{user_msg}\n助手回复：{assistant_msg}"

            # 自动检测实体（简单实现）
            if entities is None:
                entities = self._extract_entities(user_msg)

            await self.long_term.add(
                content=combined_content,
                type=memory_type,
                importance=importance,
                entities=entities,
                metadata={
                    "user_preview": user_msg[:100],
                    "assistant_preview": assistant_msg[:100],
                    **(metadata or {}),
                },
            )

    def _extract_entities(self, text: str) -> list[str]:
        """从文本中提取简单的实体（可扩展为 NLP）"""
        entities = []

        # 简单的模式匹配
        if "生日" in text or "纪念日" in text:
            entities.append("生日")
        if "工作" in text or "项目" in text:
            entities.append("工作")
        if "喜欢" in text or "爱" in text:
            entities.append("喜好")
        if "难过" in text or "伤心" in text or "失落" in text:
            entities.append("情绪")

        return entities

    async def search_long_term(
        self,
        query: str,
        top_k: int | None = None,
        memory_types: list[str] | None = None,
        min_importance: float = 0.0,
    ) -> list[MemoryRecord]:
        """多维度搜索长期记忆

        Args:
            query: 查询文本
            top_k: 返回数量
            memory_types: 记忆类型过滤 (如 ["personality", "habit"])
            min_importance: 最小重要性阈值

        Returns:
            记忆记录列表
        """
        if not self.long_term:
            return []

        filters = {}
        if memory_types:
            filters["type"] = memory_types
        if min_importance > 0:
            filters["importance_min"] = min_importance

        return await self.long_term.search(
            query=query,
            top_k=top_k,
            filters=filters if filters else None,
            sort_by="importance",
        )

    def get_context_messages(self) -> list[dict]:
        """获取当前上下文消息（短期记忆窗口）"""
        return self.short_term.to_messages(n=self.window_size)

    async def build_enhanced_system_prompt(
        self,
        current_query: str,
        base_system_prompt: str,
        character_name: str | None = None,
        include_wiki: bool = True,
        include_personality_memory: bool = True,
        include_habit_memory: bool = True,
        long_term_top_k: int = 5,
    ) -> str:
        """构建增强的系统提示词 - 结合 Wiki + RAG

        优先级：
        1. Wiki 人设定义（最高）
        2. 相关的 personality/habit 记忆（按重要性）
        3. 基础系统提示词

        Args:
            current_query: 当前用户查询
            base_system_prompt: 基础系统提示词
            character_name: 角色名称（自动使用当前角色）
            include_wiki: 是否包含 Wiki 定义
            include_personality_memory: 是否包含人设记忆
            include_habit_memory: 是否包含习惯记忆
            long_term_top_k: 长期记忆检索数量

        Returns:
            增强后的系统提示词
        """
        sections = []

        # 1. Wiki 人设定义（最高优先级）
        if include_wiki and self.current_character:
            wiki_injection = self.current_character.get_system_prompt_injection()
            sections.append(wiki_injection)
        else:
            sections.append(base_system_prompt)

        # 2. 相关记忆（按类型检索）
        memory_sections = []

        if include_personality_memory or include_habit_memory:
            types_to_search = []
            if include_personality_memory:
                types_to_search.append("personality")
            if include_habit_memory:
                types_to_search.append("habit")

            if types_to_search:
                relevant_memories = await self.search_long_term(
                    query=current_query,
                    top_k=long_term_top_k,
                    memory_types=types_to_search,
                    min_importance=0.3,
                )

                if relevant_memories:
                    memory_text = "\n".join([f"- {m.content}" for m in relevant_memories])
                    memory_sections.append(f"【相关记忆】\n{memory_text}")

        if memory_sections:
            sections.append("\n\n".join(memory_sections))

        # 3. 重要提醒
        sections.append(
            "【重要提醒】\n"
            "- 你必须始终保持上述人设\n"
            "- 在对话中自然地展现这些特点，不要生硬\n"
            "- 如果用户的话题涉及你的喜好或禁忌，要有相应的情感反应"
        )

        return "\n\n".join(sections)

    async def build_context(
        self,
        current_query: str,
        system_prompt: str,
        character_name: str | None = None,
        long_term_top_k: int = 5,
    ) -> tuple[str, list[dict]]:
        """构建完整 AI 上下文（向后兼容的简化版本）

        Returns:
            (增强的系统提示词, 对话消息列表)
        """
        # 如果指定了角色名，设置当前角色
        if character_name and character_name != getattr(self.current_character, "name", None):
            await self.set_character(character_name)

        # 构建增强的系统提示词
        enhanced_system = await self.build_enhanced_system_prompt(
            current_query=current_query,
            base_system_prompt=system_prompt,
            long_term_top_k=long_term_top_k,
        )

        # 对话历史
        conversation = self.get_context_messages()

        return enhanced_system, conversation

    async def get_personality_keywords(self) -> list[str]:
        """获取当前角色的性格关键词"""
        if not self.current_character:
            return []
        return self.current_character.get_personality_keywords()

    async def search_related_memories(
        self,
        query: str,
        top_k: int = 5,
    ) -> dict:
        """搜索相关的所有记忆并分类

        Returns:
            {
                "personality": [...],  # 人设相关
                "habit": [...],        # 习惯相关
                "preference": [...],   # 喜好相关
                "event": [...],        # 事件相关
                "conversation": [...], # 对话相关
            }
        """
        result = {}

        types = ["personality", "habit", "preference", "event", "conversation"]

        for mem_type in types:
            memories = await self.search_long_term(
                query=query,
                top_k=top_k,
                memory_types=[mem_type],
            )
            result[mem_type] = memories

        return result

    async def get_high_importance_memories(
        self,
        min_importance: float = 0.7,
        top_k: int = 10,
    ) -> list[MemoryRecord]:
        """获取高重要性的记忆"""
        if not self.long_term:
            return []

        return await self.long_term.search_by_importance(
            min_importance=min_importance,
            top_k=top_k,
        )

    async def get_recent_memories(
        self,
        n: int = 10,
    ) -> list[MemoryRecord]:
        """获取最近的记忆"""
        if not self.long_term:
            return []

        return await self.long_term.get_recent(n=n)

    async def clear_all(self) -> None:
        """清空所有记忆"""
        self.short_term.clear()
        if self.long_term:
            await self.long_term.clear()
        self.wiki.clear_cache()
        logger.info("All memories cleared")

    @property
    def short_term_count(self) -> int:
        """短期记忆数量"""
        return len(self.short_term)

    async def long_term_count(self) -> int:
        """长期记忆数量"""
        if not self.long_term:
            return 0
        return await self.long_term.count()

    async def get_memory_stats(self) -> dict:
        """获取记忆系统统计信息"""
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
            "character": self.current_character.name if self.current_character else None,
        }

    async def export_memory_backup(self) -> dict:
        """导出记忆备份"""
        backup = {
            "short_term": self.short_term.to_messages(),
            "long_term": {},
            "character": self.current_character.name if self.current_character else None,
        }

        if self.long_term:
            backup["long_term"] = await self.long_term.export_to_dict()

        return backup
