"""评测入口点。用法: python -m tests.eval [--mock] [--datasets pref_recall ...]"""

import asyncio
import argparse
import sys
import os

# 确保项目根目录在路径中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from pathlib import Path


async def main():
    parser = argparse.ArgumentParser(description="运行记忆系统评测")
    parser.add_argument("--mock", action="store_true", help="使用 mock 模式（不调用真实 AI）")
    parser.add_argument("--datasets", nargs="*", help="指定数据集，默认全部")
    args = parser.parse_args()

    # 初始化（简化版，实际应该从配置加载）
    from vir_bot.core.ai_provider import AIProvider
    from vir_bot.core.memory import (
        ShortTermMemory, LongTermMemory, SemanticMemoryStore,
        EpisodicMemoryStore, QuestionMemoryStore, MemoryWriter, MemoryUpdater,
        MemoryManager,
    )

    # AI Provider（mock 模式或真实）
    if args.mock:
        class MockAI:
            async def chat(self, messages, system="", temperature=0.1):
                class R:
                    content = "Mock response"
                return R()
        ai_provider = MockAI()
    else:
        # 这里需要根据实际配置初始化
        print("真实模式需要从配置文件加载 AI Provider...")
        print("请使用 --mock 运行，或配置 config.yaml")
        return

    # 初始化记忆组件
    short_term = ShortTermMemory()
    long_term = None  # 可选
    semantic_store = SemanticMemoryStore()
    episodic_store = EpisodicMemoryStore()
    question_store = QuestionMemoryStore()
    memory_writer = MemoryWriter(ai_provider=ai_provider)
    memory_updater = MemoryUpdater(semantic_store=semantic_store)

    memory_manager = MemoryManager(
        short_term=short_term,
        long_term=long_term,
        semantic_store=semantic_store,
        memory_writer=memory_writer,
        memory_updater=memory_updater,
        episodic_store=episodic_store,
        question_store=question_store,
        ai_provider=ai_provider,
        features={
            "quality_gate": {"enabled": True},
            "verifier": {"enabled": True},
            "versioning": {"enabled": True},
            "graph": {"enabled": True},
            "lifecycle": {"enabled": True},
        },
    )

    # 运行评测
    from tests.eval.runner import EvaluationRunner

    runner = EvaluationRunner(
        memory_manager=memory_manager,
        ai_provider=ai_provider,
    )

    dataset_names = args.datasets if args.datasets else None
    report = await runner.run_all(dataset_names=dataset_names, use_mock=args.mock)

    # 输出报告
    print("\n" + "=" * 60)
    print("评测报告")
    print("=" * 60)
    for name, score in report["scores"].items():
        print(f"  {name}: {score:.2%}")
    print(f"\n  总分: {report['overall']:.2%}")
    print("=" * 60)

    # 保存报告
    report_path = Path("tests/eval/report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    import json
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n报告已保存: {report_path}")


if __name__ == "__main__":
    asyncio.run(main())
