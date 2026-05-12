"""消息拆分器：将 AI 回复拆分为多条独立消息发送"""

from __future__ import annotations

import re
import random
from dataclasses import dataclass

from vir_bot.utils.logger import logger


@dataclass
class SplitConfig:
    enabled: bool = True
    max_chunk_chars: int = 200   # 安全阈值：单条超过此长度才强制拆
    delay_min_ms: int = 500
    delay_max_ms: int = 2000


def split_message(text: str, config: SplitConfig | None = None) -> list[str]:
    """将 AI 回复拆分为多条消息。

    设计思路：
    - AI 被引导用换行分隔每条消息（像发微信）
    - 每个非空行 = 一条独立消息
    - 只有单行超长时才按标点进一步拆分
    """
    if not config:
        config = SplitConfig()

    if not config.enabled:
        return [text] if text.strip() else []

    text = text.strip()
    if not text:
        return []

    # 按换行拆分，每行一条消息
    lines = [line.strip() for line in text.split('\n') if line.strip()]

    # 如果只有一行且超长，才按标点拆
    if len(lines) == 1 and len(lines[0]) > config.max_chunk_chars:
        return _split_long_line(lines[0], config.max_chunk_chars)

    # 过滤掉太短的碎片（单个标点等）
    result = [line for line in lines if len(line) > 1 or line in '。！？…~💕😊🎵']

    return result if result else [text]


def get_split_delay_ms(config: SplitConfig | None = None) -> int:
    """获取拆分消息之间的随机延迟（毫秒）"""
    if not config:
        config = SplitConfig()
    return random.randint(config.delay_min_ms, config.delay_max_ms)


def _split_long_line(text: str, max_chars: int) -> list[str]:
    """对单行超长文本按标点拆分"""
    # 按中文句末标点拆分
    parts = re.split(r'([。！？…；~]+)', text)
    merged = []
    i = 0
    while i < len(parts):
        chunk = parts[i]
        if i + 1 < len(parts) and re.match(r'^[。！？…；~]+$', parts[i + 1]):
            chunk += parts[i + 1]
            i += 2
        else:
            i += 1
        if chunk.strip():
            merged.append(chunk.strip())

    # 合并过短的块
    result = []
    buffer = ""
    for chunk in merged:
        if buffer and len(buffer) + len(chunk) > max_chars:
            result.append(buffer)
            buffer = chunk
        else:
            buffer = buffer + chunk if buffer else chunk
    if buffer:
        result.append(buffer)

    return result
