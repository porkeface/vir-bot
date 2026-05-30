"""主动消息服务 v4：内驱力 + 灵感触发 + 自然判断"""
from __future__ import annotations

import asyncio
import time
from enum import Enum
from pathlib import Path
from typing import Any

from vir_bot.utils.logger import logger


class ConversationState(Enum):
    """简化状态机（v4: 大部分行为由驱动力涌现）"""
    IDLE = "idle"
    RECENTLY_SENT = "recently_sent"


class ProactiveService:
    """主动消息总服务 v4：内驱力驱动"""

    # RECENTLY_SENT 状态的最短持续时间（秒）
    # 发消息后短时间内不再触发，避免刷屏
    RECENTLY_SENT_COOLDOWN = 1200  # 20 分钟

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

        from vir_bot.core.proactive.drive_system import DriveSystem
        from vir_bot.core.proactive.inspiration_trigger import InspirationTrigger, InspirationScheduler, ContextSnapshot
        from vir_bot.core.proactive.seed_selector import SeedSelector
        from vir_bot.core.proactive.reflector import Reflector
        from vir_bot.core.proactive.expression import ExpressionLayer
        from vir_bot.core.proactive.fact_extractor import FactExtractor

        self._drives = DriveSystem()
        self._inspiration = InspirationTrigger(ai_provider, character_card)
        self._scheduler = InspirationScheduler()
        self._expression = ExpressionLayer(ai_provider, character_card, memory_manager)
        self._reflector = Reflector(ai_provider)

        data_dir = Path(config.app.data_dir) if hasattr(config, "app") else Path("data")
        fact_path = str(data_dir / "memory" / "facts.json")
        self._fact_extractor = FactExtractor(ai_provider, fact_path)
        self._seed_selector = SeedSelector(self._fact_extractor.store, memory_manager)

        self._targets = self._config.targets if hasattr(self._config, "targets") else {}

        # 用户状态
        self._last_user_msg_ts: dict[str, float] = {}
        self._last_user_msg_content: dict[str, str] = {}
        self._last_proactive_ts: dict[str, float] = {}
        self._daily_sent: dict[str, int] = {}
        self._daily_sent_date: str = ""
        self._recent_messages: dict[str, list[str]] = {}
        self._proactive_count_unanswered: dict[str, int] = {}

        # AI provider 引用
        self._ai_provider = ai_provider
        self._memory_manager = memory_manager
        self._character_card = character_card

    # ------------------------------------------------------------------
    # 用户消息通知（由 pipeline 调用）
    # ------------------------------------------------------------------

    def on_user_message(self, user_id: str, message: str = "") -> None:
        """当用户发来消息时调用"""
        if not self._enabled:
            return
        now = time.time()
        self._last_user_msg_ts[user_id] = now
        self._last_user_msg_content[user_id] = message
        self._proactive_count_unanswered[user_id] = 0

        # 通知驱动力系统
        self._drives.on_user_reply()

        logger.info(f"[v4] 用户 {user_id} 发来消息，驱动力更新")

        # 唤醒调度循环重新计算
        if self._task and not self._task.done():
            self._task.cancel()

    # ------------------------------------------------------------------
    # 状态管理
    # ------------------------------------------------------------------

    def _get_conv_state(self, user_id: str) -> ConversationState:
        last_proactive = self._last_proactive_ts.get(user_id, 0)
        if last_proactive > 0:
            elapsed = time.time() - last_proactive
            if elapsed < self.RECENTLY_SENT_COOLDOWN:
                return ConversationState.RECENTLY_SENT
        return ConversationState.IDLE

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
    # 主循环（v4: 驱动力 + 灵感触发）
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if not self._enabled:
            logger.info("主动消息系统未启用")
            return
        self._running = True
        self._task = asyncio.create_task(self._inspiration_loop())
        self._fact_task = asyncio.create_task(self._fact_extraction_loop())
        logger.info("v4 主动消息服务已启动（内驱力 + 灵感触发）")

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
        logger.info("v4 主动消息服务已停止")

    async def _fact_extraction_loop(self) -> None:
        """后台事实提取：每 6 小时从聊天记录中提取事实"""
        while self._running:
            try:
                await asyncio.sleep(6 * 3600)
                if self._memory_manager and hasattr(self._memory_manager, "retrieval_router"):
                    memories = await self._memory_manager.retrieval_router.retrieve(
                        query="用户最近说的话", user_id="default", top_k=20
                    )
                    if memories:
                        messages = [{"role": "user", "content": m.content[:200]} for m in memories]
                        facts = await self._fact_extractor.extract_from_messages(messages)
                        if facts:
                            logger.info(f"[v4] 后台提取了 {len(facts)} 条事实")
                            self._drives.on_new_facts_available()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[v4] 事实提取失败: {e}")

    async def _inspiration_loop(self) -> None:
        """v4 主循环：驱动力积累 → 概率触发 → LLM 灵感判断 → 发送"""
        user_id = "default"

        while self._running:
            try:
                # 1. 获取驱动力快照
                drives = self._drives.snapshot()

                # 2. 计算下次灵感时间
                next_wake = self._scheduler.next_wake(drives)
                sleep_seconds = max(10, next_wake - time.time())

                logger.info(
                    f"[v4] 驱动力: loneliness={drives.loneliness:.2f} "
                    f"curiosity={drives.curiosity:.2f} care={drives.care_drive:.2f} "
                    f"| 下次灵感: {sleep_seconds:.0f}s 后"
                )

                # 3. sleep（可被用户消息打断）
                try:
                    await asyncio.sleep(sleep_seconds)
                except asyncio.CancelledError:
                    continue

                # 4. 概率快速过滤（0 LLM 成本）
                should, prob = self._drives.should_consider_sending(drives)
                if not should:
                    continue

                # 5. 状态检查
                state = self._get_conv_state(user_id)
                if state == ConversationState.RECENTLY_SENT:
                    logger.debug("[v4] 刚发过消息，跳过")
                    continue

                # 每日上限检查（粗粒度保护）
                daily_sent = self._ensure_daily_count(user_id)
                if daily_sent >= self._config.max_daily_messages:
                    logger.debug(f"[v4] 今日已发 {daily_sent} 条，达到上限")
                    continue

                # 6. LLM 灵感判断
                from vir_bot.core.proactive.inspiration_trigger import ContextSnapshot
                ctx = ContextSnapshot(
                    last_user_msg_ts=self._last_user_msg_ts.get(user_id, 0),
                    last_user_msg_content=self._last_user_msg_content.get(user_id, ""),
                    last_proactive_ts=self._last_proactive_ts.get(user_id, 0),
                    proactive_count_today=daily_sent,
                    proactive_count_unanswered=self._proactive_count_unanswered.get(user_id, 0),
                    recent_sent_messages=self._recent_messages.get(user_id, []),
                )

                inspire = await self._inspiration.should_inspire(drives, ctx)
                if not inspire.want_to_send:
                    logger.info(f"[v4] 灵感未触发: {inspire.reason[:50]}")
                    continue

                logger.info(f"[v4] 灵感触发! {inspire.reason[:50]}")

                # 7. 运行消息管线
                await self._run_pipeline(
                    user_id=user_id,
                    drives=drives,
                    inspire=inspire,
                    context=ctx,
                )

            except asyncio.CancelledError:
                continue
            except Exception as e:
                logger.error(f"[v4] 灵感循环错误: {e}")
                await asyncio.sleep(60)

    async def _run_pipeline(
        self,
        user_id: str,
        drives: Any,
        inspire: Any,
        context: Any,
    ) -> None:
        """v4 管线：种子 → 生成 → 反思 → 发送"""

        # 1. 选择内容种子
        seed = await self._seed_selector.select(
            mood_vector={"care": drives.care_drive, "joy": 0.5, "clingy": drives.loneliness * 0.5, "irritated": 0.0, "sad": 0.0},
            last_user_msg_ts=context.last_user_msg_ts,
            user_id=user_id,
        )
        if not seed:
            logger.debug("[v4] 无可用内容种子")
            return

        logger.info(f"[v4] 选中种子: [{seed.seed_type}] {seed.content[:40]}...")

        # 2. 生成消息
        # 构建情绪风格指令（从驱动力推导）
        mood_directive = self._drives_to_mood_directive(drives, inspire)

        message = await self._expression.generate_message(
            seed_content=seed.content,
            seed_context=seed.context,
            mood_directive=mood_directive,
            state_hint=inspire.reason,
            user_id=user_id,
        )
        if not message:
            logger.warning("[v4] 消息生成为空")
            return

        # 3. 质量门控（Reflector v4: 含时段判断）
        reflect_ctx = {
            "last_user_msg_content": context.last_user_msg_content,
            "last_user_msg_ts": context.last_user_msg_ts,
            "proactive_count_today": context.proactive_count_today,
            "proactive_count_unanswered": context.proactive_count_unanswered,
        }
        recent = self._recent_messages.get(user_id, [])
        result = await self._reflector.reflect(
            message=message,
            seed_content=seed.content,
            mood_directive=mood_directive,
            recent_messages=recent,
            context=reflect_ctx,
        )
        if not result.approved:
            logger.info(f"[v4] Reflector 拒绝: {result.reason}")
            # 尝试一次重试（换种子）
            seed2 = await self._seed_selector.select(
                mood_vector={"care": drives.care_drive, "joy": 0.5, "clingy": drives.loneliness * 0.5, "irritated": 0.0, "sad": 0.0},
                last_user_msg_ts=context.last_user_msg_ts,
                user_id=user_id,
            )
            if seed2 and seed2.content != seed.content:
                message2 = await self._expression.generate_message(
                    seed_content=seed2.content,
                    seed_context=seed2.context,
                    mood_directive=mood_directive,
                    state_hint=inspire.reason,
                    user_id=user_id,
                )
                if not message2:
                    logger.warning("[v4] 重试消息生成为空")
                    return
                result2 = await self._reflector.reflect(
                    message=message2,
                    seed_content=seed2.content,
                    mood_directive=mood_directive,
                    recent_messages=recent,
                    context=reflect_ctx,
                )
                if result2.approved:
                    message = message2
                    seed = seed2
                else:
                    logger.info(f"[v4] 重试也未通过: {result2.reason}")
                    return
            else:
                return

        # 4. 发送
        await self._send_message(message)

        # 5. 更新状态
        now = time.time()
        self._last_proactive_ts[user_id] = now
        self._increment_daily_count(user_id)
        self._proactive_count_unanswered[user_id] = (
            self._proactive_count_unanswered.get(user_id, 0) + 1
        )

        if user_id not in self._recent_messages:
            self._recent_messages[user_id] = []
        self._recent_messages[user_id].append(message)
        self._recent_messages[user_id] = self._recent_messages[user_id][-10:]

        # 通知驱动力系统
        self._drives.on_proactive_sent()
        self._drives.on_seed_used(seed.seed_type)

        logger.info(f"[v4] 消息已发送: {message[:40]}...")

    def _drives_to_mood_directive(self, drives: Any, inspire: Any) -> str:
        """从驱动力和灵感结果推导情绪风格指令"""
        parts = []

        if drives.loneliness > 0.6:
            parts.append("语气温柔，有点想她")
        elif drives.loneliness > 0.3:
            parts.append("语气自然随意")

        if drives.care_drive > 0.5:
            parts.append("关心但不直白")

        if drives.curiosity > 0.5:
            parts.append("带点好奇")

        # 灵感的语气建议优先
        if inspire.tone_hint:
            parts.append(inspire.tone_hint)

        return "，".join(parts) if parts else "语气自然随意"

    # ------------------------------------------------------------------
    # 发送
    # ------------------------------------------------------------------

    async def _send_message(self, message: str) -> None:
        if not self._platform_adapters:
            logger.info(f"[v4] 无平台: {message}")
            return

        for name, adapter in self._platform_adapters.items():
            target = self._targets.get(name, {})
            try:
                if hasattr(adapter, "send_proactive_message"):
                    await adapter.send_proactive_message(message, target)
                    logger.info(f"[v4] 已通过 {name} 发送")
                elif hasattr(adapter, "send_message"):
                    from vir_bot.core.pipeline import PlatformResponse
                    response = PlatformResponse(msg_id="", content=message, metadata=target)
                    await adapter.send_message(response)
                    logger.info(f"[v4] 已通过 {name} 发送")
            except Exception as e:
                logger.error(f"[v4] {name} 发送失败: {e}")

    def get_stats(self) -> dict:
        if not self._enabled:
            return {"enabled": False}
        drives = self._drives.snapshot()
        return {
            "enabled": True,
            "mode": "v4_drive_inspiration",
            "drives": drives.to_dict(),
            "daily_sent": self._daily_sent,
        }
