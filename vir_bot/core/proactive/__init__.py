"""主动消息系统 v3：动态调度 + 内容种子 + 情绪向量 + 质量门控"""

from vir_bot.core.proactive.proactive_service import ProactiveService
from vir_bot.core.proactive.scheduler import ProactiveScheduler
from vir_bot.core.proactive.mood_model import MoodModel, MoodVector
from vir_bot.core.proactive.seed_selector import SeedSelector, ContentSeed
from vir_bot.core.proactive.reflector import Reflector, ReflectResult
from vir_bot.core.proactive.fact_extractor import FactExtractor, FactStore, Fact
from vir_bot.core.proactive.expression import ExpressionLayer

__all__ = [
    "ProactiveService",
    "ProactiveScheduler",
    "MoodModel",
    "MoodVector",
    "SeedSelector",
    "ContentSeed",
    "Reflector",
    "ReflectResult",
    "FactExtractor",
    "FactStore",
    "Fact",
    "ExpressionLayer",
]
