"""角色卡系统（SillyTavern 兼容）"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vir_bot.utils.logger import logger


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
) -> str:
    """
    从角色卡构建 System Prompt。
    将结构化字段拼装为自然语言系统提示词。
    """
    parts = []

    # 基础设定
    if card.name:
        parts.append(f"你是 {card.name}。")

    if card.personality:
        parts.append(f"你的性格：{card.personality}")

    if card.description:
        parts.append(f"关于你：{card.description}")

    if card.scenario:
        parts.append(f"当前场景：{card.scenario}")

    if card.world_info:
        parts.append(f"世界观设定：\n{card.world_info}")

    # 语气风格
    if voice_style:
        parts.append(f"说话风格：{voice_style}")

    # 人格标签
    if personality_tags:
        parts.append(f"人格标签：{', '.join(personality_tags)}")

    # 示例对话（作为few-shot）
    if card.example_dialogue:
        parts.append(f"\n对话示例：\n{card.example_dialogue}")

    # 额外上下文
    if extra_context:
        parts.append(f"\n额外信息：\n{extra_context}")

    # 主动行为指引（从角色卡扩展读取）
    proactive = card.extensions.get("proactive_behavior", {})
    avoid = proactive.get("避免的表达", [])
    if avoid:
        parts.append(f"绝不要说这些话：{'、'.join(avoid)}")

    response_style = card.extensions.get("response_style", {})
    if response_style:
        style_parts = [f"{k}：{v}" for k, v in response_style.items() if isinstance(v, str)]
        if style_parts:
            parts.append("说话方式：" + "；".join(style_parts))

    # 通用消息格式指令（所有角色统一，不写在角色卡里）
    parts.append(
        "回复格式：用2-4条短消息回复，每条10-40字，用换行分隔。"
        "不要把一句话拆太碎，叙事时可以稍长但不超过80字。"
        "不要超过5条消息。"
    )

    return "\n\n".join(parts)