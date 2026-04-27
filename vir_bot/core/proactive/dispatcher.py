"""分发器 - 将生成的主动消息通过平台适配器发送。"""

from __future__ import annotations

import time
from typing import Any, Optional

from vir_bot.utils.logger import logger


class ProactiveDispatcher:
    """消息分发器：通过现有平台适配器发送主动消息。"""

    def __init__(self, pipeline: Any = None, memory_manager: Any = None):
        self.pipeline = pipeline
        self.memory = memory_manager
        self._last_sent: dict[str, float] = {}  # user_id -> timestamp

    async def dispatch(
        self,
        user_id: str,
        message: str,
        channel: str = "default",
    ) -> bool:
        """
        发送主动消息。
        尝试通过pipeline的现有平台适配器发送。
        返回：是否发送成功
        """
        if not message:
            return False

        # 记录发送时间
        self._last_sent[user_id] = time.time()

        # 方式1：通过pipeline发送（如果有）
        if self.pipeline:
            try:
                from vir_bot.core.pipeline import PlatformMessage, Platform, MessageType

                msg = PlatformMessage(
                    platform=Platform.API,  # 使用API作为中继
                    msg_id=f"proactive_{int(time.time())}",
                    user_id=user_id,
                    user_name="系统",
                    content=message,
                    msg_type=MessageType.SYSTEM,
                )

                # 尝试通过pipeline处理（会被路由到对应平台）
                response = await self.pipeline.process(msg)
                if response:
                    logger.info(f"主动消息已分发: {message[:30]}...")
                    return True

            except Exception as e:
                logger.warning(f"通过pipeline分发失败: {e}")

        # 方式2：直接写入记忆（作为fallback，让下次对话时提及）
        if self.memory:
            try:
                await self.memory.add_interaction(
                    user_msg=f"[系统主动关心] {message}",
                    assistant_msg="（系统主动消息记录）",
                    metadata={
                        "user_id": user_id,
                        "source": "proactive",
                    },
                )
                logger.info(f"主动消息已写入记忆: {message[:30]}...")
                return True
            except Exception as e:
                logger.warning(f"写入记忆失败: {e}")

        logger.warning(f"主动消息未能发送: {message[:30]}...")
        return False

    def get_last_sent_time(self, user_id: str) -> float | None:
        """获取上次发送时间。"""
        return self._last_sent.get(user_id)

    async def broadcast(
        self,
        message: str,
        user_ids: list[str] | None = None,
    ) -> dict[str, bool]:
        """广播消息给多个用户。"""
        if not user_ids and self.memory:
            # 从记忆系统获取所有用户
            try:
                user_ids = list(set(
                    r.user_id for r in self.memory.semantic_store._records.values()
                    if r.is_active and r.user_id
                ))
            except Exception:
                pass

        if not user_ids:
            return {}

        results = {}
        for uid in user_ids:
            results[uid] = await self.dispatch(uid, message)
        return results
