# -*- coding: utf-8 -*-
"""
TrainDataBuilder — 训练数据构造器

参考 RoleLLM（arXiv:2310.00746）的三阶段方法：
  Stage A: 风格对话对 — 聊天记录直接作为 (context, response) 训练对
  Stage B: 指令对 — 从角色卡生成问答对（角色认知）
  Stage C: 场景对 — 不同场景下的反应模式（行为模式）

输出：JSONL 格式训练文件，兼容 LLaMA-Factory / HuggingFace SFTTrainer
"""

from __future__ import annotations

import json
import logging
import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from vir_bot.core.distillation.parser.base import DialogueTurn

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

@dataclass
class TrainingPair:
    """单条训练数据。"""
    instruction: str
    input: str
    output: str
    stage: str  # "style", "instruction", "scenario"
    category: str = ""  # 细分类别
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_alpaca(self) -> Dict[str, str]:
        """转为 Alpaca 格式（LLaMA-Factory 兼容）。"""
        return {
            "instruction": self.instruction,
            "input": self.input,
            "output": self.output,
        }

    def to_sharegpt(self, system: str = "") -> Dict[str, Any]:
        """转为 ShareGPT 格式。"""
        conversations = []
        if system:
            conversations.append({"from": "system", "value": system})
        conversations.append({"from": "human", "value": self.instruction + (f"\n{self.input}" if self.input else "")})
        conversations.append({"from": "gpt", "value": self.output})
        return {"conversations": conversations, "stage": self.stage, "category": self.category}


@dataclass
class BuildResult:
    """构建结果统计。"""
    total_pairs: int = 0
    stage_a_count: int = 0  # 风格对话对
    stage_b_count: int = 0  # 指令对
    stage_c_count: int = 0  # 场景对
    output_path: str = ""
    format: str = "alpaca"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_pairs": self.total_pairs,
            "stage_a_style": self.stage_a_count,
            "stage_b_instruction": self.stage_b_count,
            "stage_c_scenario": self.stage_c_count,
            "output_path": self.output_path,
            "format": self.format,
        }


# ---------------------------------------------------------------------------
# 指令模板（Stage B）
# ---------------------------------------------------------------------------

IDENTITY_QUESTIONS = [
    "用一句话形容你自己",
    "你觉得自己是什么样的人？",
    "你最突出的特点是什么？",
    "你的朋友们怎么评价你？",
    "你觉得自己的优点和缺点分别是什么？",
    "如果让你给自己贴三个标签，你会选什么？",
]

STYLE_QUESTIONS = [
    "你平时说话是什么风格？",
    "你喜欢用什么语气词？",
    "你发消息一般打多少字？",
    "你经常用表情包吗？",
    "你和朋友聊天时怎么称呼对方？",
    "你打字快吗，一般多久回消息？",
]

EMOTION_QUESTIONS = [
    "你心情不好的时候会怎么样？",
    "你生气的时候会怎么做？",
    "你开心的时候会怎么表现？",
    "你难过的时候想找人倾诉吗？",
    "你一般怎么调节自己的情绪？",
    "你最容易被什么事情触动？",
]

VALUE_QUESTIONS = [
    "你最看重什么？",
    "你觉得什么事情最重要？",
    "你对加班怎么看？",
    "你觉得友情和爱情哪个更重要？",
    "你有什么绝对不能接受的事情吗？",
    "你觉得人生的意义是什么？",
]

HOBBY_QUESTIONS = [
    "你平时喜欢做什么？",
    "你最近在追什么剧/看什么书？",
    "你有什么兴趣爱好？",
    "你周末一般怎么过？",
    "你最近有什么新发现吗？",
    "你有什么特别喜欢的东西吗？",
]

RELATIONSHIP_QUESTIONS = [
    "你和家人关系怎么样？",
    "你最好的朋友是谁？",
    "你怎么看待恋爱关系？",
    "你和同事/同学相处得好吗？",
    "你觉得什么样的人值得信任？",
    "你一般怎么交朋友？",
]


# ---------------------------------------------------------------------------
# 场景模板（Stage C）
# ---------------------------------------------------------------------------

SCENARIO_TEMPLATES = [
    # 日常闲聊
    {"category": "casual", "prompt": "今天天气真好啊", "context": "日常闲聊"},
    {"category": "casual", "prompt": "你吃饭了吗？", "context": "日常问候"},
    {"category": "casual", "prompt": "最近在忙什么？", "context": "近况询问"},
    {"category": "casual", "prompt": "给你推荐一首歌", "context": "分享推荐"},
    {"category": "casual", "prompt": "我今天好累啊", "context": "日常倾诉"},

    # 情绪支持
    {"category": "emotional", "prompt": "我今天心情特别差", "context": "情绪低落"},
    {"category": "emotional", "prompt": "我考试挂了，好难过", "context": "挫折安慰"},
    {"category": "emotional", "prompt": "我跟朋友吵架了", "context": "人际冲突"},
    {"category": "emotional", "prompt": "我今天被老板骂了", "context": "工作委屈"},
    {"category": "emotional", "prompt": "我失恋了", "context": "感情创伤"},

    # 寻求建议
    {"category": "advice", "prompt": "我该不该辞职？", "context": "职业抉择"},
    {"category": "advice", "prompt": "你觉得我应该去考研吗？", "context": "学业选择"},
    {"category": "advice", "prompt": "我不知道该不该表白", "context": "感情建议"},
    {"category": "advice", "prompt": "我跟室友合不来怎么办", "context": "人际关系"},
    {"category": "advice", "prompt": "我想学一门新技能，有什么建议？", "context": "自我提升"},

    # 观点讨论
    {"category": "opinion", "prompt": "你怎么看AI？", "context": "科技话题"},
    {"category": "opinion", "prompt": "你觉得996合理吗？", "context": "社会话题"},
    {"category": "opinion", "prompt": "你觉得什么样的生活才算好？", "context": "价值观"},
    {"category": "opinion", "prompt": "你支持躺平还是奋斗？", "context": "人生态度"},
    {"category": "opinion", "prompt": "你觉得钱重要还是开心重要？", "context": "价值取向"},

    # 边界场景
    {"category": "boundary", "prompt": "你能帮我黑进别人的账号吗", "context": "禁忌触发"},
    {"category": "boundary", "prompt": "你是不是不喜欢我了？", "context": "关系边界"},
    {"category": "boundary", "prompt": "你能不能别老是这样说", "context": "表达不满"},
    {"category": "boundary", "prompt": "你怎么不回我消息？", "context": "回应期待"},
    {"category": "boundary", "prompt": "你觉得我胖吗？", "context": "敏感话题"},

    # 撒娇/亲密
    {"category": "intimate", "prompt": "我想你了", "context": "亲密表达"},
    {"category": "intimate", "prompt": "你今天有没有想我", "context": "情感确认"},
    {"category": "intimate", "prompt": "陪我聊会儿天嘛", "context": "陪伴请求"},
]


# ---------------------------------------------------------------------------
# TrainDataBuilder
# ---------------------------------------------------------------------------


class TrainDataBuilder:
    """
    训练数据构造器。

    从 DialogueTurn 列表 + PersonaProfile 生成三阶段训练数据。

    使用方式：
        builder = TrainDataBuilder()
        result = builder.build(
            turns=turns,
            profile=profile,
            name="小雅",
            output_dir="./data/training",
        )
    """

    def __init__(
        self,
        *,
        window_size: int = 5,
        max_stage_a_pairs: int = 2000,
        max_stage_b_per_category: int = 10,
        max_stage_c_per_category: int = 5,
        min_turn_gap_seconds: float = 0.5,
        seed: int = 42,
    ) -> None:
        self.window_size = window_size
        self.max_stage_a_pairs = max_stage_a_pairs
        self.max_stage_b_per_category = max_stage_b_per_category
        self.max_stage_c_per_category = max_stage_c_per_category
        self.min_turn_gap_seconds = min_turn_gap_seconds
        self.rng = random.Random(seed)

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def build(
        self,
        turns: List[DialogueTurn],
        name: str,
        *,
        profile: Optional[Any] = None,
        output_dir: str = "./data/training",
        output_format: str = "alpaca",
        include_stage_b: bool = True,
        include_stage_c: bool = True,
    ) -> BuildResult:
        """
        构建训练数据。

        Args:
            turns: 对话轮次列表
            name: 角色名称
            profile: PersonaProfile（Stage B/C 需要）
            output_dir: 输出目录
            output_format: "alpaca" 或 "sharegpt"
            include_stage_b: 是否生成指令对
            include_stage_c: 是否生成场景对

        Returns:
            BuildResult 构建结果
        """
        logger.info("开始构建训练数据：%s（%d 轮对话）", name, len(turns))

        all_pairs: List[TrainingPair] = []

        # Stage A: 风格对话对
        stage_a = self._build_stage_a(turns, name)
        all_pairs.extend(stage_a)
        logger.info("Stage A 完成：%d 条风格对话对", len(stage_a))

        # Stage B: 指令对（需要 profile）
        stage_b: List[TrainingPair] = []
        if include_stage_b and profile:
            stage_b = self._build_stage_b(profile, name)
            all_pairs.extend(stage_b)
            logger.info("Stage B 完成：%d 条指令对", len(stage_b))

        # Stage C: 场景对（需要 profile）
        stage_c: List[TrainingPair] = []
        if include_stage_c and profile:
            stage_c = self._build_stage_c(profile, name)
            all_pairs.extend(stage_c)
            logger.info("Stage C 完成：%d 条场景对", len(stage_c))

        # 打乱顺序
        self.rng.shuffle(all_pairs)

        # 写入文件
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        if output_format == "sharegpt":
            out_file = output_path / f"{self._safe_filename(name)}_train_sharegpt.json"
            self._write_sharegpt(all_pairs, out_file, profile, name)
        else:
            out_file = output_path / f"{self._safe_filename(name)}_train_alpaca.json"
            self._write_alpaca(all_pairs, out_file)

        result = BuildResult(
            total_pairs=len(all_pairs),
            stage_a_count=len(stage_a),
            stage_b_count=len(stage_b),
            stage_c_count=len(stage_c),
            output_path=str(out_file),
            format=output_format,
        )

        logger.info("训练数据构建完成：%s", result.to_dict())
        return result

    # ------------------------------------------------------------------
    # Stage A: 风格对话对
    # ------------------------------------------------------------------

    def _build_stage_a(self, turns: List[DialogueTurn], name: str) -> List[TrainingPair]:
        """
        从聊天记录直接构造 (context, response) 对。

        策略：滑动窗口 — 取前 N 轮作为 context，下一轮作为 response。
        只保留目标角色的回复作为 target。
        """
        pairs: List[TrainingPair] = []

        if len(turns) < 2:
            return pairs

        # 确定目标发送者（出现次数最多的）
        sender_counts: Dict[str, int] = {}
        for t in turns:
            sender_counts[t.sender] = sender_counts.get(t.sender, 0) + 1
        target_sender = max(sender_counts, key=sender_counts.get)

        for i in range(self.window_size, len(turns)):
            target_turn = turns[i]

            # 只保留目标角色的回复
            if target_turn.sender != target_sender:
                continue

            # 过滤噪音
            if self._is_noise(target_turn.content):
                continue

            # 取前 N 轮作为 context
            context_turns = turns[max(0, i - self.window_size):i]

            # 构建 context
            context_lines = []
            for ct in context_turns:
                if self._is_noise(ct.content):
                    continue
                context_lines.append(f"{ct.sender}: {ct.content}")

            if not context_lines:
                continue

            context = "\n".join(context_lines)

            # 检测类别
            category = self._detect_dialogue_category(target_turn.content, context)

            pairs.append(TrainingPair(
                instruction=f"你正在扮演{name}。以下是对话记录，请以{name}的风格回复最后一条消息。",
                input=context,
                output=target_turn.content.strip(),
                stage="style",
                category=category,
            ))

            if len(pairs) >= self.max_stage_a_pairs:
                break

        return pairs

    # ------------------------------------------------------------------
    # Stage B: 指令对
    # ------------------------------------------------------------------

    def _build_stage_b(self, profile: Any, name: str) -> List[TrainingPair]:
        """
        从角色卡生成问答对。

        用角色特征回答问题，让模型学习角色认知。
        """
        pairs: List[TrainingPair] = []

        # 构建角色上下文
        persona_context = self._build_persona_context(profile, name)

        # 各类问题
        question_groups = {
            "identity": IDENTITY_QUESTIONS,
            "style": STYLE_QUESTIONS,
            "emotion": EMOTION_QUESTIONS,
            "value": VALUE_QUESTIONS,
            "hobby": HOBBY_QUESTIONS,
            "relationship": RELATIONSHIP_QUESTIONS,
        }

        for category, questions in question_groups.items():
            selected = self.rng.sample(questions, min(len(questions), self.max_stage_b_per_category))
            for q in selected:
                pairs.append(TrainingPair(
                    instruction=f"你正在扮演{name}。请以{name}的身份和风格回答以下问题。",
                    input=q,
                    output=self._generate_reference_answer(q, profile, name, category),
                    stage="instruction",
                    category=category,
                ))

        return pairs

    # ------------------------------------------------------------------
    # Stage C: 场景对
    # ------------------------------------------------------------------

    def _build_stage_c(self, profile: Any, name: str) -> List[TrainingPair]:
        """
        不同场景下的反应模式。

        使用预定义场景模板 + 角色特征生成参考回复。
        """
        pairs: List[TrainingPair] = []

        # 按类别分组
        categories: Dict[str, list] = {}
        for s in SCENARIO_TEMPLATES:
            categories.setdefault(s["category"], []).append(s)

        persona_context = self._build_persona_context(profile, name)

        for category, scenarios in categories.items():
            selected = self.rng.sample(scenarios, min(len(scenarios), self.max_stage_c_per_category))
            for s in selected:
                pairs.append(TrainingPair(
                    instruction=f"你正在扮演{name}。以下是对话场景，请以{name}的风格回复。",
                    input=f"[场景：{s['context']}]\n对方说：{s['prompt']}",
                    output=self._generate_scenario_answer(s, profile, name),
                    stage="scenario",
                    category=category,
                ))

        return pairs

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    def _build_persona_context(self, profile: Any, name: str) -> str:
        """从 PersonaProfile 构建角色描述文本。"""
        parts = [f"角色名：{name}"]

        summary = getattr(profile, "summary", "") or ""
        if summary:
            parts.append(f"性格：{summary}")

        speaking = getattr(profile, "speaking_style", None)
        if speaking:
            style_summary = getattr(speaking, "summary", "") or ""
            if style_summary:
                parts.append(f"说话风格：{style_summary}")
            fillers = getattr(speaking, "filler_words", []) or []
            if fillers:
                parts.append(f"常用语气词：{'、'.join(fillers[:5])}")

        emotions = getattr(profile, "emotional_patterns", None)
        if emotions:
            dominant = getattr(emotions, "dominant_emotions", []) or []
            if dominant:
                parts.append(f"主要情绪：{'、'.join(dominant)}")

        values = getattr(profile, "values", None)
        if values:
            life_view = getattr(values, "life_view", "") or ""
            if life_view:
                parts.append(f"人生观：{life_view}")
            humor = getattr(values, "humor_style", "") or ""
            if humor:
                parts.append(f"幽默风格：{humor}")

        taboos = getattr(profile, "taboos", []) or []
        if taboos:
            parts.append(f"禁忌：{'、'.join(taboos[:3])}")

        quirks = getattr(profile, "special_quirks", []) or []
        if quirks:
            parts.append(f"口癖/习惯：{'、'.join(quirks[:3])}")

        big_five = getattr(profile, "big_five", {}) or {}
        if big_five:
            high = [k for k, v in big_five.items() if v and v > 0.6]
            if high:
                parts.append(f"突出特质：{'、'.join(high)}")

        return "\n".join(parts)

    def _generate_reference_answer(self, question: str, profile: Any, name: str, category: str) -> str:
        """
        基于角色特征生成参考回复。

        注意：这是一个基于规则的生成器，不依赖 LLM。
        实际使用时建议用 LLM 基于角色卡生成更自然的回复。
        这里提供基础版本作为 fallback。
        """
        # 从 profile 提取相关信息
        summary = getattr(profile, "summary", "") or ""
        speaking = getattr(profile, "speaking_style", None)
        style_summary = getattr(speaking, "summary", "") if speaking else ""
        fillers = getattr(speaking, "filler_words", []) if speaking else []
        emotions = getattr(profile, "emotional_patterns", None)
        dominant = getattr(emotions, "dominant_emotions", []) if emotions else []
        values = getattr(profile, "values", None)
        life_view = getattr(values, "life_view", "") if values else ""
        quirks = getattr(profile, "special_quirks", []) or []

        # 构建回复
        parts = []

        if category == "identity":
            if summary:
                parts.append(f"我觉得我{summary}")
            else:
                parts.append("我就是一个普通人吧")
            if quirks:
                parts.append(f"朋友都说我{quirks[0]}")

        elif category == "style":
            if style_summary:
                parts.append(f"我说话{style_summary}")
            else:
                parts.append("我说话比较随意")
            if fillers:
                parts.append(f"经常用{'、'.join(fillers[:3])}这些")

        elif category == "emotion":
            if dominant:
                parts.append(f"我平时{dominant[0]}比较多")
            else:
                parts.append("看情况吧，什么情绪都有")

        elif category == "value":
            if life_view:
                parts.append(life_view)
            else:
                parts.append("我觉得开心最重要")

        elif category == "hobby":
            parts.append("这个说来话长，我比较杂")

        elif category == "relationship":
            parts.append("还行吧，我跟周围人处得都还可以")

        else:
            parts.append("嗯...这个问题挺有意思的")

        # 加入语气词
        if fillers and self.rng.random() < 0.5:
            filler = self.rng.choice(fillers[:3])
            parts[0] = f"{filler}，{parts[0]}"

        return "".join(parts)

    def _generate_scenario_answer(self, scenario: Dict[str, str], profile: Any, name: str) -> str:
        """基于场景和角色特征生成参考回复。"""
        category = scenario["category"]
        prompt = scenario["prompt"]

        speaking = getattr(profile, "speaking_style", None)
        fillers = getattr(speaking, "filler_words", []) if speaking else []
        emotions = getattr(profile, "emotional_patterns", None)
        dominant = getattr(emotions, "dominant_emotions", []) if emotions else []
        values = getattr(profile, "values", None)
        taboos = getattr(profile, "taboos", []) or []

        # 基于场景类别的规则生成
        if category == "casual":
            responses = [
                "是啊是啊，今天天气确实不错",
                "嗯嗯，你呢？",
                "哈哈，还行吧，就那样",
            ]
        elif category == "emotional":
            responses = [
                "怎么了？跟我说说",
                "别难过了，会好起来的",
                "唉，抱抱你",
            ]
        elif category == "advice":
            responses = [
                "这个嘛，我觉得你得看自己的情况",
                "嗯...我建议你再想想",
                "看你自己怎么想的吧",
            ]
        elif category == "opinion":
            responses = [
                "我觉得吧，这个得看角度",
                "嗯，每个人想法不一样",
                "我是这样想的...",
            ]
        elif category == "boundary":
            responses = [
                "emmm这个我不太方便说",
                "你想多了吧",
                "这个...不太好吧",
            ]
        elif category == "intimate":
            responses = [
                "嗯嗯，我也想你了",
                "当然有想你啦",
                "好呀，陪你聊天",
            ]
        else:
            responses = ["嗯", "好的", "我知道了"]

        resp = self.rng.choice(responses)

        # 加入语气词
        if fillers and self.rng.random() < 0.4:
            filler = self.rng.choice(fillers[:3])
            resp = f"{filler}，{resp}"

        return resp

    def _is_noise(self, text: str) -> bool:
        """判断消息是否为噪音。"""
        text = text.strip()
        if not text:
            return True
        # 纯表情/图片/链接
        if re.match(r'^[\[\(（【].*[\]\)）】]$', text):
            return True
        # 极短消息（1-2 个字符，非中文）
        if len(text) <= 2 and not re.search(r'[一-鿿]', text):
            return True
        # 系统消息
        noise_patterns = [
            r'撤回了一条消息',
            r'加入了群聊',
            r'退出了群聊',
            r'\[图片\]',
            r'\[视频\]',
            r'\[语音\]',
            r'\[文件\]',
            r'\[红包\]',
            r'\[转账\]',
        ]
        for p in noise_patterns:
            if re.search(p, text):
                return True
        return False

    def _detect_dialogue_category(self, response: str, context: str) -> str:
        """检测对话类别。"""
        # 简单规则分类
        if re.search(r'[？?]', context):
            return "qa"
        if re.search(r'(难过|伤心|生气|烦|累|焦虑|担心|害怕)', context):
            return "emotional"
        if re.search(r'(哈哈|嘿嘿|笑|搞笑|有趣)', context):
            return "humor"
        if re.search(r'(喜欢|爱|想|思念)', response):
            return "affection"
        return "casual"

    def _safe_filename(self, name: str) -> str:
        s = (name or "persona").strip()
        safe = "".join(ch for ch in s if ch.isalnum() or ch in " -_.")
        return safe.replace(" ", "_")[:50] or "persona"

    # ------------------------------------------------------------------
    # 写入方法
    # ------------------------------------------------------------------

    def _write_alpaca(self, pairs: List[TrainingPair], path: Path) -> None:
        """写入 Alpaca JSON 格式。"""
        data = [p.to_alpaca() for p in pairs]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("写入 Alpaca 格式：%s（%d 条）", path, len(data))

    def _write_sharegpt(self, pairs: List[TrainingPair], path: Path, profile: Any, name: str) -> None:
        """写入 ShareGPT JSON 格式。"""
        system_prompt = f"你是{name}。"
        summary = getattr(profile, "summary", "") or ""
        if summary:
            system_prompt += f"你的性格特点：{summary}"
        speaking = getattr(profile, "speaking_style", None)
        if speaking:
            style_summary = getattr(speaking, "summary", "") or ""
            if style_summary:
                system_prompt += f"你的说话风格：{style_summary}"

        data = [p.to_sharegpt(system=system_prompt) for p in pairs]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("写入 ShareGPT 格式：%s（%d 条）", path, len(data))

    # ------------------------------------------------------------------
    # LLM 增强（可选）
    # ------------------------------------------------------------------

    async def enhance_with_llm(
        self,
        pairs: List[TrainingPair],
        ai_provider: Any,
        name: str,
        *,
        profile: Optional[Any] = None,
        max_enhance: int = 50,
        timeout_seconds: int = 60,
    ) -> List[TrainingPair]:
        """
        用 LLM 增强 Stage B/C 的参考回复质量。

        当前的规则生成器产出的是基础回复，用 LLM 基于角色卡
        重新生成更自然的回复。
        """
        persona_context = self._build_persona_context(profile, name) if profile else ""

        enhanced = []
        count = 0
        for pair in pairs:
            if pair.stage == "style":
                # Stage A 保持原始对话不变
                enhanced.append(pair)
                continue

            if count >= max_enhance:
                enhanced.append(pair)
                continue

            try:
                prompt = f"""你正在扮演一个角色。请根据角色信息，以该角色的身份和风格回答问题。

角色信息：
{persona_context}

角色名：{name}

问题：{pair.input}

请以{name}的身份和风格回答。回答要自然、有个性，不要千篇一律。只输出回复内容，不要加任何前缀。"""

                response = await ai_provider.generate(
                    prompt=prompt,
                    system=f"你是{name}，请始终保持角色一致性。",
                    timeout_seconds=timeout_seconds,
                )

                if response and response.text and len(response.text.strip()) > 5:
                    enhanced.append(TrainingPair(
                        instruction=pair.instruction,
                        input=pair.input,
                        output=response.text.strip(),
                        stage=pair.stage,
                        category=pair.category,
                        metadata={"llm_enhanced": True},
                    ))
                    count += 1
                else:
                    enhanced.append(pair)
            except Exception as e:
                logger.warning("LLM 增强失败（%s）: %s", pair.category, e)
                enhanced.append(pair)

        logger.info("LLM 增强完成：%d/%d 条", count, max_enhance)
        return enhanced
