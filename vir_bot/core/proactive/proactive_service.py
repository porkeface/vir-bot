"""主动消息服务 v3：动态调度 + 状态机 + 内容种子 + 情绪向量"""
from __future__ import annotations

import asyncio
import time
from enum import Enum
from typing import Any

from vir_bot.utils.logger import logger


class ConversationState(Enum):
    """对话状态机：控制主动消息的情绪和节奏"""
    IDLE = "idle"
    WAITING = "waiting"
    CONCERNED = "concerned"
    WORRIED = "worried"
    BACK_OFF = "back_off"


class ProactiveService:
    """主动消息总服务 v3"""

    # 状态转移时间阈值（秒）
    WAIT_TO_CONCERNED = 15 * 60
    CONCERNED_TO_WORRIED = 30 * 60
    WORRIED_TO_BACKOFF = 30 * 60
    BACK_OFF_RESET = 2 * 3600

    # 状态对应的每日限额和冷却（与 scheduler 保持一致）
    STATE_LIMITS = {
        ConversationState.IDLE:      (5, 7200),
        ConversationState.WAITING:   (3, 1800),
        ConversationState.CONCERNED: (2, 3600),
        ConversationState.WORRIED:   (1, 14400),
        ConversationState.BACK_OFF:  (0, 86400),
    }

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
        from vir_bot.core.proactive.scheduler import ProactiveScheduler

        self._tracker = StateTracker(memory_manager, character_card)
        self._concern_engine = ConcernEngine(
            ai_provider, memory_manager, character_card, self._tracker, self._config
        )
        self._evaluator = ConcernEvaluator(ai_provider, self._config)
        self._expression = ExpressionLayer(ai_provider, character_card, memory_manager)
        self._scheduler = ProactiveScheduler(self._config)

        self._targets = self._config.targets if hasattr(self._config, "targets") else {}

        # 对话状态
        self._last_user_msg_ts: dict[str, float] = {}
        self._first_unanswered_ts: dict[str, float] = {}
        self._proactive_count_since_reply: dict[str, int] = {}
        self._last_proactive_ts: dict[str, float] = {}
        self._daily_sent: dict[str, int] = {}
        self._daily_sent_date: str = ""

    # ------------------------------------------------------------------
    # 用户消息通知（由 pipeline 调用）
    # ------------------------------------------------------------------

    def on_user_message(self, user_id: str, message: str = "") -> None:
        """当用户发来消息时调用"""
        if not self._enabled:
            return
        now = time.time()
        self._last_user_msg_ts[user_id] = now
        self._proactive_count_since_reply[user_id] = 0
        self._first_unanswered_ts.pop(user_id, None)

        self._tracker.update_from_message(user_id, message, direction="in")

        logger.info(f"[主动消息] 用户 {user_id} 发来消息，状态重置为 IDLE")

        # 唤醒调度循环重新计算 sleep
        if self._task and not self._task.done():
            self._task.cancel()

    # ------------------------------------------------------------------
    # 状态机
    # ------------------------------------------------------------------

    def _get_conv_state(self, user_id: str) -> ConversationState:
        first_ts = self._first_unanswered_ts.get(user_id)
        if first_ts is None:
            return ConversationState.IDLE

        elapsed = time.time() - first_ts
        if elapsed < self.WAIT_TO_CONCERNED:
            return ConversationState.WAITING
        if elapsed < self.WAIT_TO_CONCERNED + self.CONCERNED_TO_WORRIED:
            return ConversationState.CONCERNED
        if elapsed < self.WAIT_TO_CONCERNED + self.CONCERNED_TO_WORRIED + self.WORRIED_TO_BACKOFF:
            return ConversationState.WORRIED
        return ConversationState.BACK_OFF

    def _should_send_by_state(self, state: ConversationState) -> tuple[bool, str]:
        if state == ConversationState.IDLE:
            return True, "空闲状态"
        if state == ConversationState.WAITING:
            return False, "正在等用户回复"
        if state == ConversationState.CONCERNED:
            count = self._get_proactive_count()
            if count < 2:
                return True, "用户没回，发一条关心"
            return False, "已经关心过了"
        if state == ConversationState.WORRIED:
            count = self._get_proactive_count()
            if count < 4:
                return True, "用户还没回，继续关心"
            return False, "已经发了几条了"
        if state == ConversationState.BACK_OFF:
            return False, "停止打扰"
        return False, "未知状态"

    def _get_proactive_count(self) -> int:
        for c in self._proactive_count_since_reply.values():
            return c
        return 0

    def _get_state_hint(self, state: ConversationState) -> str:
        hints = {
            ConversationState.IDLE: "你想主动找对方聊天。",
            ConversationState.CONCERNED: "你之前发了消息但对方没回，有点担心。",
            ConversationState.WORRIED: "你发了好几条消息对方都没回，很着急。",
        }
        return hints.get(state, "你想主动找对方聊天。")

    # ------------------------------------------------------------------
    # 每日计数
    # ------------------------------------------------------------------

    def _ensure_daily_count(self, user_id: str) -> int:
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        if self._daily_sent_date != today:
            self._daily_sent = {}
            self._daily_sent_date = today
        return self._daily_sent.get(user_id, 0)

    def _increment_daily_count(self, user_id: str) -> None:
        self._ensure_daily_count(user_id)
        self._daily_sent[user_id] = self._daily_sent.get(user_id, 0) + 1

    # ------------------------------------------------------------------
    # 主循环（动态调度）
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if not self._enabled:
            logger.info("主动消息系统未启用")
            return
        self._running = True
        self._task = asyncio.get_event_loop().create_task(self._scheduler_loop())
        logger.info("主动消息服务已启动（动态调度模式）")

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

    async def _scheduler_loop(self) -> None:
        """动态调度主循环：计算下次唤醒 → sleep → 检查 → 发送或跳过"""
        while self._running:
            try:
                # 1. 构建调度上下文
                user_id = "default"
                conv_state = self._get_conv_state(user_id)
                ctx = self._build_scheduler_context(user_id, conv_state)

                # 2. 计算下次唤醒时间
                next_wake = self._scheduler.calculate_next_wake(ctx)
                sleep_seconds = max(10, next_wake - time.time())
                logger.info(
                    f"[主动消息] 下次唤醒: {sleep_seconds:.0f}s 后 "
                    f"(状态: {conv_state.value})"
                )

                # 3. sleep（可被 on_user_message 打断）
                try:
                    await asyncio.sleep(sleep_seconds)
                except asyncio.CancelledError:
                    continue  # 被打断（用户发消息了），重新计算

                # 4. 预过滤（0 次 LLM）
                daily_sent = self._ensure_daily_count(user_id)
                filter_ctx = self._scheduler.build_filter_context(
                    user_id=user_id,
                    conv_state=conv_state.value,
                    last_proactive_ts=self._last_proactive_ts.get(user_id, 0),
                    last_user_msg_ts=self._last_user_msg_ts.get(user_id, 0),
                    daily_sent=daily_sent,
                    unanswered_count=self._get_proactive_count(),
                )
                passed, reason = self._scheduler.run_pre_filters(filter_ctx)
                if not passed:
                    logger.debug(f"[主动消息] 预过滤未通过: {reason}")
                    continue

                # 5. 状态机检查
                can_send, state_reason = self._should_send_by_state(conv_state)
                if not can_send:
                    logger.debug(f"[主动消息] 状态不允许: {state_reason}")
                    continue

                # 6. LLM 管线（ConcernEngine → Evaluator → Expression）
                await self._run_llm_pipeline(user_id, conv_state)

            except asyncio.CancelledError:
                continue
            except Exception as e:
                logger.error(f"[主动消息] 调度循环错误: {e}")
                await asyncio.sleep(60)

    def _build_scheduler_context(self, user_id: str, conv_state: ConversationState) -> dict:
        return {
            "user_id": user_id,
            "conv_state": conv_state.value,
            "last_user_msg_ts": self._last_user_msg_ts.get(user_id, 0),
            "first_unanswered_ts": self._first_unanswered_ts.get(user_id, 0),
            "last_proactive_ts": self._last_proactive_ts.get(user_id, 0),
        }

    async def _run_llm_pipeline(self, user_id: str, conv_state: ConversationState) -> None:
        """LLM 管线：生成 → 评估 → 表达 → 发送"""
        # 1. 获取上下文
        context = await self._tracker.get_user_context(
            max_memories=self._config.expression.max_context_memories
        )
        context["state_hint"] = self._get_state_hint(conv_state)

        # 2. 生成牵挂念头
        thought = await self._concern_engine._generate_thought(context)
        if not thought or not thought.content:
            logger.debug("[主动消息] 未生成牵挂念头")
            return

        # 3. 评估
        send, score, eval_reason = await self._evaluator.evaluate(thought, context)
        if not send:
            logger.debug(f"[主动消息] 评估未通过: {eval_reason} (分数: {score:.2f})")
            return

        logger.info(f"[主动消息] 通过评估: {eval_reason} (分数: {score:.2f})")

        # 4. 生成消息
        state = self._tracker.get_state(user_id)
        message = await self._expression.generate_message(thought, user_id, state)
        if not message:
            logger.warning("[主动消息] 消息生成为空")
            return

        # 5. 发送
        await self._send_message(message)

        # 6. 更新状态
        self._last_proactive_ts[user_id] = time.time()
        self._increment_daily_count(user_id)
        self._proactive_count_since_reply[user_id] = (
            self._proactive_count_since_reply.get(user_id, 0) + 1
        )

        if conv_state == ConversationState.IDLE:
            self._first_unanswered_ts[user_id] = time.time()
            logger.info(f"[主动消息] IDLE → 发出消息，开始计时")

        self._tracker.update_proactive_sent(user_id)

    # ------------------------------------------------------------------
    # 发送
    # ------------------------------------------------------------------

    async def _send_message(self, message: str) -> None:
        if not self._platform_adapters:
            logger.info(f"[主动消息] 无平台: {message}")
            return

        for name, adapter in self._platform_adapters.items():
            target = self._targets.get(name, {})
            try:
                if hasattr(adapter, "send_proactive_message"):
                    await adapter.send_proactive_message(message, target)
                    logger.info(f"[主动消息] 已通过 {name} 发送")
                elif hasattr(adapter, "send_message"):
                    from vir_bot.core.pipeline import PlatformResponse
                    response = PlatformResponse(msg_id="", content=message, metadata=target)
                    await adapter.send_message(response)
                    logger.info(f"[主动消息] 已通过 {name} 发送")
            except Exception as e:
                logger.error(f"[主动消息] {name} 发送失败: {e}")

    def get_stats(self) -> dict:
        if not self._enabled:
            return {"enabled": False}
        return {"enabled": True, "mode": "dynamic_scheduler"}
