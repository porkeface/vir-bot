"""主动消息系统 v4：内驱力 + 灵感触发 + 自然判断"""

from vir_bot.core.proactive.proactive_service import ProactiveService
from vir_bot.core.proactive.drive_system import DriveSystem, DriveSnapshot
from vir_bot.core.proactive.inspiration_trigger import InspirationTrigger, InspirationScheduler, InspireResult
from vir_bot.core.proactive.seed_selector import SeedSelector, ContentSeed
from vir_bot.core.proactive.reflector import Reflector, ReflectResult
from vir_bot.core.proactive.fact_extractor import FactExtractor, FactStore, Fact
from vir_bot.core.proactive.expression import ExpressionLayer
from vir_bot.core.proactive.mood_model import MoodModel, MoodVector

__all__ = [
    "ProactiveService",
    "DriveSystem",
    "DriveSnapshot",
    "InspirationTrigger",
    "InspirationScheduler",
    "InspireResult",
    "SeedSelector",
    "ContentSeed",
    "Reflector",
    "ReflectResult",
    "FactExtractor",
    "FactStore",
    "Fact",
    "ExpressionLayer",
    "MoodModel",
    "MoodVector",
]
