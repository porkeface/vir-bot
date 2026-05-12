"""Telegram 平台适配器（python-telegram-bot）"""
from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator

from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

from vir_bot.core.pipeline import Platform, PlatformMessage, PlatformResponse, MessageType
from vir_bot.platforms.base_adapter import PlatformAdapter
from vir_bot.utils.logger import logger


class TelegramAdapter(PlatformAdapter):
    """Telegram 适配器（polling 模式）"""

    def __init__(self, pipeline, config):
        super().__init__(pipeline)
        self.config = config
        self._app = None
        self._queue: asyncio.Queue[PlatformMessage] = asyncio.Queue()
        self._pending_messages: dict[str, dict] = {}
        self._rate_limiter: dict[str, list[float]] = {}

    @property
    def platform(self) -> Platform:
        return Platform.TELEGRAM

    async def connect(self) -> None:
        builder = ApplicationBuilder().token(self.config.bot_token)
        self._app = builder.build()

        # 注册消息处理器
        handler = MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            self._handle_message,
        )
        self._app.add_handler(handler)

        logger.info("[Telegram] 正在启动 polling...")

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理收到的 Telegram 消息"""
        message = update.effective_message
        if not message or not message.text:
            return

        user = message.from_user
        if not user:
            return

        user_id = str(user.id)
        chat_id = str(message.chat_id)

        # 过滤
        if self.config.block_list and user_id in self.config.block_list:
            return
        if self.config.allowed_users and user_id not in self.config.allowed_users:
            return
        if self.config.allowed_chats and chat_id not in self.config.allowed_chats:
            return

        # 速率限制
        if not self._check_rate_limit(user_id):
            return

        msg_id = str(message.message_id)
        self._pending_messages[msg_id] = {"chat_id": chat_id}

        # 判断是否群聊
        is_group = message.chat.type in ("group", "supergroup")
        group_id = chat_id if is_group else None

        platform_msg = PlatformMessage(
            platform=Platform.TELEGRAM,
            msg_id=msg_id,
            user_id=user_id,
            user_name=user.full_name or user.username or user_id,
            group_id=group_id,
            content=message.text,
            msg_type=MessageType.TEXT,
            raw_data={"chat_id": chat_id},
            timestamp=time.time(),
        )

        await self._queue.put(platform_msg)

    def _check_rate_limit(self, key: str) -> bool:
        now = time.time()
        window = 60.0
        if key not in self._rate_limiter:
            self._rate_limiter[key] = []
        ts = self._rate_limiter[key]
        ts[:] = [t for t in ts if now - t < window]
        ts.append(now)
        return len(ts) <= self.config.rate_limit.per_user

    async def disconnect(self) -> None:
        if self._app:
            await self._app.stop()
            self._app = None

    async def start(self) -> None:
        """启动适配器（重写基类，因为 telegram polling 需要特殊处理）"""
        self._running = True
        await self.connect()

        if self._app:
            await self._app.initialize()
            await self._app.start()
            await self._app.updater.start_polling(drop_pending_updates=True)
            logger.info("[Telegram] polling 已启动")

        # 启动消息处理循环
        asyncio.create_task(self._run())
        logger.info(f"[{self.platform.value}] 平台适配器已启动")

    async def stop(self) -> None:
        """停止适配器"""
        self._running = False
        if self._app:
            try:
                await self._app.updater.stop()
                await self._app.stop()
                await self._app.shutdown()
            except Exception as e:
                logger.warning(f"[Telegram] 关闭时出错: {e}")
            self._app = None

    async def _receive_loop(self) -> AsyncIterator[PlatformMessage]:
        """从消息队列接收消息"""
        while self._running:
            try:
                msg = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                yield msg
            except asyncio.TimeoutError:
                continue

    async def send_message(self, response: PlatformResponse) -> None:
        """通过 Telegram 发送消息"""
        if not self._app:
            return

        msg_data = self._pending_messages.get(response.msg_id, {})
        chat_id = response.metadata.get("chat_id") or msg_data.get("chat_id")
        if not chat_id:
            logger.warning("[Telegram] 无法确定 chat_id，跳过发送")
            return

        try:
            # 检查是否需要发送表情
            expression_path = response.metadata.get("expression")
            if expression_path:
                await self._send_photo(chat_id, expression_path)

            # 发送文字消息
            if response.content:
                kwargs = {
                    "chat_id": int(chat_id),
                    "text": response.content,
                }
                if self.config.parse_mode:
                    kwargs["parse_mode"] = self.config.parse_mode

                await self._app.bot.send_message(**kwargs)
                logger.info(f"[Telegram] 发送消息 -> {chat_id}: {response.content[:100]}")
        except Exception as e:
            logger.error(f"[Telegram] 发送失败: {e}")

    async def _send_photo(self, chat_id: str, photo_path: str) -> None:
        """发送图片消息"""
        try:
            from pathlib import Path
            path = Path(photo_path)
            if not path.exists():
                logger.warning(f"[Telegram] 表情文件不存在: {photo_path}")
                return

            with open(path, "rb") as photo:
                await self._app.bot.send_photo(
                    chat_id=int(chat_id),
                    photo=photo,
                )
            logger.info(f"[Telegram] 发送表情 -> {chat_id}: {path.name}")
        except Exception as e:
            logger.error(f"[Telegram] 发送表情失败: {e}")
