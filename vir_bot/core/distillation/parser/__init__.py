"""
distillation.parser package initializer.

提供解析器注册与工厂函数，便于按平台（wechat/qq/discord/generic）选择或扩展
聊天记录解析器实现。对外暴露的接口包括：

- register_parser(name, cls_or_path)
- get_parser_class(name)
- create_parser(name, *args, **kwargs)
- get_base_parser_class()

设计要点：
- 懒加载外部实现：允许传入字符串形式的导入路径（'package.module:Class'）
  或直接传入类对象。
- 提供可读的错误提示，方便定位缺失模块。
"""

from __future__ import annotations

import importlib
from typing import Any, Dict, Type

__all__ = [
    "register_parser",
    "get_parser_class",
    "create_parser",
    "get_base_parser_class",
]

# 默认注册表，值可以是类对象或导入路径字符串 "package.module:ClassName"
_registry: Dict[str, Type | str] = {
    # 常见解析器占位（实现文件建议放在同目录下）
    "generic": "vir_bot.core.distillation.parser.generic:GenericParser",
    "wechat": "vir_bot.core.distillation.parser.wechat:WeChatParser",
    "qq": "vir_bot.core.distillation.parser.qq:QQParser",
    "discord": "vir_bot.core.distillation.parser.discord:DiscordParser",
}


def register_parser(name: str, cls_or_path: Type | str) -> None:
    """
    注册一个解析器实现。

    Args:
        name: 解析器名称（如 'wechat'、'generic'）
        cls_or_path: 解析器类对象，或导入路径字符串 'package.module:ClassName'
    """
    if not isinstance(name, str) or not name:
        raise ValueError("name must be a non-empty string")
    _registry[name] = cls_or_path


def _load_from_path(path: str) -> Type:
    """
    支持的 path 格式： 'package.module:ClassName'
    返回目标类对象或抛出 ImportError。
    """
    if ":" not in path:
        raise ImportError(f"Invalid import path '{path}'. Expected format 'module:ClassName'.")
    module_path, class_name = path.split(":", 1)
    try:
        module = importlib.import_module(module_path)
    except Exception as e:
        raise ImportError(f"Failed to import module '{module_path}' for parser: {e}") from e
    try:
        cls = getattr(module, class_name)
    except AttributeError as e:
        raise ImportError(
            f"Module '{module_path}' does not define class '{class_name}': {e}"
        ) from e
    return cls


def get_parser_class(name: str) -> Type:
    """
    返回注册名对应的解析器类（懒加载）。

    Raises:
        KeyError: 如果 name 未注册
        ImportError: 如果导入失败或目标不是类
    """
    try:
        entry = _registry[name]
    except KeyError as e:
        raise KeyError(
            f"No parser registered under name '{name}'. Available: {list(_registry.keys())}"
        ) from e

    # 已经是类
    if isinstance(entry, type):
        return entry

    # 字符串路径 -> 懒加载
    if isinstance(entry, str):
        cls = _load_from_path(entry)
        if not isinstance(cls, type):
            raise ImportError(f"Imported object from '{entry}' is not a class.")
        # cache the resolved class for subsequent calls
        _registry[name] = cls
        return cls

    raise ImportError(f"Unsupported registry entry for '{name}': {_registry[name]!r}")


def create_parser(name: str, *args: Any, **kwargs: Any) -> Any:
    """
    创建解析器实例。

    Example:
        parser = create_parser("generic", path="./data/chat.txt")
    """
    ParserCls = get_parser_class(name)
    return ParserCls(*args, **kwargs)


def get_base_parser_class() -> Type:
    """
    返回抽象基类 ChatParser（如果可用），否则抛出 ImportError 并提示修复方式。
    """
    try:
        module = importlib.import_module("vir_bot.core.distillation.parser.base")
        cls = getattr(module, "ChatParser")
        return cls
    except Exception as e:
        raise ImportError(
            "Base ChatParser class is not available. Make sure 'vir_bot/core/distillation/parser/base.py' exists "
            "and defines 'ChatParser'."
        ) from e
