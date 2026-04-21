"""消息处理管道"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from vir_bot.core.ai_provider import AIProvider, AIResponse
    from vir_bot.core.memory.memory_manager import MemoryManager
    from vir_bot.core.character import CharacterCard
    from vir_bot.core.mcp import ToolRegistry, ToolCall
    from vir_bot.config import PipelineConfig

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

    def to_messages(self) -> list[dict]:
        return [{"role": "user", "content": self.content}]


@dataclass
class PlatformResponse:
    """回复结构"""
    msg_id: str
    content: str
    reply: bool = True
    quote: bool = False


# =============================================================================
# 频率限制器
# =============================================================================


class RateLimiter:
    def __init__(self, per_user: int = 20, per_group: int = 60):
        self.per_user = per_user
        self.per_group = per_group
        self._user_timestamps: dict[str, list[float]] = {}
        self._group_timestamps: dict[str, list[float]] = {}

    async def check(self, msg: PlatformMessage) -> bool:
        now = time.time()
        window = 60.0

        # 检查用户频率
        uid = msg.user_id
        if uid not in self._user_timestamps:
            self._user_timestamps[uid] = []
        ts = self._user_timestamps[uid]
        ts[:] = [t for t in ts if now - t < window]
        ts.append(now)
        if len(ts) > self.per_user:
            logger.warning(f"用户 {uid} 超过频率限制")
            return False

        # 检查群频率（如果适用）
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


# =============================================================================
# 消息处理管道（核心编排器）
# =============================================================================


class MessagePipeline:
    """
    消息处理管道。
    接收 PlatformMessage → 上下文构建 → AI 推理 → MCP 工具调用 → 返回 PlatformResponse
    """

    def __init__(
        self,
        ai_provider: "AIProvider",
        memory_manager: "MemoryManager",
        character_card: "CharacterCard",
        mcp_registry: "ToolRegistry",
        config: "PipelineConfig",
    ):
        self.ai = ai_provider
        self.memory = memory_manager
        self.character = character_card
        self.mcp = mcp_registry
        self.config = config
        self._rate_limiter = RateLimiter()

    async def process(self, msg: PlatformMessage) -> PlatformResponse | None:
        """主入口：处理一条消息"""
        # 前置过滤
        if not self._pre_filter(msg):
            return None

        # 频率控制
        if not await self._rate_limiter.check(msg):
            return PlatformResponse(msg_id=msg.msg_id, content="[消息过于频繁，请稍后再试]", reply=True)

        # 构建上下文（角色卡 + 记忆）
        system_prompt, conversation = await self._build_context(msg)

        # 获取 MCP tools schema
        tools_schema = self.mcp.get_tools_schemas()

        # AI 推理（带重试）
        response: "AIResponse" | None = None
        for attempt in range(3):
            try:
                response = await self.ai.chat(
                    messages=conversation,
                    system=system_prompt,
                    tools=tools_schema if tools_schema else None,
                )
                break
            except Exception as e:
                logger.error(f"AI 调用失败 (attempt {attempt + 1}): {e}")
                if attempt == 2:
                    return PlatformResponse(
                        msg_id=msg.msg_id, content="抱歉，AI 服务暂时不可用。", reply=True
                    )
                await asyncio.sleep(2**attempt)

        if response is None:
            return None

        # 处理工具调用（最多递归2层）
        response = await self._handle_tool_calls(response, system_prompt, tools_schema, depth=0)

        # 记忆写入（异步，不阻塞）
        asyncio.create_task(self._update_memory(msg, response))

        return PlatformResponse(msg_id=msg.msg_id, content=response.content, reply=True)

    def _pre_filter(self, msg: PlatformMessage) -> bool:
        """前置过滤器"""
        f = self.config.filters
        if f.block_self and msg.user_id == "self":
            return False
        if not f.block_bots and msg.raw_data.get("is_bot", False):
            return False
        content_len = len(msg.content.strip())
        if content_len < f.min_content_length:
            return False
        if content_len > f.max_content_length:
            logger.warning(f"消息过长 ({content_len} chars)，截断")
            msg.content = msg.content[: f.max_content_length]
        return True

    async def _build_context(self, msg: PlatformMessage) -> tuple[str, list[dict]]:
        """构建 AI 上下文"""
        # 系统提示词（含记忆注入）
        system_prompt = self._build_system_prompt()
        # 对话历史
        conversation = self.memory.get_context_messages()
        # 追加当前消息
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

        # 尝试从响应中解析工具调用
        from vir_bot.core.mcp import ToolCall

        calls = self.mcp.parse_tool_calls_from_response(response.content, tools_schema)
        if not calls:
            return response

        logger.info(f"检测到 {len(calls)} 个工具调用: {[c.name for c in calls]}")

        # 执行工具
        tool_results = await self.mcp.execute_all(calls)

        # 将结果追加到对话
        conversation = [{"role": "user", "content": "Please continue."}]
        tool_messages = []
        for call, result in zip(calls, tool_results):
            tool_messages.append({"role": "tool", "tool_call_id": call.id, "content": result.result})

        # 重新推理
        try:
            new_response = await self.ai.chat(
                messages=conversation,
                system=system_prompt + "\n\n[Tool Results]\n" + "\n".join(
                    f"Tool {tc.role}: {tc.content}" for tc in tool_messages
                ),
            )
            return await self._handle_tool_calls(new_response, system_prompt, tools_schema, depth + 1)
        except Exception as e:
            logger.error(f"工具调用后重推理失败: {e}")
            return response

    async def _update_memory(self, msg: PlatformMessage, response: "AIResponse") -> None:
        """更新记忆"""
        try:
            await self.memory.add_interaction(
                user_msg=msg.content,
                assistant_msg=response.content,
                metadata={"platform": msg.platform.value, "user_id": msg.user_id},
            )
        except Exception as e:
            logger.error(f"记忆更新失败: {e}")