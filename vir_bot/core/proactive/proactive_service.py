"""主动消息服务：整合牵挂引擎、评估、表达、节奏管理"""
from __future__ import annotations

import asyncio
import time
from enum import Enum
from typing import Any

from vir_bot.utils.logger import logger


class ConversationState(Enum):
    """对话状态机：控制主动消息的情绪和节奏"""
    IDLE = "idle"                   # 空闲，正常节奏
    WAITING = "waiting"             # 刚发了主动消息，等用户回复
    CONCERNED = "concerned"         # 等了一会没回，可以发一条关心
    WORRIED = "worried"            # 还没回，更急切
    BACK_OFF = "back_off"          # 发了很多都没回，用户可能在忙/睡了，停止


class ProactiveService:
    """主动消息总服务"""

    # 状态转移时间阈值（秒）
    WAIT_TO_CONCERNED = 10 * 60      # 发了消息后等 10 分钟没回 → 关心
    CONCERNED_TO_WORRIED = 20 * 60   # 关心后又等 20 分钟 → 着急
    WORRIED_TO_BACKOFF = 30 * 60     # 着急后又等 30 分钟 → 停止打扰
    BACK_OFF_RESET = 2 * 3600       # 停止 2 小时后重置回 IDLE

    def __init__(
        self,
        ai_provider: Any,
        memory_manager: Any,
        character_card: Any,
        config: Any,
        platform_adapters: dict | None = None,
    ):
        self._config = config.proactive
        self._platform_adapters = platform_adapters or {}
        self._running = False
        self._task = None

        if not self._config.enabled:
            self._enabled = False
            return

        self._enabled = True
        from vir_bot.core.proactive.state_tracker import StateTracker
        from vir_bot.core.proactive.concern_engine import ConcernEngine
        from vir_bot.core.proactive.evaluator import ConcernEvaluator
        from vir_bot.core.proactive.expression import ExpressionLayer
        from vir_bot.core.proactive.rhythm_manager import RhythmManager

        self._tracker = StateTracker(memory_manager, character_card)
        self._concern_engine = ConcernEngine(
            ai_provider, memory_manager, character_card, self._tracker, self._config
        )
        self._evaluator = ConcernEvaluator(ai_provider, self._config)
        self._expression = ExpressionLayer(ai_provider, character_card, memory_manager)
        self._rhythm = RhythmManager(self._config)

        # 从配置读取发送目标
        self._targets = self._config.targets if hasattr(self._config, "targets") else {}

        # 对话状态机
        self._conv_state: dict[str, ConversationState] = {}  # user_id -> state
        self._last_proactive_ts: dict[str, float] = {}       # user_id -> 最后一次主动消息时间
        self._last_user_msg_ts: dict[str, float] = {}        # user_id -> 最后一次用户消息时间
        self._proactive_count_since_reply: dict[str, int] = {}  # user_id -> 用户回复前发了几条

    # ------------------------------------------------------------------
    # 用户消息通知（由 pipeline 调用）
    # ------------------------------------------------------------------

    def on_user_message(self, user_id: str, message: str = "") -> None:
        """当用户发来消息时调用 — 更新状态机和追踪器"""
        if not self._enabled:
            return
        now = time.time()
        self._last_user_msg_ts[user_id] = now
        self._proactive_count_since_reply[user_id] = 0

        # 通知 StateTracker 和 RhythmManager
        self._tracker.update_from_message(user_id, message, direction="in")
        self._rhythm.record_interaction(user_id, initiator="user")

        # 用户回复了 → 状态回到 IDLE
        old_state = self._conv_state.get(user_id, ConversationState.IDLE)
        self._conv_state[user_id] = ConversationState.IDLE
        if old_state != ConversationState.IDLE:
            logger.info(f"[主动消息] 用户 {user_id} 回复了，状态 {old_state.value} → IDLE")

    def _get_conv_state(self, user_id: str) -> ConversationState:
        """获取用户的对话状态，自动处理状态转移"""
        state = self._conv_state.get(user_id, ConversationState.IDLE)
        now = time.time()

        if state == ConversationState.WAITING:
            elapsed = now - self._last_proactive_ts.get(user_id, 0)
            if elapsed > self.WAIT_TO_CONCERNED:
                self._conv_state[user_id] = ConversationState.CONCERNED
                logger.info(f"[主动消息] 用户 {user_id}: WAITING → CONCERNED ({elapsed:.0f}s)")
                return ConversationState.CONCERNED

        elif state == ConversationState.CONCERNED:
            elapsed = now - self._last_proactive_ts.get(user_id, 0)
            if elapsed > self.WAIT_TO_CONCERNED + self.CONCERNED_TO_WORRIED:
                self._conv_state[user_id] = ConversationState.WORRIED
                logger.info(f"[主动消息] 用户 {user_id}: CONCERNED → WORRIED ({elapsed:.0f}s)")
                return ConversationState.WORRIED

        elif state == ConversationState.WORRIED:
            elapsed = now - self._last_proactive_ts.get(user_id, 0)
            if elapsed > self.WAIT_TO_CONCERNED + self.CONCERNED_TO_WORRIED + self.WORRIED_TO_BACKOFF:
                self._conv_state[user_id] = ConversationState.BACK_OFF
                logger.info(f"[主动消息] 用户 {user_id}: WORRIED → BACK_OFF ({elapsed:.0f}s)")
                return ConversationState.BACK_OFF

        elif state == ConversationState.BACK_OFF:
            elapsed = now - self._last_proactive_ts.get(user_id, 0)
            if elapsed > self.BACK_OFF_RESET:
                self._conv_state[user_id] = ConversationState.IDLE
                logger.info(f"[主动消息] 用户 {user_id}: BACK_OFF → IDLE (重置)")
                return ConversationState.IDLE

        return state

    def _should_send_by_state(self, state: ConversationState) -> tuple[bool, str]:
        """根据对话状态判断是否允许发送"""
        if state == ConversationState.IDLE:
            return True, "空闲状态，可以主动发消息"
        if state == ConversationState.WAITING:
            return False, "正在等用户回复"
        if state == ConversationState.CONCERNED:
            return True, "用户没回，发一条关心"
        if state == ConversationState.WORRIED:
            count = 0
            # 取任意用户的 count（单用户场景）
            for c in self._proactive_count_since_reply.values():
                count = c
                break
            if count < 3:
                return True, "用户还没回，继续关心"
            return False, "已经发了几条了，等等"
        if state == ConversationState.BACK_OFF:
            return False, "用户可能在忙/睡了，停止打扰"
        return False, "未知状态"

    def _get_state_hint(self, state: ConversationState) -> str:
        """给 LLM 的状态提示"""
        hints = {
            ConversationState.IDLE: "你想主动找对方聊天。",
            ConversationState.CONCERNED: "你之前发了消息但对方没回，有点担心。",
            ConversationState.WORRIED: "你发了好几条消息对方都没回，很着急，想知道对方是不是出什么事了。",
        }
        return hints.get(state, "你想主动找对方聊天。")

    async def start(self) -> None:
        if not self._enabled:
            logger.info("主动消息系统未启用")
            return
        self._running = True
        self._task = asyncio.get_event_loop().create_task(self._concern_loop())
        logger.info("主动消息服务已启动")

    async def stop(self) -> None:
        if not self._enabled:
            return
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("主动消息服务已停止")

    async def _concern_loop(self) -> None:
        """完整的牵挂→评估→生成→发送循环"""
        while self._running:
            try:
                await self._run_once()
            except Exception as e:
                logger.error(f"主动消息循环错误: {e}")
            await asyncio.sleep(self._config.check_interval_seconds)

    async def _run_once(self) -> None:
        """执行一次完整流程"""
        # 1. 获取用户上下文
        context = await self._tracker.get_user_context(
            max_memories=self._config.expression.max_context_memories
        )
        user_id = context.get("user_id", "default")

        # 2. 对话状态机检查
        conv_state = self._get_conv_state(user_id)
        can_send, state_reason = self._should_send_by_state(conv_state)
        if not can_send:
            logger.debug(f"对话状态不允许发送: {state_reason}")
            return

        # 3. 节奏检查
        can_send, reason = self._rhythm.can_send(user_id)
        if not can_send:
            logger.debug(f"节奏检查未通过: {reason}")
            return

        # 4. 生成牵挂念头（传入状态提示）
        context["state_hint"] = self._get_state_hint(conv_state)
        thought = await self._concern_engine._generate_thought(context)
        if not thought or not thought.content:
            logger.debug("未生成牵挂念头")
            return

        # 5. 评估牵挂
        send, score, eval_reason = await self._evaluator.evaluate(thought, context)
        if not send:
            logger.debug(f"牵挂评估未通过: {eval_reason} (分数: {score:.2f})")
            return

        logger.info(f"牵挂通过评估: {eval_reason} (分数: {score:.2f})")

        # 6. 生成消息
        state = self._tracker.get_state(user_id)
        message = await self._expression.generate_message(thought, user_id, state)
        if not message:
            logger.warning("消息生成为空")
            return

        # 7. 发送消息
        await self._send_message(message)

        # 8. 记录状态
        self._rhythm.on_proactive_sent(user_id)
        self._tracker.update_proactive_sent(user_id)
        self._last_proactive_ts[user_id] = time.time()
        self._proactive_count_since_reply[user_id] = (
            self._proactive_count_since_reply.get(user_id, 0) + 1
        )

        # 发了主动消息 → 进入 WAITING
        if conv_state == ConversationState.IDLE:
            self._conv_state[user_id] = ConversationState.WAITING
            logger.info(f"[主动消息] 用户 {user_id}: IDLE → WAITING")

    async def _send_message(self, message: str) -> None:
        """通过平台适配器发送消息"""
        if not self._platform_adapters:
            logger.info(f"主动消息（无平台）: {message}")
            return

        for name, adapter in self._platform_adapters.items():
            target = self._targets.get(name, {})
            try:
                if hasattr(adapter, "send_proactive_message"):
                    await adapter.send_proactive_message(message, target)
                    logger.info(f"主动消息已通过 {name} 发送")
                elif hasattr(adapter, "send_message"):
                    # 构造 PlatformResponse 并调用 send_message
                    from vir_bot.core.pipeline import PlatformResponse, MessageType

                    response = PlatformResponse(
                        msg_id="",
                        content=message,
                        metadata=target,
                    )
                    await adapter.send_message(response)
                    logger.info(f"主动消息已通过 {name} 发送")
                else:
                    logger.warning(f"平台 {name} 不支持主动消息发送")
            except Exception as e:
                logger.error(f"通过 {name} 发送主动消息失败: {e}")

    def get_stats(self) -> dict:
        """获取服务统计"""
        if not self._enabled:
            return {"enabled": False}
        return {
            "enabled": True,
            "rhythm": self._rhythm.get_stats(),
        }
