"""
测试脚本：模拟应用程序的实际请求
"""

import asyncio
import json
import os
import sys
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))


async def test_vir_bot_request():
    """模拟 vir-bot 应用的实际 API 调用"""

    # 1. 加载配置
    print("=" * 70)
    print("步骤 1: 加载配置")
    print("=" * 70)

    from vir_bot.config import load_config

    config = load_config()

    api_key = os.environ.get("VIRBOT_OPENAI_KEY")
    if not api_key:
        print("❌ 错误: 环境变量 VIRBOT_OPENAI_KEY 未设置")
        return

    print(f"✓ Provider: {config.ai.provider}")
    print(f"✓ Base URL: {config.ai.openai.base_url}")
    print(f"✓ Model: {config.ai.openai.model}")
    print(f"✓ API Key: {api_key[:20]}...")

    # 2. 初始化记忆系统
    print("\n" + "=" * 70)
    print("步骤 2: 初始化记忆系统")
    print("=" * 70)

    from vir_bot.core.memory import LongTermMemory, MemoryManager, ShortTermMemory

    short_term = ShortTermMemory(max_turns=config.memory.short_term.max_turns)
    long_term = (
        LongTermMemory(
            persist_dir=config.memory.long_term.persist_dir,
            collection_name=config.memory.long_term.collection_name,
            embedding_model=config.memory.long_term.embedding_model,
            top_k=config.memory.long_term.top_k,
        )
        if config.memory.long_term.enabled
        else None
    )

    memory_manager = MemoryManager(
        short_term=short_term,
        long_term=long_term,
        window_size=config.memory.short_term.window_size,
    )

    print(f"✓ 短期记忆: max_turns={config.memory.short_term.max_turns}")
    print(f"✓ 长期记忆: enabled={config.memory.long_term.enabled}")
    print(f"✓ 窗口大小: {config.memory.short_term.window_size}")

    # 3. 初始化 MCP 工具注册表
    print("\n" + "=" * 70)
    print("步骤 3: 初始化 MCP 工具")
    print("=" * 70)

    from vir_bot.core.mcp import ToolRegistry, register_builtin_tools

    mcp_registry = ToolRegistry()
    register_builtin_tools(mcp_registry, memory_manager, None)
    tools_schemas = mcp_registry.get_tools_schemas()

    print(f"✓ MCP 工具数量: {mcp_registry.count()}")
    if tools_schemas:
        print(f"✓ 工具 schemas: {len(tools_schemas)} 个")
        for tool in tools_schemas:
            print(f"    - {tool.get('name', 'unknown')}")

    # 3. 加载角色卡
    print("\n" + "=" * 70)
    print("步骤 4: 加载角色卡")
    print("=" * 70)

    from vir_bot.core.character import build_system_prompt, load_character_card

    character_card = load_character_card(config.character.card_path)
    print(f"✓ 角色卡: {character_card.name}")
    print(f"✓ 性格标签: {character_card.extensions.get('personality_tags', [])}")

    # 5. 构建系统提示词
    print("\n" + "=" * 70)
    print("步骤 5: 构建系统提示词")
    print("=" * 70)

    ext = character_card.extensions
    system_prompt = build_system_prompt(
        card=character_card,
        voice_style=ext.get("voice_style", ""),
        personality_tags=ext.get("personality_tags", []),
    )

    print(f"系统提示词 ({len(system_prompt)} 字符):")
    print(f"  {system_prompt[:200]}...")

    # 6. 构建对话上下文
    print("\n" + "=" * 70)
    print("步骤 6: 构建对话上下文")
    print("=" * 70)

    test_message = "你好，请自我介绍一下"
    # 先添加系统提示词
    conversation = [{"role": "system", "content": system_prompt}]
    # 再添加历史对话
    conversation.extend(memory_manager.get_context_messages())
    # 最后添加当前消息
    conversation.append({"role": "user", "content": test_message})

    print(f"对话消息数: {len(conversation)}")
    for i, msg in enumerate(conversation):
        print(f"  [{i}] {msg['role']}: {msg['content'][:50]}...")

    # 7. 构建 AI 请求体
    print("\n" + "=" * 70)
    print("步骤 7: 构建 AI 请求体")
    print("=" * 70)

    body = {
        "model": config.ai.openai.model,
        "messages": conversation,
        "stream": False,
    }
    if tools_schemas:
        body["tools"] = tools_schemas
        body["tool_choice"] = "auto"

    print(f"请求体:")
    print(json.dumps(body, indent=2, ensure_ascii=False))

    # 8. 发送请求
    print("\n" + "=" * 70)
    print("步骤 8: 发送请求到 DeepSeek API")
    print("=" * 70)

    import aiohttp

    url = f"{config.ai.openai.base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    print(f"URL: {url}")
    print(f"Headers: Authorization: Bearer {api_key[:20]}...")
    print(f"Body size: {len(json.dumps(body))} bytes")

    try:
        async with aiohttp.ClientSession() as session:
            print("\n⏳ 发送请求中...")
            async with session.post(
                url,
                json=body,
                headers=headers,
                timeout=aiohttp.ClientTimeout(config.ai.openai.timeout),
            ) as resp:
                print(f"\n📥 响应状态码: {resp.status}")
                text = await resp.text()

                try:
                    data = json.loads(text)
                    print(f"响应体:")
                    print(json.dumps(data, indent=2, ensure_ascii=False))

                    if resp.status == 200:
                        content = data["choices"][0]["message"]["content"]
                        print(f"\n✅ 成功!")
                        print(f"AI 回复: {content}")
                    else:
                        print(f"\n❌ API 返回错误")
                        if "error" in data:
                            error = data["error"]
                            print(f"错误信息: {error.get('message')}")
                            print(f"错误代码: {error.get('code')}")
                except json.JSONDecodeError:
                    print(f"❌ 响应不是 JSON 格式: {text[:500]}")

    except asyncio.TimeoutError:
        print(f"\n❌ 超时: 请求超过 {config.ai.openai.timeout} 秒")
    except Exception as e:
        print(f"\n❌ 异常: {type(e).__name__}: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    print("\n")
    print("█" * 70)
    print("█  vir-bot 实际请求模拟测试")
    print("█" * 70)
    print("\n")

    asyncio.run(test_vir_bot_request())
