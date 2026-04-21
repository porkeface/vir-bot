import asyncio
import json
import os

import aiohttp


async def test_deepseek():
    """直接测试 DeepSeek API 调用"""
    api_key = os.environ.get("VIRBOT_OPENAI_KEY")
    if not api_key:
        print("❌ 错误: 环境变量 VIRBOT_OPENAI_KEY 未设置")
        print("请先运行: $env:VIRBOT_OPENAI_KEY = 'sk-你的密钥'")
        return

    print(f"✓ API Key 已设置: {api_key[:20]}...")

    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    body = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {
                "role": "user",
                "content": "Hello, please introduce yourself briefly in one sentence.",
            },
        ],
        "stream": False,
        "temperature": 0.7,
        "max_tokens": 100,
    }

    print("\n📤 请求详情:")
    print(f"  URL: {url}")
    print(f"  Model: {body['model']}")
    print(f"  Messages: {len(body['messages'])} 条")
    for i, msg in enumerate(body["messages"]):
        print(f"    [{i}] {msg['role']}: {msg['content'][:50]}...")

    try:
        async with aiohttp.ClientSession() as session:
            print("\n⏳ 发送请求中...")
            async with session.post(
                url, json=body, headers=headers, timeout=aiohttp.ClientTimeout(60)
            ) as resp:
                print(f"\n📥 响应:")
                print(f"  状态码: {resp.status}")
                print(f"  Content-Type: {resp.headers.get('Content-Type')}")

                text = await resp.text()
                print(f"  响应体 ({len(text)} 字节):")

                try:
                    data = json.loads(text)
                    print(f"    {json.dumps(data, indent=4, ensure_ascii=False)}")

                    if resp.status == 200:
                        content = data["choices"][0]["message"]["content"]
                        print(f"\n✅ 成功!")
                        print(f"   AI 回复: {content}")
                    else:
                        print(f"\n❌ API 返回错误:")
                        if "error" in data:
                            error = data["error"]
                            print(f"   Code: {error.get('code')}")
                            print(f"   Message: {error.get('message')}")
                            print(f"   Type: {error.get('type')}")
                except json.JSONDecodeError:
                    print(f"    {text[:500]}")
                    print(f"\n❌ 响应不是 JSON 格式")

    except asyncio.TimeoutError:
        print(f"\n❌ 超时: 请求超过 60 秒")
    except Exception as e:
        print(f"\n❌ 异常: {type(e).__name__}: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    print("=" * 60)
    print("DeepSeek API 测试脚本")
    print("=" * 60)
    asyncio.run(test_deepseek())
