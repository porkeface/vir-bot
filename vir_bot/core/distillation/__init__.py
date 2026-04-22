"""
vir_bot.core.distillation
=========================

Distillation 子包的初始化文件。

该包负责将原始聊天记录（多平台）通过 LLM 分析、结构化抽取、生成角色卡并进行评估的
完整蒸馏流程。此模块提供若干便捷的懒加载辅助函数，方便从外部按需创建蒸馏流水线实例或获取
核心类（当子模块已被实现时）。

设计原则：
- 延迟导入子模块（避免在包导入时抛出 ImportError，便于单元测试和增量开发）
- 提供友好的错误信息，便于定位缺失/未实现的子模块
- 暴露工厂函数：`create_pipeline`，以便快速构建 `DistillationPipeline` 实例

注意：具体类实现位于子模块中（比如 `pipeline.py`, `analyzer/extractor.py`,
`parser/base.py`, `generator/wiki_generator.py`）。若这些文件尚未创建或存在错误，
惰性导入会抛出 ImportError 并提示如何修复。
"""

from __future__ import annotations

__all__ = [
    "get_pipeline_class",
    "get_persona_extractor_class",
    "get_chat_parser_base",
    "get_wiki_generator_class",
    "create_pipeline",
    "create_persona_extractor",
    "create_wiki_generator",
]

__version__ = "0.1.0"

from typing import Any, Type


def _raise_missing(name: str, hint: str | None = None) -> None:
    msg = f"Distillation submodule '{name}' is not available. Make sure the corresponding file exists and is importable."
    if hint:
        msg += " " + hint
    raise ImportError(msg)


def get_pipeline_class() -> Type:
    """
    返回 `DistillationPipeline` 类（惰性导入）。

    Raises:
        ImportError: 如果子模块不可用或导入失败，会返回可读的错误信息。
    """
    try:
        from .pipeline import DistillationPipeline

        return DistillationPipeline
    except Exception as e:  # noqa: BLE001 - we want to wrap any import error
        _raise_missing(
            "pipeline",
            "Expected file: vir_bot/core/distillation/pipeline.py with class 'DistillationPipeline'.",
        )


def get_persona_extractor_class() -> Type:
    """
    返回 `PersonaExtractor` 类（惰性导入）。
    """
    try:
        from .analyzer.extractor import PersonaExtractor

        return PersonaExtractor
    except Exception:
        _raise_missing(
            "analyzer.extractor",
            "Expected file: vir_bot/core/distillation/analyzer/extractor.py with class 'PersonaExtractor'.",
        )


def get_chat_parser_base() -> Type:
    """
    返回 `ChatParser` 抽象基类（惰性导入）。
    """
    try:
        from .parser.base import ChatParser

        return ChatParser
    except Exception:
        _raise_missing(
            "parser.base",
            "Expected file: vir_bot/core/distillation/parser/base.py with class 'ChatParser'.",
        )


def get_wiki_generator_class() -> Type:
    """
    返回 `WikiGenerator` 类（惰性导入）。
    """
    try:
        from .generator.wiki_generator import WikiGenerator

        return WikiGenerator
    except Exception:
        _raise_missing(
            "generator.wiki_generator",
            "Expected file: vir_bot/core/distillation/generator/wiki_generator.py with class 'WikiGenerator'.",
        )


def create_pipeline(*args: Any, **kwargs: Any) -> Any:
    """
    创建并返回一个 `DistillationPipeline` 实例（工厂函数）。

    使用示例：
        pipeline = create_pipeline(ai_provider, config)

    这里没有对传入参数做任何检查，直接传递给构造函数，由具体实现负责验证。
    """
    PipelineCls = get_pipeline_class()
    return PipelineCls(*args, **kwargs)


def create_persona_extractor(*args: Any, **kwargs: Any) -> Any:
    """
    创建并返回一个 `PersonaExtractor` 实例（工厂函数）。
    """
    ExtractorCls = get_persona_extractor_class()
    return ExtractorCls(*args, **kwargs)


def create_wiki_generator(*args: Any, **kwargs: Any) -> Any:
    """
    创建并返回一个 `WikiGenerator` 实例（工厂函数）。
    """
    GeneratorCls = get_wiki_generator_class()
    return GeneratorCls(*args, **kwargs)
