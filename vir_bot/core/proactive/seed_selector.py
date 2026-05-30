"""SeedSelector: 选择内容种子，让主动消息有具体信息可引用"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from vir_bot.utils.logger import logger


@dataclass
class ContentSeed:
    """一条内容种子"""
    seed_type: str     # callback / interest / situation / shared_memory / observation
    content: str       # 具体内容："用户周六要和朋友去爬山"
    context: str = ""  # 补充上下文
    priority: int = 5  # 优先级 1-10


# 种子类型权重（情绪会影响权重，这里给默认值）
DEFAULT_WEIGHTS = {
    "callback": 0.30,       # 回忆最近对话
    "interest": 0.20,       # 兴趣触发
    "situation": 0.25,      # 情境感知
    "shared_memory": 0.15,  # 共享记忆
    "observation": 0.10,    # 观察推断
}


class SeedSelector:
    """内容种子选择器：根据情绪和轮转选择合适的种子"""

    def __init__(self, fact_store: Any, memory_manager: Any = None):
        self._fact_store = fact_store
        self._memory = memory_manager
        self._recent_seed_types: list[str] = []  # 最近用过的种子类型
        self._max_history = 10

    async def select(
        self,
        mood_vector: dict[str, float] | None = None,
        conv_state: str = "IDLE",
        last_user_msg_ts: float = 0,
    ) -> ContentSeed | None:
        """选择一个内容种子，None 表示没有可用种子"""

        # 根据情绪调整权重
        weights = self._adjust_weights_by_mood(mood_vector or {}, conv_state)

        # 轮转：降低最近用过的类型权重
        for used_type in self._recent_seed_types[-3:]:
            if used_type in weights:
                weights[used_type] *= 0.3

        # 尝试每种类型，按权重排序
        sorted_types = sorted(weights.items(), key=lambda x: x[1], reverse=True)

        for seed_type, _ in sorted_types:
            seed = await self._try_seed_type(seed_type, last_user_msg_ts)
            if seed:
                self._recent_seed_types.append(seed_type)
                if len(self._recent_seed_types) > self._max_history:
                    self._recent_seed_types.pop(0)
                return seed

        return None

    async def _try_seed_type(
        self, seed_type: str, last_user_msg_ts: float
    ) -> ContentSeed | None:
        """尝试获取某种类型的种子"""
        if seed_type == "callback":
            return self._callback_seed()
        if seed_type == "situation":
            return self._situation_seed(last_user_msg_ts)
        if seed_type == "interest":
            return await self._interest_seed()
        if seed_type == "shared_memory":
            return await self._shared_memory_seed()
        if seed_type == "observation":
            return self._observation_seed(last_user_msg_ts)
        return None

    def _callback_seed(self) -> ContentSeed | None:
        """从 FactStore 中取最近的事实作为回调"""
        facts = self._fact_store.get_available_facts()
        if not facts:
            return None
        # 优先选最近的、使用次数少的
        facts.sort(key=lambda f: (f.used_count, -f.source_ts))
        fact = facts[0]
        return ContentSeed(
            seed_type="callback",
            content=fact.fact,
            context=f"话题: {', '.join(fact.topic_tags)}" if fact.topic_tags else "",
            priority=7,
        )

    def _situation_seed(self, last_user_msg_ts: float) -> ContentSeed | None:
        """基于当前时间段生成情境种子"""
        now = datetime.now()
        hour = now.hour
        weekday = now.weekday()  # 0=周一

        # 时间段情境
        situations = []
        if 7 <= hour < 9:
            situations.append(("早上了，新的一天开始", "morning"))
        elif 11 <= hour < 13:
            situations.append(("中午了，该吃饭了", "noon"))
        elif 17 <= hour < 19:
            situations.append(("傍晚了，下班了吧", "evening"))
        elif 21 <= hour < 23:
            situations.append(("夜深了，该休息了", "night"))

        # 星期几
        if weekday == 4:  # 周五
            situations.append(("周五了，明天不用上班", "friday"))
        elif weekday == 5:  # 周六
            situations.append(("周六，休息日", "weekend"))
        elif weekday == 6:  # 周日
            situations.append(("周日，明天又要上班了", "sunday"))

        # 用户沉默时间
        if last_user_msg_ts > 0:
            import time
            silence_hours = (time.time() - last_user_msg_ts) / 3600
            if silence_hours > 24:
                situations.append((f"超过一天没联系了", "long_silence"))
            elif silence_hours > 6:
                situations.append((f"半天没联系了", "half_day_silence"))

        if not situations:
            return None

        content, tag = random.choice(situations)
        return ContentSeed(
            seed_type="situation",
            content=content,
            context=f"时间: {now.strftime('%H:%M')}, 星期{weekday + 1}",
            priority=5,
        )

    async def _interest_seed(self) -> ContentSeed | None:
        """从记忆中找用户的兴趣点"""
        if not self._memory:
            return None
        try:
            if hasattr(self._memory, "retrieval_router"):
                result = await self._memory.retrieval_router.retrieve(
                    query="用户兴趣爱好 喜欢什么", user_id="default", top_k=3
                )
                records = result.semantic_records or result.long_term_records
                if records:
                    mem = records[0]
                    content = mem.object if hasattr(mem, "object") else getattr(mem, "content", "")[:100]
                    return ContentSeed(
                        seed_type="interest",
                        content=content[:100],
                        context="来自记忆",
                        priority=6,
                    )
        except Exception as e:
            logger.debug(f"[SeedSelector] 兴趣种子查询失败: {e}")
        return None

    async def _shared_memory_seed(self) -> ContentSeed | None:
        """从记忆中找共享的回忆"""
        if not self._memory:
            return None
        try:
            if hasattr(self._memory, "retrieval_router"):
                result = await self._memory.retrieval_router.retrieve(
                    query="一起做过的事 共同回忆", user_id="default", top_k=3
                )
                records = result.semantic_records or result.episodic_records or result.long_term_records
                if records:
                    mem = records[0]
                    content = mem.object if hasattr(mem, "object") else getattr(mem, "content", "")[:100]
                    return ContentSeed(
                        seed_type="shared_memory",
                        content=content[:100],
                        context="共同回忆",
                        priority=8,
                    )
        except Exception as e:
            logger.debug(f"[SeedSelector] 共享记忆查询失败: {e}")
        return None

    def _observation_seed(self, last_user_msg_ts: float) -> ContentSeed | None:
        """从聊天间隔中推断观察"""
        import time
        if last_user_msg_ts <= 0:
            return None

        silence = time.time() - last_user_msg_ts
        if silence < 3600:
            return None  # 不够长，没什么好观察的

        hours = int(silence / 3600)
        if hours >= 48:
            return ContentSeed(
                seed_type="observation",
                content=f"两天没理我了",
                context=f"沉默 {hours} 小时",
                priority=6,
            )
        if hours >= 12:
            return ContentSeed(
                seed_type="observation",
                content=f"好久没理我了",
                context=f"沉默 {hours} 小时",
                priority=5,
            )
        return None

    def _adjust_weights_by_mood(
        self, mood: dict[str, float], conv_state: str
    ) -> dict[str, float]:
        """根据情绪调整种子类型权重"""
        weights = dict(DEFAULT_WEIGHTS)

        # 心情低落 → 更多回忆和观察
        sad = mood.get("sad", 0.5)
        if sad > 0.7:
            weights["shared_memory"] += 0.15
            weights["observation"] += 0.10
            weights["situation"] -= 0.10

        # 撒娇 → 更多观察和回忆
        clingy = mood.get("clingy", 0.5)
        if clingy > 0.7:
            weights["observation"] += 0.15
            weights["callback"] += 0.10

        # 开心 → 更多兴趣和情境
        joy = mood.get("joy", 0.5)
        if joy > 0.7:
            weights["interest"] += 0.15
            weights["situation"] += 0.10

        # CONCERNED/WORRIED → 更多观察
        if conv_state in ("CONCERNED", "WORRIED"):
            weights["observation"] += 0.20
            weights["situation"] -= 0.10

        # 归一化
        total = sum(weights.values())
        if total > 0:
            weights = {k: v / total for k, v in weights.items()}

        return weights
