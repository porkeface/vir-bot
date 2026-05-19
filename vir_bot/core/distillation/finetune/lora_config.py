# -*- coding: utf-8 -*-
"""
LoRA 训练配置

提供 LoRA/QLoRA 微调的超参数配置。
参考 CharLoRA（ACL 2025 Findings）的推荐设置。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import json
import logging

logger = logging.getLogger(__name__)


@dataclass
class LoRAConfig:
    """
    LoRA 微调配置。

    基于 CharLoRA 和 RoleLLM 的推荐参数：
    - rank 16-64（角色扮演任务通常 32 足够）
    - alpha 2x rank
    - target_modules: q/k/v/o_proj（注意力层）
    - dropout 0.05-0.1
    """
    # 基座模型
    base_model: str = "Qwen/Qwen2.5-7B-Instruct"
    model_revision: str = "main"
    trust_remote_code: bool = True

    # LoRA 参数
    lora_rank: int = 32
    lora_alpha: int = 64
    lora_dropout: float = 0.05
    target_modules: List[str] = field(
        default_factory=lambda: ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]
    )
    bias: str = "none"
    task_type: str = "CAUSAL_LM"

    # 训练参数
    num_epochs: int = 3
    per_device_batch_size: int = 4
    gradient_accumulation_steps: int = 4
    learning_rate: float = 2e-4
    lr_scheduler_type: str = "cosine"
    warmup_ratio: float = 0.1
    weight_decay: float = 0.01
    max_grad_norm: float = 1.0
    max_seq_length: int = 2048
    logging_steps: int = 10
    save_steps: int = 100
    save_total_limit: int = 3
    eval_steps: int = 100
    eval_ratio: float = 0.05  # 验证集比例

    # QLoRA（量化 + LoRA）
    use_qlora: bool = False
    quantization_bits: int = 4  # 4-bit 或 8-bit
    quant_type: str = "nf4"  # nf4 或 fp4
    double_quant: bool = True  # 双重量化

    # 混合精度
    fp16: bool = False
    bf16: bool = True  # 推荐 A100/4090 使用 bf16

    # 输出
    output_dir: str = "./data/lora_adapters"
    adapter_name: str = "persona_adapter"

    # DeepSpeed（可选）
    use_deepspeed: bool = False
    deepspeed_stage: int = 2

    def to_peft_config(self) -> Dict[str, Any]:
        """转为 PEFT LoraConfig 参数。"""
        return {
            "r": self.lora_rank,
            "lora_alpha": self.lora_alpha,
            "lora_dropout": self.lora_dropout,
            "target_modules": self.target_modules,
            "bias": self.bias,
            "task_type": self.task_type,
        }

    def to_training_args(self) -> Dict[str, Any]:
        """转为 TrainingArguments 参数。"""
        args = {
            "output_dir": str(Path(self.output_dir) / self.adapter_name),
            "num_train_epochs": self.num_epochs,
            "per_device_train_batch_size": self.per_device_batch_size,
            "gradient_accumulation_steps": self.gradient_accumulation_steps,
            "learning_rate": self.learning_rate,
            "lr_scheduler_type": self.lr_scheduler_type,
            "warmup_ratio": self.warmup_ratio,
            "weight_decay": self.weight_decay,
            "max_grad_norm": self.max_grad_norm,
            "logging_steps": self.logging_steps,
            "save_steps": self.save_steps,
            "save_total_limit": self.save_total_limit,
            "eval_steps": self.eval_steps,
            "eval_strategy": "steps",
            "fp16": self.fp16,
            "bf16": self.bf16,
            "gradient_checkpointing": True,
            "gradient_checkpointing_kwargs": {"use_reentrant": False},
            "report_to": "none",
        }

        if self.use_deepspeed:
            args["deepspeed"] = self._get_deepspeed_config()

        return args

    def to_bitsandbytes_config(self) -> Optional[Dict[str, Any]]:
        """转为 BitsAndBytesConfig 参数（QLoRA 时使用）。"""
        if not self.use_qlora:
            return None
        return {
            "load_in_4bit": self.quantization_bits == 4,
            "load_in_8bit": self.quantization_bits == 8,
            "bnb_4bit_quant_type": self.quant_type,
            "bnb_4bit_use_double_quant": self.double_quant,
            "bnb_4bit_compute_dtype": "bfloat16" if self.bf16 else "float16",
        }

    def _get_deepspeed_config(self) -> Dict[str, Any]:
        """DeepSpeed ZeRO 配置。"""
        return {
            "stage": self.deepspeed_stage,
            "offload_optimizer": {"device": "cpu"} if self.deepspeed_stage == 3 else {},
            "offload_param": {"device": "none"},
            "overlap_comm": True,
            "contiguous_gradients": True,
            "sub_group_size": 1e9,
            "reduce_bucket_size": "auto",
            "stage3_prefetch_bucket_size": "auto",
            "stage3_param_persistence_threshold": "auto",
            "stage3_max_live_parameters": 1e9,
            "stage3_max_reuse_distance": 1e9,
        }

    def save(self, path: str) -> None:
        """保存配置到 JSON 文件。"""
        from dataclasses import asdict
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, ensure_ascii=False, indent=2)
        logger.info("LoRA 配置保存到：%s", p)

    @classmethod
    def load(cls, path: str) -> "LoRAConfig":
        """从 JSON 文件加载配置。"""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(**data)

    @classmethod
    def qlora_default(cls) -> "LoRAConfig":
        """QLoRA 默认配置（8GB VRAM 可跑 7B 模型）。"""
        return cls(
            use_qlora=True,
            quantization_bits=4,
            per_device_batch_size=2,
            gradient_accumulation_steps=8,
            fp16=True,
            bf16=False,
        )

    @classmethod
    def full_lora_default(cls) -> "LoRAConfig":
        """全精度 LoRA 默认配置（需要 24GB+ VRAM）。"""
        return cls(
            use_qlora=False,
            per_device_batch_size=4,
            gradient_accumulation_steps=4,
            bf16=True,
        )
