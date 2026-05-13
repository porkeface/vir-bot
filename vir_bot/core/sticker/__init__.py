"""表情包管理系统"""
from __future__ import annotations

import random
from pathlib import Path
from typing import Any

import yaml

from vir_bot.utils.logger import logger


class ExpressionManager:
    """角色表情管理器（文件夹 + metadata）"""

    def __init__(self, character_dir: str | Path):
        self.base_path = Path(character_dir) / "expressions"
        self.metadata: dict[str, dict[str, Any]] = {}
        self.emotions: dict[str, list[Path]] = {}
        self._loaded = False
        self._downloader = None

    @property
    def downloader(self):
        """延迟加载下载器"""
        if self._downloader is None:
            from vir_bot.core.sticker.downloader import ExpressionDownloader
            self._downloader = ExpressionDownloader(self.base_path)
        return self._downloader

    def load(self) -> None:
        """加载 metadata 和表情图片"""
        if not self.base_path.exists():
            logger.warning(f"[表情] 表情目录不存在: {self.base_path}")
            return

        # 加载 metadata.yaml
        meta_path = self.base_path / "metadata.yaml"
        if meta_path.exists():
            with open(meta_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
                self.metadata = data.get("expressions", {})
                logger.info(f"[表情] 加载 metadata: {len(self.metadata)} 种情绪")

        # 扫描文件夹
        valid_suffixes = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
        for emotion_dir in self.base_path.iterdir():
            if emotion_dir.is_dir():
                images = [
                    f for f in emotion_dir.iterdir()
                    if f.is_file() and f.suffix.lower() in valid_suffixes
                ]
                if images:
                    self.emotions[emotion_dir.name] = images
                    logger.debug(f"[表情] {emotion_dir.name}: {len(images)} 张")

        self._loaded = True
        logger.info(f"[表情] 加载完成: {len(self.emotions)} 种情绪, 共 {sum(len(v) for v in self.emotions.values())} 张")

    def detect_emotion(self, text: str) -> str | None:
        """从文本中检测情绪（基于 metadata 中的 tags）"""
        for emotion, config in self.metadata.items():
            tags = config.get("tags", [])
            for tag in tags:
                if tag in text:
                    return emotion
        return None

    def get_expression(self, emotion: str | None = None, text: str | None = None) -> Path | None:
        """获取表情图片路径（随机选择）- 同步版本"""
        if not self._loaded:
            self.load()

        # 从文本检测情绪
        if emotion is None and text:
            emotion = self.detect_emotion(text)

        # 默认用 neutral
        if emotion is None:
            emotion = "neutral"

        # 获取该情绪的图片列表
        images = self.emotions.get(emotion)
        if not images:
            images = self.emotions.get("neutral", [])
        if not images:
            logger.debug(f"[表情] 没有可用的表情图片: {emotion}")
            return None

        # 按权重决定是否降级到 neutral
        weight = self.metadata.get(emotion, {}).get("weight", 1)
        if weight < 1 and random.random() > weight:
            neutral_images = self.emotions.get("neutral", [])
            if neutral_images:
                images = neutral_images

        return random.choice(images)

    async def get_expression_async(
        self,
        emotion: str | None = None,
        text: str | None = None,
    ) -> Path | None:
        """获取表情图片路径 - 异步版本"""
        if not self._loaded:
            self.load()

        # 从文本检测情绪
        if emotion is None and text:
            emotion = self.detect_emotion(text)

        if emotion is None:
            emotion = "neutral"

        return self.get_expression(emotion=emotion)

    def _refresh_emotion(self, emotion: str) -> None:
        """刷新指定情绪的图片列表"""
        valid_suffixes = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
        emotion_dir = self.base_path / emotion
        if emotion_dir.exists():
            images = [
                f for f in emotion_dir.iterdir()
                if f.is_file() and f.suffix.lower() in valid_suffixes
            ]
            if images:
                self.emotions[emotion] = images

    async def save_user_expression(
        self,
        file_data: bytes,
        emotion: str,
        filename: str = "",
    ) -> Path | None:
        """保存用户上传的表情包"""
        path = await self.downloader.save_user_upload(file_data, emotion, filename)
        if path:
            self._refresh_emotion(emotion)
        return path

    async def close(self) -> None:
        """清理资源"""
        if self._downloader:
            await self._downloader.close()

    def get_available_emotions(self) -> list[str]:
        """获取所有可用的情绪类型"""
        return list(self.emotions.keys())

    def get_expression_count(self, emotion: str | None = None) -> int:
        """获取表情数量"""
        if emotion:
            return len(self.emotions.get(emotion, []))
        return sum(len(v) for v in self.emotions.values())
