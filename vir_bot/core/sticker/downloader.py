"""动态表情包下载器（Tenor API + 用户收藏）"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

import aiohttp

from vir_bot.utils.logger import logger


class ExpressionDownloader:
    """表情包下载器：在线搜索 + 用户收藏"""

    def __init__(self, expressions_dir: Path, tenor_api_key: str = ""):
        self.expressions_dir = expressions_dir
        self.tenor_api_key = tenor_api_key
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def search_and_download(
        self,
        keyword: str,
        emotion: str = "neutral",
        limit: int = 3,
    ) -> list[Path]:
        """从 Tenor 搜索并下载表情包"""
        if not self.tenor_api_key:
            logger.debug("[表情下载] Tenor API Key 未配置，跳过在线搜索")
            return []

        try:
            results = await self._search_tenor(keyword, limit)
            if not results:
                return []

            downloaded = []
            for url in results[:limit]:
                path = await self._download_image(url, emotion)
                if path:
                    downloaded.append(path)

            if downloaded:
                logger.info(f"[表情下载] 搜索 '{keyword}' 下载 {len(downloaded)} 张到 {emotion}/")
            return downloaded

        except Exception as e:
            logger.warning(f"[表情下载] 搜索失败: {e}")
            return []

    async def _search_tenor(self, keyword: str, limit: int = 3) -> list[str]:
        """调用 Tenor API 搜索表情包"""
        session = await self._get_session()
        url = "https://tenor.googleapis.com/v2/search"
        params = {
            "q": keyword,
            "key": self.tenor_api_key,
            "limit": limit,
            "media_filter": "gif,tinygif",
            "contentfilter": "medium",
        }

        try:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(10)) as resp:
                if resp.status != 200:
                    logger.warning(f"[表情下载] Tenor API 返回 {resp.status}")
                    return []
                data = await resp.json()
                results = data.get("results", [])
                # 优先取 gif 格式
                urls = []
                for r in results:
                    media_formats = r.get("media_formats", {})
                    gif = media_formats.get("gif", {})
                    if gif and gif.get("url"):
                        urls.append(gif["url"])
                    elif media_formats.get("tinygif", {}).get("url"):
                        urls.append(media_formats["tinygif"]["url"])
                return urls
        except Exception as e:
            logger.warning(f"[表情下载] Tenor 请求失败: {e}")
            return []

    async def _download_image(self, url: str, emotion: str) -> Path | None:
        """下载图片到本地"""
        session = await self._get_session()

        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(15)) as resp:
                if resp.status != 200:
                    return None

                content = await resp.read()
                if len(content) < 1000:  # 太小的文件跳过
                    return None

                # 确定文件扩展名
                content_type = resp.headers.get("content-type", "")
                if "gif" in content_type:
                    ext = ".gif"
                elif "webp" in content_type:
                    ext = ".webp"
                else:
                    ext = ".png"

                # 生成唯一文件名
                hash_name = hashlib.md5(content).hexdigest()[:12]
                filename = f"{hash_name}{ext}"

                # 保存到对应情绪文件夹
                emotion_dir = self.expressions_dir / emotion
                emotion_dir.mkdir(parents=True, exist_ok=True)
                filepath = emotion_dir / filename

                # 如果已存在就跳过
                if filepath.exists():
                    return filepath

                filepath.write_bytes(content)
                logger.debug(f"[表情下载] 已保存: {filepath.name}")
                return filepath

        except Exception as e:
            logger.warning(f"[表情下载] 下载失败: {e}")
            return None

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