"""简单的主动消息测试 - 不依赖完整服务"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

# Mock 配置
class MockConfig:
    class ProactiveConfig:
        enabled = True
        check_interval_seconds = 5
        min_cooldown_seconds = 10
        max_daily_messages = 10
        class concern:
            threshold = 0.7
            llm_evaluate = False  # 关闭 LLM 评估，用规则
        class expression:
            max_context_memories = 3
            max_tokens = 200
        class targets:
            qq = {"user_id": "123", "group_id": ""}
            discord = {"channel_id": ""}
            wechat = {"touser": ""}
    proactive = ProactiveConfig()

class MockAI:
    """模拟 AI Provider"""
    model_name = "mock-model"
    
    async def chat(self, messages, system=None, **kwargs):
        class Response:
            content = "这都过去俩小时了，你那边还好吗？"
            model = "mock"
            usage = {}
            finish_reason = "stop"
            raw = {}
        return Response()

class MockMemory:
    pass

class MockCharacter:
    name = "测试角色"

async def test_proactive_flow():
    """测试主动消息流程"""
    print("=== 开始测试主动消息流程 ===\n")
    
    # 1. 创建组件
    from vir_bot.core.proactive.state_tracker import StateTracker, UserState
    from vir_bot.core.proactive.concern_engine import ConcernEngine
    from vir_bot.core.proactive.evaluator import ConcernEvaluator
    from vir_bot.core.proactive.expression import ExpressionLayer
    from vir_bot.core.proactive.rhythm_manager import RhythmManager
    
    mock_ai = MockAI()
    mock_memory = MockMemory()
    mock_char = MockCharacter()
    config = MockConfig.ProactiveConfig()
    
    # 2. 测试状态追踪器
    print("1. 测试状态追踪器...")
    tracker = StateTracker(mock_memory, mock_char)
    tracker.update_from_message("user1", "你好，我今天面试去了")
    state = tracker.get_state("user1")
    print(f"   ✓ 用户状态已更新，最后交互类型: {state.last_interaction_type}")
    print(f"   ✓ 最近话题: {state.recent_topics}")
    
    # 3. 测试节奏管理器
    print("\n2. 测试节奏管理器...")
    rhythm = RhythmManager(config)
    can_send, reason = rhythm.can_send("user1")
    print(f"   ✓ 是否可以发送: {can_send}, 原因: {reason}")
    
    # 4. 测试牵挂引擎（需要 mock AI 调用）
    print("\n3. 测试牵挂引擎...")
    with patch.object(mock_ai, 'chat', new_callable=AsyncMock) as mock_chat:
        mock_chat.return_value.content = "他之前说今天面试，现在应该结束了，不知道结果怎么样。"
        
        engine = ConcernEngine(mock_ai, mock_memory, mock_char, tracker, config)
        thought = await engine._generate_thought({
            "user_id": "user1",
            "seconds_since_last": 7200,  # 2小时
            "recent_topics": ["面试"],
            "daily_proactive_count": 0,
            "recent_memories": [
                {"content": "用户说今天要去面试", "score": 0.9, "type": "episodic"}
            ]
        })
        print(f"   ✓ 牵挂念头: {thought.content}")
    
    # 5. 测试表达引擎
    print("\n4. 测试表达引擎...")
    with patch.object(mock_ai, 'chat', new_callable=AsyncMock) as mock_chat:
        mock_chat.return_value.content = "面试结束啦？感觉怎么样呀~"

        expr = ExpressionLayer(mock_ai, mock_char, mock_memory)
        state = tracker.get_state("user1")
        message = await expr.generate_message(thought, "user1", state)
        print(f"   ✓ 生成消息: {message}")
    
    # 6. 测试完整流程（模拟）
    print("\n5. 测试完整流程...")
    tracker.update_proactive_sent("user1")
    print(f"   ✓ 主动消息已记录")
    stats = rhythm.get_stats("user1")
    print(f"   ✓ 统计信息: {stats}")
    
    print("\n=== 测试完成 ===")
    print("\n💡 要完整测试，请：")
    print("   1. 确保 ollama 正在运行（qwen2.5:7b）")
    print("   2. 修改 config.yaml: proactive.enabled: true")
    print("   3. 启动服务: uv run python -m vir_bot.main")
    print("   4. 调用 API: POST /api/proactive/send（手动触发）")

if __name__ == "__main__":
    asyncio.run(test_proactive_flow())
