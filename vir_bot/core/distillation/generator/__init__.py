"""
vir_bot.core.distillation.generator
==================================

Generator package initializer for the distillation subpackage.

Responsibilities:
- Provide lazy-loading factory utilities for generator components:
  - `WikiGenerator`            -> generates markdown wiki character files
  - `CardGenerator`            -> generates SillyTavern / character JSON cards
  - `prompt_templates` module  -> contains prompt templates used by analyzers/generators

Design goals:
- Delay importing potentially heavy modules until actually needed.
- Provide helpful error messages when expected modules/classes are missing.
- Allow runtime registration/override of implementations via `register_generator`.
"""

from __future__ import annotations

import importlib
from typing import Any, Dict, Type

__all__ = [
    "register_generator",
    "get_generator_class",
    "create_generator",
    "get_wiki_generator_class",
    "create_wiki_generator",
    "get_card_generator_class",
    "create_card_generator",
    "get_prompt_templates_module",
]

# Default registry entries.
# Values may be either:
#  - a class object (already imported), or
#  - a lazy import path string in the form "module.path:ClassName"
_registry: Dict[str, Type | str] = {
    # Core generators (expect these modules to be implemented)
    "wiki": "vir_bot.core.distillation.generator.wiki_generator:WikiGenerator",
    "card": "vir_bot.core.distillation.generator.card_generator:CardGenerator",
    # prompt_templates is a module (not a class). We store the module path string
    # and expose a separate loader function for it.
    "prompt_templates_module": "vir_bot.core.distillation.generator.prompt_templates",
}


def register_generator(name: str, cls_or_path: Type | str) -> None:
    """
    Register or override a generator implementation.

    Args:
        name: logical name (e.g. "wiki", "card")
        cls_or_path: either a class object or an import path string "module:ClassName"
    """
    if not isinstance(name, str) or not name:
        raise ValueError("name must be a non-empty string")
    _registry[name] = cls_or_path


def _load_from_path(path: str) -> Type:
    """
    Load a class object from a path string "module:ClassName".
    Raises ImportError on failure with helpful diagnostics.
    """
    if ":" not in path:
        raise ImportError(f"Invalid import path '{path}'. Expected format 'module:ClassName'.")
    module_path, class_name = path.split(":", 1)
    try:
        module = importlib.import_module(module_path)
    except Exception as e:
        raise ImportError(f"Failed to import module '{module_path}' for generator: {e}") from e
    try:
        cls = getattr(module, class_name)
    except AttributeError as e:
        raise ImportError(
            f"Module '{module_path}' does not define class '{class_name}': {e}"
        ) from e
    if not isinstance(cls, type):
        raise ImportError(f"Imported object from '{path}' is not a class.")
    return cls


def get_generator_class(name: str) -> Type:
    """
    Return the generator class registered under `name` (lazy-load when needed).

    Raises:
        KeyError: if name is not registered
        ImportError: if lazy import fails
    """
    try:
        entry = _registry[name]
    except KeyError as e:
        raise KeyError(
            f"No generator registered under name '{name}'. Available: {list(_registry.keys())}"
        ) from e

    if isinstance(entry, type):
        return entry

    if isinstance(entry, str):
        # If the entry looks like a module-only path (no ':') it's not a class path.
        if ":" not in entry:
            raise ImportError(
                f"Registered entry for '{name}' is a module path, not a class path: '{entry}'"
            )
        cls = _load_from_path(entry)
        # cache resolved class
        _registry[name] = cls
        return cls

    raise ImportError(f"Unsupported registry entry for '{name}': {_registry[name]!r}")


def create_generator(name: str, *args: Any, **kwargs: Any) -> Any:
    """
    Instantiate a generator by name.

    Example:
        g = create_generator("wiki", output_dir="./data/wiki/characters")
    """
    GeneratorCls = get_generator_class(name)
    return GeneratorCls(*args, **kwargs)


# Convenience helpers for common generator types
def get_wiki_generator_class() -> Type:
    """
    Return the WikiGenerator class (lazy-import).
    """
    return get_generator_class("wiki")


def create_wiki_generator(*args: Any, **kwargs: Any) -> Any:
    """
    Create an instance of the WikiGenerator.
    """
    return create_generator("wiki", *args, **kwargs)


def get_card_generator_class() -> Type:
    """
    Return the CardGenerator class (lazy-import).
    """
    return get_generator_class("card")


def create_card_generator(*args: Any, **kwargs: Any) -> Any:
    """
    Create an instance of the CardGenerator.
    """
    return create_generator("card", *args, **kwargs)


# prompt_templates is a module rather than a class; provide a loader for it.
def get_prompt_templates_module():
    """
    Lazily import and return the `prompt_templates` module for generators.

    Raises:
        ImportError: if the module cannot be imported or is not registered.
    """
    try:
        entry = _registry["prompt_templates_module"]
    except KeyError as e:
        raise KeyError("prompt_templates_module not registered in generator registry") from e

    if isinstance(entry, str):
        # import as module path (no ":ClassName" expected)
        try:
            mod = importlib.import_module(entry)
            # cache the module object for subsequent calls
            _registry["prompt_templates_module"] = mod
            return mod
        except Exception as exc:
            raise ImportError(f"Failed to import prompt_templates module '{entry}': {exc}") from exc

    # If already resolved to a module object, return it
    if not isinstance(entry, str):
        return entry

    raise ImportError("Unable to load prompt_templates module.")


# Small introspection helper
def available_generators() -> list[str]:
    """
    Return a list of registered generator names.
    """
    return list(_registry.keys())
