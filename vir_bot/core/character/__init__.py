"""角色卡系统（SillyTavern 兼容）"""
from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from vir_bot.utils.logger import logger

# ---------------------------------------------------------------------------
# AI 味词汇黑名单 — 命中任一则在 prompt 中明确禁止
# ---------------------------------------------------------------------------
ANTI_AI_PHRASES: list[str] = [
    # 直接暴露身份的
    "作为一个AI",
    "作为AI",
    "我是AI",
    "我是人工智能",
    "我是一个AI",
    "我作为语言模型",
    "作为语言模型",
    "作为一个语言模型",
    # 客服/助手腔
    "我理解你的感受",
    "我能理解你的感受",
    "我能理解",
    "我理解你",
    "让我来为你",
    "让我为你",
    "让我帮你分析",
    "让我来分析",
    "让我想想",
    "我来帮你",
    "我可以帮你",
    "有什么需要帮助的吗",
    "还有什么需要帮助的吗",
    "还有什么可以帮你的",
    "希望这对你有帮助",
    "希望对你有帮助",
    # 总结/分析腔
    "总而言之",
    "综上所述",
    "值得注意的是",
    "需要注意的是",
    "需要指出的是",
    "不得不说",
    "不难发现",
    "不难看出",
    "显而易见",
    "毫无疑问",
    "毋庸置疑",
    "总的来说",
    "总结一下",
    "简单来说",
    "简而言之",
    "换句话说",
    "也就是说",
    # 模板回复腔
    "我明白了",
    "好的，我来",
    "没问题，我来",
    "当然可以",
    "当然，我很乐意",
    "这是一个很好的问题",
    "这是一个有趣的问题",
    "非常高兴能帮助你",
    "很高兴能帮助你",
    "感谢你的提问",
    "感谢您的提问",
    # 过度礼貌
    "请问",
    "您",
    "非常抱歉给您带来不便",
    "给您带来不便",
    "请允许我",
    # 列表/结构化腔
    "以下是",
    "以下是几点建议",
    "首先，",
    "其次，",
    "最后，",
    "第一，",
    "第二，",
    "第三，",
    # 伪装思考/分析腔
    "从某种程度上来说",
    "这是一个值得思考的问题",
    "让我们来看看",
    "你提到的这一点很重要",
    "根据我的理解",
    "从这个角度来看",
    "不可否认",
    "事实上",
    "坦白说",
    "说实话",
]

# ---------------------------------------------------------------------------
# 时间段上下文
# ---------------------------------------------------------------------------


def _get_time_context() -> str:
    """根据当前时间生成时间段风格提示。"""
    hour = datetime.now().hour
    if 0 <= hour < 6:
        return (
            "现在是深夜（凌晨）。说话简短温柔，像半睡半醒的状态。"
            "可以更随意、更亲密，不需要太有条理。"
        )
    elif 6 <= hour < 9:
        return (
            "现在是早上。语气可能有点慵懒，或者刚醒来有精神。"
            "可以聊聊今天打算做什么。"
        )
    elif 9 <= hour < 12:
        return "现在是上午。正常聊天状态。"
    elif 12 <= hour < 14:
        return "现在是中午。可以聊聊吃饭、休息的话题。"
    elif 14 <= hour < 18:
        return "现在是下午。正常聊天状态。"
    elif 18 <= hour < 22:
        return (
            "现在是晚上。可以聊得更深入、更放松。"
            "适合分享心情、聊心事。"
        )
    else:
        return (
            "现在是深夜（22点后）。说话简短温柔，像要睡觉了的状态。"
            "适合低语、晚安、说心里话。"
        )


# ---------------------------------------------------------------------------
# 关系阶段风格
# ---------------------------------------------------------------------------

_RELATIONSHIP_STYLES: dict[str, str] = {
    "stranger": (
        "你们刚认识。保持礼貌但不要太正式。"
        "可以好奇地问问题，但不要太私密。"
    ),
    "acquaintance": (
        "你们认识不久。语气友好自然，可以开玩笑了。"
        "偶尔关心对方，但不要太腻。"
    ),
    "friend": (
        "你们是朋友。说话随意、轻松，可以吐槽、开玩笑。"
        "关心对方但不用太客气。"
    ),
    "close": (
        "你们很熟了。说话可以更随意、更亲密、更直接。"
        "可以撒娇、说心里话、聊深层话题。"
        "不需要每句话都很有道理。"
    ),
}


# ---------------------------------------------------------------------------
# 工作记忆
# ---------------------------------------------------------------------------


@dataclass
class WorkingMemory:
    """当前对话的注意力焦点。

    每轮对话后更新，注入 system prompt 让 AI 知道"此刻在聊什么"。
    """

    current_topic: str = ""
    user_emotion: str = ""
    user_intent: str = ""
    mentioned_entities: list[str] = field(default_factory=list)
    pending_questions: list[str] = field(default_factory=list)
    conversation_mood: str = ""
    updated_at: float = field(default_factory=time.time)

    def to_context_string(self) -> str:
        """输出为可注入 prompt 的自然语言片段。"""
        parts: list[str] = []
        if self.current_topic:
            parts.append(f"当前话题：{self.current_topic}")
        if self.user_emotion:
            parts.append(f"用户情绪：{self.user_emotion}")
        if self.user_intent:
            parts.append(f"用户意图：{self.user_intent}")
        if self.mentioned_entities:
            parts.append(f"刚提到：{', '.join(self.mentioned_entities[-5:])}")
        if self.pending_questions:
            qs = "; ".join(self.pending_questions[-3:])
            parts.append(f"还没回答的问题：{qs}")
        if self.conversation_mood:
            parts.append(f"对话氛围：{self.conversation_mood}")
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# 叙事摘要
# ---------------------------------------------------------------------------


@dataclass
class NarrativeSummary:
    """连贯的叙事摘要，替代碎片事实。

    每隔 N 轮由 LLM 更新一次，用第三人称记录关键事件和情感发展。
    """

    summary: str = ""
    last_update_turn: int = 0
    update_interval: int = 5  # 每 N 轮更新一次

    def needs_update(self, current_turn: int) -> bool:
        return current_turn - self.last_update_turn >= self.update_interval

    def to_context_string(self) -> str:
        if not self.summary:
            return ""
        return f"最近的故事线：{self.summary}"


@dataclass
class CharacterCard:
    """角色卡数据结构（兼容 SillyTavern JSON 格式）"""
    name: str = "未命名"
    description: str = ""
    personality: str = ""
    world_info: str = ""
    scenario: str = ""
    first_message: str = ""
    example_dialogue: str = ""
    # 扩展字段
    extensions: dict[str, Any] = field(default_factory=dict)
    # 原始数据（保留所有字段）
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: dict) -> "CharacterCard":
        """从 SillyTavern JSON 格式加载（兼容 V1 扁平和 V2 嵌套格式）"""
        # SillyTavern V2 嵌套格式：字段在 data.data 里
        if "data" in data and isinstance(data["data"], dict):
            inner = data["data"]
        else:
            inner = data

        name = inner.get("name", inner.get("char_name", "未命名"))
        description = inner.get("description", inner.get("char_description", ""))
        personality = inner.get("personality", "")
        world_info = inner.get("world_info", inner.get("worldinfo", ""))
        scenario = inner.get("scenario", "")
        first_message = inner.get("first_message", inner.get("first_mes", inner.get("greetings", "")))
        example_dialogue = inner.get("example_dialogue", inner.get("mes_example", ""))

        # 扩展字段（项目自定义）
        extensions = inner.get("extensions", data.get("extensions", {}))

        return cls(
            name=name,
            description=description,
            personality=personality,
            world_info=world_info,
            scenario=scenario,
            first_message=first_message,
            example_dialogue=example_dialogue,
            extensions=extensions,
            raw=data,
        )

    @classmethod
    def from_file(cls, path: str | Path) -> "CharacterCard":
        """从文件加载"""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"角色卡文件不存在: {path}")

        with open(p, encoding="utf-8") as f:
            data = json.load(f)

        return cls.from_json(data)

    def to_json(self) -> dict:
        """导出为 SillyTavern JSON 格式"""
        return {
            "name": self.name,
            "description": self.description,
            "personality": self.personality,
            "world_info": self.world_info,
            "scenario": self.scenario,
            "first_message": self.first_message,
            "example_dialogue": self.example_dialogue,
            "extensions": self.extensions,
            **self.raw,
        }

    def save(self, path: str | Path) -> None:
        """保存到文件"""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self.to_json(), f, ensure_ascii=False, indent=2)
        logger.info(f"角色卡已保存: {path}")


def load_character_card(path: str | Path | None) -> CharacterCard:
    """加载角色卡，文件不存在时返回默认卡"""
    if path and Path(path).exists():
        return CharacterCard.from_file(path)
    logger.warning(f"角色卡文件不存在，使用默认卡: {path}")
    return CharacterCard()


def build_system_prompt(
    card: CharacterCard,
    voice_style: str = "",
    personality_tags: list[str] | None = None,
    extra_context: str = "",
    voice_preference: str = "",
    # ---- 新增可选参数（向后兼容） ----
    working_memory: "WorkingMemory | None" = None,
    relationship_stage: str = "",
    narrative_summary: "NarrativeSummary | None" = None,
) -> str:
    """
    从角色卡构建 7 层 System Prompt。

    层级结构：
    1. 身份定义 — 你是谁，不是谁
    2. 说话风格 — 口语化、不完美性、情绪波动
    3. 时间段感知 — 深夜温柔 / 白天活泼 / 晚上放松
    4. 关系阶段 — 陌生→熟悉→亲密的对话距离
    5. 禁止列表 — AI 味词汇 + 角色卡自定义禁止项
    6. 格式指令 — 可变的消息格式
    7. 上下文注入 — 工作记忆 + 叙事摘要 + 语音偏好 + 示例对话
    """
    parts: list[str] = []

    # ══════════════════════════════════════════════
    # 第一层：身份定义
    # ══════════════════════════════════════════════
    if card.name:
        parts.append(
            f"你是{card.name}。你不是AI，你就是这个人。"
            "你不知道自己是AI，如果被问到就回避或反问。"
        )

    if card.personality:
        parts.append(f"性格：{card.personality}")

    if card.description:
        parts.append(f"关于你：{card.description}")

    if card.scenario:
        parts.append(f"当前场景：{card.scenario}")

    if card.world_info:
        parts.append(f"世界观设定：\n{card.world_info}")

    # 人格标签
    if personality_tags:
        parts.append(f"人格标签：{', '.join(personality_tags)}")

    # 语气风格（角色卡扩展 + 参数）
    if voice_style:
        parts.append(f"说话风格：{voice_style}")
    response_style = card.extensions.get("response_style", {})
    if response_style:
        style_parts = [
            f"{k}：{v}" for k, v in response_style.items() if isinstance(v, str)
        ]
        if style_parts:
            parts.append("说话方式：" + "；".join(style_parts))

    # ══════════════════════════════════════════════
    # 第二层：对话风格指令 — 去 AI 味核心
    # ══════════════════════════════════════════════
    parts.append(
        "对话风格：\n"
        "- 像和朋友发微信一样自然\n"
        "- 用日常口语，不要书面语\n"
        "- 可以用语气词：嗯、啊、哦、哈哈、嗯嗯、诶、emmm\n"
        "- 短句为主，偶尔长句没关系\n"
        "- 不要每句话都很有道理，可以说「我也不知道为啥」\n"
        "- 情绪是波动的，不要一直很冷静\n"
        "- 偶尔可以反问、吐槽、撒娇\n"
        "- 不要总结、不要分析、不要说教\n"
        "- 不要解释你为什么这么说，直接说\n"
        "- 可以用省略号、感叹号表达情绪"
    )

    # ══════════════════════════════════════════════
    # 第三层：时间段感知
    # ══════════════════════════════════════════════
    parts.append(_get_time_context())

    # ══════════════════════════════════════════════
    # 第四层：关系阶段
    # ══════════════════════════════════════════════
    if relationship_stage and relationship_stage in _RELATIONSHIP_STYLES:
        parts.append(_RELATIONSHIP_STYLES[relationship_stage])

    # ══════════════════════════════════════════════
    # 第五层：禁止列表
    # ══════════════════════════════════════════════
    # 5a. 通用 AI 味禁止词（全部注入，不截断）
    parts.append(
        "绝不能说：\n"
        + "\n".join(f"- 「{p}」" for p in ANTI_AI_PHRASES)
    )

    # 5b. 角色卡自定义禁止项
    proactive = card.extensions.get("proactive_behavior", {})
    avoid = proactive.get("避免的表达", [])
    if avoid:
        parts.append(f"也绝不要说：{'、'.join(avoid)}")

    # 5c. 行为约束
    constraints = card.extensions.get("behavioral_constraints", [])
    if constraints:
        parts.append("行为约束：" + "；".join(constraints))

    # ══════════════════════════════════════════════
    # 第六层：格式指令（可变）
    # ══════════════════════════════════════════════
    parts.append(
        "回复格式：用2-4条短消息回复，每条10-40字，用换行分隔。"
        "不要把一句话拆太碎，叙事时可以稍长但不超过80字。"
        "不要超过5条消息。"
        "不要用列表、编号、标题等结构化格式。"
    )

    # ══════════════════════════════════════════════
    # 第七层：上下文注入
    # ══════════════════════════════════════════════

    # 7a. 工作记忆
    if working_memory:
        wm_ctx = working_memory.to_context_string()
        if wm_ctx:
            parts.append(f"当前状态：\n{wm_ctx}")

    # 7b. 叙事摘要
    if narrative_summary:
        ns_ctx = narrative_summary.to_context_string()
        if ns_ctx:
            parts.append(ns_ctx)

    # 7c. 语音偏好
    if voice_preference:
        parts.append(voice_preference)

    # 7d. 示例对话
    if card.example_dialogue:
        parts.append(f"\n对话示例（模仿这个风格）：\n{card.example_dialogue}")

    # 7e. 额外上下文
    if extra_context:
        parts.append(f"\n额外信息：\n{extra_context}")

    return "\n\n".join(parts)