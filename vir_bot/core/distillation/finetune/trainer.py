# -*- coding: utf-8 -*-
"""
LoRA 微调训练器

支持：
- HuggingFace transformers + PEFT 训练
- QLoRA（4-bit 量化 + LoRA）
- Alpaca / ShareGPT 格式训练数据
- 训练进度监控和评估
- 训练完成后自动保存 adapter

使用方式：
    from vir_bot.core.distillation.finetune import create_trainer
    trainer = create_trainer(config)
    result = trainer.train(train_file="data/training/train_alpaca.json")
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

@dataclass
class TrainingResult:
    """训练结果。"""
    adapter_path: str = ""
    total_steps: int = 0
    total_epochs: int = 0
    final_loss: float = 0.0
    best_loss: float = 0.0
    training_time_seconds: float = 0.0
    config: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "adapter_path": self.adapter_path,
            "total_steps": self.total_steps,
            "total_epochs": self.total_epochs,
            "final_loss": round(self.final_loss, 4),
            "best_loss": round(self.best_loss, 4),
            "training_time_seconds": round(self.training_time_seconds, 1),
            "config": self.config,
        }


# ---------------------------------------------------------------------------
# 训练回调
# ---------------------------------------------------------------------------


class LoggingCallback:
    """训练日志回调。通过 __getattr__ 兼容 transformers Trainer 所有回调事件。"""

    def __init__(self, log_interval: int = 10):
        self.log_interval = log_interval
        self.step = 0
        self.losses: List[float] = []

    def __getattr__(self, name):
        """对未定义的回调事件返回 no-op，避免 AttributeError。"""
        if name.startswith("on_"):
            return lambda *args, **kwargs: None
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

    def on_log(self, args, state, control, logs=None, **kwargs):
        if logs is None:
            return
        self.step += 1
        if "loss" in logs:
            self.losses.append(logs["loss"])
        if self.step % self.log_interval == 0:
            loss = logs.get("loss", 0)
            lr = logs.get("learning_rate", 0)
            epoch = logs.get("epoch", 0)
            logger.info("Step %d | Epoch %.2f | Loss: %.4f | LR: %.2e", self.step, epoch, loss, lr)


# ---------------------------------------------------------------------------
# LoRATrainer
# ---------------------------------------------------------------------------


class LoRATrainer:
    """
    LoRA 微调训练器。

    封装 HuggingFace transformers + PEFT 的训练流程：
    1. 加载基座模型
    2. 配置 LoRA/QLoRA
    3. 加载训练数据
    4. 执行训练
    5. 保存 adapter
    """

    def __init__(self, config: Optional[Any] = None) -> None:
        """
        Args:
            config: LoRAConfig 实例。如果为 None，使用默认配置。
        """
        if config is None:
            from vir_bot.core.distillation.finetune.lora_config import LoRAConfig
            config = LoRAConfig()

        self.config = config
        self._model = None
        self._tokenizer = None
        self._trainer = None

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def train(
        self,
        train_file: str,
        *,
        eval_file: Optional[str] = None,
        resume_from: Optional[str] = None,
    ) -> TrainingResult:
        """
        执行 LoRA 微调训练。

        Args:
            train_file: 训练数据文件路径（JSON 格式）
            eval_file: 验证数据文件路径（可选）
            resume_from: 从 checkpoint 恢复训练（可选）

        Returns:
            TrainingResult 训练结果
        """
        start_time = time.time()
        logger.info("开始 LoRA 训练：%s", self.config.base_model)
        logger.info("训练数据：%s", train_file)

        # 1. 加载模型和 tokenizer
        self._load_model()

        # 2. 配置 LoRA
        self._apply_lora()

        # 3. 加载训练数据
        train_dataset, eval_dataset = self._load_datasets(train_file, eval_file)

        # 4. 配置训练器
        self._setup_trainer(train_dataset, eval_dataset, resume_from)

        # 5. 执行训练
        train_output = self._do_train()

        # 6. 保存 adapter
        adapter_path = self._save_adapter()

        elapsed = time.time() - start_time

        result = TrainingResult(
            adapter_path=adapter_path,
            total_steps=train_output.global_step,
            total_epochs=self.config.num_epochs,
            final_loss=train_output.training_loss if hasattr(train_output, 'training_loss') else 0.0,
            best_loss=min(self._callback.losses) if self._callback.losses else 0.0,
            training_time_seconds=elapsed,
            config={
                "base_model": self.config.base_model,
                "lora_rank": self.config.lora_rank,
                "lora_alpha": self.config.lora_alpha,
                "use_qlora": self.config.use_qlora,
                "epochs": self.config.num_epochs,
                "learning_rate": self.config.learning_rate,
            },
        )

        logger.info("训练完成！耗时 %.1f 分钟", elapsed / 60)
        logger.info("Adapter 路径：%s", adapter_path)
        logger.info("最终 Loss: %.4f | 最佳 Loss: %.4f", result.final_loss, result.best_loss)

        return result

    # ------------------------------------------------------------------
    # 模型加载
    # ------------------------------------------------------------------

    def _load_model(self) -> None:
        """加载基座模型和 tokenizer。"""
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
        except ImportError as e:
            raise ImportError(
                "需要安装 transformers 和 torch: pip install transformers torch"
            ) from e

        logger.info("加载基座模型：%s", self.config.base_model)

        # 量化配置（QLoRA）
        quantization_config = None
        if self.config.use_qlora:
            bnb_config = self.config.to_bitsandbytes_config()
            quantization_config = BitsAndBytesConfig(**bnb_config)
            logger.info("启用 QLoRA：%d-bit 量化", self.config.quantization_bits)

        # 加载模型（low_cpu_mem_usage 减少加载时峰值内存，防止 8GB 显卡 OOM）
        model_kwargs: Dict[str, Any] = {
            "trust_remote_code": self.config.trust_remote_code,
            "torch_dtype": torch.bfloat16 if self.config.bf16 else torch.float16,
            "low_cpu_mem_usage": True,
        }

        if quantization_config:
            model_kwargs["quantization_config"] = quantization_config
            model_kwargs["device_map"] = "auto"

        # 尝试从本地加载，失败则在线下载
        model_path = self.config.base_model
        local_path = Path("./pretrained_models") / self.config.base_model.split("/")[-1]
        if local_path.exists():
            model_path = str(local_path)
            logger.info("从本地加载模型：%s", model_path)

        self._model = AutoModelForCausalLM.from_pretrained(model_path, **model_kwargs)
        self._model.config.use_cache = False  # 训练时禁用 KV cache

        # 加载 tokenizer
        self._tokenizer = AutoTokenizer.from_pretrained(
            model_path,
            trust_remote_code=self.config.trust_remote_code,
            padding_side="right",
        )

        if self._tokenizer.pad_token is None:
            self._tokenizer.pad_token = self._tokenizer.eos_token

        logger.info("模型加载完成，参数量：%s", self._count_params())

    def _count_params(self) -> str:
        """格式化模型参数量。"""
        if self._model is None:
            return "unknown"
        total = sum(p.numel() for p in self._model.parameters())
        if total >= 1e9:
            return f"{total / 1e9:.1f}B"
        return f"{total / 1e6:.1f}M"

    # ------------------------------------------------------------------
    # LoRA 配置
    # ------------------------------------------------------------------

    def _apply_lora(self) -> None:
        """应用 LoRA/QLoRA 配置。"""
        try:
            from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training, TaskType
        except ImportError as e:
            raise ImportError("需要安装 peft: pip install peft") from e

        # QLoRA 需要先准备模型
        if self.config.use_qlora:
            self._model = prepare_model_for_kbit_training(
                self._model,
                use_gradient_checkpointing=True,
            )

        # 创建 LoRA 配置
        peft_config = self.config.to_peft_config()
        peft_config["task_type"] = TaskType.CAUSAL_LM

        lora_config = LoraConfig(**peft_config)
        self._model = get_peft_model(self._model, lora_config)

        # 打印可训练参数
        trainable, total = self._get_trainable_params()
        logger.info("LoRA 配置完成：rank=%d, alpha=%d", self.config.lora_rank, self.config.lora_alpha)
        logger.info("可训练参数：%s / %s (%.2f%%)", f"{trainable:,}", f"{total:,}", 100 * trainable / total)

    def _get_trainable_params(self) -> tuple:
        """获取可训练参数数量。"""
        trainable = sum(p.numel() for p in self._model.parameters() if p.requires_grad)
        total = sum(p.numel() for p in self._model.parameters())
        return trainable, total

    # ------------------------------------------------------------------
    # 数据加载
    # ------------------------------------------------------------------

    def _load_datasets(
        self,
        train_file: str,
        eval_file: Optional[str],
    ) -> tuple:
        """加载训练和验证数据集。"""
        try:
            from datasets import load_dataset
        except ImportError as e:
            raise ImportError("需要安装 datasets: pip install datasets") from e

        logger.info("加载训练数据：%s", train_file)

        # 加载训练数据
        data = load_dataset("json", data_files=train_file, split="train")

        # 分割验证集
        if eval_file:
            eval_data = load_dataset("json", data_files=eval_file, split="train")
        else:
            split = data.train_test_split(test_size=self.config.eval_ratio, seed=42)
            data = split["train"]
            eval_data = split["test"]

        logger.info("训练集：%d 条，验证集：%d 条", len(data), len(eval_data))

        # 预处理：用独立闭包避免 pickle 整个 trainer（含 4B 模型）
        # num_proc=1 避免 Windows 下 pickle tokenizer 卡死
        tokenizer = self._tokenizer
        max_length = self.config.max_seq_length

        def _preprocess_fn(examples: Dict[str, Any]) -> Dict[str, Any]:
            prompts = []
            inputs = examples.get("input", [""] * len(examples["instruction"]))
            for i in range(len(examples["instruction"])):
                instruction = examples["instruction"][i]
                inp = inputs[i] or ""
                output = examples["output"][i]
                if inp:
                    prompts.append(f"### 指令：\n{instruction}\n\n### 输入：\n{inp}\n\n### 回复：\n{output}")
                else:
                    prompts.append(f"### 指令：\n{instruction}\n\n### 回复：\n{output}")

            tokenized = tokenizer(prompts, truncation=True, max_length=max_length, padding=False)
            tokenized["labels"] = tokenized["input_ids"].copy()
            return tokenized

        train_dataset = data.map(
            _preprocess_fn,
            batched=True,
            batch_size=256,
            remove_columns=data.column_names,
            num_proc=1,
            desc="预处理训练数据",
        )

        eval_dataset = eval_data.map(
            _preprocess_fn,
            batched=True,
            batch_size=256,
            remove_columns=eval_data.column_names,
            num_proc=1,
            desc="预处理验证数据",
        )

        return train_dataset, eval_dataset

    # ------------------------------------------------------------------
    # 训练器设置
    # ------------------------------------------------------------------

    def _setup_trainer(
        self,
        train_dataset: Any,
        eval_dataset: Any,
        resume_from: Optional[str],
    ) -> None:
        """配置 HuggingFace Trainer。"""
        try:
            from transformers import TrainingArguments, Trainer, DataCollatorForSeq2Seq
        except ImportError as e:
            raise ImportError("需要安装 transformers: pip install transformers") from e

        # 训练参数
        training_args_dict = self.config.to_training_args()
        training_args = TrainingArguments(**training_args_dict)

        # 数据整理器
        data_collator = DataCollatorForSeq2Seq(
            tokenizer=self._tokenizer,
            padding=True,
            max_length=self.config.max_seq_length,
        )

        # 回调
        self._callback = LoggingCallback(log_interval=self.config.logging_steps)

        # 创建 Trainer
        self._trainer = Trainer(
            model=self._model,
            args=training_args,
            train_dataset=train_dataset,
            eval_dataset=eval_dataset,
            data_collator=data_collator,
            callbacks=[self._callback],
        )

    def _do_train(self) -> Any:
        """执行训练。"""
        if self._trainer is None:
            raise RuntimeError("Trainer 未初始化")

        logger.info("开始训练...")
        train_output = self._trainer.train()

        # 最终评估（恢复 use_cache 以启用推理加速）
        try:
            self._model.config.use_cache = True
            eval_result = self._trainer.evaluate()
            logger.info("最终验证 Loss: %.4f", eval_result.get("eval_loss", 0))
            self._model.config.use_cache = False
        except Exception as e:
            logger.warning("最终评估失败: %s", e)

        return train_output

    # ------------------------------------------------------------------
    # 保存
    # ------------------------------------------------------------------

    def _save_adapter(self) -> str:
        """保存 LoRA adapter。"""
        output_dir = Path(self.config.output_dir) / self.config.adapter_name
        output_dir.mkdir(parents=True, exist_ok=True)

        # 保存 adapter
        self._model.save_pretrained(str(output_dir))
        self._tokenizer.save_pretrained(str(output_dir))

        # 保存训练配置
        config_path = output_dir / "training_config.json"
        from dataclasses import asdict
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(asdict(self.config), f, ensure_ascii=False, indent=2)

        logger.info("Adapter 保存到：%s", output_dir)
        return str(output_dir)

    # ------------------------------------------------------------------
    # 便捷方法
    # ------------------------------------------------------------------

    @classmethod
    def train_from_cli(cls, args: list[str] | None = None) -> TrainingResult:
        """
        从命令行参数训练。

        用法：
            python -m vir_bot.core.distillation.finetune.trainer \\
                --train-file data/training/train_alpaca.json \\
                --base-model Qwen/Qwen2.5-7B-Instruct \\
                --use-qlora \\
                --epochs 3
        """
        import argparse

        parser = argparse.ArgumentParser(description="LoRA 微调训练")
        parser.add_argument("--train-file", required=True, help="训练数据文件")
        parser.add_argument("--eval-file", help="验证数据文件")
        parser.add_argument("--base-model", default="Qwen/Qwen2.5-7B-Instruct", help="基座模型")
        parser.add_argument("--lora-rank", type=int, default=32, help="LoRA rank")
        parser.add_argument("--lora-alpha", type=int, default=64, help="LoRA alpha")
        parser.add_argument("--epochs", type=int, default=3, help="训练轮数")
        parser.add_argument("--batch-size", type=int, default=4, help="批大小")
        parser.add_argument("--lr", type=float, default=2e-4, help="学习率")
        parser.add_argument("--use-qlora", action="store_true", help="启用 QLoRA")
        parser.add_argument("--qlora-bits", type=int, default=4, choices=[4, 8], help="量化位数")
        parser.add_argument("--max-seq-length", type=int, default=2048, help="最大序列长度")
        parser.add_argument("--grad-accum", type=int, default=4, help="梯度累积步数")
        parser.add_argument("--eval-steps", type=int, default=100, help="评估间隔（设大值跳过中间eval）")
        parser.add_argument("--save-steps", type=int, default=100, help="保存间隔")
        parser.add_argument("--output-dir", default="./data/lora_adapters", help="输出目录")
        parser.add_argument("--adapter-name", default="persona_adapter", help="adapter 名称")

        parsed = parser.parse_args(args)

        from vir_bot.core.distillation.finetune.lora_config import LoRAConfig

        config = LoRAConfig(
            base_model=parsed.base_model,
            lora_rank=parsed.lora_rank,
            lora_alpha=parsed.lora_alpha,
            num_epochs=parsed.epochs,
            per_device_batch_size=parsed.batch_size,
            gradient_accumulation_steps=parsed.grad_accum,
            learning_rate=parsed.lr,
            use_qlora=parsed.use_qlora,
            quantization_bits=parsed.qlora_bits,
            max_seq_length=parsed.max_seq_length,
            eval_steps=parsed.eval_steps,
            save_steps=parsed.save_steps,
            output_dir=parsed.output_dir,
            adapter_name=parsed.adapter_name,
        )

        trainer = cls(config)
        return trainer.train(
            train_file=parsed.train_file,
            eval_file=parsed.eval_file,
        )


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    result = LoRATrainer.train_from_cli()
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
