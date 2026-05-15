# -*- coding: utf-8 -*-
"""
vir_bot.core.distillation.finetune
===================================

LoRA 微调基础设施。

提供：
- 训练数据构造（聊天记录 → 训练对）
- LoRA/QLoRA 训练配置与脚本
- LoRA adapter 推理集成
- 人格评测（InCharacter 风格）
"""

from __future__ import annotations

import importlib
from typing import Any, Dict, Type

__all__ = [
    "get_builder_class",
    "create_builder",
    "get_trainer_class",
    "create_trainer",
    "get_inference_class",
    "create_inference",
    "get_evaluator_class",
    "create_evaluator",
]

_registry: Dict[str, Type | str] = {
    "builder": "vir_bot.core.distillation.finetune.train_data_builder:TrainDataBuilder",
    "trainer": "vir_bot.core.distillation.finetune.trainer:LoRATrainer",
    "inference": "vir_bot.core.distillation.finetune.lora_inference:LoRAInference",
    "evaluator": "vir_bot.core.distillation.finetune.personality_evaluator:PersonalityEvaluator",
}


def _load_from_path(path: str) -> Type:
    if ":" not in path:
        raise ImportError(f"Invalid import path '{path}'. Expected 'module:ClassName'.")
    module_path, class_name = path.split(":", 1)
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    if not isinstance(cls, type):
        raise ImportError(f"'{class_name}' from '{module_path}' is not a class.")
    return cls


def _get(name: str) -> Type:
    entry = _registry.get(name)
    if entry is None:
        raise KeyError(f"No finetune component registered under '{name}'. Available: {list(_registry.keys())}")
    if isinstance(entry, type):
        return entry
    cls = _load_from_path(entry)
    _registry[name] = cls
    return cls


def get_builder_class() -> Type:
    return _get("builder")


def create_builder(*args: Any, **kwargs: Any) -> Any:
    return get_builder_class()(*args, **kwargs)


def get_trainer_class() -> Type:
    return _get("trainer")


def create_trainer(*args: Any, **kwargs: Any) -> Any:
    return get_trainer_class()(*args, **kwargs)


def get_inference_class() -> Type:
    return _get("inference")


def create_inference(*args: Any, **kwargs: Any) -> Any:
    return get_inference_class()(*args, **kwargs)


def get_evaluator_class() -> Type:
    return _get("evaluator")


def create_evaluator(*args: Any, **kwargs: Any) -> Any:
    return get_evaluator_class()(*args, **kwargs)
