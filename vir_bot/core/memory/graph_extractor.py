"""关系抽取器 - 从对话中抽取实体关系三元组，存入知识图谱。"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from vir_bot.utils.logger import logger

if TYPE_CHECKING:
    from vir_bot.core.ai_provider import AIProvider

# 实体别名映射表：将用户输入中的自称统一映射为标准化实体
ENTITY_ALIASES = {
    "我": "user",
    "俺": "user",
    "老子": "user",
    "本大爷": "user",
    "用户": "user",
}

EXTRACTION_PROMPT = """你是一个知识图谱关系抽取器。从以下对话中提取所有显式提及的实体关系三元组。

输出必须是严格的 JSON 数组，每个元素包含：
- "subject": 主语（人物或实体，用户标准化为 "user"）
- "predicate": 谓语关系（简短的动词短语，如 "喜欢"、"住在"、"是"）
- "object": 宾语（人物或实体）
- "confidence": 置信度（0.0-1.0）

规则：
1. 只提取**明确陈述**的事实，不推测、不反问、不抽取助手的回复内容。
2. 如果对话中没有可提取的关系，返回空数组 []。
3. 将用户本人标准化为 "user:{user_id}"。
4. 同一关系的不同表述合并为一条最高置信度的记录。
5. 不要输出 markdown 代码块，只输出纯 JSON。

示例对话1：
用户: 我叫张三，我女朋友叫李四，我们住在北京。
助手: 很高兴认识你张三！

输出：
[
  {"subject": "user:user_id", "predicate": "name_is", "object": "张三", "confidence": 0.95},
  {"subject": "user:user_id", "predicate": "has_girlfriend", "object": "李四", "confidence": 0.92},
  {"subject": "user:user_id", "predicate": "lives_in", "object": "北京", "confidence": 0.93}
]

示例对话2：
用户: 我喜欢吃火锅，尤其是麻辣火锅。
助手: 好的，我记住了你喜欢火锅。

输出：
[
  {"subject": "user:user_id", "predicate": "likes", "object": "火锅", "confidence": 0.94}
]

示例对话3（纠正意图）：
用户: 我不叫张三，我叫李四。
助手: 好的，我记住了你叫李四。

输出：
[
  {"subject": "user:user_id", "predicate": "name_is", "object": "李四", "confidence": 0.92}
]

示例对话4（无可提取关系）：
用户: 你好啊
助手: 你好！有什么我可以帮你的吗？

输出：
[]

现在请处理以下对话（只输出 JSON 数组）：
用户: {user_msg}
助手: {assistant_msg}
用户ID: {user_id}
输出：
"""


class GraphRelationExtractor:
    """从对话中抽取实体关系三元组，支持实体消歧和冲突检测。"""

    def __init__(self, ai_provider: "AIProvider"):
        self.ai = ai_provider

    async def extract(
        self,
        *,
        user_msg: str,
        assistant_msg: str,
        user_id: str,
    ) -> list[dict]:
        """
        从对话中抽取关系三元组。

        返回格式：
        [
            {"subject": "user:xxx", "predicate": "likes", "object": "火锅", "confidence": 0.9},
            ...
        ]
        """
        # 跳过短消息或无意义消息
        if not self._should_extract(user_msg):
            logger.debug(f"跳过关系抽取（消息过短或无实体）: {user_msg[:30]}")
            return []

        prompt = self._build_prompt(
            user_msg=user_msg,
            assistant_msg=assistant_msg,
            user_id=user_id,
        )

        try:
            response = await self.ai.chat(
                messages=[{"role": "user", "content": prompt}],
                system="你是知识图谱关系抽取器。只输出 JSON 数组，不要解释。",
                temperature=0.1,
            )
        except Exception as exc:
            logger.warning(f"关系抽取 LLM 调用失败: {exc}")
            return []

        triples = self._parse_response(response.content)
        # 实体消歧：统一别名
        triples = [self._normalize_entities(t, user_id) for t in triples]
        # 去重
        triples = self._deduplicate(triples)
        return triples

    def _should_extract(self, user_msg: str) -> bool:
        """判断是否值得调用 LLM 抽取。"""
        msg = user_msg.strip()
        if len(msg) < 4:  # 太短的消息通常无关系
            return False
        # 纯问候语
        greetings = {"你好", "hello", "hi", "嗨", "在吗", "在不在"}
        if msg.lower() in greetings:
            return False
        return True

    def _build_prompt(self, *, user_msg: str, assistant_msg: str, user_id: str) -> str:
        return EXTRACTION_PROMPT.format(
            user_msg=user_msg,
            assistant_msg=assistant_msg[:200],  # 截断，避免 prompt 过长
            user_id=user_id,
        )

    def _parse_response(self, content: str) -> list[dict]:
        """解析 LLM 返回的 JSON。"""
        content = content.strip()
        if not content:
            return []

        # 去掉可能的 markdown 代码块
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            # 尝试提取 [...]
            start = content.find("[")
            end = content.rfind("]")
            if start != -1 and end != -1 and end > start:
                try:
                    data = json.loads(content[start : end + 1])
                except json.JSONDecodeError:
                    logger.warning(f"关系抽取：JSON 解析失败，原始内容: {content[:100]}")
                    return []
            else:
                logger.warning(f"关系抽取：未找到 JSON 数组，原始内容: {content[:100]}")
                return []

        if not isinstance(data, list):
            return []

        results = []
        for item in data:
            if not isinstance(item, dict):
                continue
            subject = str(item.get("subject", "")).strip()
            predicate = str(item.get("predicate", "")).strip()
            object_val = str(item.get("object", "")).strip()
            confidence = float(item.get("confidence", 0.0) or 0.0)

            if not subject or not predicate or not object_val:
                continue
            if confidence <= 0.0:
                confidence = 0.7  # 默认置信度

            results.append({
                "subject": subject,
                "predicate": predicate,
                "object": object_val,
                "confidence": max(0.0, min(1.0, confidence)),
            })

        return results

    def _normalize_entities(self, triple: dict, user_id: str) -> dict:
        """实体消歧：统一别名为标准实体名。"""
        subject = triple["subject"]
        object_val = triple["object"]

        # 处理 subject
        normalized_subject = ENTITY_ALIASES.get(subject.lower(), subject)
        if normalized_subject == "user":
            normalized_subject = f"user:{user_id}"
        triple["subject"] = normalized_subject

        # 处理 object（如果 object 是用户别名）
        normalized_object = ENTITY_ALIASES.get(object_val.lower(), object_val)
        if normalized_object == "user":
            normalized_object = f"user:{user_id}"
        triple["object"] = normalized_object

        return triple

    def _deduplicate(self, triples: list[dict]) -> list[dict]:
        """去重：相同 (subject, predicate, object) 保留置信度最高的。"""
        seen = {}
        for t in triples:
            key = (t["subject"], t["predicate"], t["object"])
            if key not in seen or t["confidence"] > seen[key]["confidence"]:
                seen[key] = t
        return list(seen.values())

    def detect_conflicts(
        self,
        new_triples: list[dict],
        existing_edges: list[tuple],
    ) -> list[tuple]:
        """
        检测新三元组与图中已有边的冲突。

        冲突定义：相同 subject 和 predicate，但 object 不同。
        返回：[(new_triple, existing_object, conflict_type), ...]
        """
        existing_map = {}  # (subject, predicate) -> object
        for edge in existing_edges:
            subj, pred, obj = edge[0], edge[1], edge[2]
            existing_map[(subj, pred)] = obj

        conflicts = []
        for triple in new_triples:
            key = (triple["subject"], triple["predicate"])
            if key in existing_map and existing_map[key] != triple["object"]:
                conflicts.append((
                    triple,
                    existing_map[key],
                    "contradiction",  # 矛盾：同一事实有两个不同值
                ))
        return conflicts
