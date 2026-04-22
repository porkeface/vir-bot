"""
vir_bot.core.distillation.analyzer
=================================

Analyzer package initializer for the distillation subpackage.

This module provides:
- lazy loaders for analyzer components (extractor, big_five, style_analyzer, emotion_mapper, dialogue_sampler)
- simple registry and factory utilities to create analyzer instances by name
- helpful import-time error messages when modules are missing

Design goals:
- Delay importing heavy modules until actually needed.
- Provide a small, stable public API so the pipeline can obtain analyzer classes without caring about concrete module layout.
- Allow runtime registration of custom analyzer implementations.
"""

from __future__ import annotations

import importlib
from typing import Any, Dict, Optional, Type

__all__ = [
    "register_analyzer",
    "get_analyzer_class",
    "create_analyzer",
    "get_extractor_class",
    "create_extractor",
]

# Default registry maps logical analyzer names to either:
# - a class object (if already loaded)
# - or a lazy import path string in the form "package.module:ClassName"
_registry: Dict[str, Type | str] = {
    # Core extractor which performs multi-round LLM-based persona extraction
    "extractor": "vir_bot.core.distillation.analyzer.extractor:PersonaExtractor",
    # Optional components (placeholders). Implementations may be added later.
    "big_five": "vir_bot.core.distillation.analyzer.big_five:BigFiveAnalyzer",
    "style": "vir_bot.core.distillation.analyzer.style_analyzer:StyleAnalyzer",
    "emotion": "vir_bot.core.distillation.analyzer.emotion_mapper:EmotionMapper",
    "dialogue_sampler": "vir_bot.core.distillation.analyzer.dialogue_sampler:DialogueSampler",
}


def register_analyzer(name: str, cls_or_path: Type | str) -> None:
    """
    Register or override an analyzer implementation.

    Args:
        name: logical name for the analyzer (e.g. "extractor", "big_five")
        cls_or_path: either a class object or an import path string "module.sub:ClassName"
    """
    if not isinstance(name, str) or not name:
        raise ValueError("name must be a non-empty string")
    _registry[name] = cls_or_path


def _load_from_path(path: str) -> Type:
    """
    Load a class object from a path string "module:ClassName".

    Raises ImportError with a helpful message on failure.
    """
    if ":" not in path:
        raise ImportError(f"Invalid analyzer import path '{path}'. Expected 'module:ClassName'.")
    module_path, class_name = path.split(":", 1)
    try:
        module = importlib.import_module(module_path)
    except Exception as e:
        raise ImportError(f"Failed to import module '{module_path}': {e}") from e
    try:
        cls = getattr(module, class_name)
    except AttributeError as e:
        raise ImportError(f"Module '{module_path}' does not define '{class_name}': {e}") from e
    if not isinstance(cls, type):
        raise ImportError(f"Imported object '{class_name}' from '{module_path}' is not a class.")
    return cls


def get_analyzer_class(name: str) -> Type:
    """
    Return the analyzer class registered under `name`.

    Raises:
        KeyError: if name is not registered
        ImportError: if lazy import fails
    """
    try:
        entry = _registry[name]
    except KeyError as e:
        raise KeyError(
            f"No analyzer registered under name '{name}'. Available: {list(_registry.keys())}"
        ) from e

    if isinstance(entry, type):
        return entry
    if isinstance(entry, str):
        cls = _load_from_path(entry)
        # cache resolved class for future calls
        _registry[name] = cls
        return cls

    raise ImportError(f"Unsupported registry entry for '{name}': {_registry[name]!r}")


def create_analyzer(name: str, *args: Any, **kwargs: Any) -> Any:
    """
    Instantiate an analyzer by name.

    Example:
        extractor = create_analyzer("extractor", ai_provider=provider, config=config)
    """
    AnalyzerCls = get_analyzer_class(name)
    return AnalyzerCls(*args, **kwargs)


# Convenience helpers for commonly used analyzer components.
def get_extractor_class() -> Type:
    """
    Return the PersonaExtractor class (lazy-import).
    """
    return get_analyzer_class("extractor")


def create_extractor(*args: Any, **kwargs: Any) -> Any:
    """
    Create an instance of the PersonaExtractor.
    """
    return create_analyzer("extractor", *args, **kwargs)


# Allow introspection of available analyzers
def available_analyzers() -> list[str]:
    """Return the list of registered analyzer names."""
    return list(_registry.keys())
