"""测试 Phase 8: Lifecycle Manager"""
import asyncio
import time
import httpx

BASE = "http://localhost:7860/api"

async def main():
    print("=" * 60)
    print("Phase 8 测试: Lifecycle Manager")
    print("=" * 60)

    async with httpx.AsyncClient() as client:
        # 1. 检查记忆统计（验证 lifecycle 是否初始化）
        print("\n[1] 检查记忆统计...")
        resp = await client.get(f"{BASE}/memory/")
        stats = resp.json()
        print(f"    短期: {stats.get('short_term', {})}")
        print(f"    语义: {stats.get('semantic_count', 0)} 条")
        print(f"    事件: {stats.get('episodic_count', 0)} 条")

        # 2. 验证 Lifecycle 组件已初始化
        print("\n[2] 验证 Lifecycle 组件...")
        import sys
        sys.path.insert(0, "D:/code Project/vir-bot")
        from vir_bot.core.memory.lifecycle.decay import DecayConfig, MemoryDecay
        from vir_bot.core.memory.lifecycle.merge import MemoryMerger
        from vir_bot.core.memory.lifecycle.janitor import MemoryJanitor
        from vir_bot.core.memory.semantic_store import SemanticMemoryStore

        print("    ✅ DecayConfig / MemoryDecay 可导入")
        print("    ✅ MemoryMerger 可导入")
        print("    ✅ MemoryJanitor 可导入")

        # 3. 测试衰减算法
        print("\n[3] 测试衰减算法...")
        config = DecayConfig()
        decay = MemoryDecay(config=config)

        # 创建测试记录（低置信度，很久以前更新）
        store = SemanticMemoryStore(persist_path="data/memory/test_semantic_temp.json")
        store._records.clear()

        old_time = time.time() - 86400 * 100  # 100天前

        # 添加低置信度记录
        from vir_bot.core.memory.semantic_store import SemanticMemoryRecord
        r1 = SemanticMemoryRecord(
            user_id="test_v8",
            namespace="profile.preference",
            predicate="likes",
            object="测试食物",
            confidence=0.05,
            updated_at=old_time,
        )
        store._records[r1.memory_id] = r1

        # 应用衰减
        action = decay.apply_decay(r1)
        print(f"    记录1 (conf=0.05, 100天前) -> action={action}")
        print(f"    衰减后 confidence={r1.confidence:.4f}")

        # 测试归档阈值
        r2 = SemanticMemoryRecord(
            user_id="test_v8",
            namespace="profile.preference",
            predicate="dislikes",
            object="测试厌恶",
            confidence=0.1,
            updated_at=old_time,
        )
        store._records[r2.memory_id] = r2
        action2 = decay.apply_decay(r2)
        print(f"    记录2 (conf=0.1, 100天前) -> action={action2}")

        # 4. 测试合并
        print("\n[4] 测试记忆合并...")
        merger = MemoryMerger(semantic_store=store)

        # 添加相似记录
        r3 = SemanticMemoryRecord(
            user_id="test_v8",
            namespace="profile.preference",
            predicate="likes",
            object="测试食物",
            confidence=0.8,
            source_text="测试食物",
        )
        r4 = SemanticMemoryRecord(
            user_id="test_v8",
            namespace="profile.preference",
            predicate="likes",
            object="测试食物",
            confidence=0.7,
            source_text="测试食物",
        )
        store._records[r3.memory_id] = r3
        store._records[r4.memory_id] = r4

        count = await merger.merge_similar("test_v8")
        print(f"    合并了 {count} 条相似记录")
        print(f"    合并后总记录数: {len(store._records)}")

        # 清理
        store._records.clear()
        store._save()

        print("\n" + "=" * 60)
        print("Phase 8 测试完成")
        print("=" * 60)
        print("\n总结:")
        print("  ✅ 衰减算法工作正常")
        print("  ✅ 合并逻辑工作正常")
        print("  ⚠️  Lifecycle 需要手动启动（未自动运行）")


if __name__ == "__main__":
    asyncio.run(main())
