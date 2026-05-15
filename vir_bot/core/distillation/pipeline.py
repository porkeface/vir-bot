# -*- coding: utf-8 -*-
"""
蒸馏流水线编排器（v2）

改进：
1. 支持分块提取（由 extractor 内部处理）
2. 支持增量蒸馏
3. 用 LLM-as-Judge 替换 Jaccard 评测
4. 支持 SillyTavern V2 JSON 输出
5. 集成统计分析（StyleAnalyzer）+ 话题聚类（TopicClusterer）+ 融合（FusionEngine）
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from vir_bot.core.ai_provider import AIProvider
from vir_bot.core.distillation.analyzer import create_extractor
from vir_bot.core.distillation.analyzer.style_analyzer import StyleAnalyzer
from vir_bot.core.distillation.analyzer.topic_clusterer import TopicClusterer
from vir_bot.core.distillation.analyzer.fusion import FusionEngine
from vir_bot.core.distillation.evaluator import LLMJudgeEvaluator
from vir_bot.core.distillation.generator import create_wiki_generator
from vir_bot.core.distillation.parser import create_parser

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 结果模型
# ---------------------------------------------------------------------------
@dataclass
class DistillationResult:
    name: str
    profile: Dict[str, Any]
    markdown: Optional[str] = None
    markdown_path: Optional[str] = None
    json_path: Optional[str] = None
    metrics: Dict[str, Any] = None
    raw_notes: Dict[str, Any] = None
    evaluation: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "profile": self.profile,
            "markdown_path": self.markdown_path,
            "json_path": self.json_path,
            "metrics": self.metrics or {},
            "evaluation": self.evaluation,
            "raw_notes": self.raw_notes or {},
        }


# ---------------------------------------------------------------------------
# DistillationPipeline
# ---------------------------------------------------------------------------
class DistillationPipeline:
    """
    蒸馏流水线编排器。

    支持的模式：
    - 标准蒸馏：聊天文件 → 角色卡
    - 增量蒸馏：已有角色卡 + 新聊天 → 更新角色卡
    - 评测模式：对生成的角色卡做人格还原度评测
    """

    def __init__(
        self,
        ai_provider: AIProvider,
        *,
        config: Optional[Any] = None,
        parser_name: Optional[str] = None,
        wiki_output_dir: str = "./data/wiki/characters",
        json_output_dir: str = "./data/characters",
        chunk_size: int = 400,
        enable_judge_eval: bool = True,
    ) -> None:
        self.ai = ai_provider
        self.config = config
        self.parser_name = parser_name or "generic"
        self.wiki_output_dir = wiki_output_dir
        self.json_output_dir = json_output_dir
        self.chunk_size = chunk_size
        self.enable_judge_eval = enable_judge_eval

    async def run(
        self,
        input_path: str,
        name: str,
        *,
        evaluate: bool = False,
        dry_run: bool = False,
        incremental: bool = False,
        existing: Optional[str] = None,
        timeout_seconds: int = 120,
    ) -> DistillationResult:
        """
        执行蒸馏流水线。

        Args:
            input_path: 聊天记录文件路径
            name: 角色名称
            evaluate: 是否执行评测
            dry_run: 是否只预览不写文件
            incremental: 是否增量模式
            existing: 增量模式下的已有角色卡路径
            timeout_seconds: 单次 LLM 调用超时
        """
        logger.info("开始蒸馏：%s（模式：%s）", name, "增量" if incremental else "标准")

        # 验证输入
        p = Path(input_path)
        if not p.exists():
            raise FileNotFoundError(f"输入文件不存在: {input_path}")

        # Step 1: 解析
        parser_name = self._choose_parser_name(p)
        parser = create_parser(parser_name)
        turns = await self._maybe_blocking_call(parser.parse, input_path)
        logger.info("解析了 %d 轮对话", len(turns))

        # Step 2: 创建提取器
        extractor = create_extractor(
            self.ai,
            prompts=getattr(self.config, "prompts", None),
            timeout_seconds=timeout_seconds,
            chunk_size=self.chunk_size,
        )

        # Step 3: 提取
        if incremental and existing:
            # 增量模式
            existing_content = self._read_existing_persona(existing)
            profile_obj = await extractor.extract_incremental(
                existing_persona=existing_content,
                new_turns=turns,
                name=name,
            )
        else:
            # 标准模式
            profile_obj = await extractor.extract(turns, name=name)

        # Step 3.5: 统计分析 + 话题聚类 + 融合
        profile_obj = await self._enrich_with_stats(profile_obj, turns, name)

        # 转为 dict
        profile = self._profile_to_dict(profile_obj)

        # Step 4: 生成 Markdown
        wiki_gen = create_wiki_generator(author=None, include_raw_notes=True)
        md = wiki_gen.generate(profile_obj, name=name)

        md_path = None
        json_path = None
        if not dry_run:
            # 写 Markdown
            os.makedirs(self.wiki_output_dir, exist_ok=True)
            md_path_obj = Path(self.wiki_output_dir) / f"{self._safe_filename(name)}.md"
            md_path_obj.write_text(md, encoding="utf-8")
            md_path = str(md_path_obj)
            logger.info("写入 Markdown: %s", md_path)

            # 写 SillyTavern JSON
            json_path = self._write_character_json(name, profile_obj, dry_run)

        # Step 5: 评测（可选）
        evaluation = None
        if evaluate and self.enable_judge_eval:
            try:
                eval_result = await self._run_judge_evaluation(md, name)
                evaluation = eval_result
            except Exception as e:
                logger.exception("评测失败: %s", e)
                evaluation = {"error": str(e)}
        elif evaluate:
            # 回退到简单的 overlap 评测
            evaluation = self._simple_overlap_eval(profile_obj, turns)

        result = DistillationResult(
            name=name,
            profile=profile,
            markdown=md,
            markdown_path=md_path,
            json_path=json_path,
            metrics=evaluation.get("metrics", {}) if isinstance(evaluation, dict) else {},
            evaluation=evaluation,
            raw_notes=profile.get("raw_notes", {}) if isinstance(profile, dict) else {},
        )

        logger.info("蒸馏完成：%s", name)
        return result

    # ------------------------------------------------------------------
    # 评测
    # ------------------------------------------------------------------

    async def _run_judge_evaluation(
        self,
        persona_markdown: str,
        name: str,
    ) -> Dict[str, Any]:
        """用 LLM-as-Judge 评测人格还原度。"""
        logger.info("执行 LLM-as-Judge 评测")
        evaluator = LLMJudgeEvaluator(
            self.ai,
            num_scenarios=8,
            timeout_seconds=60,
        )
        result = await evaluator.evaluate(persona_description=persona_markdown)
        eval_dict = result.to_dict()
        eval_dict["method"] = "llm_judge"
        return eval_dict

    def _simple_overlap_eval(self, profile_obj: Any, turns: List[Any]) -> Dict[str, Any]:
        """简单的重叠度评测（保留作为 fallback）。"""
        source_texts = [getattr(t, "content", "") or str(t) for t in turns]
        source_text = "\n".join(source_texts)

        distilled_parts = []
        summary = getattr(profile_obj, "summary", None) or ""
        if summary:
            distilled_parts.append(summary)

        examples = getattr(profile_obj, "dialogue_examples", []) or []
        for ex in examples:
            distilled_parts.append(getattr(ex, "original", "") or "")

        distilled_text = "\n".join(distilled_parts)

        import re
        src_tokens = set(t.lower() for t in re.split(r"[^0-9A-Za-z一-鿿]+", source_text) if t)
        dst_tokens = set(t.lower() for t in re.split(r"[^0-9A-Za-z一-鿿]+", distilled_text) if t)

        if not src_tokens or not dst_tokens:
            return {"method": "overlap", "metrics": {"overlap_similarity": 0.0}}

        inter = src_tokens.intersection(dst_tokens)
        union = src_tokens.union(dst_tokens)
        jaccard = len(inter) / len(union) if union else 0.0

        return {
            "method": "overlap",
            "metrics": {"overlap_similarity": round(jaccard, 3)},
        }

    # ------------------------------------------------------------------
    # 统计分析 + 融合
    # ------------------------------------------------------------------

    async def _enrich_with_stats(
        self,
        profile_obj: Any,
        turns: List[Any],
        name: str,
    ) -> Any:
        """用统计分析结果丰富人格描述。"""
        try:
            # 1. StyleAnalyzer：统计说话风格
            logger.info("执行统计分析...")
            style_analyzer = StyleAnalyzer()
            style_stats = style_analyzer.analyze(turns)
            style_dict = style_analyzer.to_dict(style_stats)
            logger.info("统计分析完成：句数=%d, 平均句长=%.1f, 语气词率=%.2f",
                        style_stats.sentence_count,
                        style_stats.sentence_length_mean,
                        style_stats.filler_word_rate)

            # 2. FusionEngine：融合统计与 LLM 结果
            logger.info("执行融合...")
            fusion = FusionEngine()
            fusion_result = fusion.fuse(profile_obj, style_stats)
            logger.info("融合完成：注入 %d 项，发现 %d 个矛盾",
                        len(fusion_result.stats_injected),
                        len(fusion_result.contradictions))

            # 将统计和融合结果存入 raw_notes
            if not hasattr(profile_obj, 'raw_notes') or profile_obj.raw_notes is None:
                profile_obj.raw_notes = {}
            profile_obj.raw_notes["style_stats"] = style_dict
            profile_obj.raw_notes["fusion"] = fusion.to_dict(fusion_result)

            # 3. TopicClusterer：话题聚类（可选，可能比较慢）
            try:
                logger.info("执行话题聚类...")
                topic_clusterer = TopicClusterer(n_clusters=6)
                topic_analysis = topic_clusterer.analyze(turns)
                topic_dict = topic_clusterer.to_dict(topic_analysis)
                profile_obj.raw_notes["topic_analysis"] = topic_dict
                logger.info("话题聚类完成：%d 个话题", len(topic_analysis.clusters))
            except Exception as e:
                logger.warning("话题聚类失败（非致命）: %s", e)

            return profile_obj

        except Exception as e:
            logger.warning("统计分析失败（非致命，保留 LLM 结果）: %s", e)
            return profile_obj

    # ------------------------------------------------------------------
    # SillyTavern JSON 输出
    # ------------------------------------------------------------------

    def _write_character_json(
        self,
        name: str,
        profile_obj: Any,
        dry_run: bool = False,
    ) -> Optional[str]:
        """生成 SillyTavern V2 格式的 JSON 角色卡。"""
        card = self._build_st_v2_card(name, profile_obj)

        if dry_run:
            return None

        os.makedirs(self.json_output_dir, exist_ok=True)
        json_path = Path(self.json_output_dir) / f"{self._safe_filename(name)}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(card, f, ensure_ascii=False, indent=2)
        logger.info("写入 SillyTavern JSON: %s", json_path)
        return str(json_path)

    def _build_st_v2_card(self, name: str, profile_obj: Any) -> Dict[str, Any]:
        """从 PersonaProfile 构建 SillyTavern V2 角色卡。"""
        summary = getattr(profile_obj, "summary", "") or ""
        big_five = getattr(profile_obj, "big_five", {}) or {}
        speaking_style = getattr(profile_obj, "speaking_style", None)
        emotional_patterns = getattr(profile_obj, "emotional_patterns", None)
        values = getattr(profile_obj, "values", None)
        taboos = getattr(profile_obj, "taboos", []) or []
        quirks = getattr(profile_obj, "special_quirks", []) or []
        examples = getattr(profile_obj, "dialogue_examples", []) or []

        # Description: 角色核心描述
        desc_parts = [f"{name}是一个有鲜明个性的人。"]
        if summary:
            desc_parts.append(f"性格特点：{summary}")

        if speaking_style and getattr(speaking_style, "summary", None):
            desc_parts.append(f"说话风格：{speaking_style.summary}")

        if emotional_patterns:
            dom = getattr(emotional_patterns, "dominant_emotions", []) or []
            if dom:
                desc_parts.append(f"主要情绪：{'、'.join(dom)}")

        if taboos:
            desc_parts.append(f"禁忌：{'、'.join(taboos[:5])}")

        if quirks:
            desc_parts.append(f"口癖/习惯：{'、'.join(quirks[:5])}")

        # Personality: 简短性格标签
        personality_parts = []
        if big_five:
            high_traits = [k for k, v in big_five.items() if v and v > 0.6]
            personality_parts.extend(high_traits)
        if quirks:
            personality_parts.extend(quirks[:3])

        # Example dialogue: 对话示例
        example_lines = []
        for ex in examples[:5]:
            ctx = getattr(ex, "context", "") or ""
            orig = getattr(ex, "original", "") or ""
            if orig:
                example_lines.append(f"<START>\n{{{{char}}}}: {orig}")

        # Extensions
        extensions = {}
        if speaking_style:
            extensions["voice_style"] = getattr(speaking_style, "summary", "")
        if emotional_patterns:
            triggers = getattr(emotional_patterns, "triggers", []) or []
            recovery = getattr(emotional_patterns, "recovery_behaviors", []) or []
            extensions["emotional_patterns"] = {
                "dominant": getattr(emotional_patterns, "dominant_emotions", []),
                "triggers": triggers,
                "recovery": recovery,
            }
        if values:
            extensions["values"] = {
                "frequent_topics": getattr(values, "frequent_topics", []),
                "attitudes": getattr(values, "attitudes", {}),
            }

        return {
            "spec": "chara_card_v2",
            "spec_version": "2.0",
            "data": {
                "name": name,
                "description": "\n".join(desc_parts),
                "personality": "、".join(personality_parts) if personality_parts else summary,
                "scenario": f"你正在和{name}对话。",
                "first_mes": f"你好！我是{name}。",
                "mes_example": "\n".join(example_lines) if example_lines else "",
                "system_prompt": "",
                "post_history_instructions": "",
                "alternate_greetings": [],
                "tags": ["distilled", "auto-generated"],
                "creator": "vir-bot distillation pipeline",
                "character_version": "1.0",
                "creator_notes": f"由 vir-bot 蒸馏系统自动生成。基于聊天记录提取的人格特征。",
                "extensions": extensions,
            },
        }

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    def _read_existing_persona(self, path: str) -> str:
        """读取已有的角色卡文件。"""
        p = Path(path)
        if not p.exists():
            logger.warning("已有角色卡不存在: %s", path)
            return ""
        return p.read_text(encoding="utf-8")

    def _choose_parser_name(self, path_obj: Path) -> str:
        if self.parser_name and self.parser_name != "auto":
            return self.parser_name
        return "generic"

    async def _maybe_blocking_call(self, func, *args, **kwargs):
        if asyncio.iscoroutinefunction(func):
            return await func(*args, **kwargs)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))

    def _safe_filename(self, name: str) -> str:
        s = (name or "persona").strip()
        safe = "".join(ch for ch in s if ch.isalnum() or ch in " -_.")
        safe = safe.replace(" ", "_")
        return safe[:200] or "persona"

    def _profile_to_dict(self, profile_obj: Any) -> Dict[str, Any]:
        """将 profile 对象转为字典。"""
        try:
            from dataclasses import is_dataclass, asdict
            if is_dataclass(profile_obj):
                return asdict(profile_obj)
        except Exception:
            pass
        if isinstance(profile_obj, dict):
            return profile_obj
        return json.loads(
            json.dumps(profile_obj, default=lambda o: getattr(o, "__dict__", str(o)), ensure_ascii=False)
        )
