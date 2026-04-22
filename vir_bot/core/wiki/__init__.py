"""Wiki 知识库管理器 - 解析和管理角色人设卡"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from vir_bot.utils.logger import logger

# =============================================================================
# 数据模型
# =============================================================================


@dataclass
class PersonalityTrait:
    """性格特点"""

    name: str
    description: str
    examples: list[str] = field(default_factory=list)


@dataclass
class CatchPhrase:
    """口头禅"""

    phrase: str
    scenario: str
    emotion: str
    example_sentence: str


@dataclass
class SpeakingStyle:
    """说话风格"""

    dos: list[str] = field(default_factory=list)
    donts: list[str] = field(default_factory=list)
    other_traits: list[str] = field(default_factory=list)


@dataclass
class Preference:
    """个人喜好"""

    name: str
    description: str


@dataclass
class Taboo:
    """禁忌事项"""

    action: str
    consequence: str


@dataclass
class DialogueExample:
    """对话示例"""

    title: str
    trigger: str
    character_behavior: str
    dialogue: str
    explanation: str


@dataclass
class CharacterProfile:
    """角色完整人设"""

    # 基本信息
    name: str
    gender: str
    age_feeling: str
    position: str
    background: str

    # 核心性格
    personality_traits: list[PersonalityTrait] = field(default_factory=list)

    # 口头禅
    catch_phrases: list[CatchPhrase] = field(default_factory=list)

    # 说话风格
    speaking_style: SpeakingStyle = field(default_factory=SpeakingStyle)

    # 喜好和禁忌
    preferences: list[Preference] = field(default_factory=list)
    taboos: list[Taboo] = field(default_factory=list)

    # 对话示例
    dialogue_examples: list[DialogueExample] = field(default_factory=list)

    # 特殊设定
    special_settings: list[str] = field(default_factory=list)

    # 创建信息
    created_date: str = ""
    last_modified: str = ""
    maintainer: str = ""

    def get_system_prompt_injection(self) -> str:
        """生成用于系统提示词的人设注入文本"""
        lines = []

        # 基本身份
        lines.append(f"你是 {self.name}。")
        lines.append("")

        # 核心性格
        if self.personality_traits:
            lines.append("【核心性格（必须遵守）】")
            for trait in self.personality_traits:
                lines.append(f"- {trait.name}: {trait.description}")
            lines.append("")

        # 常用口头禅
        if self.catch_phrases:
            lines.append("【常用口头禅】")
            phrases = [f'"{cp.phrase}" ({cp.scenario})' for cp in self.catch_phrases[:5]]
            lines.append("、".join(phrases))
            lines.append("")

        # 说话风格简述
        if self.speaking_style.dos:
            lines.append("【说话风格】")
            lines.append("应该这样说:")
            for do in self.speaking_style.dos[:3]:
                lines.append(f"- {do}")
            lines.append("")

        # 喜好
        if self.preferences:
            lines.append("【个人喜好】")
            for pref in self.preferences:
                lines.append(f"- 喜欢{pref.name}")
            lines.append("")

        # 禁忌
        if self.taboos:
            lines.append("【禁忌（绝不要做）】")
            for taboo in self.taboos:
                lines.append(f"- 不要{taboo.action}")
            lines.append("")

        # 特殊设定
        if self.special_settings:
            lines.append("【特殊设定】")
            for setting in self.special_settings:
                lines.append(f"- {setting}")
            lines.append("")

        return "\n".join(lines)

    def get_personality_keywords(self) -> list[str]:
        """提取性格关键词，用于检索相关记忆"""
        keywords = []

        # 性格名称
        keywords.extend([trait.name for trait in self.personality_traits])

        # 口头禅
        keywords.extend([cp.phrase for cp in self.catch_phrases])

        # 喜好
        keywords.extend([p.name for p in self.preferences])

        return keywords


# =============================================================================
# Wiki 知识库解析器
# =============================================================================


class WikiKnowledgeBase:
    """Wiki 知识库管理器"""

    def __init__(self, wiki_dir: str = "./data/wiki"):
        self.wiki_dir = Path(wiki_dir)
        self.characters_dir = self.wiki_dir / "characters"
        self._character_cache: dict[str, CharacterProfile] = {}

        logger.info(f"WikiKnowledgeBase initialized: wiki_dir={wiki_dir}")

    async def load_character(self, name: str) -> Optional[CharacterProfile]:
        """加载角色人设卡"""
        # 先查缓存
        if name in self._character_cache:
            return self._character_cache[name]

        # 从文件加载
        char_file = self.characters_dir / f"{name}.md"

        if not char_file.exists():
            logger.warning(f"Character file not found: {char_file}")
            return None

        try:
            profile = self._parse_character_markdown(char_file)
            self._character_cache[name] = profile
            logger.info(f"Character loaded: {name}")
            return profile
        except Exception as e:
            logger.error(f"Error loading character {name}: {e}")
            return None

    def _parse_character_markdown(self, file_path: Path) -> CharacterProfile:
        """解析 Markdown 格式的人设卡"""
        with open(file_path, encoding="utf-8") as f:
            content = f.read()

        # 提取各个部分
        profile = CharacterProfile(
            name=self._extract_name(content),
            gender=self._extract_field(content, "性别", "女性"),
            age_feeling=self._extract_field(content, "年龄感", ""),
            position=self._extract_field(content, "定位", ""),
            background=self._extract_field(content, "背景", ""),
            created_date=self._extract_field(content, "创建日期", ""),
            last_modified=self._extract_field(content, "最后修改", ""),
            maintainer=self._extract_field(content, "维护者", ""),
        )

        # 解析各部分
        profile.personality_traits = self._parse_personality_traits(content)
        profile.catch_phrases = self._parse_catch_phrases(content)
        profile.speaking_style = self._parse_speaking_style(content)
        profile.preferences = self._parse_preferences(content)
        profile.taboos = self._parse_taboos(content)
        profile.dialogue_examples = self._parse_dialogue_examples(content)
        profile.special_settings = self._parse_special_settings(content)

        return profile

    def _extract_name(self, content: str) -> str:
        """从内容中提取角色名称"""
        match = re.search(r"^#\s+(.+?)$", content, re.MULTILINE)
        if match:
            return match.group(1).strip()
        return "Unknown"

    def _extract_field(self, content: str, field_name: str, default: str = "") -> str:
        """提取指定字段的值"""
        pattern = rf"-\s*\*?\*?{field_name}\*?\*?:\s*(.+?)(?:\n|$)"
        match = re.search(pattern, content)
        if match:
            return match.group(1).strip()
        return default

    def _parse_personality_traits(self, content: str) -> list[PersonalityTrait]:
        """解析核心性格部分"""
        traits = []

        # 匹配"## 核心性格"或"## Core Personality"
        pattern = r"##\s+核心性格[^\n]*\n(.*?)(?=\n##|\Z)"
        match = re.search(pattern, content, re.DOTALL)

        if not match:
            return traits

        trait_section = match.group(1)

        # 匹配"1. **名称** - 描述"的模式
        trait_pattern = r"(\d+)\.\s+\*\*(.+?)\*\*\s*-\s*(.+?)(?=\n\d+\.|\n-\s|$)"
        for trait_match in re.finditer(trait_pattern, trait_section, re.DOTALL):
            name = trait_match.group(2).strip()
            description = trait_match.group(3).strip()
            # 移除"例子:"部分
            description = re.sub(r"\n\s*-?\s*例子:.*", "", description, flags=re.DOTALL)
            description = description.replace("\n   - ", " ").replace("\n", " ")

            traits.append(PersonalityTrait(name=name, description=description))

        return traits

    def _parse_catch_phrases(self, content: str) -> list[CatchPhrase]:
        """解析常用口头禅"""
        phrases = []

        # 匹配表格部分
        pattern = r"##\s+常用口头禅[^\n]*\n\|.*?\|.*?\|.*?\|.*?\|\n\|.*?\|\n(.*?)(?=\n##|\Z)"
        match = re.search(pattern, content, re.DOTALL)

        if not match:
            return phrases

        table_content = match.group(1)

        # 解析表格行
        row_pattern = r"\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|"
        for row_match in re.finditer(row_pattern, table_content):
            phrase = row_match.group(1).strip()
            scenario = row_match.group(2).strip()
            emotion = row_match.group(3).strip()
            example = row_match.group(4).strip()

            if phrase and scenario:  # 过滤掉表头或空行
                phrases.append(
                    CatchPhrase(
                        phrase=phrase, scenario=scenario, emotion=emotion, example_sentence=example
                    )
                )

        return phrases

    def _parse_speaking_style(self, content: str) -> SpeakingStyle:
        """解析说话风格"""
        style = SpeakingStyle()

        # 提取"应该这样说"部分
        dos_pattern = r"###\s+应该这样说\s*✅\n(.*?)(?=\n###|\n##)"
        dos_match = re.search(dos_pattern, content, re.DOTALL)
        if dos_match:
            dos_text = dos_match.group(1)
            style.dos = [
                line.strip("- ").strip()
                for line in dos_text.split("\n")
                if line.strip().startswith("-")
            ]

        # 提取"不应该这样说"部分
        donts_pattern = r"###\s+不应该这样说\s*❌\n(.*?)(?=\n###|\n##)"
        donts_match = re.search(donts_pattern, content, re.DOTALL)
        if donts_match:
            donts_text = donts_match.group(1)
            style.donts = [
                line.strip("- ").strip()
                for line in donts_text.split("\n")
                if line.strip().startswith("-")
            ]

        # 提取"其他特点"部分
        traits_pattern = r"###\s+其他特点\n(.*?)(?=\n##|\Z)"
        traits_match = re.search(traits_pattern, content, re.DOTALL)
        if traits_match:
            traits_text = traits_match.group(1)
            style.other_traits = [
                line.strip("- ").strip()
                for line in traits_text.split("\n")
                if line.strip().startswith("-")
            ]

        return style

    def _parse_preferences(self, content: str) -> list[Preference]:
        """解析个人喜好"""
        prefs = []

        pattern = r"##\s+个人喜好[^\n]*\n(.*?)(?=\n##|\Z)"
        match = re.search(pattern, content, re.DOTALL)

        if not match:
            return prefs

        prefs_text = match.group(1)

        # 匹配"- ❤️ 名称 - 描述"模式
        pref_pattern = r"-\s*❤️\s*\*?\*?(.+?)\*?\*?\s*-\s*(.+?)(?=\n-|\Z)"
        for pref_match in re.finditer(pref_pattern, prefs_text, re.DOTALL):
            name = pref_match.group(1).strip()
            description = pref_match.group(2).strip()
            description = description.replace("\n", " ")

            prefs.append(Preference(name=name, description=description))

        return prefs

    def _parse_taboos(self, content: str) -> list[Taboo]:
        """解析禁忌事项"""
        taboos = []

        pattern = r"##\s+禁忌[^\n]*\n(.*?)(?=\n##|\Z)"
        match = re.search(pattern, content, re.DOTALL)

        if not match:
            return taboos

        taboos_text = match.group(1)

        # 匹配"- ❌ 行为 - 后果"模式
        taboo_pattern = r"-\s*❌\s*\*?\*?(.+?)\*?\*?\s*-\s*后果：(.+?)(?=\n-|\Z)"
        for taboo_match in re.finditer(taboo_pattern, taboos_text, re.DOTALL):
            action = taboo_match.group(1).strip()
            consequence = taboo_match.group(2).strip()
            consequence = consequence.replace("\n", " ")

            taboos.append(Taboo(action=action, consequence=consequence))

        return taboos

    def _parse_dialogue_examples(self, content: str) -> list[DialogueExample]:
        """解析对话示例"""
        examples = []

        # 匹配所有"### 场景 N"部分
        pattern = r"###\s+场景\s+\d+：?\s*(.+?)\n(.*?)(?=###\s+场景|\n##|\Z)"
        for match in re.finditer(pattern, content, re.DOTALL):
            title = match.group(1).strip()
            scene_content = match.group(2)

            # 提取各个字段
            trigger = self._extract_section(scene_content, "触发条件")
            behavior = self._extract_section(scene_content, "角色表现")
            dialogue = self._extract_section(scene_content, "示例对话")
            explanation = self._extract_section(scene_content, "为什么这样回应")

            if title and dialogue:
                examples.append(
                    DialogueExample(
                        title=title,
                        trigger=trigger,
                        character_behavior=behavior,
                        dialogue=dialogue,
                        explanation=explanation,
                    )
                )

        return examples

    def _parse_special_settings(self, content: str) -> list[str]:
        """解析特殊设定"""
        settings = []

        pattern = r"##\s+特殊设定[^\n]*\n(.*?)(?=\n##|\Z)"
        match = re.search(pattern, content, re.DOTALL)

        if match:
            settings_text = match.group(1)
            settings = [
                line.strip("- ").strip()
                for line in settings_text.split("\n")
                if line.strip().startswith("-")
            ]

        return settings

    def _extract_section(self, text: str, section_name: str) -> str:
        """提取指定部分的内容"""
        pattern = rf"\*\*{section_name}\*?\*?:\s*(.+?)(?=\n\*\*|\n###|\Z)"
        match = re.search(pattern, text, re.DOTALL)
        if match:
            return match.group(1).strip()
        return ""

    def clear_cache(self) -> None:
        """清除缓存"""
        self._character_cache.clear()
        logger.info("Wiki character cache cleared")

    async def get_all_characters(self) -> list[str]:
        """获取所有可用角色"""
        characters = []
        if self.characters_dir.exists():
            for file in self.characters_dir.glob("*.md"):
                if file.name not in ["_index.md", "template.md"]:
                    name = file.stem
                    characters.append(name)
        return sorted(characters)
