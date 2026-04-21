"""QQ 平台适配器（OneBot v11/v12）"""
from __future__ import annotations

import asyncio
import json
import time
from typing import AsyncIterator

import websockets
from websockets.client import connect

from vir_bot.core.pipeline import Platform, PlatformMessage, PlatformResponse, MessageType
from vir_bot.platforms.base_adapter import PlatformAdapter
from vir_bot.utils.logger import logger


class QQAdapter(PlatformAdapter):
    """QQ (OneBot v11 / v12) 适配器"""

    def __init__(self, pipeline, config):
        super().__init__(pipeline)
        self.config = config
        self.ws: websockets.WebSocketClientProtocol | None = None

    @property
    def platform(self) -> Platform:
        return Platform.QQ

    async def connect(self) -> None:
        conn = self.config.connection
        if conn.type == "正向WebSocket":
            uri = f"ws://{conn.host}:{conn.port}"
        else:
            uri = conn.type  # 反向 WS

        headers = {}
        if self.config.access_token:
            headers["Authorization"] = f"Bearer {self.config.access_token}"

        try:
            self.ws = await connect(uri, additional_headers=headers)
            logger.info(f"[QQ] 已连接: {uri}")
        except Exception as e:
            logger.error(f"[QQ] 连接失败: {e}")

    async def disconnect(self) -> None:
        if self.ws:
            await self.ws.close()
            self.ws = None

    async def _receive_loop(self) -> AsyncIterator[PlatformMessage]:
        """从 WebSocket 接收消息"""
        if not self.ws:
            return

        async for raw in self.ws:
            data = json.loads(raw)
            msg = self._parse_message(data)
            if msg:
                yield msg

    def _parse_message(self, data: dict) -> PlatformMessage | None:
        """解析 OneBot 消息为 PlatformMessage"""
        post_type = data.get("post_type", "")
        if post_type != "message":
            return None

        # 过滤
        user_id = str(data.get("user_id", ""))
        if self.config.allowed_users and user_id not in self.config.allowed_users:
            return None
        if user_id in self.config.block_list:
            return None

        group_id = str(data.get("group_id", "")) or None
        if group_id and self.config.allowed_groups and group_id not in self.config.allowed_groups:
            return None

        # 提取内容
        raw_message = data.get("raw_message", "")
        message_seg = data.get("message", [])
        content = raw_message or self._extract_text(message_seg)

        if not content:
            return None

        return PlatformMessage(
            platform=Platform.QQ,
            msg_id=str(data.get("message_id", "")),
            user_id=user_id,
            user_name=str(data.get("sender", {}).get("nickname", user_id)),
            group_id=group_id,
            content=content,
            msg_type=self._detect_msg_type(message_seg),
            raw_data=data,
            timestamp=time.time(),
        )

    def _extract_text(self, message: list[dict]) -> str:
        parts = []
        for seg in message:
            if seg.get("type") == "text":
                parts.append(seg.get("text", ""))
        return "".join(parts)

    def _detect_msg_type(self, message: list[dict]) -> MessageType:
        for seg in message:
            if seg.get("type") == "image":
                return MessageType.IMAGE
            if seg.get("type") in ("record", "voice"):
                return MessageType.VOICE
        return MessageType.TEXT

    async def send_message(self, response: PlatformResponse) -> None:
        """通过 OneBot 发送消息"""
        if not self.ws:
            return

        # 查找原始消息的会话信息
        data = self._pending_messages.get(response.msg_id, {})
        message = [{"type": "text", "data": {"text": response.content}}]

        payload = {
            "action": "send_msg",
            "params": {
                "message": message,
                "user_id": data.get("user_id"),
                "group_id": data.get("group_id"),
            },
        }

        try:
            await self.ws.send(json.dumps(payload))
        except Exception as e:
            logger.error(f"[QQ] 发送失败: {e}")

    def _pending_messages: dict = {}