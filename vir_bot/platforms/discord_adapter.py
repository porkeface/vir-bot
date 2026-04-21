"""Discord 平台适配器"""
from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator

import discord

from vir_bot.core.pipeline import Platform, PlatformMessage, PlatformResponse, MessageType
from vir_bot.platforms.base_adapter import PlatformAdapter
from vir_bot.utils.logger import logger


class DiscordAdapter(PlatformAdapter):
    """Discord 适配器"""

    def __init__(self, pipeline, config):
        super().__init__(pipeline)
        self.config = config
        self.client: discord.Client | None = None
        self._queue: asyncio.Queue[PlatformMessage] = asyncio.Queue()
        self._rate_limiter: dict[str, list[float]] = {}
        self._pending_messages: dict[str, dict] = {}

    @property
    def platform(self) -> Platform:
        return Platform.DISCORD

    async def connect(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guild_messages = True

        self.client = discord.Client(intents=intents)

        @self.client.event
        async def on_message(message: discord.Message):
            # 忽略机器人消息
            if message.author.bot and self.config.guilds:
                return
            # 速率限制
            if not await self._check_rate_limit(message.channel.id):
                return

            content = message.content.strip()
            if not content:
                return

            msg = PlatformMessage(
                platform=Platform.DISCORD,
                msg_id=str(message.id),
                user_id=str(message.author.id),
                user_name=message.author.display_name,
                group_id=str(message.guild.id) if message.guild else None,
                content=content,
                msg_type=MessageType.TEXT,
                raw_data={"channel_id": str(message.channel.id)},
                timestamp=message.created_at.timestamp(),
            )
            self._pending_messages[str(message.id)] = {"channel_id": str(message.channel.id)}
        await self._queue.put(msg)

        @self.client.event
        async def on_ready():
            logger.info(f"[Discord] 已登录: {self.client.user}")

        try:
            await self.client.start(self.config.bot_token)
        except Exception as e:
            logger.error(f"[Discord] 连接失败: {e}")

    async def disconnect(self) -> None:
        if self.client:
            await self.client.close()

    async def _receive_loop(self) -> AsyncIterator[PlatformMessage]:
        """从消息队列接收消息"""
        while True:
            msg = await self._queue.get()
            yield msg

    async def _check_rate_limit(self, channel_id: str) -> bool:
        now = time.time()
        window = 60.0
        if channel_id not in self._rate_limiter:
            self._rate_limiter[channel_id] = []
        ts = self._rate_limiter[channel_id]
        ts[:] = [t for t in ts if now - t < window]
        ts.append(now)
        return len(ts) <= self.config.rate_limit.per_channel

    async def send_message(self, response: PlatformResponse) -> None:
        """通过 Discord 发送消息"""
        if not self.client:
            return

        msg_data = self._pending_messages.get(response.msg_id, {})
        channel_id = msg_data.get("channel_id")
        if not channel_id:
            return

        channel = self.client.get_channel(int(channel_id))
        if channel:
            await channel.send(response.content)