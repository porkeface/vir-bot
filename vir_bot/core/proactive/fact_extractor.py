"""FactExtractor: 从聊天记录中提取结构化事实，供内容种子使用"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from vir_bot.utils.logger import logger


@dataclass
class Fact:
    """一条提取的事实"""
    fact: str                          # "用户周六要和朋友去爬山"
    timestamp: str = ""                # 提取时间 ISO
    source_ts: float = 0.0             # 原始消息时间戳
    emotion_tag: str = "neutral"       # 情绪标签
    topic_tags: list[str] = field(default_factory=list)  # 话题标签
    usable_after: str = ""             # 可引用时间 ISO（过早引用会奇怪）
    expires: str = ""                  # 过期时间 ISO（过时引用没意义）
    used_count: int = 0                # 被引用次数


class FactStore:
    """事实存储：JSON 文件持久化"""

    def __init__(self, persist_path: str):
        self._path = Path(persist_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._facts: list[Fact] = []
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._facts = [Fact(**f) for f in data]
                logger.debug(f"[FactStore] 加载了 {len(self._facts)} 条事实")
            except Exception as e:
                logger.warning(f"[FactStore] 加载失败: {e}")
                self._facts = []

    def _save(self) -> None:
        self._path.write_text(
            json.dumps([asdict(f) for f in self._facts], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add_facts(self, facts: list[Fact]) -> None:
        """添加新事实，去重后保存"""
        existing = {f.fact for f in self._facts}
        added = 0
        for f in facts:
            if f.fact not in existing:
                self._facts.append(f)
                added += 1
        if added > 0:
            self._cleanup()
            self._save()
            logger.info(f"[FactStore] 新增 {added} 条事实，共 {len(self._facts)} 条")

    def get_available_facts(self, topic_tags: list[str] | None = None) -> list[Fact]:
        """获取当前可用的事实（未过期、已到可用时间、未过度使用）"""
        now = datetime.now()
        available = []
        for f in self._facts:
            # 检查可用时间
            if f.usable_after:
                try:
                    if datetime.fromisoformat(f.usable_after) > now:
                        continue
                except ValueError:
                    pass
            # 检查过期
            if f.expires:
                try:
                    if datetime.fromisoformat(f.expires) < now:
                        continue
                except ValueError:
                    pass
            # 检查使用次数（最多用 3 次）
            if f.used_count >= 3:
                continue
            # 可选：按话题过滤
            if topic_tags and not any(t in f.topic_tags for t in topic_tags):
                continue
            available.append(f)
        return available

    def mark_used(self, fact_text: str) -> None:
        """标记事实被引用"""
        for f in self._facts:
            if f.fact == fact_text:
                f.used_count += 1
                self._save()
                break

    def _cleanup(self) -> None:
        """清理过期事实，保留最多 100 条"""
        now = datetime.now()
        # 移除过期的
        self._facts = [
            f for f in self._facts
            if not f.expires or not _is_expired(f.expires, now)
        ]
        # 按时间排序保留最新 100 条
        self._facts.sort(key=lambda f: f.timestamp, reverse=True)
        self._facts = self._facts[:100]


def _is_expired(expires: str, now: datetime) -> bool:
    try:
        return datetime.fromisoformat(expires) < now
    except ValueError:
        return False


class FactExtractor:
    """从事实提取器：定期从聊天记录中提取结构化事实"""

    SYSTEM_PROMPT = """你是一个事实提取器。从对话中提取用户提到的具体事实、计划、偏好、事件。

提取规则：
1. 只提取用户说的内容，不要提取 AI 的回复
2. 每条事实应该是具体的、可引用的（有时间、地点、人物、事件）
3. 忽略泛泛的寒暄（"你好"、"在干嘛"、"吃了吗"）
4. 标注情绪和话题

输出 JSON 数组，每条格式：
{"fact": "事实描述", "emotion_tag": "情绪", "topic_tags": ["话题1", "话题2"]}

最多提取 10 条。如果没有值得提取的事实，输出空数组 []。"""

    def __init__(self, ai_provider: Any, persist_path: str):
        self._ai = ai_provider
        self._store = FactStore(persist_path)

    @property
    def store(self) -> FactStore:
        return self._store

    async def extract_from_messages(self, messages: list[dict]) -> list[Fact]:
        """从消息列表中提取事实"""
        if not messages:
            return []

        # 只取用户消息
        user_msgs = [m for m in messages if m.get("role") == "user"]
        if not user_msgs:
            return []

        # 拼成对话文本
        conversation = "\n".join(
            f"用户: {m.get('content', '')[:200]}" for m in user_msgs[-30:]
        )

        try:
            response = await self._ai.chat(
                messages=[{"role": "user", "content": conversation}],
                system=self.SYSTEM_PROMPT,
                stream=False,
            )
            content = response.content.strip()

            # 解析 JSON
            if content.startswith("```"):
                content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

            raw_facts = json.loads(content)
            if not isinstance(raw_facts, list):
                return []

            now = datetime.now()
            facts = []
            for rf in raw_facts[:10]:
                if not isinstance(rf, dict) or "fact" not in rf:
                    continue
                fact = Fact(
                    fact=rf["fact"],
                    timestamp=now.isoformat(),
                    source_ts=time.time(),
                    emotion_tag=rf.get("emotion_tag", "neutral"),
                    topic_tags=rf.get("topic_tags", []),
                    usable_after=self._calc_usable_after(rf),
                    expires=self._calc_expires(rf),
                )
                facts.append(fact)

            if facts:
                self._store.add_facts(facts)
            return facts

        except Exception as e:
            logger.error(f"[FactExtractor] 提取失败: {e}")
            return []

    def _calc_usable_after(self, rf: dict) -> str:
        """计算可引用时间（默认 1 小时后，避免刚说完就提）"""
        return (datetime.now()).isoformat()  # 立即可用，后续可优化

    def _calc_expires(self, rf: dict) -> str:
        """计算过期时间（默认 7 天后）"""
        from datetime import timedelta
        return (datetime.now() + timedelta(days=7)).isoformat()
