# -*- coding: utf-8 -*-
"""
LLM-as-Judge 人格还原度评测器

替代原有的 Jaccard 词汇重叠度评测，用 LLM 评估角色回复是否符合人格描述。

评测流程：
1. 从角色卡提取关键特征
2. 构造测试场景
3. 让 LLM 以角色身份回复
4. 用 Judge LLM 评估还原度
5. 输出各维度得分
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from vir_bot.core.ai_provider import AIProvider, AIResponse
from vir_bot.core.distillation.prompt_templates import render_prompt

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass
class ScenarioScore:
    """单个测试场景的评分。"""
    scenario_id: int
    trigger: str
    category: str
    style_match: float = 0.0
    emotion_match: float = 0.0
    value_match: float = 0.0
    taboo_avoidance: float = 0.0
    overall: float = 0.0
    reasons: Dict[str, str] = field(default_factory=dict)
    role_response: str = ""


@dataclass
class EvaluationResult:
    """评测总结果。"""
    overall_score: float = 0.0
    style_score: float = 0.0
    emotion_score: float = 0.0
    value_score: float = 0.0
    taboo_score: float = 0.0
    scenario_scores: List[ScenarioScore] = field(default_factory=list)
    num_scenarios: int = 0
    raw_notes: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_score": round(self.overall_score, 3),
            "style_score": round(self.style_score, 3),
            "emotion_score": round(self.emotion_score, 3),
            "value_score": round(self.value_score, 3),
            "taboo_score": round(self.taboo_score, 3),
            "num_scenarios": self.num_scenarios,
            "pass": self.overall_score >= 0.7,
            "scenarios": [
                {
                    "id": s.scenario_id,
                    "trigger": s.trigger,
                    "category": s.category,
                    "overall": round(s.overall, 3),
                    "style": round(s.style_match, 3),
                    "emotion": round(s.emotion_match, 3),
                    "value": round(s.value_match, 3),
                    "taboo": round(s.taboo_avoidance, 3),
                }
                for s in self.scenario_scores
            ],
        }


# ---------------------------------------------------------------------------
# LLMJudgeEvaluator
# ---------------------------------------------------------------------------


class LLMJudgeEvaluator:
    """
    LLM-as-Judge 人格还原度评测器。

    流程：
    1. 从人格描述生成测试场景
    2. 对每个场景，让 LLM 以角色身份回复
    3. 用 Judge LLM 评估回复的人格还原度
    4. 汇总各维度得分
    """

    def __init__(
        self,
        ai_provider: AIProvider,
        *,
        num_scenarios: int = 8,
        timeout_seconds: int = 60,
    ) -> None:
        self.ai = ai_provider
        self.num_scenarios = num_scenarios
        self.timeout_seconds = timeout_seconds

    async def evaluate(
        self,
        persona_description: str,
        character_system_prompt: Optional[str] = None,
    ) -> EvaluationResult:
        """
        执行完整评测。

        Args:
            persona_description: 角色人格描述（Markdown 或纯文本）
            character_system_prompt: 角色的 system prompt（如果有的话）
        """
        logger.info("开始 LLM-as-Judge 评测（%d 个测试场景）", self.num_scenarios)

        # Step 1: 生成测试场景
        scenarios = await self._generate_scenarios(persona_description)
        logger.info("生成了 %d 个测试场景", len(scenarios))

        # Step 2: 对每个场景生成角色回复并评分
        scenario_scores: List[ScenarioScore] = []
        for i, scenario in enumerate(scenarios):
            logger.info("评测场景 %d/%d: %s", i + 1, len(scenarios), scenario.get("trigger", ""))
            score = await self._evaluate_scenario(
                scenario=scenario,
                persona_description=persona_description,
                system_prompt=character_system_prompt,
            )
            scenario_scores.append(score)

        # Step 3: 汇总
        result = self._aggregate_scores(scenario_scores)
        logger.info("评测完成：综合得分 %.2f（%s）", result.overall_score, "通过" if result.overall_score >= 0.7 else "未通过")

        return result

    # ------------------------------------------------------------------
    # 场景生成
    # ------------------------------------------------------------------

    async def _generate_scenarios(self, persona_description: str) -> List[Dict[str, Any]]:
        """用 LLM 生成测试场景。"""
        prompt = render_prompt(
            "scenario_generation",
            persona_description=persona_description,
            num_scenarios=self.num_scenarios,
        )
        response = await self._call_llm(prompt, system="你是一位专业的AI角色评测专家。")
        parsed = self._safe_parse_json(response)

        if parsed and "scenarios" in parsed:
            return parsed["scenarios"]

        # fallback: 返回基础场景
        return self._default_scenarios()

    def _default_scenarios(self) -> List[Dict[str, Any]]:
        """默认测试场景（当 LLM 生成失败时使用）。"""
        return [
            {"id": 1, "trigger": "用户说'今天好累啊'", "expected_traits": ["关心", "安慰"], "category": "日常关心"},
            {"id": 2, "trigger": "用户说'我喜欢你'", "expected_traits": ["害羞", "回应"], "category": "情感表达"},
            {"id": 3, "trigger": "用户说'我要去忙了'", "expected_traits": ["撒娇", "支持"], "category": "告别"},
            {"id": 4, "trigger": "用户忘记了约定的事情", "expected_traits": ["失望", "但不真生气"], "category": "禁忌触发"},
            {"id": 5, "trigger": "用户问'你在干嘛'", "expected_traits": ["活泼", "反问"], "category": "日常闲聊"},
            {"id": 6, "trigger": "用户说'今天被领导批评了'", "expected_traits": ["安慰", "鼓励"], "category": "情绪低落"},
            {"id": 7, "trigger": "用户开玩笑说她啰嗦", "expected_traits": ["傲娇", "反驳"], "category": "玩笑调侃"},
            {"id": 8, "trigger": "用户分享一个好消息", "expected_traits": ["开心", "祝贺"], "category": "分享喜悦"},
        ]

    # ------------------------------------------------------------------
    # 单场景评测
    # ------------------------------------------------------------------

    async def _evaluate_scenario(
        self,
        scenario: Dict[str, Any],
        persona_description: str,
        system_prompt: Optional[str] = None,
    ) -> ScenarioScore:
        """对单个场景执行：生成角色回复 → Judge 评分。"""

        trigger = scenario.get("trigger", "")
        category = scenario.get("category", "")
        scenario_id = scenario.get("id", 0)

        score = ScenarioScore(
            scenario_id=scenario_id,
            trigger=trigger,
            category=category,
        )

        # Step A: 让 LLM 以角色身份回复
        role_system = system_prompt or f"你现在要扮演以下角色，严格按照角色的性格和说话方式回复。\n\n{persona_description}"
        role_response = await self._call_llm(
            trigger,
            system=role_system,
            temperature=0.7,
        )
        score.role_response = role_response

        # Step B: 用 Judge 评估
        judge_prompt = render_prompt(
            "judge_evaluate",
            persona_description=persona_description,
            test_scenario=f"场景：{trigger}\n类别：{category}",
            role_response=role_response,
        )
        judge_response = await self._call_llm(
            judge_prompt,
            system=render_prompt("judge_system"),
            temperature=0.1,
        )
        judge_json = self._safe_parse_json(judge_response)

        if judge_json:
            score.style_match = self._extract_score(judge_json, "style_match")
            score.emotion_match = self._extract_score(judge_json, "emotion_match")
            score.value_match = self._extract_score(judge_json, "value_match")
            score.taboo_avoidance = self._extract_score(judge_json, "taboo_avoidance")
            score.overall = self._extract_score(judge_json, "overall")

            # 提取理由
            for dim in ("style_match", "emotion_match", "value_match", "taboo_avoidance", "overall"):
                if dim in judge_json and isinstance(judge_json[dim], dict):
                    score.reasons[dim] = judge_json[dim].get("reason", "")
        else:
            # Judge 输出解析失败，给默认分
            score.overall = 0.5
            score.reasons["overall"] = "Judge 输出解析失败"

        return score

    def _extract_score(self, data: Dict[str, Any], key: str) -> float:
        """从 judge 输出中提取分数。"""
        val = data.get(key)
        if isinstance(val, dict):
            return float(val.get("score", 0.5))
        if isinstance(val, (int, float)):
            return float(val)
        return 0.5

    # ------------------------------------------------------------------
    # 汇总
    # ------------------------------------------------------------------

    def _aggregate_scores(self, scores: List[ScenarioScore]) -> EvaluationResult:
        """汇总各场景得分。"""
        if not scores:
            return EvaluationResult()

        result = EvaluationResult(
            scenario_scores=scores,
            num_scenarios=len(scores),
        )

        # 计算各维度平均分
        n = len(scores)
        result.style_score = sum(s.style_match for s in scores) / n
        result.emotion_score = sum(s.emotion_match for s in scores) / n
        result.value_score = sum(s.value_match for s in scores) / n
        result.taboo_score = sum(s.taboo_avoidance for s in scores) / n
        result.overall_score = sum(s.overall for s in scores) / n

        return result

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    async def _call_llm(
        self,
        user_prompt: str,
        *,
        system: str = "",
        temperature: float = 0.2,
    ) -> str:
        """调用 LLM。"""
        messages = [{"role": "user", "content": user_prompt}]
        try:
            coro = self.ai.chat(
                messages=messages, system=system, stream=False, temperature=temperature
            )
            resp: AIResponse = await asyncio.wait_for(coro, timeout=self.timeout_seconds)
            return resp.content or ""
        except asyncio.TimeoutError:
            logger.error("LLM 调用超时")
            return ""
        except Exception:
            logger.exception("LLM 调用失败")
            return ""

    def _safe_parse_json(self, text: str) -> Optional[Dict[str, Any]]:
        """解析 JSON，带 fallback。"""
        if not text:
            return None
        text = text.strip()
        try:
            return json.loads(text)
        except Exception:
            pass
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except Exception:
                pass
        return None
