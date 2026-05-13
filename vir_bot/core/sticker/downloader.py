"""表情包下载器（用户收藏）"""
from __future__ import annotations

import hashlib
from pathlib import Path

from vir_bot.utils.logger import logger


class ExpressionDownloader:
    """表情包下载器：用户收藏"""

    def __init__(self, expressions_dir: Path):
        self.expressions_dir = expressions_dir

    async def save_user_upload(
        self,
        file_data: bytes,
        emotion: str,
        filename: str = "",
    ) -> Path | None:
        """保存用户上传的表情包"""
        try:
            # 确定文件扩展名
            if filename:
                ext = Path(filename).suffix.lower()
                if ext not in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
                    ext = ".png"
            else:
                # 根据文件头判断
                if file_data[:4] == b"GIF8":
                    ext = ".gif"
                elif file_data[:4] == b"\x89PNG":
                    ext = ".png"
                elif file_data[:2] == b"\xff\xd8":
                    ext = ".jpg"
                elif file_data[:4] == b"RIFF":
                    ext = ".webp"
                else:
                    ext = ".png"

            # 生成文件名
            hash_name = hashlib.md5(file_data).hexdigest()[:12]
            save_name = f"{hash_name}{ext}"

            # 保存
            emotion_dir = self.expressions_dir / emotion
            emotion_dir.mkdir(parents=True, exist_ok=True)
            filepath = emotion_dir / save_name

            filepath.write_bytes(file_data)
            logger.info(f"[表情收藏] 用户上传已保存: {filepath}")
            return filepath

        except Exception as e:
            logger.error(f"[表情收藏] 保存失败: {e}")
            return None
