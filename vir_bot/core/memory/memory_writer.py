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

【核心规则】
1. 只抽取用户主动、明确陈述的事实，而非他们的提问。
2. 提问、让你回忆、测试记忆、反问等 → 不生成事实，返回 []。
3. 仅当用户用"我...""我是...""我叫...""我来自..."等明确陈述句时，才抽取。
4. object 不能是纯疑问词（什么、哪些、吗、呢、吧、么、啥）。
5. 不从助手回复中抽取信息，只从用户消息抽取。
6. 每条用户消息最多生成 1-2 条记忆操作。

【判断要点】
- "我喜欢..." → 抽取偏好
- "我讨厌..." → 抽取厌恶
- "我经常..." / "我每天..." → 抽取习惯
- "我叫..." / "我是..." / "我来自..." → 抽取身份
- "我最近..." / "昨天我..." → 抽取事件（仅当具体事实时）
- "你还记得我喜欢吃什么吗?" → 不抽取（这是测试性提问）
- "我好像..." / "可能..." / "不确定..." → 如果信息不确定，返回 []
- "我刚才说过..." / "之前我告诉你..." → 跳过，这是用户在测试或强调
- "我叫你小美好不好" / "以后我管你叫..." → 这是给助手起名，不是用户姓名，返回 []

【纠正意图识别】（关键：当用户纠正之前说过的事实时，用 UPDATE 而非 ADD）
- 用户说 "不对，我..." / "不是，我..." / "我改了..." / "现在我是..." → 纠正之前的事实，生成 UPDATE 操作
- 用户说 "我不叫X，我叫Y" → UPDATE name_is 为 Y
- 用户说 "我搬家了，现在住X" → UPDATE from 为 X
- 用户说 "我换工作了，现在是X" → UPDATE is 为 X
- 用户说 "早就不喜欢X了，现在喜欢Y" → UPDATE likes 为 Y（替换旧偏好）
- 纠正时，predicate 要与旧事实一致，object 是新值，op 必须是 UPDATE
- 示例：用户之前说 "我叫张三"，现在说 "我不叫张三，我叫李四" → [{"op":"UPDATE","namespace":"profile.identity","subject":"user","predicate":"name_is","object":"李四","confidence":0.92}]

【示例集】

例1 - 清晰偏好：
用户: 我最喜欢吃麻辣烫
输出: [{"op":"ADD","namespace":"profile.preference","subject":"user","predicate":"likes","object":"麻辣烫","confidence":0.94}]

例2 - 厌恶：
用户: 我不喜欢吃茄子
输出: [{"op":"ADD","namespace":"profile.preference","subject":"user","predicate":"dislikes","object":"茄子","confidence":0.92}]

例3 - 习惯：
用户: 我每天早上都要喝咖啡
输出: [{"op":"ADD","namespace":"profile.habit","subject":"user","predicate":"daily_does","object":"喝咖啡","confidence":0.9}]

例4 - 身份：
用户: 我来自浙江杭州
输出: [{"op":"ADD","namespace":"profile.identity","subject":"user","predicate":"from","object":"浙江杭州","confidence":0.95}]

例5 - 测试性提问（不抽取）：
用户: 你记得我喜欢吃什么吗
输出: []

例6 - 提问询问（不抽取）：
用户: 我这周忙什么呢
输出: []

例7 - 模糊表述（不抽取）：
用户: 我好像喜欢某些食物吧
输出: []

例8 - 多条事实：
用户: 我叫张三，来自深圳，喜欢编程
输出: [{"op":"ADD","namespace":"profile.identity","subject":"user","predicate":"name_is","object":"张三","confidence":0.95},{"op":"ADD","namespace":"profile.identity","subject":"user","predicate":"from","object":"深圳","confidence":0.92},{"op":"ADD","namespace":"profile.preference","subject":"user","predicate":"likes","object":"编程","confidence":0.88}]

例9 - 纠正姓名：
用户: 我不叫张三，我叫李四
输出: [{"op":"UPDATE","namespace":"profile.identity","subject":"user","predicate":"name_is","object":"李四","confidence":0.92}]

例10 - 纠正住址：
用户: 我搬家了，现在住在北京
输出: [{"op":"UPDATE","namespace":"profile.identity","subject":"user","predicate":"from","object":"北京","confidence":0.91}]

例11 - 纠正偏好：
用户: 早就不喜欢编程了，现在喜欢旅游
输出: [{"op":"UPDATE","namespace":"profile.preference","subject":"user","predicate":"likes","object":"旅游","confidence":0.90}]
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

    async def extract_relations(
        self,
        *,
        user_msg: str,
        assistant_msg: str,
        user_id: str,
    ) -> list[tuple[str, str, str, float]]:
        """从对话中抽取实体关系三元组，用于知识图谱。"""
        prompt = self._build_relation_prompt(
            user_msg=user_msg, assistant_msg=assistant_msg, user_id=user_id
        )
        try:
            response = await self.ai.chat(
                messages=[{"role": "user", "content": prompt}],
                system=(
                    "你是一个关系抽取器。"
                    "从对话中抽取实体关系三元组，只输出 JSON 数组。"
                    "不要输出解释或 markdown 代码块。"
                ),
                temperature=0.1,
            )
        except Exception as exc:
            logger.warning(f"MemoryWriter 关系抽取失败: {exc}")
            return []

        return self._parse_relations(response.content)

    def _build_relation_prompt(self, *, user_msg: str, assistant_msg: str, user_id: str) -> str:
        """构建关系抽取提示词。"""
        return f"""从以下对话中抽取实体关系三元组（subject, predicate, object），用于构建知识图谱。

规则：
1. 只抽取用户明确陈述的关系，不抽取提问或猜测。
2. subject 通常是用户（user:{user_id}）或其他实体。
3. predicate 是关系类型，如 likes, from, is, lives_in, works_as 等。
4. object 是目标实体。
5. 返回 JSON 数组，每个元素格式：
   {{"subject": "user:{user_id}", "predicate": "likes", "object": "火锅", "confidence": 0.9}}

示例：
用户: 我喜欢吃火锅，来自四川
助手: 好的，我记住了。
输出: [
  {{"subject": "user:{user_id}", "predicate": "likes", "object": "火锅", "confidence": 0.95}},
  {{"subject": "user:{user_id}", "predicate": "from", "object": "四川", "confidence": 0.95}}
]

示例2：
用户: 我不叫张三，我叫李四
助手: 好的，我记住了你叫李四。
输出: [
  {{"subject": "user:{user_id}", "predicate": "name_is", "object": "李四", "confidence": 0.92}}
]

当前用户ID: {user_id}
用户消息: {user_msg}
助手回复: {assistant_msg}
请输出 JSON 数组："""

    def _parse_relations(self, content: str) -> list[tuple[str, str, str, float]]:
        """解析关系抽取结果。"""
        data = self._extract_json(content)
        if not isinstance(data, list):
            return []

        relations = []
        for item in data:
            if not isinstance(item, dict):
                continue
            subject = str(item.get("subject", "")).strip()
            predicate = str(item.get("predicate", "")).strip()
            object_val = str(item.get("object", "")).strip()
            confidence = float(item.get("confidence", 0.0) or 0.0)
            if not subject or not predicate or not object_val:
                continue
            relations.append((subject, predicate, object_val, max(0.0, min(1.0, confidence))))
        return relations
