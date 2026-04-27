"""牵挂驱动型主动消息系统。

轻量实现，复用现有：
- AIProvider（LLM调用）
- MemoryManager（记忆检索作为牵挂评估上下文）
- CharacterCard（角色人设约束）
- config.yaml（配置管理）
"""

from vir_bot.core.proactive.concern_engine import ConcernEngine
from vir_bot.core.proactive.perception import PerceptionLayer
from vir_bot.core.proactive.expression import ExpressionLayer
from vir_bot.core.proactive.rhythm_manager import RhythmManager
from vir_bot.core.proactive.dispatcher import ProactiveDispatcher

__all__ = [
    "ConcernEngine",
    "PerceptionLayer",
    "ExpressionLayer",
    "RhythmManager",
    "ProactiveDispatcher",
]
