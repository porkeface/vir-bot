"""测试 StateTracker"""
import pytest
import time
from vir_bot.core.proactive.state_tracker import StateTracker, UserState


@pytest.fixture
def tracker():
    """创建测试用的 StateTracker"""
    # 模拟 memory_manager 和 character_card
    class FakeMemory:
        pass

    class FakeChar:
        name = "测试角色"

    return StateTracker(FakeMemory(), FakeChar())


class TestUserState:
    def test_default_state(self):
        state = UserState(user_id="test")
        assert state.user_id == "test"
        assert state.daily_message_count == 0
        assert state.last_interaction_ts == 0.0


class TestStateTracker:
    def test_get_state_creates_new(self, tracker):
        state = tracker.get_state("user1")
        assert state.user_id == "user1"

    def test_update_from_message(self, tracker):
        tracker.update_from_message("user1", "你好呀", direction="in")
        state = tracker.get_state("user1")
        assert state.last_interaction_type == "user_message"
        assert len(state.recent_topics) >= 0

    def test_can_send_proactive_cooldown(self, tracker):
        # 刚发送过，冷却时间未到
        tracker.update_proactive_sent("user1")
        can_send = tracker.can_send_proactive("user1", min_cooldown=3600, max_daily=10)
        assert can_send is False

    def test_can_send_proactive_daily_limit(self, tracker):
        state = tracker.get_state("user1")
        state.daily_message_count = 10
        from datetime import datetime
        state.last_message_date = datetime.now().strftime("%Y-%m-%d")
        can_send = tracker.can_send_proactive("user1", min_cooldown=0, max_daily=10)
        assert can_send is False
