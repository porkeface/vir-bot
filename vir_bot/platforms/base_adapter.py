"""平台适配器基类"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from vir_bot.core.pipeline import PlatformMessage, PlatformResponse, MessagePipeline, Platform, MessageType
from vir_bot.core.pipeline.message_splitter import SplitConfig, split_message, get_split_delay_ms
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
        self._split_config = self._build_split_config()

    def _build_split_config(self) -> SplitConfig:
        """从 pipeline 配置构建拆分配置"""
        cfg = getattr(self.pipeline, "config", None)
        if cfg and hasattr(cfg, "split"):
            s = cfg.split
            return SplitConfig(
                enabled=s.enabled,
                max_chunk_chars=s.max_chunk_chars,
                delay_min_ms=s.delay_min_ms,
                delay_max_ms=s.delay_max_ms,
            )
        return SplitConfig()

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
        self._run_task = asyncio.create_task(self._run())
        self._run_task.add_done_callback(self._on_task_done)
        logger.info(f"[{self.platform.value}] 平台适配器已启动")

    @staticmethod
    def _on_task_done(task: asyncio.Task) -> None:
        """任务结束时记录异常"""
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            import traceback

            logger.error(f"[平台] 适配器任务异常退出:\n{''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))}")

    async def _run(self) -> None:
        """收发循环"""
        try:
            async for msg in self._receive_loop():
                logger.info(f"[{self.platform.value}] 收到消息: {msg.content[:50]} from {msg.user_id}")
                try:
                    response = await self.pipeline.process(msg, send_callback=self.send_message)
                except Exception as e:
                    import traceback

                    logger.error(f"[{self.platform.value}] 处理消息异常:\n{''.join(traceback.format_exception(type(e), e, e.__traceback__))}")
                    continue
                if response and response.metadata.get("already_streamed"):
                    # 流式输出已通过回调逐句发送
                    expression_path = response.metadata.get("expression")
                    if expression_path:
                        await self._send_expression(response.msg_id, expression_path)
                    # 发送语音文件（TTS 合成可能在流式文字之后完成）
                    voice_file = response.metadata.get("voice_file")
                    if voice_file:
                        voice_mode = getattr(self, "voice_mode", "replace")
                        logger.info(f"[{self.platform.value}] 流式后发送语音: msg_id={response.msg_id}, file={voice_file}, mode={voice_mode}")
                        voice_response = PlatformResponse(
                            msg_id=response.msg_id,
                            content="",
                            reply=True,
                            metadata={"voice_file": voice_file, "use_voice": True, "chat_id": response.metadata.get("chat_id")},
                        )
                        await self.send_message(voice_response)
                    continue
                if response and response.content:
                    await self._send_split(response)
                elif not response:
                    logger.warning(f"[{self.platform.value}] Pipeline 返回空响应")
        except asyncio.CancelledError:
            logger.info(f"[{self.platform.value}] 接收循环被取消")
        except Exception as e:
            import traceback

            logger.error(f"[{self.platform.value}] 接收循环异常:\n{''.join(traceback.format_exception(type(e), e, e.__traceback__))}")
        finally:
            logger.info(f"[{self.platform.value}] 接收循环退出，正在断开连接")
            await self.disconnect()

    async def _send_split(self, response: PlatformResponse) -> None:
        """拆分长消息并逐条发送"""
        chunks = split_message(response.content, self._split_config)

        if len(chunks) <= 1:
            logger.info(f"[{self.platform.value}] AI 回复: {response.content[:80]}")
            await self.send_message(response)
            return

        # 判断是否为 voice both 模式：文字分片发送，语音最后单独发一次
        voice_file = response.metadata.get("voice_file")
        voice_mode = response.metadata.get("voice_mode") or getattr(self, "voice_mode", None)
        is_voice_both = voice_file and voice_mode == "both"

        # both 模式下，分片不携带 voice metadata，避免每个分片重复发语音
        chunk_metadata = dict(response.metadata)
        if is_voice_both:
            chunk_metadata.pop("voice_file", None)
            chunk_metadata.pop("voice_mode", None)

        logger.info(f"[{self.platform.value}] AI 回复拆分为 {len(chunks)} 条")
        for i, chunk in enumerate(chunks):
            chunk_response = PlatformResponse(
                msg_id=response.msg_id,
                content=chunk,
                reply=response.reply,
                quote=response.quote and i == 0,
                metadata=chunk_metadata,
            )
            logger.info(f"[{self.platform.value}] [{i+1}/{len(chunks)}] {chunk[:80]}")
            await self.send_message(chunk_response)
            if i < len(chunks) - 1:
                delay = get_split_delay_ms(self._split_config)
                await asyncio.sleep(delay / 1000.0)

        # both 模式：所有文字分片发完后，单独发送一次语音
        if is_voice_both:
            voice_response = PlatformResponse(
                msg_id=response.msg_id,
                content="",
                reply=True,
                metadata={"voice_file": voice_file, "chat_id": response.metadata.get("chat_id")},
            )
            await self.send_message(voice_response)

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

    async def _send_expression(self, msg_id: str, expression_path: str) -> None:
        """发送表情图片（子类可重写以适配不同平台）"""
        response = PlatformResponse(
            msg_id=msg_id,
            content="",
            reply=True,
            metadata={"expression": expression_path},
        )
        await self.send_message(response)

    async def _send_voice(self, msg_id: str, voice_path: str) -> None:
        """发送语音文件（子类可重写以适配不同平台）"""
        response = PlatformResponse(
            msg_id=msg_id,
            content="",
            reply=True,
            metadata={"voice_file": voice_path},
        )
        logger.info(f"[{self.platform.value}] base._send_voice 调用 send_message: msg_id={msg_id}")
        await self.send_message(response)