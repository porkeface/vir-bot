"""chat_ws 模块单元测试"""
from __future__ import annotations

import json

from vir_bot.api.routers.chat_ws import ChatMessage, parse_message


def test_parse_text_message():
    """解析正常的文本消息"""
    raw = json.dumps({"type": "text", "content": "你好"})
    msg = parse_message(raw)
    assert msg is not None
    assert msg.type == "text"
    assert msg.content == "你好"
    assert msg.audio == ""
    assert msg.format == ""


def test_parse_interrupt_message():
    """解析中断消息"""
    raw = json.dumps({"type": "interrupt"})
    msg = parse_message(raw)
    assert msg is not None
    assert msg.type == "interrupt"
    assert msg.content == ""


def test_parse_invalid_json():
    """无效 JSON 返回 None"""
    assert parse_message("not json") is None
    assert parse_message("") is None
    assert parse_message("{broken") is None


def test_parse_missing_type():
    """缺少 type 字段返回 None"""
    assert parse_message(json.dumps({"content": "你好"})) is None
    assert parse_message(json.dumps({})) is None


def test_parse_voice_message():
    """解析语音消息（含 audio 和 format 字段）"""
    raw = json.dumps({"type": "voice", "audio": "base64data", "format": "wav"})
    msg = parse_message(raw)
    assert msg is not None
    assert msg.type == "voice"
    assert msg.audio == "base64data"
    assert msg.format == "wav"


def test_parse_type_not_string():
    """type 字段非字符串返回 None"""
    assert parse_message(json.dumps({"type": 123})) is None
    assert parse_message(json.dumps({"type": None})) is None


def test_parse_non_dict():
    """非字典 JSON 返回 None"""
    assert parse_message(json.dumps([1, 2, 3])) is None
    assert parse_message(json.dumps("just a string")) is None
