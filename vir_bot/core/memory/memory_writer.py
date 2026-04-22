"""LLM 驱动的记忆写入器。"""

from __future__ import annotations

import json
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

    def __init__(self, ai_provider: "AIProvider"):
        self.ai = ai_provider

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
        schema = """
返回 JSON 数组。每个元素字段如下：
{
  "op": "ADD" | "UPDATE" | "DELETE" | "NOOP",
  "namespace": "profile.preference" | "profile.habit" | "profile.identity" | "profile.event",
  "subject": "user",
  "predicate": "likes" | "dislikes" | "often_does" | "daily_does" | "name_is" | "from" | "is" | "mentioned_event",
  "object": "事实内容",
  "confidence": 0.0-1.0
}

规则：
1. 如果用户只是提问、让你回忆、测试记忆、反问，不要生成事实，返回 []。
2. 只有用户明确陈述自己的偏好、身份、习惯、近况，才生成 ADD 或 UPDATE。
3. object 不得是“什么/哪些/吗/呢/吧/？”这类疑问词。
4. 如果信息不确定，宁可返回 []。
5. 不要提取助手内容里的信息。

示例：
用户: 我喜欢吃火锅
输出: [{"op":"ADD","namespace":"profile.preference","subject":"user","predicate":"likes","object":"火锅","confidence":0.93}]

用户: 你记得我喜欢吃什么吗
输出: []

用户: 我不喜欢香菜
输出: [{"op":"ADD","namespace":"profile.preference","subject":"user","predicate":"dislikes","object":"香菜","confidence":0.95}]

用户: 我来自厦门
输出: [{"op":"ADD","namespace":"profile.identity","subject":"user","predicate":"from","object":"厦门","confidence":0.9}]
"""
        return (
            f"{schema}\n\n"
            f"当前用户ID: {user_id}\n"
            f"用户消息: {user_msg}\n"
            f"助手回复: {assistant_msg}\n"
            "请输出 JSON 数组："
        )

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
