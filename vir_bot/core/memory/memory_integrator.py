"""记忆整合器 — 用 LLM 整合新旧记忆，去重合并处理矛盾。

借鉴 NachoBot 海马体的设计：
- 新记忆写入时，如果概念节点已存在，用 LLM 整合新旧记忆
- 整合后权重增加，表示这条记忆被多次确认
"""
from __future__ import annotations

import inspect
from typing import TYPE_CHECKING

from vir_bot.core.memory.semantic_store import SemanticMemoryStore, SemanticMemoryRecord
from vir_bot.utils.logger import logger

if TYPE_CHECKING:
    from vir_bot.core.ai_provider import AIProvider


class MemoryIntegrator:
    """记忆整合器：在写入前检查是否有可整合的已有记忆。"""

    def __init__(
        self,
        ai_provider: "AIProvider",
        semantic_store: SemanticMemoryStore,
    ):
        self._ai = ai_provider
        self._store = semantic_store

    async def try_integrate(
        self,
        user_id: str,
        namespace: str,
        predicate: str,
        new_object: str,
        new_confidence: float,
        source_text: str = "",
    ) -> tuple[bool, str, float]:
        """尝试整合新记忆与已有记忆。

        返回 (是否整合, 整合后的object, 整合后的confidence)。
        如果没有找到可整合的已有记忆，返回 (False, new_object, new_confidence)。
        """
        # 查找同一 namespace + predicate 的已有记忆
        # 兼容同步（JSON store）和异步（SQLite store）两种实现
        result = self._store.find_by_predicate(
            user_id=user_id,
            namespace=namespace,
            predicate=predicate,
        )
        if inspect.isawaitable(result):
            existing = await result
        else:
            existing = result

        if not existing:
            return False, new_object, new_confidence

        # 如果已有记忆和新记忆完全相同，不需要整合
        if existing.object.strip() == new_object.strip():
            return False, new_object, new_confidence

        # 用 LLM 整合
        try:
            integrated_object, integrated_confidence = await self._llm_integrate(
                existing_object=existing.object,
                existing_confidence=existing.confidence,
                new_object=new_object,
                new_confidence=new_confidence,
                predicate=predicate,
                source_text=source_text,
            )

            if integrated_object:
                logger.info(
                    f"[MemoryIntegrator] 整合记忆: "
                    f"「{existing.object}」+「{new_object}」→「{integrated_object}」"
                )
                return True, integrated_object, integrated_confidence

        except Exception as e:
            logger.warning(f"[MemoryIntegrator] LLM 整合失败: {e}")

        return False, new_object, new_confidence

    async def _llm_integrate(
        self,
        existing_object: str,
        existing_confidence: float,
        new_object: str,
        new_confidence: float,
        predicate: str,
        source_text: str = "",
    ) -> tuple[str, float]:
        """用 LLM 整合新旧记忆。"""
        prompt = f"""你是一个记忆整合器。将以下两条关于同一主题的记忆整合为一条。

已有记忆：{existing_object}（置信度：{existing_confidence:.2f}）
新信息：{new_object}（置信度：{new_confidence:.2f}）
关系类型：{predicate}
{"原始对话：" + source_text[:100] if source_text else ""}

整合规则：
1. 如果两条一致，合并为更完整的描述
2. 如果两条矛盾，以置信度更高的为准
3. 如果新信息更具体，用新信息补充旧信息
4. 输出整合后的记忆，20字以内，不要解释

输出格式（纯文本，不要JSON）：
整合后的记忆"""

        try:
            response = await self._ai.chat(
                messages=[{"role": "user", "content": prompt}],
                system="你是记忆整合器。只输出整合后的记忆文本，不要任何解释。",
                temperature=0.1,
            )
            integrated = response.content.strip()

            # 清理可能的引号包裹
            if integrated.startswith('"') and integrated.endswith('"'):
                integrated = integrated[1:-1]
            if integrated.startswith("「") and integrated.endswith("」"):
                integrated = integrated[1:-1]

            if not integrated:
                return "", 0.0

            # 整合后的置信度取加权平均（非简单 max）
            integrated_confidence = (existing_confidence + new_confidence) / 2

            return integrated, integrated_confidence

        except Exception as e:
            logger.warning(f"[MemoryIntegrator] LLM 调用失败: {e}")
            return "", 0.0
