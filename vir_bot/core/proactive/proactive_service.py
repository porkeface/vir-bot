"""主动消息服务 v3：动态调度 + 状态机 + 内容种子 + 情绪向量 + 质量门控"""
from __future__ import annotations

import asyncio
import time
from enum import Enum
from pathlib import Path
from typing import Any

from vir_bot.utils.logger import logger


class ConversationState(Enum):
    """对话状态机"""
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

    # 状态对应的每日限额和冷却
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
        self._fact_task = None

        if not self._config.enabled:
            self._enabled = False
            return

        self._enabled = True

        from vir_bot.core.proactive.state_tracker import StateTracker
        from vir_bot.core.proactive.scheduler import ProactiveScheduler
        from vir_bot.core.proactive.mood_model import MoodModel
        from vir_bot.core.proactive.seed_selector import SeedSelector
        from vir_bot.core.proactive.reflector import Reflector
        from vir_bot.core.proactive.expression import ExpressionLayer
        from vir_bot.core.proactive.fact_extractor import FactExtractor

        self._tracker = StateTracker(memory_manager, character_card)
        self._scheduler = ProactiveScheduler(self._config)
        self._mood_model = MoodModel()
        self._expression = ExpressionLayer(ai_provider, character_card, memory_manager)
        self._reflector = Reflector(ai_provider)

        # FactExtractor：后台提取事实
        data_dir = Path(config.app.data_dir) if hasattr(config, "app") else Path("data")
        fact_path = str(data_dir / "memory" / "facts.json")
        self._fact_extractor = FactExtractor(ai_provider, fact_path)
        self._seed_selector = SeedSelector(self._fact_extractor.store, memory_manager)

        self._targets = self._config.targets if hasattr(self._config, "targets") else {}

        # 对话状态
        self._last_user_msg_ts: dict[str, float] = {}
        self._first_unanswered_ts: dict[str, float] = {}
        self._proactive_count_since_reply: dict[str, int] = {}
        self._last_proactive_ts: dict[str, float] = {}
        self._daily_sent: dict[str, int] = {}
        self._daily_sent_date: str = ""
        self._recent_messages: dict[str, list[str]] = {}  # 最近发的消息（防重复）

        # AI provider 引用（FactExtractor 后台任务需要）
        self._ai_provider = ai_provider
        self._memory_manager = memory_manager

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
        # 后台事实提取任务
        self._fact_task = asyncio.get_event_loop().create_task(self._fact_extraction_loop())
        logger.info("主动消息服务已启动（动态调度模式）")

    async def stop(self) -> None:
        if not self._enabled:
            return
        self._running = False
        for task in [self._task, self._fact_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        logger.info("主动消息服务已停止")

    async def _fact_extraction_loop(self) -> None:
        """后台事实提取：每 6 小时从聊天记录中提取事实"""
        while self._running:
            try:
                await asyncio.sleep(6 * 3600)  # 6 小时
                # 从记忆系统获取最近对话
                if self._memory_manager and hasattr(self._memory_manager, "retrieval_router"):
                    memories = await self._memory_manager.retrieval_router.retrieve(
                        query="用户最近说的话", top_k=20
                    )
                    if memories:
                        messages = [{"role": "user", "content": m.content[:200]} for m in memories]
                        facts = await self._fact_extractor.extract_from_messages(messages)
                        if facts:
                            logger.info(f"[主动消息] 后台提取了 {len(facts)} 条事实")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[主动消息] 事实提取失败: {e}")

    async def _scheduler_loop(self) -> None:
        """动态调度主循环"""
        while self._running:
            try:
                user_id = "default"
                conv_state = self._get_conv_state(user_id)
                ctx = self._build_scheduler_context(user_id, conv_state)

                next_wake = self._scheduler.calculate_next_wake(ctx)
                sleep_seconds = max(10, next_wake - time.time())
                logger.info(
                    f"[主动消息] 下次唤醒: {sleep_seconds:.0f}s 后 "
                    f"(状态: {conv_state.value})"
                )

                try:
                    await asyncio.sleep(sleep_seconds)
                except asyncio.CancelledError:
                    continue

                # 预过滤
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

                # 状态机检查
                can_send, state_reason = self._should_send_by_state(conv_state)
                if not can_send:
                    logger.debug(f"[主动消息] 状态不允许: {state_reason}")
                    continue

                # LLM 管线
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
        """v3 LLM 管线：情绪 → 种子 → 生成 → 反思 → 发送"""

        # 1. 计算情绪向量
        mood = self._mood_model.compute(
            user_id=user_id,
            conv_state=conv_state.value,
            last_user_msg_ts=self._last_user_msg_ts.get(user_id, 0),
            last_proactive_ts=self._last_proactive_ts.get(user_id, 0),
            proactive_count=self._get_proactive_count(),
        )

        # 2. 选择内容种子
        seed = await self._seed_selector.select(
            mood_vector=mood.to_dict(),
            conv_state=conv_state.value,
            last_user_msg_ts=self._last_user_msg_ts.get(user_id, 0),
        )
        if not seed:
            logger.debug("[主动消息] 无可用内容种子")
            return

        logger.info(f"[主动消息] 选中种子: [{seed.seed_type}] {seed.content[:40]}...")

        # 3. 生成消息
        state_hint = self._get_state_hint(conv_state)
        message = await self._expression.generate_message(
            seed_content=seed.content,
            seed_context=seed.context,
            mood_directive=mood.style_directive,
            state_hint=state_hint,
            user_id=user_id,
        )
        if not message:
            logger.warning("[主动消息] 消息生成为空")
            return

        # 4. 质量门控（Reflector）
        recent = self._recent_messages.get(user_id, [])
        result = await self._reflector.reflect(
            message=message,
            seed_content=seed.content,
            mood_directive=mood.style_directive,
            recent_messages=recent,
        )
        if not result.approved:
            logger.info(f"[主动消息] Reflector 拒绝: {result.reason} (score={result.score:.2f})")
            # 尝试一次重试（换种子）
            seed2 = await self._seed_selector.select(
                mood_vector=mood.to_dict(),
                conv_state=conv_state.value,
                last_user_msg_ts=self._last_user_msg_ts.get(user_id, 0),
            )
            if seed2 and seed2.content != seed.content:
                message2 = await self._expression.generate_message(
                    seed_content=seed2.content,
                    seed_context=seed2.context,
                    mood_directive=mood.style_directive,
                    state_hint=state_hint,
                    user_id=user_id,
                )
                result2 = await self._reflector.reflect(
                    message=message2,
                    seed_content=seed2.content,
                    mood_directive=mood.style_directive,
                    recent_messages=recent,
                )
                if result2.approved:
                    message = message2
                    seed = seed2
                else:
                    logger.info(f"[主动消息] 重试也未通过: {result2.reason}")
                    return
            else:
                return

        # 5. 发送
        await self._send_message(message)

        # 6. 更新状态
        self._last_proactive_ts[user_id] = time.time()
        self._increment_daily_count(user_id)
        self._proactive_count_since_reply[user_id] = (
            self._proactive_count_since_reply.get(user_id, 0) + 1
        )

        # 记录最近消息（防重复）
        if user_id not in self._recent_messages:
            self._recent_messages[user_id] = []
        self._recent_messages[user_id].append(message)
        self._recent_messages[user_id] = self._recent_messages[user_id][-10:]

        if conv_state == ConversationState.IDLE:
            self._first_unanswered_ts[user_id] = time.time()
            logger.info(f"[主动消息] IDLE → 发出消息，开始计时")

        self._tracker.update_proactive_sent(user_id)

        # 标记种子已使用
        self._fact_extractor.store.mark_used(seed.content)

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
