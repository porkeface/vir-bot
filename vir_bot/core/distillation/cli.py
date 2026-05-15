#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
蒸馏命令行工具（v2）

新增功能：
- --chunk-size: 分块大小（每块对话轮数）
- --incremental + --existing: 增量蒸馏
- --judge: 使用 LLM-as-Judge 评测（默认开启）
- --no-judge: 禁用 LLM-as-Judge，回退到简单重叠度评测
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from vir_bot.config import get_config, load_config
from vir_bot.core.ai_provider import AIProviderFactory
from vir_bot.core.distillation import create_pipeline

logger = logging.getLogger("vir_bot.distillation.cli")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="vir-bot-distill",
        description="角色蒸馏 CLI — 从聊天记录提取人格特征，生成角色卡。",
    )

    sub = p.add_subparsers(dest="command", help="子命令")

    # ---- 默认：蒸馏流程 ----
    p.add_argument(
        "--config", "-c",
        help="配置文件路径（默认使用 config.yaml）",
        default=None,
    )
    p.add_argument(
        "--input", "-i",
        help="聊天记录文件路径（json/ndjson/txt）",
    )
    p.add_argument(
        "--name", "-n",
        help="角色名称",
    )
    p.add_argument(
        "--output", "-o",
        help="Markdown 输出目录（默认 ./data/wiki/characters/）",
        default="./data/wiki/characters/",
    )
    p.add_argument(
        "--json-output",
        help="SillyTavern JSON 输出目录（默认 ./data/characters/）",
        default="./data/characters/",
    )
    p.add_argument(
        "--evaluate", "-e",
        action="store_true",
        help="执行评测",
    )
    p.add_argument(
        "--judge",
        action="store_true",
        default=True,
        help="使用 LLM-as-Judge 评测（默认开启）",
    )
    p.add_argument(
        "--no-judge",
        action="store_true",
        help="禁用 LLM-as-Judge，使用简单重叠度评测",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="预览模式，不写入文件",
    )
    p.add_argument(
        "--incremental",
        action="store_true",
        help="增量模式：基于已有角色卡更新",
    )
    p.add_argument(
        "--existing",
        help="增量模式下的已有角色卡路径",
        default=None,
    )
    p.add_argument(
        "--parser",
        help="强制指定解析器（generic/wechat/qq/discord）",
        default="auto",
    )
    p.add_argument(
        "--chunk-size",
        type=int,
        default=400,
        help="每块对话轮数（默认 400）",
    )
    p.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="单次 LLM 调用超时秒数（默认 120）",
    )
    p.add_argument(
        "--verbose", "-v",
        action="count",
        help="增加详细度（-v 或 -vv）",
    )
    p.add_argument(
        "--target", "-t",
        help="目标分析对象的发送者名称（两人聊天时指定要分析谁）",
        default=None,
    )

    # ---- 子命令：train ----
    train_parser = sub.add_parser("train", help="LoRA 微调训练")
    train_parser.add_argument("--train-file", required=True, help="训练数据文件（JSON）")
    train_parser.add_argument("--eval-file", help="验证数据文件")
    train_parser.add_argument("--base-model", default="Qwen/Qwen2.5-7B-Instruct", help="基座模型")
    train_parser.add_argument("--lora-rank", type=int, default=32, help="LoRA rank")
    train_parser.add_argument("--lora-alpha", type=int, default=64, help="LoRA alpha")
    train_parser.add_argument("--epochs", type=int, default=3, help="训练轮数")
    train_parser.add_argument("--batch-size", type=int, default=4, help="批大小")
    train_parser.add_argument("--lr", type=float, default=2e-4, help="学习率")
    train_parser.add_argument("--use-qlora", action="store_true", help="启用 QLoRA（4-bit 量化）")
    train_parser.add_argument("--qlora-bits", type=int, default=4, choices=[4, 8], help="量化位数")
    train_parser.add_argument("--max-seq-length", type=int, default=2048, help="最大序列长度")
    train_parser.add_argument("--output-dir", default="./data/lora_adapters", help="输出目录")
    train_parser.add_argument("--adapter-name", default="persona_adapter", help="adapter 名称")

    # ---- 子命令：build-data ----
    build_parser = sub.add_parser("build-data", help="构造 LoRA 训练数据")
    build_parser.add_argument("--dialogue-file", required=True, help="对话记录文件（JSON）")
    build_parser.add_argument("--profile-file", required=True, help="PersonaProfile 文件（JSON）")
    build_parser.add_argument("--output", "-o", help="输出文件路径")
    build_parser.add_argument("--format", choices=["alpaca", "sharegpt"], default="alpaca", help="输出格式")
    build_parser.add_argument("--stages", nargs="+", default=["a", "b", "c"], help="训练阶段（a/b/c）")
    build_parser.add_argument("--max-stage-a", type=int, default=2000, help="Stage A 最大样本数")
    build_parser.add_argument("--window-size", type=int, default=5, help="滑动窗口大小")

    # ---- 子命令：eval-persona ----
    eval_parser = sub.add_parser("eval-persona", help="人格保真度评测")
    eval_parser.add_argument("--adapter-path", required=True, help="LoRA adapter 目录路径")
    eval_parser.add_argument("--profile-file", required=True, help="PersonaProfile 文件（JSON）")
    eval_parser.add_argument("--base-model", help="基座模型（默认从 adapter 配置读取）")
    eval_parser.add_argument("--output", "-o", help="评测报告输出路径")
    eval_parser.add_argument("--quick", action="store_true", help="快速评测（每维度 3 题）")
    eval_parser.add_argument("--load-4bit", action="store_true", help="4-bit 量化加载")

    # ---- 子命令：infer ----
    infer_parser = sub.add_parser("infer", help="使用 LoRA adapter 生成回复")
    infer_parser.add_argument("--adapter-path", required=True, help="LoRA adapter 目录路径")
    infer_parser.add_argument("--base-model", help="基座模型")
    infer_parser.add_argument("--system-prompt", "-s", help="系统提示词（角色卡描述）")
    infer_parser.add_argument("--input", "-i", help="用户输入（不指定则交互模式）")
    infer_parser.add_argument("--max-tokens", type=int, default=512, help="最大生成 token 数")
    infer_parser.add_argument("--temperature", type=float, default=0.7, help="生成温度")
    infer_parser.add_argument("--load-4bit", action="store_true", help="4-bit 量化加载")

    return p


async def _run_distillation_async(args: argparse.Namespace) -> int:
    # 加载配置
    if args.config:
        cfg = load_config(args.config)
    else:
        cfg = get_config()

    # 创建 AI Provider
    try:
        ai_provider = AIProviderFactory.create(cfg.ai)
    except Exception as e:
        logger.exception("创建 AI Provider 失败: %s", e)
        return 2

    # 创建 Pipeline
    pipeline = create_pipeline(
        ai_provider,
        config=cfg,
        parser_name=(args.parser if args.parser != "auto" else None),
        wiki_output_dir=args.output,
        json_output_dir=args.json_output,
        chunk_size=args.chunk_size,
        enable_judge_eval=(not args.no_judge),
        target_sender=getattr(args, "target", None),
    )

    # 执行蒸馏
    try:
        result = await pipeline.run(
            input_path=args.input,
            name=args.name,
            evaluate=args.evaluate,
            dry_run=args.dry_run,
            incremental=args.incremental,
            existing=args.existing,
            timeout_seconds=args.timeout,
        )
    except FileNotFoundError as e:
        logger.error("输入错误: %s", e)
        return 3
    except Exception as e:
        logger.exception("蒸馏失败: %s", e)
        return 4
    finally:
        try:
            close_coro = getattr(ai_provider, "close", None)
            if close_coro:
                maybe = close_coro()
                if asyncio.iscoroutine(maybe):
                    await maybe
        except Exception:
            pass

    # 输出结果
    try:
        print_summary(result, args)
    except Exception:
        logger.exception("输出结果摘要失败")

    return 0


def print_summary(result: Any, args: argparse.Namespace) -> None:
    """打印蒸馏结果摘要。"""
    print("\n" + "=" * 50)
    print("  蒸馏结果摘要")
    print("=" * 50)

    name = getattr(result, "name", "<unknown>")
    print(f"\n角色: {name}")

    if args.dry_run:
        print("模式: 预览（未写入文件）")
    else:
        md_path = getattr(result, "markdown_path", None)
        json_path = getattr(result, "json_path", None)
        if md_path:
            print(f"Markdown: {md_path}")
        if json_path:
            print(f"JSON: {json_path}")

    # 评测结果
    evaluation = getattr(result, "evaluation", None)
    if evaluation and isinstance(evaluation, dict) and "error" not in evaluation:
        method = evaluation.get("method", "unknown")
        print(f"\n评测方法: {method}")

        if method == "llm_judge":
            overall = evaluation.get("overall_score", 0)
            style = evaluation.get("style_score", 0)
            emotion = evaluation.get("emotion_score", 0)
            value = evaluation.get("value_score", 0)
            taboo = evaluation.get("taboo_score", 0)
            passed = evaluation.get("pass", False)

            print(f"\n  综合得分: {overall:.3f}  {'✓ 通过' if passed else '✗ 未通过'}")
            print(f"  风格匹配: {style:.3f}")
            print(f"  情绪匹配: {emotion:.3f}")
            print(f"  价值观匹配: {value:.3f}")
            print(f"  禁忌回避: {taboo:.3f}")

            # 各场景详情
            scenarios = evaluation.get("scenarios", [])
            if scenarios and args.verbose:
                print("\n  场景详情:")
                for s in scenarios:
                    print(f"    [{s['id']}] {s['category']}: {s['overall']:.2f} — {s['trigger']}")
        else:
            metrics = evaluation.get("metrics", {})
            for k, v in metrics.items():
                print(f"  {k}: {v:.3f}" if isinstance(v, float) else f"  {k}: {v}")

    # Profile 摘要
    profile = getattr(result, "profile", None)
    if profile and isinstance(profile, dict):
        summary = profile.get("summary")
        if summary:
            print(f"\n人格摘要: {summary}")

        big_five = profile.get("big_five", {})
        if big_five and any(v for v in big_five.values() if v):
            print("\n大五人格:")
            for k in ("openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism"):
                v = big_five.get(k)
                if v is not None:
                    bar = "█" * int(v * 10) + "░" * (10 - int(v * 10))
                    print(f"  {k:20s} [{bar}] {v:.2f}")

    # 详细模式
    if args.verbose:
        raw_notes = getattr(result, "raw_notes", None)
        if raw_notes:
            print("\n原始笔记:")
            print(json.dumps(raw_notes, ensure_ascii=False, indent=2)[:2000])

    print("\n" + "=" * 50)


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    ns = parser.parse_args(argv)

    if getattr(ns, "verbose", None):
        if ns.verbose >= 2:
            logging.getLogger().setLevel(logging.DEBUG)
        else:
            logging.getLogger().setLevel(logging.INFO)

    # 子命令路由
    command = getattr(ns, "command", None)

    if command == "train":
        return _run_train(ns)
    elif command == "build-data":
        return _run_build_data(ns)
    elif command == "eval-persona":
        return _run_eval_persona(ns)
    elif command == "infer":
        return _run_infer(ns)
    else:
        # 默认：蒸馏流程
        if not getattr(ns, "input", None) or not getattr(ns, "name", None):
            parser.print_help()
            return 1
        try:
            return asyncio.run(_run_distillation_async(ns))
        except KeyboardInterrupt:
            logger.warning("用户中断")
            return 130
        except Exception:
            logger.exception("意外错误")
            return 1


def _run_train(ns: argparse.Namespace) -> int:
    """执行 LoRA 训练。"""
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

    print("\n" + "=" * 50)
    print("  LoRA 训练完成")
    print("=" * 50)
    print(f"\nAdapter 路径: {result.adapter_path}")
    print(f"总步数: {result.total_steps}")
    print(f"最终 Loss: {result.final_loss:.4f}")
    print(f"最佳 Loss: {result.best_loss:.4f}")
    print(f"耗时: {result.training_time_seconds / 60:.1f} 分钟")
    print("=" * 50)

    return 0


def _run_build_data(ns: argparse.Namespace) -> int:
    """构造 LoRA 训练数据。"""
    from vir_bot.core.distillation.finetune.train_data_builder import TrainDataBuilder

    # 加载对话数据
    with open(ns.dialogue_file, "r", encoding="utf-8") as f:
        dialogue_data = json.load(f)

    # 加载 Profile
    with open(ns.profile_file, "r", encoding="utf-8") as f:
        profile_data = json.load(f)

    # 构造 PersonaProfile（从 dict 构造）
    from vir_bot.core.distillation.analyzer.extractor import PersonaProfile
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

    print("\n" + "=" * 50)
    print("  训练数据构造完成")
    print("=" * 50)
    print(f"\n输出文件: {result.output_path}")
    print(f"Stage A 样本数: {result.stage_a_count}")
    print(f"Stage B 样本数: {result.stage_b_count}")
    print(f"Stage C 样本数: {result.stage_c_count}")
    print(f"总样本数: {result.total_count}")
    print("=" * 50)

    return 0


def _run_eval_persona(ns: argparse.Namespace) -> int:
    """执行人格保真度评测。"""
    from vir_bot.core.distillation.finetune.lora_inference import LoRAInference, GenerationConfig
    from vir_bot.core.distillation.finetune.personality_evaluator import PersonalityEvaluator

    # 加载 Profile
    with open(ns.profile_file, "r", encoding="utf-8") as f:
        profile_data = json.load(f)

    from vir_bot.core.distillation.analyzer.extractor import PersonaProfile
    profile = PersonaProfile(**profile_data) if isinstance(profile_data, dict) else profile_data

    # 创建推理引擎
    engine = LoRAInference(
        adapter_path=ns.adapter_path,
        base_model=ns.base_model,
        load_in_4bit=ns.load_4bit,
    )

    # 生成函数
    def generate_fn(question: str) -> str:
        result = engine.generate(question)
        return result.text

    # 执行评测
    evaluator = PersonalityEvaluator()
    if ns.quick:
        eval_result = evaluator.evaluate_quick(profile, generate_fn)
    else:
        eval_result = evaluator.evaluate(profile, generate_fn)

    # 输出报告
    print(eval_result.summary())

    if ns.output:
        evaluator.save_report(eval_result, ns.output)
        print(f"\n报告已保存到: {ns.output}")

    return 0


def _run_infer(ns: argparse.Namespace) -> int:
    """使用 LoRA adapter 进行推理。"""
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

    system_prompt = ns.system_prompt

    if ns.input:
        # 单次推理
        result = engine.generate(ns.input, system_prompt=system_prompt)
        print(result.text)
        return 0
    else:
        # 交互模式
        print("LoRA 推理交互模式（输入 'quit' 退出）")
        print("-" * 40)
        history = []

        while True:
            try:
                user_input = input("\n你: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n退出")
                break

            if not user_input:
                continue
            if user_input.lower() in ("quit", "exit", "q"):
                break

            result = engine.generate(
                user_input,
                system_prompt=system_prompt,
                history=history,
            )

            print(f"\n角色: {result.text}")

            history.append({"role": "user", "content": user_input})
            history.append({"role": "assistant", "content": result.text})

            # 限制历史长度
            if len(history) > 20:
                history = history[-20:]

        return 0


if __name__ == "__main__":
    raise SystemExit(main())
