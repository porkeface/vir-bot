# -*- coding: utf-8 -*-
"""
LoRA 微调模块独立入口

用法：
    # 训练
    python -m vir_bot.core.distillation.finetune train --train-file data/train.json --base-model Qwen/Qwen2.5-7B-Instruct

    # 构造训练数据
    python -m vir_bot.core.distillation.finetune build-data --dialogue-file data/dialogues.json --profile-file data/profile.json

    # 人格评测
    python -m vir_bot.core.distillation.finetune eval-persona --adapter-path data/lora_adapters/persona_adapter --profile-file data/profile.json

    # 交互推理
    python -m vir_bot.core.distillation.finetune infer --adapter-path data/lora_adapters/persona_adapter
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Optional

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m vir_bot.core.distillation.finetune",
        description="LoRA 微调工具集 — 训练数据构造、LoRA 训练、推理、评测。",
    )

    sub = p.add_subparsers(dest="command", help="子命令")

    # ---- train ----
    train_p = sub.add_parser("train", help="LoRA 微调训练")
    train_p.add_argument("--train-file", required=True, help="训练数据文件（JSON）")
    train_p.add_argument("--eval-file", help="验证数据文件")
    train_p.add_argument("--base-model", default="Qwen/Qwen2.5-7B-Instruct", help="基座模型")
    train_p.add_argument("--lora-rank", type=int, default=32, help="LoRA rank")
    train_p.add_argument("--lora-alpha", type=int, default=64, help="LoRA alpha")
    train_p.add_argument("--epochs", type=int, default=3, help="训练轮数")
    train_p.add_argument("--batch-size", type=int, default=4, help="批大小")
    train_p.add_argument("--lr", type=float, default=2e-4, help="学习率")
    train_p.add_argument("--use-qlora", action="store_true", help="启用 QLoRA")
    train_p.add_argument("--qlora-bits", type=int, default=4, choices=[4, 8], help="量化位数")
    train_p.add_argument("--max-seq-length", type=int, default=2048, help="最大序列长度")
    train_p.add_argument("--output-dir", default="./data/lora_adapters", help="输出目录")
    train_p.add_argument("--adapter-name", default="persona_adapter", help="adapter 名称")

    # ---- build-data ----
    build_p = sub.add_parser("build-data", help="构造 LoRA 训练数据")
    build_p.add_argument("--dialogue-file", required=True, help="对话记录文件（JSON）")
    build_p.add_argument("--profile-file", required=True, help="PersonaProfile 文件（JSON）")
    build_p.add_argument("--output", "-o", help="输出文件路径")
    build_p.add_argument("--format", choices=["alpaca", "sharegpt"], default="alpaca", help="输出格式")
    build_p.add_argument("--stages", nargs="+", default=["a", "b", "c"], help="训练阶段")
    build_p.add_argument("--max-stage-a", type=int, default=2000, help="Stage A 最大样本数")
    build_p.add_argument("--window-size", type=int, default=5, help="滑动窗口大小")

    # ---- eval-persona ----
    eval_p = sub.add_parser("eval-persona", help="人格保真度评测")
    eval_p.add_argument("--adapter-path", required=True, help="LoRA adapter 目录")
    eval_p.add_argument("--profile-file", required=True, help="PersonaProfile 文件（JSON）")
    eval_p.add_argument("--base-model", help="基座模型")
    eval_p.add_argument("--output", "-o", help="评测报告输出路径")
    eval_p.add_argument("--quick", action="store_true", help="快速评测")
    eval_p.add_argument("--load-4bit", action="store_true", help="4-bit 量化加载")

    # ---- infer ----
    infer_p = sub.add_parser("infer", help="LoRA adapter 推理")
    infer_p.add_argument("--adapter-path", required=True, help="LoRA adapter 目录")
    infer_p.add_argument("--base-model", help="基座模型")
    infer_p.add_argument("--system-prompt", "-s", help="系统提示词")
    infer_p.add_argument("--input", "-i", help="用户输入")
    infer_p.add_argument("--max-tokens", type=int, default=512, help="最大生成 token 数")
    infer_p.add_argument("--temperature", type=float, default=0.7, help="生成温度")
    infer_p.add_argument("--load-4bit", action="store_true", help="4-bit 量化加载")

    return p


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    parser = build_parser()
    ns = parser.parse_args(argv)

    if not ns.command:
        parser.print_help()
        return 1

    if ns.command == "train":
        return _cmd_train(ns)
    elif ns.command == "build-data":
        return _cmd_build_data(ns)
    elif ns.command == "eval-persona":
        return _cmd_eval_persona(ns)
    elif ns.command == "infer":
        return _cmd_infer(ns)
    else:
        parser.print_help()
        return 1


def _cmd_train(ns: argparse.Namespace) -> int:
    from vir_bot.core.distillation.finetune.lora_config import LoRAConfig
    from vir_bot.core.distillation.finetune.trainer import LoRATrainer

    config = LoRAConfig(
        base_model=ns.base_model,
        lora_rank=ns.lora_rank,
        lora_alpha=ns.lora_alpha,
        num_epochs=ns.epochs,
        per_device_batch_size=ns.batch_size,
        learning_rate=ns.lr,
        use_qlora=ns.use_qlora,
        quantization_bits=ns.qlora_bits,
        max_seq_length=ns.max_seq_length,
        output_dir=ns.output_dir,
        adapter_name=ns.adapter_name,
    )

    trainer = LoRATrainer(config)
    result = trainer.train(train_file=ns.train_file, eval_file=ns.eval_file)

    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


def _cmd_build_data(ns: argparse.Namespace) -> int:
    from vir_bot.core.distillation.finetune.train_data_builder import TrainDataBuilder
    from vir_bot.core.distillation.analyzer.extractor import PersonaProfile

    with open(ns.dialogue_file, "r", encoding="utf-8") as f:
        dialogue_data = json.load(f)
    with open(ns.profile_file, "r", encoding="utf-8") as f:
        profile_data = json.load(f)

    profile = PersonaProfile(**profile_data) if isinstance(profile_data, dict) else profile_data

    builder = TrainDataBuilder(
        window_size=ns.window_size,
        max_stage_a_pairs=ns.max_stage_a,
    )

    result = builder.build(
        dialogues=dialogue_data,
        profile=profile,
        output_path=ns.output,
        output_format=ns.format,
        stages=ns.stages,
    )

    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


def _cmd_eval_persona(ns: argparse.Namespace) -> int:
    from vir_bot.core.distillation.finetune.lora_inference import LoRAInference
    from vir_bot.core.distillation.finetune.personality_evaluator import PersonalityEvaluator
    from vir_bot.core.distillation.analyzer.extractor import PersonaProfile

    with open(ns.profile_file, "r", encoding="utf-8") as f:
        profile_data = json.load(f)

    profile = PersonaProfile(**profile_data) if isinstance(profile_data, dict) else profile_data

    engine = LoRAInference(
        adapter_path=ns.adapter_path,
        base_model=ns.base_model,
        load_in_4bit=ns.load_4bit,
    )

    def generate_fn(question: str) -> str:
        return engine.generate(question).text

    evaluator = PersonalityEvaluator()
    if ns.quick:
        result = evaluator.evaluate_quick(profile, generate_fn)
    else:
        result = evaluator.evaluate(profile, generate_fn)

    print(result.summary())

    if ns.output:
        evaluator.save_report(result, ns.output)

    return 0


def _cmd_infer(ns: argparse.Namespace) -> int:
    from vir_bot.core.distillation.finetune.lora_inference import LoRAInference, GenerationConfig

    gen_config = GenerationConfig(
        max_new_tokens=ns.max_tokens,
        temperature=ns.temperature,
    )

    engine = LoRAInference(
        adapter_path=ns.adapter_path,
        base_model=ns.base_model,
        load_in_4bit=ns.load_4bit,
        generation_config=gen_config,
    )

    if ns.input:
        result = engine.generate(ns.input, system_prompt=ns.system_prompt)
        print(result.text)
    else:
        print("交互模式（输入 'quit' 退出）")
        history = []
        while True:
            try:
                user_input = input("\n你: ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not user_input or user_input.lower() in ("quit", "exit", "q"):
                break

            result = engine.generate(
                user_input,
                system_prompt=ns.system_prompt,
                history=history,
            )
            print(f"\n角色: {result.text}")

            history.append({"role": "user", "content": user_input})
            history.append({"role": "assistant", "content": result.text})
            if len(history) > 20:
                history = history[-20:]

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
