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

from vir_bot.modules.voice import _parse_voice_decision, _build_style_hint, convert_audio
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

        # 工作记忆 & 关系阶段（P0/P1 增强）
        from vir_bot.core.character import WorkingMemory, NarrativeSummary
        self._working_memory: dict[str, WorkingMemory] = {}  # user_id -> WorkingMemory
        self._narrative_summaries: dict[str, NarrativeSummary] = {}  # user_id -> NarrativeSummary
        self._turn_counts: dict[str, int] = {}  # user_id -> turn count

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

        # 解析 [VOICE] 标记
        from vir_bot.modules.voice import analyze_voice_suitability

        content, use_voice_tag = _parse_voice_decision(response.content)

        # 根据 voice_decision 决定是否合成语音
        voice_decision = getattr(self.voice_config, "voice_decision", "always")
        if voice_decision == "never":
            should_synthesize = False
        elif voice_decision == "always":
            should_synthesize = self.tts is not None and self.voice_config is not None
        elif voice_decision == "ai":
            if self.tts is None or self.voice_config is None:
                should_synthesize = False
            else:
                suitable, reason = analyze_voice_suitability(content)
                should_synthesize = suitable
                if should_synthesize:
                    logger.info(f"[Pipeline] AI 决策: 语音 (reason={reason})")
                else:
                    logger.info(f"[Pipeline] AI 决策: 文本 (reason={reason})")
        else:
            should_synthesize = False

        # 语音模式
        voice_mode = getattr(self.voice_config, "voice_mode", "both") if self.voice_config else "both"

        voice_file = None
        if should_synthesize:
            style = _build_style_hint(self.character, self.voice_config)
            voice_file = await self._synthesize_tts(content, style)
            if voice_file and self.voice_config.tts.output_format != "wav":
                ogg_path = voice_file.rsplit(".", 1)[0] + ".ogg"
                converted = await convert_audio(
                    voice_file, ogg_path,
                    self.voice_config.tts.output_format,
                    self.voice_config.tts.ffmpeg_path,
                )
                if converted:
                    voice_file = converted

        metadata["voice_file"] = voice_file
        metadata["use_voice"] = should_synthesize
        metadata["voice_mode"] = voice_mode

        return PlatformResponse(
            msg_id=msg.msg_id,
            content=content,
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
        """流式处理：逐句生成并发送。返回 None 表示回退到普通模式。

        AI 决策模式下，流式开始时缓冲文本等待 [VOICE] 标记：
        - 检测到首行 [VOICE] → 语音模式，继续缓冲，结束后合成语音
        - 未检测到 → 文本模式，释放缓冲，即时流式发送
        - 2 秒超时 → 降级为文本模式
        """
        from vir_bot.modules.voice import analyze_voice_suitability

        voice_decision = getattr(self.voice_config, "voice_decision", "always") if self.voice_config else "always"
        voice_mode = getattr(self.voice_config, "voice_mode", "replace") if self.voice_config else "replace"

        # always 模式：始终缓冲等语音；ai 模式：缓冲后内容分析决策；其他：即时发文本
        should_buffer = (
            voice_decision in ("always", "ai")
            and self.tts is not None
            and self.voice_config is not None
            and voice_mode == "replace"
        )

        try:
            buffer = ""
            full_content = ""
            chunk_count = 0
            timeout_seconds = 20  # 单个 chunk 超时

            buffered_lines: list[str] = []

            logger.info(f"[Pipeline] 开始流式 AI 调用... (voice_decision={voice_decision}, buffer={should_buffer})")
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

                    # 按换行拆分
                    while "\n" in buffer:
                        nl_pos = buffer.find("\n")
                        line = buffer[:nl_pos].strip()
                        buffer = buffer[nl_pos + 1:]
                        if line:
                            clean_line = line.replace("[VOICE]", "").strip()
                            if clean_line:
                                if should_buffer:
                                    buffered_lines.append(clean_line)
                                else:
                                    await send_callback(
                                        PlatformResponse(msg_id=msg.msg_id, content=clean_line, reply=True)
                                    )
            except Exception as e:
                logger.warning(f"[Pipeline] 流式读取异常: {e}")

            # 处理剩余内容
            if buffer.strip():
                clean_buffer = buffer.strip().replace("[VOICE]", "").strip()
                if clean_buffer:
                    if should_buffer:
                        buffered_lines.append(clean_buffer)
                    else:
                        await send_callback(
                            PlatformResponse(msg_id=msg.msg_id, content=clean_buffer, reply=True)
                        )

            logger.info(f"[Pipeline] 流式循环结束, chunks={chunk_count}, 总长度={len(full_content)}")

            if not full_content.strip():
                return None

            # 解析 [VOICE] 标记（兼容旧格式）
            content, use_voice_tag = _parse_voice_decision(full_content)

            # 语音决策
            if voice_decision == "always":
                decided_voice = True
            elif voice_decision == "ai":
                # 内容分析决策：内容适合语音就用语音，[VOICE] 标记作为额外信号
                suitable, reason = analyze_voice_suitability(content)
                decided_voice = suitable
                if decided_voice:
                    logger.info(f"[Pipeline] AI 决策: 语音 (reason={reason})")
                else:
                    logger.info(f"[Pipeline] AI 决策: 文本 (reason={reason})")
            else:
                decided_voice = False

            # 检测情绪并获取表情
            metadata = {"already_streamed": True}
            if "chat_id" in msg.raw_data:
                metadata["chat_id"] = msg.raw_data["chat_id"]
            if self.expressions:
                expression_path = await self.expressions.get_expression_async(text=content)
                if expression_path:
                    metadata["expression"] = str(expression_path)
                    logger.debug(f"[Pipeline] 流式输出检测到表情: {expression_path.name}")

            # 语音合成
            voice_file = None
            if decided_voice and should_buffer:
                style = _build_style_hint(self.character, self.voice_config)
                voice_file = await self._synthesize_tts(content, style)
                if voice_file and self.voice_config.tts.output_format != "wav":
                    ogg_path = voice_file.rsplit(".", 1)[0] + ".ogg"
                    converted = await convert_audio(
                        voice_file, ogg_path,
                        self.voice_config.tts.output_format,
                        self.voice_config.tts.ffmpeg_path,
                    )
                    if converted:
                        voice_file = converted

            metadata["voice_file"] = voice_file
            metadata["use_voice"] = decided_voice
            metadata["voice_mode"] = voice_mode

            if should_buffer:
                if decided_voice and voice_file:
                    # 语音成功 → 只发语音，丢弃缓冲文本
                    logger.info(f"[Pipeline] 语音合成成功，丢弃 {len(buffered_lines)} 条缓冲文本")
                else:
                    # 文本模式或语音失败 → 补发缓冲文本
                    reason = "语音失败" if decided_voice else "AI 选择文本"
                    logger.info(f"[Pipeline] {reason}，发送 {len(buffered_lines)} 条缓冲文本")
                    for line in buffered_lines:
                        await send_callback(
                            PlatformResponse(msg_id=msg.msg_id, content=line, reply=True)
                        )
                    metadata["voice_file"] = None

            return PlatformResponse(
                msg_id=msg.msg_id,
                content=content,
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

    async def _synthesize_tts(self, text: str, style_hint: str = "") -> str | None:
        """合成语音"""
        try:
            import hashlib
            import time as _time

            text_hash = hashlib.md5(text.encode()).hexdigest()[:8]
            output_path = f"./data/cache/voice_{int(_time.time())}_{text_hash}.wav"
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            return await self.tts.synthesize(text, output_path, style_hint=style_hint)
        except Exception as e:
            logger.error(f"TTS synthesis failed: {e}")
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
        # 更新轮次计数
        self._turn_counts[msg.user_id] = self._turn_counts.get(msg.user_id, 0) + 1

        if hasattr(self.memory, "build_context"):
            system_prompt, conversation = await self.memory.build_context(
                current_query=msg.content,
                system_prompt=self._build_system_prompt(user_id=msg.user_id),
                character_name=self.character.name,
                long_term_top_k=self.config.long_term_top_k,
                user_id=msg.user_id,
            )
        else:
            system_prompt = self._build_system_prompt(user_id=msg.user_id)
            conversation = self.memory.get_context_messages(n=20)

        # 检测用户语音偏好并注入 system prompt
        preference = self._detect_voice_preference(conversation)
        if preference:
            hint = "\n用户最近表示想听你用语音说话。" if preference == "voice" else "\n用户最近表示想看你打字。"
            system_prompt = system_prompt + hint

        conversation.append({"role": "user", "content": msg.content})
        return system_prompt, conversation

    @staticmethod
    def _detect_voice_preference(conversation: list[dict]) -> str | None:
        """从最近的用户消息中检测语音偏好。返回 'voice' | 'text' | None。"""
        recent = [m for m in conversation[-6:] if m.get("role") == "user"][-3:]
        for m in recent:
            content = m.get("content", "")
            if any(kw in content for kw in ("发语音", "语音说", "说给我听", "用语音")):
                return "voice"
            if any(kw in content for kw in ("打字", "文字", "别发语音", "看文字")):
                return "text"
        return None

    def _build_system_prompt(self, user_id: str = "default") -> str:
        """从角色卡构建增强版 7 层系统提示词"""
        from vir_bot.core.character import build_system_prompt

        ext = self.character.extensions

        # AI 语音决策指引（仅 ai 模式注入）
        voice_preference = ""
        voice_decision = getattr(self.voice_config, "voice_decision", "always") if self.voice_config else "always"
        if voice_decision == "ai":
            voice_preference = (
                "关于语音和文字的选择——你有一种直觉，像真人朋友聊天时的感觉：\n"
                "大部分时候你习惯打字，这是你的默认状态。但有些时刻，你会觉得「这句话用语音说出来更好」：\n"
                "- 你在撒娇、安慰、表达开心或者带点小情绪的时候，声音比文字更有温度\n"
                "- 你想说的内容很短很随意，两三句话的事，打字反而显得正式\n"
                "- 你犹豫了一下、或者想用反问/感叹的语气，文字很难传递那个味道\n"
                "- 你就是突然想发语音了，没有特别的理由，就像人有时候就是不想打字\n"
                "\n"
                "反过来，你会坚持打字的情况：\n"
                "- 内容比较长，或者有条理的信息（对方需要回看的那种）\n"
                "- 你发了两三条语音了，再发语音就像刷屏了\n"
                "- 对方明确说了想看文字或者想听语音，尊重对方的偏好\n"
                "\n"
                "用法：当你决定这条回复用语音时，在回复的最开头单独放一行标记：\n"
                "[VOICE]\n"
                "然后空一行再写你要说的内容。不要在其他地方提这个标记，它只是一个内部信号。\n"
                "如果你决定用文字，就像平时一样回复，什么都不用加。"
            )

        # 获取用户的工作记忆和叙事摘要
        working_memory = self._working_memory.get(user_id)
        narrative_summary = self._narrative_summaries.get(user_id)

        # 计算关系阶段（基于交互轮数，阈值可配置）
        thresholds = ext.get("relationship_thresholds", {})
        stranger_max = thresholds.get("stranger", 10)
        acquaintance_max = thresholds.get("acquaintance", 30)
        friend_max = thresholds.get("friend", 80)

        turn_count = self._turn_counts.get(user_id, 0)
        if turn_count < stranger_max:
            relationship_stage = "stranger"
        elif turn_count < acquaintance_max:
            relationship_stage = "acquaintance"
        elif turn_count < friend_max:
            relationship_stage = "friend"
        else:
            relationship_stage = "close"

        system_prompt = build_system_prompt(
            card=self.character,
            voice_style=ext.get("voice_style", ""),
            personality_tags=ext.get("personality_tags", []),
            voice_preference=voice_preference,
            working_memory=working_memory,
            relationship_stage=relationship_stage,
            narrative_summary=narrative_summary,
        )

        return system_prompt

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
        """更新记忆 + 工作记忆"""
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
            # 更新工作记忆
            self._update_working_memory(msg.user_id, msg.content, response.content)
            # 异步更新叙事摘要（不阻塞回复）
            asyncio.create_task(self._maybe_update_narrative(msg.user_id))
        except Exception as e:
            logger.error(f"记忆更新失败: {e}")

    def _update_working_memory(
        self, user_id: str, user_msg: str, assistant_msg: str
    ) -> None:
        """基于最新一轮对话更新工作记忆（轻量级，不调用 LLM）。"""
        import re as _re

        from vir_bot.core.character import WorkingMemory

        wm = self._working_memory.get(user_id)
        if wm is None:
            wm = WorkingMemory()
            self._working_memory[user_id] = wm

        # 简单的关键词提取更新话题
        if len(user_msg) > 5:
            wm.current_topic = user_msg[:50]

        # 检测问题
        if "?" in user_msg or "？" in user_msg:
            questions = [s.strip() for s in user_msg.replace("？", "?").split("?") if s.strip()]
            wm.pending_questions = questions[-3:]

        # 提取实体（2-4字中文名词短语，排除常见停用词）
        _stopwords = {
            "什么", "怎么", "为什么", "可以", "不是", "但是", "因为", "所以",
            "这个", "那个", "一个", "还是", "就是", "不是", "已经", "可能",
            "应该", "觉得", "知道", "没有", "其实", "然后", "不过", "如果",
        }
        entities = _re.findall(r'[一-鿿]{2,4}', user_msg)
        wm.mentioned_entities = [e for e in entities if e not in _stopwords][-5:]

        # 检测情绪关键词
        emotion_keywords = {
            "开心": "happy", "高兴": "happy", "哈哈": "happy",
            "难过": "sad", "伤心": "sad", "哭": "sad",
            "生气": "angry", "烦": "angry", "气死": "angry",
            "累": "tired", "困": "tired", "疲惫": "tired",
            "无聊": "bored", "寂寞": "lonely", "想你": "missing",
        }
        for cn, en in emotion_keywords.items():
            if cn in user_msg:
                wm.user_emotion = en
                break

        wm.updated_at = time.time()

    async def _maybe_update_narrative(self, user_id: str) -> None:
        """每隔 N 轮更新叙事摘要。"""
        from vir_bot.core.character import NarrativeSummary

        turn_count = self._turn_counts.get(user_id, 0)
        ns = self._narrative_summaries.get(user_id)

        if ns is None:
            ns = NarrativeSummary()
            self._narrative_summaries[user_id] = ns

        if not ns.needs_update(turn_count):
            return

        # 获取最近的对话
        recent = self.memory.short_term.get_recent(10)
        if len(recent) < 3:
            return

        conversation_text = "\n".join(
            f"{'用户' if m.role == 'user' else '助手'}: {m.content}"
            for m in recent
        )

        try:
            response = await self.ai.chat(
                messages=[{"role": "user", "content": f"""当前叙事摘要:
{ns.summary or '(无)'}

最近对话:
{conversation_text}

请更新叙事摘要。用第三人称记录对话的关键事件和情感发展，200字以内。
不要分析，不要总结，像讲故事一样描述发生了什么。"""}],
                system="你是叙事记录者。用第三人称记录对话的关键事件和情感发展。",
                temperature=0.3,
            )
            ns.summary = response.content.strip()
            ns.last_update_turn = turn_count
            logger.info(f"[Narrative] 叙事摘要已更新: {ns.summary[:60]}...")
        except Exception as e:
            logger.warning(f"[Narrative] 叙事摘要更新失败: {e}")

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
            # 更新工作记忆
            self._update_working_memory(msg.user_id, msg.content, content)
            # 异步更新叙事摘要（不阻塞回复）
            asyncio.create_task(self._maybe_update_narrative(msg.user_id))
        except Exception as e:
            logger.error(f"记忆更新失败: {e}")
