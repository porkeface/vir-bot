"""Telegram 平台适配器（python-telegram-bot）"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import AsyncIterator

from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

from vir_bot.core.pipeline import Platform, PlatformMessage, PlatformResponse, MessageType
from vir_bot.platforms.base_adapter import PlatformAdapter
from vir_bot.utils.logger import logger


class TelegramAdapter(PlatformAdapter):
    """Telegram 适配器（polling 模式）"""

    # 健康检查间隔（秒）和最大静默时间（秒）
    _HEALTH_CHECK_INTERVAL = 60
    _MAX_SILENCE_SECONDS = 180

    def __init__(self, pipeline, config):
        super().__init__(pipeline)
        self.config = config
        self._app = None
        self._queue: asyncio.Queue[PlatformMessage] = asyncio.Queue()
        self._pending_messages: dict[str, dict] = {}
        self._rate_limiter: dict[str, list[float]] = {}
        self._temp_dir = Path("./data/temp/telegram")
        self._temp_dir.mkdir(parents=True, exist_ok=True)
        self._last_poll_activity: float = time.time()
        self._health_task: asyncio.Task | None = None

    @property
    def platform(self) -> Platform:
        return Platform.TELEGRAM

    async def connect(self) -> None:
        from telegram.request import HTTPXRequest
        proxy_url = getattr(self.config, 'proxy', None)
        request = HTTPXRequest(
            connect_timeout=30,
            read_timeout=30,
            write_timeout=30,
            pool_timeout=180,
            connection_pool_size=100,
            proxy=proxy_url,
        )
        builder = ApplicationBuilder().token(self.config.bot_token).request(request)
        self._app = builder.build()

        # 注册文字消息处理器
        text_handler = MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            self._handle_message,
        )
        self._app.add_handler(text_handler)

        # 注册图片/表情包消息处理器
        photo_handler = MessageHandler(
            filters.PHOTO | filters.Sticker.ALL,
            self._handle_media,
        )
        self._app.add_handler(photo_handler)

        # 注册语音消息处理器
        voice_handler = MessageHandler(
            filters.VOICE | filters.AUDIO,
            self._handle_voice,
        )
        self._app.add_handler(voice_handler)

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

    async def _handle_media(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理收到的图片/表情包消息"""
        message = update.effective_message
        if not message:
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

        # 下载图片
        file_id = None
        file_ext = ".jpg"
        if message.photo:
            # 取最大尺寸的图片
            file_id = message.photo[-1].file_id
        elif message.sticker:
            file_id = message.sticker.file_id
            if message.sticker.is_animated:
                file_ext = ".tgs"
            elif message.sticker.is_video:
                file_ext = ".webm"
            else:
                file_ext = ".webp"

        if not file_id:
            return

        try:
            # 下载文件
            file = await context.bot.get_file(file_id)
            file_name = f"{user_id}_{int(time.time())}{file_ext}"
            file_path = self._temp_dir / file_name
            await file.download_to_drive(file_path)

            msg_id = str(message.message_id)
            self._pending_messages[msg_id] = {"chat_id": chat_id}

            # 判断是否群聊
            is_group = message.chat.type in ("group", "supergroup")
            group_id = chat_id if is_group else None

            # 构建消息
            caption = message.caption or ""
            platform_msg = PlatformMessage(
                platform=Platform.TELEGRAM,
                msg_id=msg_id,
                user_id=user_id,
                user_name=user.full_name or user.username or user_id,
                group_id=group_id,
                content=caption,
                msg_type=MessageType.IMAGE,
                raw_data={
                    "chat_id": chat_id,
                    "file_path": str(file_path),
                    "file_id": file_id,
                    "is_sticker": bool(message.sticker),
                },
                timestamp=time.time(),
            )

            await self._queue.put(platform_msg)
            logger.info(f"[Telegram] 收到图片/表情包: {file_name}")

        except Exception as e:
            logger.error(f"[Telegram] 下载图片失败: {e}")

    async def _handle_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理收到的语音/音频消息"""
        message = update.effective_message
        if not message:
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

        # 确定文件 ID 和扩展名
        file_id = None
        file_ext = ".ogg"
        if message.voice:
            file_id = message.voice.file_id
            file_ext = ".ogg"
        elif message.audio:
            file_id = message.audio.file_id
            file_ext = ".mp3"
        elif message.video_note:
            file_id = message.video_note.file_id
            file_ext = ".mp4"

        if not file_id:
            return

        try:
            file = await context.bot.get_file(file_id)
            file_name = f"{user_id}_{int(time.time())}{file_ext}"
            file_path = self._temp_dir / file_name
            await file.download_to_drive(file_path)

            msg_id = str(message.message_id)
            self._pending_messages[msg_id] = {"chat_id": chat_id}

            is_group = message.chat.type in ("group", "supergroup")
            group_id = chat_id if is_group else None

            platform_msg = PlatformMessage(
                platform=Platform.TELEGRAM,
                msg_id=msg_id,
                user_id=user_id,
                user_name=user.full_name or user.username or user_id,
                group_id=group_id,
                content="",
                msg_type=MessageType.VOICE,
                raw_data={
                    "chat_id": chat_id,
                    "file_path": str(file_path),
                    "file_id": file_id,
                },
                timestamp=time.time(),
            )

            await self._queue.put(platform_msg)
            logger.info(f"[Telegram] 收到语音消息: {file_name}")

        except Exception as e:
            logger.error(f"[Telegram] 下载语音失败: {e}")

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

        # 启动消息处理循环（存储引用防止 GC 和静默丢失异常）
        self._run_task = asyncio.create_task(self._run())
        self._run_task.add_done_callback(self._on_task_done)

        # 启动健康检查（监控 polling 连接，断线自动重连）
        self._last_poll_activity = time.time()
        self._health_task = asyncio.create_task(self._health_check_loop())
        self._health_task.add_done_callback(self._on_task_done)
        logger.info(f"[{self.platform.value}] 平台适配器已启动（含健康检查）")

    @staticmethod
    def _on_task_done(task: asyncio.Task) -> None:
        """任务结束时记录异常（如果有的话）"""
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            import traceback

            logger.error(f"[Telegram] 消息处理任务异常退出:\n{''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))}")

    async def stop(self) -> None:
        """停止适配器"""
        self._running = False
        if self._health_task:
            self._health_task.cancel()
            self._health_task = None
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
                self._last_poll_activity = time.time()
                yield msg
            except asyncio.TimeoutError:
                continue

    async def _health_check_loop(self) -> None:
        """定期检查 polling 连接是否存活，断线自动重连"""
        while self._running:
            await asyncio.sleep(self._HEALTH_CHECK_INTERVAL)
            if not self._running:
                break

            silence = time.time() - self._last_poll_activity
            if silence < self._MAX_SILENCE_SECONDS:
                continue

            logger.warning(
                f"[Telegram] polling 已静默 {int(silence)}s（阈值 {self._MAX_SILENCE_SECONDS}s），尝试重启..."
            )
            await self._restart_polling()

    async def _restart_polling(self) -> None:
        """安全重启 Telegram polling"""
        if not self._app:
            logger.error("[Telegram] 重启失败: _app 为空")
            return

        try:
            await self._app.updater.stop()
            logger.info("[Telegram] updater.stop() 完成")
        except Exception as e:
            logger.warning(f"[Telegram] updater.stop() 出错（可忽略）: {e}")

        try:
            await self._app.updater.start_polling(drop_pending_updates=True)
            self._last_poll_activity = time.time()
            logger.info("[Telegram] polling 已重启")
        except Exception as e:
            logger.error(f"[Telegram] polling 重启失败: {e}")

    async def send_message(self, response: PlatformResponse) -> None:
        """通过 Telegram 发送消息"""
        if not self._app:
            return

        msg_data = self._pending_messages.get(response.msg_id, {})
        chat_id = response.metadata.get("chat_id") or msg_data.get("chat_id")
        logger.debug(f"[Telegram] send_message: msg_id={response.msg_id}, metadata_chat_id={response.metadata.get('chat_id')}, msg_data={msg_data}, resolved_chat_id={chat_id}, pending_count={len(self._pending_messages)}")
        if not chat_id:
            logger.warning(f"[Telegram] 无法确定 chat_id，跳过发送 (msg_id={response.msg_id}, pending_keys={list(self._pending_messages.keys())[:5]})")
            return

        try:
            # 检查是否需要发送表情
            expression_path = response.metadata.get("expression")
            if expression_path:
                await self._send_photo(chat_id, expression_path)

            # 发送语音回复
            voice_file = response.metadata.get("voice_file")
            if voice_file:
                logger.info(f"[Telegram] 准备发送语音 -> chat_id={chat_id}, file={voice_file}")
                await self._send_voice(chat_id, voice_file)
                return

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

    async def send_proactive_message(self, message: str, target: dict) -> None:
        """发送主动消息（不依赖 _pending_messages）"""
        if not self._app:
            return

        chat_id = target.get("chat_id")
        if not chat_id:
            logger.warning("[Telegram] 主动消息缺少 chat_id，跳过发送")
            return

        try:
            kwargs = {
                "chat_id": int(chat_id),
                "text": message,
            }
            if self.config.parse_mode:
                kwargs["parse_mode"] = self.config.parse_mode

            await self._app.bot.send_message(**kwargs)
            logger.info(f"[Telegram] 主动消息已发送 -> {chat_id}: {message[:100]}")
        except Exception as e:
            logger.error(f"[Telegram] 主动消息发送失败: {e}")

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

    async def _send_voice(self, chat_id: str, voice_path: str) -> None:
        """发送语音消息"""
        try:
            path = Path(voice_path)
            if not path.exists():
                logger.warning(f"[Telegram] 语音文件不存在: {voice_path} (resolved: {path.resolve()})")
                return

            file_size = path.stat().st_size
            logger.info(f"[Telegram] 发送语音文件: {path.name} ({file_size} bytes) -> chat_id={chat_id}")

            with open(path, "rb") as audio:
                await self._app.bot.send_voice(
                    chat_id=int(chat_id),
                    voice=audio,
                )
            logger.info(f"[Telegram] 发送语音成功 -> {chat_id}: {path.name}")

            # 清理临时文件
            try:
                path.unlink()
            except OSError:
                pass
        except Exception as e:
            logger.error(f"[Telegram] 发送语音失败: chat_id={chat_id}, file={voice_path}, error={e}")
