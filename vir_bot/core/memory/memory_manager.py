"""记忆管理器：融合短期 + 长期记忆"""
from __future__ import annotations

from vir_bot.core.memory.short_term import ShortTermMemory, MemoryEntry
from vir_bot.core.memory.long_term import LongTermMemory, MemoryRecord

from vir_bot.utils.logger import logger


class MemoryManager:
    """统一管理短期和长期记忆"""

    def __init__(
        self,
        short_term: ShortTermMemory,
        long_term: LongTermMemory,
        window_size: int = 10,
    ):
        self.short_term = short_term
        self.long_term = long_term
        self.window_size = window_size

    async def add_interaction(self, user_msg: str, assistant_msg: str, metadata: dict | None = None) -> None:
        """添加一轮对话到记忆"""
        self.short_term.add_user(user_msg, metadata)
        self.short_term.add_assistant(assistant_msg, metadata)

        if self.long_term and metadata.get("index_long_term", True):
            await self.long_term.add(
                content=f"用户说：{user_msg}\n助手回复：{assistant_msg}",
                metadata={
                    "user_preview": user_msg[:100],
                    "assistant_preview": assistant_msg[:100],
                    **(metadata or {}),
                },
            )

    async def search_long_term(self, query: str, top_k: int | None = None) -> list[MemoryRecord]:
        """搜索长期记忆"""
        if not self.long_term:
            return []
        return await self.long_term.search(query, top_k)

    def get_context_messages(self) -> list[dict]:
        """获取当前上下文消息（短期记忆窗口）"""
        return self.short_term.to_messages(n=self.window_size)

    async def build_context(
        self,
        current_query: str,
        system_prompt: str,
        long_term_top_k: int = 5,
    ) -> tuple[str, list[dict]]:
        """
        构建完整 AI 上下文。
        Returns: (system_prompt_with_memory, conversation_messages)
        """
        # 搜索相关长期记忆
        relevant_memories = await self.search_long_term(current_query, long_term_top_k)

        # 注入长期记忆到系统提示词
        enhanced_system = system_prompt
        if relevant_memories:
            mem_lines = "\n".join(f"- {m.content}" for m in relevant_memories)
            enhanced_system += f"\n\n[相关记忆]\n{mem_lines}"

        # 对话历史
        conversation = self.get_context_messages()

        return enhanced_system, conversation

    async def clear_all(self) -> None:
        """清空所有记忆"""
        self.short_term.clear()
        if self.long_term:
            await self.long_term.clear()
        logger.info("All memory cleared")

    @property
    def short_term_count(self) -> int:
        return len(self.short_term)

    async def long_term_count(self) -> int:
        if not self.long_term:
            return 0
        return await self.long_term.count()