"""平台适配器基类"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from vir_bot.core.pipeline import PlatformMessage, PlatformResponse, MessagePipeline, Platform, MessageType
from vir_bot.utils.logger import logger

if TYPE_CHECKING:
    from vir_bot.core.pipeline import MessagePipeline


class PlatformAdapter(ABC):
    """
    平台适配器基类。
    每个平台实现一个子类：负责与平台服务建立连接，
    将平台私有格式转换为 PlatformMessage，
    将 PlatformResponse 转换回平台格式并发送。
    """

    def __init__(self, pipeline: "MessagePipeline"):
        self.pipeline = pipeline
        self._running = False
        self._send_queue: asyncio.Queue[PlatformResponse] = asyncio.Queue()

    @property
    @abstractmethod
    def platform(self) -> Platform:
        """返回平台标识"""
        ...

    @abstractmethod
    async def connect(self) -> None:
        """建立与平台的连接"""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """断开连接"""
        ...

    @abstractmethod
    async def send_message(self, response: PlatformResponse) -> None:
        """发送消息回平台"""
        ...

    @abstractmethod
    async def _receive_loop(self):
        """子类的消息接收循环（yield PlatformMessage）"""
        raise NotImplementedError

    async def start(self) -> None:
        """启动适配器"""
        self._running = True
        await self.connect()
        asyncio.create_task(self._run())
        logger.info(f"[{self.platform.value}] 平台适配器已启动")

    async def _run(self) -> None:
        """收发循环"""
        try:
            async for msg in self._receive_loop():
                response = await self.pipeline.process(msg)
                if response:
                    await self._send_queue.put(response)
        except Exception as e:
            logger.error(f"[{self.platform.value}] 接收循环异常: {e}")
        finally:
            await self.disconnect()

    async def _send_loop(self) -> None:
        """发送循环"""
        while self._running:
            try:
                response = await asyncio.wait_for(self._send_queue.get(), timeout=1.0)
                await self.send_message(response)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"[{self.platform.value}] 发送异常: {e}")

    async def stop(self) -> None:
        self._running = False
        await self.disconnect()