"""消息处理管道"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from vir_bot.config import PipelineConfig
    from vir_bot.core.ai_provider import AIProvider, AIResponse
    from vir_bot.core.character import CharacterCard
    from vir_bot.core.mcp import ToolRegistry
    from vir_bot.core.memory.memory_manager import MemoryManager

from vir_bot.utils.logger import logger


class MessageType(Enum):
    TEXT = "text"
    IMAGE = "image"
    VOICE = "voice"
    SYSTEM = "system"


class Platform(Enum):
    QQ = "qq"
    WECHAT = "wechat"
    DISCORD = "discord"
    TELEGRAM = "telegram"
    API = "api"


@dataclass
class PlatformMessage:
    """统一消息格式"""

    platform: Platform
    msg_id: str
    user_id: str
    user_name: str = ""
    group_id: str | None = None
    content: str = ""
    msg_type: MessageType = MessageType.TEXT
    raw_data: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    reply_to: str | None = None
    attachments: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def to_messages(self) -> list[dict]:
        return [{"role": "user", "content": self.content}]


@dataclass
class PlatformResponse:
    """回复结构"""

    msg_id: str
    content: str
    reply: bool = True
    quote: bool = False
    metadata: dict = field(default_factory=dict)


class RateLimiter:
    def __init__(self, per_user: int = 20, per_group: int = 60):
        self.per_user = per_user
        self.per_group = per_group
        self._user_timestamps: dict[str, list[float]] = {}
        self._group_timestamps: dict[str, list[float]] = {}

    async def check(self, msg: PlatformMessage) -> bool:
        now = time.time()
        window = 60.0

        uid = msg.user_id
        if uid not in self._user_timestamps:
            self._user_timestamps[uid] = []
        ts = self._user_timestamps[uid]
        ts[:] = [t for t in ts if now - t < window]
        ts.append(now)
        if len(ts) > self.per_user:
            logger.warning(f"用户 {uid} 超过频率限制")
            return False

        if msg.group_id:
            gid = msg.group_id
            if gid not in self._group_timestamps:
                self._group_timestamps[gid] = []
            gts = self._group_timestamps[gid]
            gts[:] = [t for t in gts if now - t < window]
            gts.append(now)
            if len(gts) > self.per_group:
                logger.warning(f"群 {gid} 超过频率限制")
                return False

        return True


class MessagePipeline:
    """消息处理管道。"""

    def __init__(
        self,
        ai_provider: "AIProvider",
        memory_manager: "MemoryManager",
        character_card: "CharacterCard",
        mcp_registry: "ToolRegistry",
        config: "PipelineConfig",
        expression_manager: Any | None = None,
        tts_provider: Any | None = None,
        asr_provider: Any | None = None,
        voice_config: Any | None = None,
    ):
        self.ai = ai_provider
        self.memory = memory_manager
        self.character = character_card
        self.mcp = mcp_registry
        self.config = config
        self.expressions = expression_manager
        self.tts = tts_provider
        self.asr = asr_provider
        self.voice_config = voice_config
        self._rate_limiter = RateLimiter()
        self._on_user_message: "Any | None" = None  # 由 main.py 注入，通知主动消息系统

    async def process(
        self,
        msg: PlatformMessage,
        send_callback: "Any | None" = None,
    ) -> PlatformResponse | None:
        """主入口：处理一条消息。"""
        # 处理图片/表情包消息（自动收藏）
        if msg.msg_type == MessageType.IMAGE and self.expressions:
            return await self._handle_image_message(msg)

        # 处理语音消息（ASR 转文字后走正常流程）
        if msg.msg_type == MessageType.VOICE:
            return await self._handle_voice_message(msg, send_callback)

        return await self._process_text_message(msg, send_callback)

    async def _process_text_message(
        self,
        msg: PlatformMessage,
        send_callback: "Any | None" = None,
    ) -> PlatformResponse | None:
        """标准文本消息处理（TEXT 和转录后的 VOICE 共用）。"""
        if not self._pre_filter(msg):
            logger.info(f"[Pipeline] 消息被过滤: {msg.content[:30]}")
            return None

        # 通知主动消息系统：用户发来了消息
        if self._on_user_message:
            try:
                self._on_user_message(msg.user_id, msg.content)
            except Exception as e:
                logger.debug(f"[Pipeline] 通知主动消息系统失败: {e}")

        if not await self._rate_limiter.check(msg):
            return PlatformResponse(
                msg_id=msg.msg_id,
                content="[消息过于频繁，请稍后再试]",
                reply=True,
            )

        try:
            system_prompt, conversation = await self._build_context(msg)
        except Exception as e:
            logger.error(f"[Pipeline] 构建上下文失败: {e}")
            return None

        tools_schema = self.mcp.get_tools_schemas()
        logger.info(f"[Pipeline] 开始 AI 调用, 消息: {msg.content[:30]}, 上下文轮数: {len(conversation)}")
        logger.debug(f"[Pipeline] System prompt 长度: {len(system_prompt)}")
        if conversation:
            logger.debug(f"[Pipeline] 最后一条消息: {conversation[-1]}")

        # 流式输出：有回调时启用
        if send_callback is not None:
            logger.info("[Pipeline] 尝试流式输出...")
            result = await self._process_streaming(
                msg, conversation, system_prompt, tools_schema, send_callback,
            )
            if result is not None:
                logger.info("[Pipeline] 流式输出成功，异步更新记忆")
                asyncio.create_task(self._update_memory_from_content(msg, result.content))
                return result
            # 流式失败，回退到普通模式
            logger.warning("[Pipeline] 流式输出失败，回退到普通模式")

        response: "AIResponse" | None = None
        for attempt in range(3):
            try:
                response = await self.ai.chat(
                    messages=conversation,
                    system=system_prompt,
                    tools=tools_schema if tools_schema else None,
                )
                logger.info(f"[Pipeline] AI 调用成功, 内容长度: {len(response.content) if response else 0}")

                # 如果内容为空，用简化消息重试（不带工具）
                if response and not response.content and attempt < 2:
                    logger.warning(f"[Pipeline] AI 返回空内容，用简化消息重试 (attempt {attempt + 1})")
                    response = await self.ai.chat(
                        messages=conversation,
                        system=system_prompt,
                        tools=None,
                    )
                    logger.info(f"[Pipeline] 重试成功, 内容长度: {len(response.content) if response else 0}")

                if response and response.content:
                    break
            except Exception as e:
                logger.error(f"AI 调用失败 (attempt {attempt + 1}): {e}")
                if attempt == 2:
                    return PlatformResponse(
                        msg_id=msg.msg_id,
                        content="抱歉，AI 服务暂时不可用。",
                        reply=True,
                    )
                await asyncio.sleep(2**attempt)

        if response is None:
            logger.warning("[Pipeline] AI 响应为 None")
            return None

        if not response.content:
            logger.warning("[Pipeline] AI 响应内容为空")
            return None

        response = await self._handle_tool_calls(response, system_prompt, tools_schema, depth=0)
        asyncio.create_task(self._update_memory(msg, response))

        # 检测情绪并获取表情
        metadata = {}
        if self.expressions:
            expression_path = await self.expressions.get_expression_async(text=response.content)
            if expression_path:
                metadata["expression"] = str(expression_path)
                logger.debug(f"[Pipeline] 检测到表情: {expression_path.name}")

        # TTS 合成语音回复
        if self.tts and self.voice_config and getattr(self.voice_config, "voice_response", False):
            voice_file = await self._synthesize_tts(response.content)
            if voice_file:
                metadata["voice_file"] = voice_file

        return PlatformResponse(
            msg_id=msg.msg_id,
            content=response.content,
            reply=True,
            metadata=metadata,
        )

    async def _process_streaming(
        self,
        msg: PlatformMessage,
        conversation: list[dict],
        system_prompt: str,
        tools_schema: list[dict],
        send_callback: Any,
    ) -> PlatformResponse | None:
        """流式处理：逐句生成并发送。返回 None 表示回退到普通模式。"""
        try:
            buffer = ""
            full_content = ""
            chunk_count = 0
            timeout_seconds = 20  # 单个 chunk 超时

            logger.info("[Pipeline] 开始流式 AI 调用...")
            stream = self.ai.chat_stream(
                messages=conversation,
                system=system_prompt,
            )

            try:
                async for chunk in stream:
                    if chunk.finish_reason == "stop":
                        break
                    if not chunk.delta:
                        continue

                    chunk_count += 1
                    buffer += chunk.delta
                    full_content += chunk.delta

                    # 只按换行拆分（AI 被引导用换行分隔消息）
                    while "\n" in buffer:
                        nl_pos = buffer.find("\n")
                        line = buffer[:nl_pos].strip()
                        buffer = buffer[nl_pos + 1:]
                        if line:
                            await send_callback(
                                PlatformResponse(msg_id=msg.msg_id, content=line, reply=True)
                            )
            except Exception as e:
                logger.warning(f"[Pipeline] 流式读取异常: {e}")

            # 发送剩余内容
            if buffer.strip():
                await send_callback(
                    PlatformResponse(msg_id=msg.msg_id, content=buffer.strip(), reply=True)
                )

            logger.info(f"[Pipeline] 流式循环结束, chunks={chunk_count}, 总长度={len(full_content)}")

            if not full_content.strip():
                return None

            logger.info(f"[Pipeline] 流式输出完成, 总长度: {len(full_content)}")

            # 检测情绪并获取表情
            metadata = {"already_streamed": True}
            # 透传平台原始数据中的 chat_id，供语音/表情发送使用
            if "chat_id" in msg.raw_data:
                metadata["chat_id"] = msg.raw_data["chat_id"]
            if self.expressions:
                expression_path = await self.expressions.get_expression_async(text=full_content)
                if expression_path:
                    metadata["expression"] = str(expression_path)
                    logger.debug(f"[Pipeline] 流式输出检测到表情: {expression_path.name}")

            # TTS 合成语音回复
            if self.tts and self.voice_config and getattr(self.voice_config, "voice_response", False):
                voice_file = await self._synthesize_tts(full_content)
                if voice_file:
                    metadata["voice_file"] = voice_file

            return PlatformResponse(
                msg_id=msg.msg_id,
                content=full_content.strip(),
                reply=True,
                metadata=metadata,
            )

        except Exception as e:
            logger.warning(f"[Pipeline] 流式输出异常: {e}")
            return None

    async def _handle_image_message(self, msg: PlatformMessage) -> PlatformResponse | None:
        """处理图片/表情包消息，自动收藏到表情库"""
        file_path = msg.raw_data.get("file_path")
        if not file_path or not Path(file_path).exists():
            return None

        # 根据上下文推断情绪分类
        emotion = await self._detect_emotion_from_context(msg)

        # 保存到表情库
        try:
            file_data = Path(file_path).read_bytes()
            filename = Path(file_path).name
            saved_path = await self.expressions.save_user_expression(
                file_data=file_data,
                emotion=emotion,
                filename=filename,
            )
            if saved_path:
                logger.info(f"[Pipeline] 表情包已收藏: {emotion}/{saved_path.name}")
                return PlatformResponse(
                    msg_id=msg.msg_id,
                    content=f"已收藏到「{emotion}」表情包～",
                    reply=True,
                )
        except Exception as e:
            logger.error(f"[Pipeline] 收藏表情包失败: {e}")

        return None

    async def _handle_voice_message(
        self,
        msg: PlatformMessage,
        send_callback: "Any | None" = None,
    ) -> PlatformResponse | None:
        """处理语音消息：ASR 转文字 → 正常 pipeline 流程。"""
        audio_path = msg.raw_data.get("file_path") or msg.raw_data.get("voice_file")
        if not audio_path:
            logger.warning("[Pipeline] 语音消息缺少音频文件路径")
            return PlatformResponse(
                msg_id=msg.msg_id,
                content="语音消息缺少音频文件。",
                reply=True,
            )

        if not self.asr:
            logger.warning("[Pipeline] ASR 未配置")
            return PlatformResponse(
                msg_id=msg.msg_id,
                content="语音识别服务未启用。",
                reply=True,
            )

        # ASR 转录（支持情绪检测）
        try:
            if hasattr(self.asr, "recognize_with_emotion"):
                asr_result = await self.asr.recognize_with_emotion(audio_path)
                transcription = asr_result.get("text", "")
                emotion = asr_result.get("emotion", "neutral")
                msg.metadata["voice_emotion"] = emotion
                logger.info(f"[Pipeline] 语音情绪: {emotion}")
            else:
                transcription = await self.asr.recognize(audio_path)
        except Exception as e:
            logger.error(f"[Pipeline] ASR 失败: {e}")
            return PlatformResponse(
                msg_id=msg.msg_id,
                content="语音识别服务暂时不可用，请稍后再试。",
                reply=True,
            )

        if not transcription or not transcription.strip():
            logger.info("[Pipeline] ASR 转录为空")
            return PlatformResponse(
                msg_id=msg.msg_id,
                content="抱歉，没有听清你说的话。",
                reply=True,
            )

        # 用转录文本替换内容，降级为 TEXT 走正常流程
        logger.info(f"[Pipeline] 语音已转录: {transcription[:50]}")
        msg.metadata["transcription"] = transcription
        msg.content = transcription.strip()
        msg.msg_type = MessageType.TEXT

        return await self._process_text_message(msg, send_callback)

    async def _synthesize_tts(self, text: str) -> str | None:
        """将文字合成为语音文件，返回文件路径。"""
        import time as _time

        try:
            logger.info(f"[Pipeline] 开始 TTS 合成, 文本长度: {len(text)}")
            cache_dir = Path("./data/cache")
            cache_dir.mkdir(parents=True, exist_ok=True)
            output_path = str(cache_dir / f"voice_{int(_time.time())}_{id(text) % 10000}.mp3")

            result = await self.tts.synthesize(text, output_path)
            if result and Path(result).exists():
                file_size = Path(result).stat().st_size
                logger.info(f"[Pipeline] TTS 合成完成: {result} ({file_size} bytes)")
                return result
            else:
                logger.warning(f"[Pipeline] TTS 合成返回空结果: {result}")
        except Exception as e:
            logger.error(f"[Pipeline] TTS 合成失败: {e}")
        return None

    async def _detect_emotion_from_context(self, msg: PlatformMessage) -> str:
        """根据上下文推断表情包的情绪分类"""
        # 如果有文字描述，用文字检测
        if msg.content:
            emotion = self.expressions.detect_emotion(msg.content)
            if emotion:
                return emotion

        # 根据最近的对话上下文推断
        recent_messages = self.memory.get_context_messages(n=3)
        for recent_msg in reversed(recent_messages):
            if recent_msg.get("role") == "assistant":
                emotion = self.expressions.detect_emotion(recent_msg.get("content", ""))
                if emotion:
                    return emotion

        # 默认分类
        return "neutral"

    def _pre_filter(self, msg: PlatformMessage) -> bool:
        """前置过滤器"""
        f = self.config.filters
        if f.block_self and msg.user_id == "self":
            return False
        if f.block_bots and msg.raw_data.get("is_bot", False):
            return False
        content_len = len(msg.content.strip())
        if content_len < f.min_content_length:
            return False
        if content_len > f.max_content_length:
            logger.warning(f"消息过长 ({content_len} chars)，截断")
            msg.content = msg.content[: f.max_content_length]
        return True

    async def _build_context(self, msg: PlatformMessage) -> tuple[str, list[dict]]:
        """构建 AI 上下文（默认主动检索长期记忆）。"""
        if hasattr(self.memory, "build_context"):
            system_prompt, conversation = await self.memory.build_context(
                current_query=msg.content,
                system_prompt=self._build_system_prompt(),
                character_name=self.character.name,
                long_term_top_k=self.config.long_term_top_k,
                user_id=msg.user_id,
            )
        else:
            system_prompt = self._build_system_prompt()
            conversation = self.memory.get_context_messages(n=20)

        conversation.append({"role": "user", "content": msg.content})
        return system_prompt, conversation

    def _build_system_prompt(self) -> str:
        """从角色卡构建系统提示词"""
        from vir_bot.core.character import build_system_prompt

        ext = self.character.extensions
        return build_system_prompt(
            card=self.character,
            voice_style=ext.get("voice_style", ""),
            personality_tags=ext.get("personality_tags", []),
        )

    async def _handle_tool_calls(
        self,
        response: "AIResponse",
        system_prompt: str,
        tools_schema: list[dict],
        depth: int,
    ) -> "AIResponse":
        """处理工具调用"""
        if depth >= 2:
            return response

        calls = self.mcp.parse_tool_calls_from_response(response.content, tools_schema)
        if not calls:
            return response

        logger.info(f"检测到 {len(calls)} 个工具调用: {[c.name for c in calls]}")
        tool_results = await self.mcp.execute_all(calls)

        conversation = [{"role": "user", "content": "Please continue."}]
        tool_messages = []
        for call, result in zip(calls, tool_results):
            tool_messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": result.result}
            )

        try:
            new_response = await self.ai.chat(
                messages=conversation,
                system=system_prompt
                + "\n\n[Tool Results]\n"
                + "\n".join(f"Tool {tc['role']}: {tc['content']}" for tc in tool_messages),
            )
            return await self._handle_tool_calls(
                new_response,
                system_prompt,
                tools_schema,
                depth + 1,
            )
        except Exception as e:
            logger.error(f"工具调用后重推理失败: {e}")
            return response

    async def _update_memory(self, msg: PlatformMessage, response: "AIResponse") -> None:
        """更新记忆"""
        try:
            await self.memory.add_interaction(
                user_msg=msg.content,
                assistant_msg=response.content,
                metadata={
                    "platform": msg.platform.value,
                    "user_id": msg.user_id,
                    "msg_id": msg.msg_id,
                },
            )
        except Exception as e:
            logger.error(f"记忆更新失败: {e}")

    async def _update_memory_from_content(self, msg: PlatformMessage, content: str) -> None:
        """从字符串内容更新记忆（流式输出完成后调用）。"""
        try:
            await self.memory.add_interaction(
                user_msg=msg.content,
                assistant_msg=content,
                metadata={
                    "platform": msg.platform.value,
                    "user_id": msg.user_id,
                    "msg_id": msg.msg_id,
                },
            )
        except Exception as e:
            logger.error(f"记忆更新失败: {e}")
