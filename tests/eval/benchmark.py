"""评测主入口 - CLI 命令。"""

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from vir_bot.config import load_config
from vir_bot.core.ai_provider import AIProviderFactory
from vir_bot.core.memory.memory_manager import MemoryManager
from vir_bot.core.memory.memory_writer import MemoryWriter
from vir_bot.core.memory.memory_updater import MemoryUpdater
from vir_bot.core.memory.semantic_store import SemanticMemoryStore
from vir_bot.core.memory.episodic_store import EpisodicMemoryStore
from vir_bot.core.memory.long_term import LongTermMemory
from vir_bot.core.memory.short_term import ShortTermMemory
from vir_bot.core.memory.question_memory import QuestionMemoryStore
from tests.eval.runner import EvaluationRunner


async def main():
    parser = argparse.ArgumentParser(description="vir-bot 评测系统")
    parser.add_argument(
        "--dataset",
        type=str,
        nargs="+",
        help="指定运行的数据集（默认全部）",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="使用 Mock AI Provider（快速测试）",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config.yaml",
        help="配置文件路径",
    )
    parser.add_argument(
        "--report",
        type=str,
        default="tests/eval/report.json",
        help="评测报告输出路径",
    )

    args = parser.parse_args()

    # 加载配置
    config = load_config(args.config)

    # 初始化评测系统
    print("初始化评测系统...")

    # 使用临时目录避免污染真实数据
    temp_dir = tempfile.mkdtemp(prefix="vir-bot-eval-")
    print(f"使用临时目录: {temp_dir}")

    try:
        # 初始化组件
        semantic_store = SemanticMemoryStore(
            persist_path=f"{temp_dir}/semantic_memory.json"
        )
        episodic_store = EpisodicMemoryStore(
            persist_path=f"{temp_dir}/episodic_memory.json"
        )
        question_store = QuestionMemoryStore(
            persist_path=f"{temp_dir}/question_memory.json"
        )
        short_term = ShortTermMemory(max_turns=20)

        # LongTermMemory（需要 ChromaDB）
        long_term = None
        try:
            long_term = LongTermMemory(
                persist_dir=f"{temp_dir}/chroma_db",
                collection_name="eval_temp",
            )
        except Exception as e:
            print(f"警告: LongTermMemory 初始化失败: {e}")
            print("将继续运行，但长期记忆评测可能受影响")

        # AI Provider
        if args.mock:
            from unittest.mock import Mock, AsyncMock

            ai_provider = Mock()
            ai_provider.chat = AsyncMock(
                return_value=Mock(content="Mock response")
            )
        else:
            ai_provider = AIProviderFactory.create(config.ai)

        # MemoryWriter & MemoryUpdater
        memory_writer = MemoryWriter(ai_provider=ai_provider)
        memory_updater = MemoryUpdater(semantic_store=semantic_store)

        # MemoryManager
        memory_manager = MemoryManager(
            short_term=short_term,
            long_term=long_term,
            semantic_store=semantic_store,
            episodic_store=episodic_store,
            question_store=question_store,
            memory_writer=memory_writer,
            memory_updater=memory_updater,
            window_size=config.memory.short_term.window_size,
            wiki_dir=str(config.app.data_dir) + "/wiki",
            ai_provider=ai_provider,
            features=getattr(config.memory, "features", {}),
        )

        # 运行评测
        runner = EvaluationRunner(
            memory_manager=memory_manager,
            ai_provider=ai_provider,
        )

        print("\n开始评测...")
        report = await runner.run_all(
            dataset_names=args.dataset,
            use_mock=args.mock,
        )

        # 输出报告
        print("\n" + "=" * 60)
        print("评测报告")
        print("=" * 60)
        print(f"总分: {report['overall']:.2%}")
        print(f"时间: {report['timestamp']}")

        scores = report["scores"]
        if "preference_recall" in scores:
            print(f"\n偏好召回: {scores['preference_recall']:.2%}")
        if "episodic_recall" in scores:
            print(f"事件回忆: {scores['episodic_recall']:.2%}")
        if "knowledge_update" in scores:
            print(f"知识更新: {scores['knowledge_update']:.2%}")
        if "temporal_reasoning" in scores:
            print(f"时间推理: {scores['temporal_reasoning']:.2%}")
        if "abstention_accuracy" in scores:
            print(f"拒答准确率: {scores['abstention_accuracy']:.2%}")

        # 保存报告
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\n报告已保存: {report_path}")

    finally:
        # 清理临时目录
        import shutil

        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
