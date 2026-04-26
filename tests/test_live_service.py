"""测试运行中的 vir-bot 服务，验证各 Phase 功能。"""

import asyncio
import json
import time
import httpx


BASE_URL = "http://localhost:7860"


async def chat(content: str, user_id: str = "test_user") -> str:
    """发送聊天消息并获取回复。"""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{BASE_URL}/api/chat/",
            json={"content": content, "user_id": user_id},
            timeout=60.0,
        )
        resp.raise_for_status()
        return resp.json()["reply"]


async def get_memory_stats() -> dict:
    """获取记忆统计。"""
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{BASE_URL}/api/memory/")
        return resp.json()


async def get_semantic_memory(user_id: str) -> list:
    """获取语义记忆。"""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/api/memory/semantic",
            params={"user_id": user_id},
        )
        return resp.json()


async def search_semantic(query: str, user_id: str) -> list:
    """搜索语义记忆。"""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/api/memory/semantic/search",
            params={"query": query, "user_id": user_id},
        )
        return resp.json()


async def clear_memory():
    """清空所有记忆。"""
    async with httpx.AsyncClient() as client:
        resp = await client.delete(f"{BASE_URL}/api/memory/")
        return resp.json()


async def test_phase6_versioning():
    """测试 Phase 6: 版本支持 & Feedback Handler。"""
    print("\n" + "=" * 60)
    print("测试 Phase 6: 版本支持 & Feedback Handler")
    print("=" * 60)

    await clear_memory()
    await asyncio.sleep(0.5)

    # 1. 教 AI 一个事实
    print("\n[Step 1] 教 AI: '我叫张三，最喜欢火锅'")
    reply = await chat("我叫张三，最喜欢火锅", user_id="test_user")
    print(f"  AI 回复: {reply[:100]}")

    await asyncio.sleep(0.5)

    # 2. 验证记忆已写入
    print("\n[Step 2] 验证记忆写入...")
    records = await get_semantic_memory("test_user")
    print(f"  语义记忆数: {len(records)}")
    for r in records:
        print(f"  - {r['predicate']}: {r['object']} (confidence={r['confidence']:.2f})")

    # 3. 查询验证
    print("\n[Step 3] 查询: '我叫什么名字？'")
    reply = await chat("我叫什么名字？", user_id="test_user")
    print(f"  AI 回复: {reply[:100]}")
    assert "张三" in reply, f"期望回复包含'张三'，实际: {reply}"

    print("\n[Step 4] 查询: '我喜欢吃什么？'")
    reply = await chat("我喜欢吃什么？", user_id="test_user")
    print(f"  AI 回复: {reply[:100]}")
    assert "火锅" in reply, f"期望回复包含'火锅'，实际: {reply}"

    # 4. 纠正测试（Feedback Handler）
    print("\n[Step 5] 纠正: '我不叫张三，我叫李四'")
    reply = await chat("我不叫张三，我叫李四", user_id="test_user")
    print(f"  AI 回复: {reply[:100]}")

    await asyncio.sleep(0.5)

    # 5. 验证更新后的记忆
    print("\n[Step 6] 验证纠正后的记忆...")
    records = await get_semantic_memory("test_user")
    print(f"  语义记忆数: {len(records)}")
    for r in records:
        print(f"  - {r['predicate']}: {r['object']} (confidence={r['confidence']:.2f})")

    print("\n[Step 7] 查询: '我叫什么名字？'（应回答李四）")
    reply = await chat("我叫什么名字？", user_id="test_user")
    print(f"  AI 回复: {reply[:100]}")

    print("\n✅ Phase 6 测试完成")
    return True


async def test_phase5_quality_gate():
    """测试 Phase 5: Quality Gate & Verifier。"""
    print("\n" + "=" * 60)
    print("测试 Phase 5: Quality Gate & Verifier")
    print("=" * 60)

    # 测试低质量输入
    print("\n[Step 1] 测试模糊词拦截: '我最近好像喜欢吃什么来着...'")
    reply = await chat("我最近好像喜欢吃什么来着...", user_id="test_user2")
    print(f"  AI 回复: {reply[:100]}")

    print("\n[Step 2] 测试正常输入: '我来自北京'")
    reply = await chat("我来自北京", user_id="test_user2")
    print(f"  AI 回复: {reply[:100]}")

    await asyncio.sleep(0.5)

    records = await get_semantic_memory("test_user2")
    print(f"  语义记忆数: {len(records)}")
    for r in records:
        print(f"  - {r['predicate']}: {r['object']} (confidence={r['confidence']:.2f})")

    print("\n✅ Phase 5 测试完成")
    return True


async def test_basic_memory():
    """测试基础记忆功能。"""
    print("\n" + "=" * 60)
    print("测试基础记忆功能")
    print("=" * 60)

    stats = await get_memory_stats()
    print(f"\n记忆统计: {json.dumps(stats, ensure_ascii=False, indent=2)}")

    print("\n✅ 基础功能正常")
    return True


async def main():
    print("开始测试 vir-bot 服务...")
    print(f"服务地址: {BASE_URL}")

    try:
        # 基础测试
        await test_basic_memory()

        # Phase 6: 版本支持
        await test_phase6_versioning()

        # Phase 5: Quality Gate
        await test_phase5_quality_gate()

        print("\n" + "=" * 60)
        print("所有测试完成！")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
