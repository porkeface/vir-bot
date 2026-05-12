"""消息拆分器：将长回复按自然边界拆分为多条短消息"""

from __future__ import annotations

import re
import random
from dataclasses import dataclass

from vir_bot.utils.logger import logger


@dataclass
class SplitConfig:
    enabled: bool = True
    max_chunk_chars: int = 120
    min_chunk_chars: int = 10
    delay_min_ms: int = 500
    delay_max_ms: int = 2000


def split_message(text: str, config: SplitConfig | None = None) -> list[str]:
    """将一段文本拆分为多条自然的短消息。

    拆分优先级：
    1. 双换行（段落分隔）
    2. 单换行
    3. 句末标点（。！？…；~）
    4. 逗号、分号等次级标点
    5. 强制按 max_chunk_chars 截断
    """
    if not config:
        config = SplitConfig()

    if not config.enabled:
        return [text] if text.strip() else []

    text = text.strip()
    if not text:
        return []

    # 清理多余的空行（Telegram 等平台双换行显示过大）
    text = re.sub(r'\n{2,}', '\n', text)

    # 如果已经够短，直接返回
    if len(text) <= config.max_chunk_chars:
        return [text]

    # 按段落拆分（双换行）
    paragraphs = re.split(r'\n{2,}', text)
    if len(paragraphs) > 1:
        result = []
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            if len(para) <= config.max_chunk_chars:
                result.append(para)
            else:
                result.extend(_split_long_text(para, config.max_chunk_chars))
        return _merge_short_chunks(result, config.min_chunk_chars, config.max_chunk_chars)

    # 按单换行拆分
    lines = text.split('\n')
    if len(lines) > 1:
        result = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if len(line) <= config.max_chunk_chars:
                result.append(line)
            else:
                result.extend(_split_long_text(line, config.max_chunk_chars))
        return _merge_short_chunks(result, config.min_chunk_chars, config.max_chunk_chars)

    # 没有换行，按句子拆分
    return _merge_short_chunks(
        _split_long_text(text, config.max_chunk_chars),
        config.min_chunk_chars,
        config.max_chunk_chars,
    )


def get_split_delay_ms(config: SplitConfig | None = None) -> int:
    """获取拆分消息之间的随机延迟（毫秒）"""
    if not config:
        config = SplitConfig()
    return random.randint(config.delay_min_ms, config.delay_max_ms)


def _split_long_text(text: str, max_chars: int) -> list[str]:
    """按句子/标点拆分长文本"""
    if len(text) <= max_chars:
        return [text]

    # 按中文句末标点拆分
    parts = re.split(r'([。！？…；~]+)', text)
    # re.split 会保留分隔符，需要合并回去
    merged = []
    i = 0
    while i < len(parts):
        chunk = parts[i]
        # 如果下一个是分隔符，合并
        if i + 1 < len(parts) and re.match(r'^[。！？…；~]+$', parts[i + 1]):
            chunk += parts[i + 1]
            i += 2
        else:
            i += 1
        if chunk.strip():
            merged.append(chunk.strip())

    # 合并短块、拆分超长块
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

    # 对仍然超长的块进一步拆分
    final = []
    for chunk in result:
        if len(chunk) <= max_chars:
            final.append(chunk)
        else:
            final.extend(_split_at_commas(chunk, max_chars))

    return final


def _split_at_commas(text: str, max_chars: int) -> list[str]:
    """按逗号等次级标点拆分"""
    if len(text) <= max_chars:
        return [text]

    # 按逗号、顿号拆分
    parts = re.split(r'([，,、；;]+)', text)
    merged = []
    i = 0
    while i < len(parts):
        chunk = parts[i]
        if i + 1 < len(parts) and re.match(r'^[，,、；;]+$', parts[i + 1]):
            chunk += parts[i + 1]
            i += 2
        else:
            i += 1
        if chunk.strip():
            merged.append(chunk.strip())

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

    # 兜底：强制截断
    final = []
    for chunk in result:
        if len(chunk) <= max_chars:
            final.append(chunk)
        else:
            final.extend(_force_split(chunk, max_chars))

    return final


def _force_split(text: str, max_chars: int) -> list[str]:
    """强制按字符数截断"""
    chunks = []
    while text:
        if len(text) <= max_chars:
            chunks.append(text)
            break
        cut = max_chars
        # 往前找标点或空格作为断点
        for i in range(min(max_chars - 1, len(text) - 1), max(max_chars - 30, 0), -1):
            if text[i] in '，。！？…；~,.!? \n':
                cut = i + 1
                break
        chunks.append(text[:cut])
        text = text[cut:]
    return chunks


def _merge_short_chunks(chunks: list[str], min_chars: int, max_chars: int) -> list[str]:
    """合并过短的块"""
    if not chunks:
        return chunks

    merged = []
    buffer = ""

    for chunk in chunks:
        if buffer and len(buffer) + len(chunk) + 1 > max_chars:
            merged.append(buffer)
            buffer = chunk
        else:
            buffer = (buffer + "\n" + chunk) if buffer else chunk

        if len(buffer) >= min_chars:
            merged.append(buffer)
            buffer = ""

    if buffer:
        if merged and len(merged[-1]) + len(buffer) + 1 <= max_chars:
            merged[-1] = merged[-1] + "\n" + buffer
        else:
            merged.append(buffer)

    return merged
