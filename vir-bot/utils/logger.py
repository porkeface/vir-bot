"""结构化日志配置"""
from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger as _logger

# 移除默认 handler
_logger.remove()


def setup_logger(
    level: str = "INFO",
    log_dir: str | Path = "./data/logs",
    rotation: str = "10 MB",
    retention: str = "7 days",
) -> type[logger]:
    """配置 loguru"""
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    # 控制台输出（带颜色）
    _logger.add(
        sys.stderr,
        level=level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        colorize=True,
    )

    # 文件输出
    _logger.add(
        log_path / "vir-bot-{time:YYYY-MM-DD}.log",
        level="DEBUG",
        rotation=rotation,
        retention=retention,
        encoding="utf-8",
        enqueue=True,
    )

    return _logger


logger = _logger