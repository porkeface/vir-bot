"""Buffer Zone — 累积消息，达到阈值后批量处理记忆提取。

借鉴 memobase 的设计：不要每条消息都调用 LLM 提取记忆，
而是累积到一定 token 量后一次性批量处理，降低 LLM 成本和噪声。

用法：
    buffer = MemoryBufferZone(ai_provider, memory_writer, token_threshold=1024)
    await buffer.add(user_msg, assistant_msg, user_id)
    # 当累积消息达到阈值时自动批量提取并写入
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from vir_bot.utils.logger import logger

if TYPE_CHECKING:
    from vir_bot.core.ai_provider import AIProvider
    from vir_bot.core.memory.memory_writer import MemoryWriter
    from vir_bot.core.memory.memory_updater import MemoryUpdater


def _estimate_tokens(text: str) -> int:
    """粗略估算 token 数（中文约 1.5 字/token，英文约 4 字符/token）。

    不需要精确，只用于判断是否达到阈值。
    """
    cn_chars = sum(1 for c in text if "一" <= c <= "鿿")
    other_chars = len(text) - cn_chars
    return int(cn_chars / 1.5 + other_chars / 4)


@dataclass
class BufferedMessage:
    """缓冲区中的一条消息对。"""

    user_msg: str
    assistant_msg: str
    user_id: str
    timestamp: float = field(default_factory=time.time)
    token_estimate: int = 0

    def __post_init__(self) -> None:
        if self.token_estimate == 0:
            self.token_estimate = _estimate_tokens(self.user_msg + self.assistant_msg)


class MemoryBufferZone:
    """记忆缓冲区：累积消息，达到 token 阈值后批量提取。

    核心思想（借鉴 memobase）：
    - 每条消息先存入缓冲区，不立即调用 LLM
    - 当缓冲区 token 总量超过阈值时，触发批量处理
    - 一次性让 LLM 从多轮对话中提取重要事实
    - 减少 LLM 调用次数，降低噪声，提高提取质量
    """

    def __init__(
        self,
        ai_provider: "AIProvider",
        memory_writer: "MemoryWriter",
        memory_updater: "MemoryUpdater | None" = None,
        token_threshold: int = 1024,
        max_buffer_age_seconds: float = 600.0,  # 10 分钟
    ):
        self._ai = ai_provider
        self._writer = memory_writer
        self._updater = memory_updater
        self._token_threshold = token_threshold
        self._max_age = max_buffer_age_seconds

        # user_id -> 消息列表
        self._buffers: dict[str, list[BufferedMessage]] = {}
        self._token_counts: dict[str, int] = {}
        self._last_flush: dict[str, float] = {}

        self._lock = asyncio.Lock()

    async def add(
        self,
        user_msg: str,
        assistant_msg: str,
        user_id: str = "default",
    ) -> None:
        """添加一条消息对到缓冲区。达到阈值时自动触发批量处理。"""
        async with self._lock:
            msg = BufferedMessage(
                user_msg=user_msg,
                assistant_msg=assistant_msg,
                user_id=user_id,
            )

            if user_id not in self._buffers:
                self._buffers[user_id] = []
                self._token_counts[user_id] = 0
                self._last_flush[user_id] = time.time()

            self._buffers[user_id].append(msg)
            self._token_counts[user_id] += msg.token_estimate

            logger.debug(
                f"[BufferZone] user={user_id} "
                f"tokens={self._token_counts[user_id]}/{self._token_threshold} "
                f"msgs={len(self._buffers[user_id])}"
            )

            # 检查是否需要刷新
            should_flush = self._token_counts[user_id] >= self._token_threshold
            # 也检查时间超时
            age = time.time() - self._last_flush[user_id]
            if age > self._max_age and self._buffers[user_id]:
                should_flush = True

        if should_flush:
            await self.flush(user_id)

    async def flush(self, user_id: str = "default") -> list[dict]:
        """立即处理指定用户的缓冲区。返回提取的记忆操作。"""
        async with self._lock:
            messages = self._buffers.get(user_id, [])
            if not messages:
                return []

            # 取出并清空缓冲区
            self._buffers[user_id] = []
            self._token_counts[user_id] = 0
            self._last_flush[user_id] = time.time()

        # 批量提取（不持锁，避免阻塞其他用户）
        try:
            operations = await self._batch_extract(messages, user_id)
            logger.info(
                f"[BufferZone] 批量提取完成: user={user_id} "
                f"msgs={len(messages)} ops={len(operations)}"
            )
            return operations
        except Exception as e:
            logger.error(f"[BufferZone] 批量提取失败: {e}")
            return []

    async def _batch_extract(
        self, messages: list[BufferedMessage], user_id: str
    ) -> list[dict]:
        """从多条消息中批量提取记忆操作并写入存储。"""
        if not messages:
            return []

        # 将前面的对话作为上下文，最后一条作为主对话
        last = messages[-1]
        if len(messages) > 1:
            context_lines: list[str] = []
            for msg in messages[:-1]:
                context_lines.append(f"用户: {msg.user_msg}")
                context_lines.append(f"助手: {msg.assistant_msg}")
            context = "\n".join(context_lines)
            # 将上下文拼到 user_msg 前面，让 LLM 看到完整对话
            user_msg = f"[之前的对话]\n{context}\n\n[当前用户消息]\n{last.user_msg}"
        else:
            user_msg = last.user_msg

        # 使用 MemoryWriter 公开 API 提取操作（内部会调用 LLM）
        operations = await self._writer.extract(
            user_msg=user_msg,
            assistant_msg=last.assistant_msg,
            user_id=user_id,
        )

        if not operations:
            return []

        # 写入存储（通过 memory_updater）
        if self._updater:
            try:
                await self._updater.apply(
                    user_id=user_id,
                    operations=operations,
                )
                logger.info(f"[BufferZone] 写入 {len(operations)} 条记忆")
            except Exception as e:
                logger.error(f"[BufferZone] 批量写入失败: {e}")

        return [
            {
                "op": op.op,
                "namespace": op.namespace,
                "subject": op.subject,
                "predicate": op.predicate,
                "object": op.object,
                "confidence": op.confidence,
            }
            for op in operations
        ]

    def get_buffer_stats(self) -> dict[str, dict]:
        """获取缓冲区统计信息。"""
        stats = {}
        for user_id, msgs in self._buffers.items():
            stats[user_id] = {
                "message_count": len(msgs),
                "token_count": self._token_counts.get(user_id, 0),
                "token_threshold": self._token_threshold,
                "last_flush_age_seconds": round(
                    time.time() - self._last_flush.get(user_id, time.time()), 1
                ),
            }
        return stats
