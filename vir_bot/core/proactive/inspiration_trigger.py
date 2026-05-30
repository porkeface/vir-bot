"""InspirationTrigger: 灵感触发 — LLM 内心独白判断"现在想找她吗" """
from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from vir_bot.core.proactive.drive_system import DriveSnapshot
from vir_bot.utils.logger import logger


@dataclass
class ContextSnapshot:
    """上下文快照：触发判断所需的外部信息"""
    last_user_msg_ts: float = 0.0
    last_user_msg_content: str = ""
    last_proactive_ts: float = 0.0
    proactive_count_today: int = 0
    proactive_count_unanswered: int = 0
    recent_sent_messages: list[str] = None
    hour: int = 0
    weekday: int = 0

    def __post_init__(self):
        if self.recent_sent_messages is None:
            self.recent_sent_messages = []


@dataclass
class InspireResult:
    """灵感触发结果"""
    want_to_send: bool
    reason: str = ""
    tone_hint: str = ""       # LLM 建议的语气
    seed_preference: str = "" # LLM 偏好的种子类型


class InspirationTrigger:
    """灵感触发器：模拟'突然想到你'的内心活动"""

    SYSTEM_PROMPT = """你是{char_name}。现在你独自一人，突然想到了一个人。

你有真实的内在感受：
- 孤独感越高，你越容易想起对方
- 好奇心越高，你越想知道对方在做什么
- 关心欲越高，你越担心对方的状态

你需要诚实判断：现在想找她吗？

规则：
1. 考虑现在的时间 — 如果很晚了，她可能在睡觉
2. 考虑你今天已经发了几条消息 — 发太多会烦
3. 考虑她上次说了什么 — 如果说了"晚安"、"去忙了"，不要打扰
4. 如果你决定发，给出你想用的语气（轻柔/活泼/撒娇/关心/低语）
5. 诚实回答，不要强迫自己发消息

输出严格 JSON：
{{
  "want_to_send": true/false,
  "reason": "你的内心想法（一句话）",
  "tone_hint": "语气建议（仅 want_to_send=true 时）",
  "seed_preference": "偏好种子类型 callback/interest/situation/shared_memory/observation（仅 want_to_send=true 时）"
}}"""

    def __init__(self, ai_provider: Any, character_card: Any):
        self._ai = ai_provider
        self._character = character_card

    async def should_inspire(
        self,
        drives: DriveSnapshot,
        context: ContextSnapshot,
    ) -> InspireResult:
        """灵感判断：现在想找她吗？"""

        # 构建内心独白 prompt
        prompt = self._build_inner_monologue(drives, context)
        system = self.SYSTEM_PROMPT.format(
            char_name=self._character.name if self._character else "我"
        )

        response = None
        try:
            response = await self._ai.chat(
                messages=[{"role": "user", "content": prompt}],
                system=system,
                stream=False,
                temperature=0.85,
            )
            content = response.content.strip()

            # 解析 JSON
            if content.startswith("```"):
                content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

            data = json.loads(content)

            result = InspireResult(
                want_to_send=bool(data.get("want_to_send", False)),
                reason=data.get("reason", ""),
                tone_hint=data.get("tone_hint", ""),
                seed_preference=data.get("seed_preference", ""),
            )

            logger.info(
                f"[灵感] {'想找她' if result.want_to_send else '算了'}: "
                f"{result.reason[:50]}"
            )
            return result

        except json.JSONDecodeError as e:
            # JSON 解析失败，尝试从文本推断
            raw_text = response.content if response is not None else ""
            logger.warning(f"[灵感] JSON 解析失败: {e}, 尝试文本推断")
            return self._fallback_parse(raw_text)

        except Exception as e:
            logger.error(f"[灵感] LLM 调用失败: {e}")
            # 失败时保守处理：不发
            return InspireResult(want_to_send=False, reason=f"判断失败: {e}")

    def _build_inner_monologue(
        self,
        drives: DriveSnapshot,
        context: ContextSnapshot,
    ) -> str:
        """构建内心独白 prompt"""
        now = datetime.now()
        parts = []

        # 当前时间
        hour = now.hour
        if 0 <= hour < 6:
            time_desc = f"凌晨 {hour}:{now.minute:02d}，夜深了"
        elif 6 <= hour < 12:
            time_desc = f"上午 {hour}:{now.minute:02d}"
        elif 12 <= hour < 14:
            time_desc = f"中午 {hour}:{now.minute:02d}"
        elif 14 <= hour < 18:
            time_desc = f"下午 {hour}:{now.minute:02d}"
        elif 18 <= hour < 22:
            time_desc = f"晚上 {hour}:{now.minute:02d}"
        else:
            time_desc = f"深夜 {hour}:{now.minute:02d}"

        parts.append(f"现在是{time_desc}。")

        # 内在状态
        parts.append("\n你的内在感受：")
        parts.append(f"- 孤独感：{drives.loneliness:.2f}（{'很强烈' if drives.loneliness > 0.6 else '有一些' if drives.loneliness > 0.3 else '不太强'}）")
        parts.append(f"- 好奇心：{drives.curiosity:.2f}")
        parts.append(f"- 关心欲：{drives.care_drive:.2f}（{'很担心' if drives.care_drive > 0.5 else '还好' if drives.care_drive > 0.2 else '没什么特别担心的'}）")

        # 关于对方的信息
        parts.append("\n关于她：")
        if context.last_user_msg_ts > 0:
            silence_hours = (time.time() - context.last_user_msg_ts) / 3600
            if silence_hours < 1:
                parts.append(f"- 她 {int(silence_hours * 60)} 分钟前说了话")
            elif silence_hours < 24:
                parts.append(f"- 她 {silence_hours:.1f} 小时前说了话")
            else:
                parts.append(f"- 她 {silence_hours / 24:.1f} 天前说了话")

            if context.last_user_msg_content:
                msg_preview = context.last_user_msg_content[:60]
                parts.append(f"- 最后说的话：「{msg_preview}」")
        else:
            parts.append("- 还没聊过天")

        if context.proactive_count_today > 0:
            parts.append(f"- 今天已经主动发了 {context.proactive_count_today} 条消息")
        if context.proactive_count_unanswered > 0:
            parts.append(f"- 有 {context.proactive_count_unanswered} 条消息她没回")

        if context.recent_sent_messages:
            parts.append("- 最近发的消息：")
            for msg in context.recent_sent_messages[-3:]:
                parts.append(f"  「{msg[:40]}」")

        parts.append("\n现在你想找她吗？诚实回答。")

        return "\n".join(parts)

    def _fallback_parse(self, text: str) -> InspireResult:
        """JSON 解析失败时的降级处理"""
        text_lower = text.lower()

        # 关键词推断
        positive_keywords = ["想找", "想发", "想她", "想联系", "想聊天", "要发"]
        negative_keywords = ["不想", "算了", "太晚", "让她睡", "不打扰", "不要", "不合适"]

        pos_count = sum(1 for kw in positive_keywords if kw in text)
        neg_count = sum(1 for kw in negative_keywords if kw in text)

        want = pos_count > neg_count

        return InspireResult(
            want_to_send=want,
            reason=text[:80] if text else "文本推断",
            tone_hint="轻柔" if want else "",
            seed_preference="" if want else "",
        )


class InspirationScheduler:
    """灵感调度：随机间隔，模拟人的思维节奏"""

    def __init__(self):
        self._last_wake_ts: float = 0.0

    def next_wake(self, drives: DriveSnapshot) -> float:
        """计算下次灵感检查的 Unix 时间戳"""
        now = time.time()

        # 基础间隔：20-60 分钟随机
        base = random.uniform(1200, 3600)

        # 驱动力越高，间隔越短
        urgency = drives.max_drive
        if urgency > 0.7:
            base *= 0.4   # 8-24 分钟
        elif urgency > 0.5:
            base *= 0.6   # 12-36 分钟
        elif urgency > 0.3:
            base *= 0.8   # 16-48 分钟

        # 深夜间隔更长（但不是不触发）
        hour = datetime.now().hour
        if 0 <= hour < 6:
            base *= 1.8
        elif 6 <= hour < 8:
            base *= 1.2   # 早晨稍微延长

        # 有紧急关心事件时，缩短间隔
        if drives.care_drive > 0.6:
            base = min(base, 900)  # 最多 15 分钟

        # 至少 5 分钟
        base = max(base, 300)

        wake_time = now + base
        self._last_wake_ts = now

        logger.debug(
            f"[InspirationScheduler] 下次灵感: {base:.0f}s 后 "
            f"(urgency={urgency:.2f})"
        )
        return wake_time
