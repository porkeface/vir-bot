"""LLM 驱动的记忆写入器。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from vir_bot.utils.logger import logger

if TYPE_CHECKING:
    from vir_bot.core.ai_provider import AIProvider


@dataclass
class MemoryOperation:
    """结构化记忆操作。"""

    op: str
    namespace: str
    subject: str
    predicate: str
    object: str
    confidence: float
    source_text: str


class MemoryWriter:
    """使用 LLM 从对话中提取可写入的用户事实。"""

    def __init__(self, ai_provider: "AIProvider", quality_gate=None):
        self.ai = ai_provider
        self.quality_gate = quality_gate

    def _is_quality_gate_enabled(self) -> bool:
        """检查质量门是否启用。"""
        return self.quality_gate is not None

    async def extract_with_quality_check(
        self,
        *,
        user_msg: str,
        assistant_msg: str,
        user_id: str,
    ) -> list[MemoryOperation]:
        """提取记忆并通过质量门检查。"""
        operations = await self.extract(
            user_msg=user_msg,
            assistant_msg=assistant_msg,
            user_id=user_id,
        )

        if self._is_quality_gate_enabled():
            filtered = []
            for op in operations:
                passed, reason, conf_adjust = self.quality_gate.check(op)
                if passed:
                    op.confidence *= conf_adjust
                    filtered.append(op)
                else:
                    logger.info(f"Quality Gate blocked: {reason} (op: {op.op} {op.predicate}={op.object})")
            operations = filtered

        return operations

    async def extract(
        self,
        *,
        user_msg: str,
        assistant_msg: str,
        user_id: str,
    ) -> list[MemoryOperation]:
        prompt = self._build_prompt(user_msg=user_msg, assistant_msg=assistant_msg, user_id=user_id)
        try:
            response = await self.ai.chat(
                messages=[{"role": "user", "content": prompt}],
                system=(
                    "你是一个记忆抽取器。"
                    "只抽取用户明确陈述、适合长期保存的事实。"
                    "用户的提问、猜测、反问、让你回忆的句子，不是事实。"
                    "输出必须是 JSON 数组，不要输出解释。"
                ),
                temperature=0.1,
            )
        except Exception as exc:
            logger.warning(f"MemoryWriter 调用失败，跳过 LLM 抽取: {exc}")
            return []

        return self._parse_operations(response.content, user_msg)

    def _build_prompt(self, *, user_msg: str, assistant_msg: str, user_id: str) -> str:
        return f"""你是一个记忆管理助手。分析用户的消息，决定如何将信息写入长期记忆。

【任务】
根据用户消息，生成记忆操作（JSON 数组）。每条操作告诉系统：是新增(ADD)、更新(UPDATE)还是删除(DELETE)一条事实。

【输出格式】
每个元素字段：
- "op": "ADD" | "UPDATE" | "DELETE" | "NOOP"
- "namespace": "profile.preference" | "profile.habit" | "profile.identity" | "profile.event"
- "subject": "user"
- "predicate": "likes" | "dislikes" | "often_does" | "daily_does" | "name_is" | "from" | "is" | "mentioned_event"
- "object": "事实内容（简洁）"
- "confidence": 0.0-1.0（你对该事实的确信度）

【核心原则】
- 只从用户消息中抽取**明确陈述**的事实，不抽取提问、猜测、反问。
- 如果是用户在测试记忆（"你还记得吗？"），返回 []。
- 如果信息模糊（"好像"、"可能"），返回 []。
- 判断操作类型：新事实 → ADD，纠正旧事实 → UPDATE，否定旧事实 → DELETE。
- 置信度：用户明确陈述 0.9+，带情绪词 0.8，较模糊 0.6-0.7。

【示例】

示例1 - 新增偏好：
用户: 我最喜欢吃麻辣烫
输出: [{{"op":"ADD","namespace":"profile.preference","subject":"user","predicate":"likes","object":"麻辣烫","confidence":0.94}}]

示例2 - 新增厌恶：
用户: 我不喜欢吃茄子
输出: [{{"op":"ADD","namespace":"profile.preference","subject":"user","predicate":"dislikes","object":"茄子","confidence":0.92}}]

示例3 - 纠正姓名（用户说"我不叫张三，我叫李四"）：
用户: 我不叫张三，我叫李四
输出: [{{"op":"UPDATE","namespace":"profile.identity","subject":"user","predicate":"name_is","object":"李四","confidence":0.92}}]

示例4 - 纠正住址（用户说"我搬家了，现在住在北京"）：
用户: 我搬家了，现在住在北京
输出: [{{"op":"UPDATE","namespace":"profile.identity","subject":"user","predicate":"from","object":"北京","confidence":0.91}}]

示例5 - 测试性提问（不抽取）：
用户: 你记得我喜欢吃什么吗
输出: []

示例6 - 模糊表述（不抽取）：
用户: 我好像喜欢某些食物吧
输出: []

示例7 - 多条事实：
用户: 我叫张三，来自深圳，喜欢编程
输出: [{{"op":"ADD","namespace":"profile.identity","subject":"user","predicate":"name_is","object":"张三","confidence":0.95}},{{"op":"ADD","namespace":"profile.identity","subject":"user","predicate":"from","object":"深圳","confidence":0.92}},{{"op":"ADD","namespace":"profile.preference","subject":"user","predicate":"likes","object":"编程","confidence":0.88}}]

---

现在处理：
用户ID: {user_id}
用户消息: {user_msg}
助手回复: {assistant_msg}
输出（JSON 数组）："""

    def _parse_operations(self, content: str, source_text: str) -> list[MemoryOperation]:
        data = self._extract_json(content)
        if not isinstance(data, list):
            return []

        operations: list[MemoryOperation] = []
        for item in data:
            if not isinstance(item, dict):
                continue

            op = str(item.get("op", "")).upper().strip()
            namespace = str(item.get("namespace", "")).strip()
            subject = str(item.get("subject", "user")).strip() or "user"
            predicate = str(item.get("predicate", "")).strip()
            object_value = str(item.get("object", "")).strip()
            confidence = float(item.get("confidence", 0.0) or 0.0)

            if op == "NOOP":
                continue
            if op not in {"ADD", "UPDATE", "DELETE"}:
                continue
            if not namespace or not predicate or not object_value:
                continue
            if self._looks_like_question_value(object_value):
                continue
            if not self._is_supported_operation(
                predicate=predicate,
                object_value=object_value,
                source_text=source_text,
            ):
                continue

            operations.append(
                MemoryOperation(
                    op=op,
                    namespace=namespace,
                    subject=subject,
                    predicate=predicate,
                    object=object_value,
                    confidence=max(0.0, min(confidence, 1.0)),
                    source_text=source_text,
                )
            )

        return operations

    def _extract_json(self, content: str):
        stripped = content.strip()
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            start = stripped.find("[")
            end = stripped.rfind("]")
            if start == -1 or end == -1 or end <= start:
                logger.warning("MemoryWriter 未返回可解析 JSON")
                return []
            try:
                return json.loads(stripped[start : end + 1])
            except json.JSONDecodeError:
                logger.warning("MemoryWriter JSON 解析失败")
                return []

    def _looks_like_question_value(self, value: str) -> bool:
        lowered = value.strip().lower()
        invalid_values = {"什么", "哪些", "哪个", "吗", "呢", "吧", "么", "啥"}
        if lowered in invalid_values:
            return True
        return any(token in value for token in ["?", "？"])

    def _is_supported_operation(self, *, predicate: str, object_value: str, source_text: str) -> bool:
        normalized_source = source_text.strip()
        normalized_object = self._normalize_value(object_value)
        if not normalized_object:
            return False

        invalid_suffixes = ("好不好", "行不行", "可以吗", "好吗", "对不对", "行吗")
        if normalized_object.endswith(invalid_suffixes):
            return False

        if predicate == "name_is":
            if "我叫你" in normalized_source or "叫你" in normalized_source:
                return False
            patterns = [
                r"我叫(?!你)(?P<value>[^，。！？；\n]+)",
                r"我的名字是(?P<value>[^，。！？；\n]+)",
            ]
            return normalized_object in self._extract_values(normalized_source, patterns)

        if predicate == "from":
            patterns = [
                r"我来自(?P<value>[^，。！？；\n]+)",
                r"我是(?P<value>[^，。！？；\n]+)人",
            ]
            return normalized_object in self._extract_values(normalized_source, patterns)

        if predicate == "is":
            if any(signal in normalized_source for signal in ["我是不是", "如果我是", "要是我是"]):
                return False
            patterns = [r"我是(?!不)(?P<value>[^，。！？；\n]{1,20})"]
            return normalized_object in self._extract_values(normalized_source, patterns)

        return True

    def _extract_values(self, text: str, patterns: list[str]) -> set[str]:
        values: set[str] = set()
        for pattern in patterns:
            for match in re.finditer(pattern, text):
                value = self._normalize_value(match.group("value"))
                if value:
                    values.add(value)
        return values

    def _normalize_value(self, value: str) -> str:
        compact = value.strip(" ，。！？；,.!?;:")
        compact = re.sub(r"\s+", "", compact)
        return compact
