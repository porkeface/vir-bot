"""主动消息服务：整合牵挂引擎、评估、表达、节奏管理"""
from __future__ import annotations

import asyncio
from typing import Any

from vir_bot.utils.logger import logger


class ProactiveService:
    """主动消息总服务"""

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

        # 2. 节奏检查
        can_send, reason = self._rhythm.can_send(user_id)
        if not can_send:
            logger.debug(f"节奏检查未通过: {reason}")
            return

        # 3. 生成牵挂念头
        thought = await self._concern_engine._generate_thought(context)
        if not thought or not thought.content:
            logger.debug("未生成牵挂念头")
            return

        # 4. 评估牵挂
        send, score, eval_reason = await self._evaluator.evaluate(thought, context)
        if not send:
            logger.debug(f"牵挂评估未通过: {eval_reason} (分数: {score:.2f})")
            return

        logger.info(f"牵挂通过评估: {eval_reason} (分数: {score:.2f})")

        # 5. 生成消息
        state = self._tracker.get_state(user_id)
        message = await self._expression.generate_message(thought, user_id, state)
        if not message:
            logger.warning("消息生成为空")
            return

        # 6. 发送消息
        await self._send_message(message)

        # 7. 记录状态
        self._rhythm.on_proactive_sent(user_id)
        self._tracker.update_proactive_sent(user_id)

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
