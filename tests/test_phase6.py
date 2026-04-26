"""测试 Phase 6: 版本支持 & Feedback Handler"""
import asyncio
import httpx
import json

BASE = "http://localhost:7860/api"

async def chat(content, user_id="test_v6"):
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{BASE}/chat/", json={"content": content, "user_id": user_id}, timeout=60.0)
        r.raise_for_status()
        return r.json()["reply"]

async def get_memory(user_id="test_v6"):
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{BASE}/memory/semantic", params={"user_id": user_id})
        return r.json()

async def get_stats():
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{BASE}/memory/stats")
        return r.json()

async def clear():
    async with httpx.AsyncClient() as c:
        await c.delete(f"{BASE}/memory/")

async def main():
    print("=" * 60)
    print("Phase 6 测试: 版本支持 & Feedback Handler")
    print("=" * 60)

    # 清空记忆
    await clear()
    print("\n[1] 清空记忆完成")

    # 教 AI：我叫张三，最喜欢火锅
    print("\n[2] 教 AI: '我叫张三，最喜欢火锅'")
    reply = await chat("我叫张三，最喜欢火锅", user_id="test_v6")
    print(f"    AI: {reply[:80]}...")
    await asyncio.sleep(1)

    # 查看记忆
    records = await get_memory("test_v6")
    print(f"\n[3] 记忆数: {len(records)}")
    for r in records:
        print(f"    {r['predicate']}: {r['object']} (conf={r['confidence']:.2f}, active={r.get('is_active', True)})")

    # 查询验证
    print("\n[4] 查询: '我叫什么？'")
    reply = await chat("我叫什么名字？", user_id="test_v6")
    print(f"    AI: {reply[:80]}...")
    assert "张三" in reply, "期望包含'张三'"

    print("\n[5] 查询: '我喜欢吃什么？'")
    reply = await chat("我喜欢吃什么？", user_id="test_v6")
    print(f"    AI: {reply[:80]}...")
    assert "火锅" in reply, "期望包含'火锅'"

    # 纠正：我不叫张三，我叫李四
    print("\n[6] 纠正: '我不叫张三，我叫李四'")
    reply = await chat("我不叫张三，我叫李四", user_id="test_v6")
    print(f"    AI: {reply[:80]}...")
    await asyncio.sleep(1)

    # 查看纠正后的记忆
    records = await get_memory("test_v6")
    print(f"\n[7] 纠正后记忆数: {len(records)}")
    for r in records:
        print(f"    {r['predicate']}: {r['object']} (conf={r['confidence']:.2f}, active={r.get('is_active', True)})")

    # 验证查询
    print("\n[8] 查询: '我叫什么名字？'（应回答李四）")
    reply = await chat("我叫什么名字？", user_id="test_v6")
    print(f"    AI: {reply[:80]}...")
    # 注意：由于 versioning 逻辑，可能两条记录都 active

    # 检查语义记忆文件中的版本链
    print("\n[9] 检查版本链...")
    import sys
    sys.path.insert(0, "D:/code Project/vir-bot")
    from vir_bot.core.memory.semantic_store import SemanticMemoryStore
    store = SemanticMemoryStore(persist_path="data/memory/semantic_memory.json")

    name_records = [r for r in store._records.values() if r.user_id == "test_v6" and r.predicate == "name_is"]
    print(f"    name_is 记录数: {len(name_records)}")
    for r in name_records:
        print(f"      {r.object} (v{r.version_number}, active={r.is_active}, valid_from={r.valid_from})")
        if r.previous_version_id:
            print(f"      -> 上一版本: {r.previous_version_id[:8]}...")

    print("\n" + "=" * 60)
    print("Phase 6 测试完成")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
