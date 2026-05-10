"""QQ 官方机器人适配器（QQ 开放平台）"""
from __future__ import annotations

import hmac
import hashlib
import json
import time
from typing import Any

import httpx

from vir_bot.core.pipeline import Platform, PlatformMessage, PlatformResponse, MessageType
from vir_bot.platforms.base_adapter import PlatformAdapter
from vir_bot.utils.logger import logger


class QQOfficialAdapter(PlatformAdapter):
    """QQ 官方机器人适配器（OpenAPI v2）"""

    def __init__(self, pipeline, config):
        super().__init__(pipeline)
        self.config = config
        self._token: str | None = None
        self._token_expires: float = 0

    @property
    def platform(self) -> Platform:
        return Platform.QQ

    async def connect(self) -> None:
        logger.info(f"[QQ官方] 适配器已就绪，回调路径: {self.config.callback_path}")

    async def disconnect(self) -> None:
        pass

    async def _receive_loop(self):
        """官方机器人通过 HTTP 回调接收消息，不走此循环"""
        while False:
            yield

    async def send_message(self, response: PlatformResponse) -> None:
        """调用 QQ OpenAPI 发送消息"""
        token = await self._get_access_token()
        if not token:
            logger.error("[QQ官方] 无法获取 access_token，发送失败")
            return

        headers = {
            "Authorization": f"QQBot {token}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient() as client:
            # 根据目标类型选择 API 端点
            if response.metadata.get("group_openid"):
                url = f"https://api.sgroup.qq.com/v2/groups/{response.metadata['group_openid']}/messages"
                payload = {
                    "content": response.content,
                    "msg_type": 0,
                    "msg_id": response.metadata.get("msg_id", ""),
                }
            elif response.metadata.get("openid"):
                url = f"https://api.sgroup.qq.com/v2/users/{response.metadata['openid']}/messages"
                payload = {
                    "content": response.content,
                    "msg_type": 0,
                    "msg_id": response.metadata.get("msg_id", ""),
                }
            else:
                logger.warning("[QQ官方] 未指定发送目标（openid/group_openid）")
                return

            try:
                r = await client.post(url, headers=headers, json=payload, timeout=10)
                if r.status_code == 200:
                    logger.info(f"[QQ官方] 消息发送成功: {response.content[:50]}...")
                else:
                    logger.error(f"[QQ官方] 发送失败 {r.status_code}: {r.text}")
            except Exception as e:
                logger.error(f"[QQ官方] 发送异常: {e}")

    async def _get_access_token(self) -> str | None:
        """获取 access_token（带缓存）"""
        now = time.time()
        if self._token and now < self._token_expires:
            return self._token

        url = "https://bots.qq.com/app/getAppAccessToken"
        payload = {
            "appId": self.config.app_id,
            "clientSecret": self.config.app_secret,
        }

        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(url, json=payload, timeout=10)
                data = r.json()
                if r.status_code == 200 and "access_token" in data:
                    self._token = data["access_token"]
                    self._token_expires = now + data.get("expires_in", 7200) - 60
                    logger.debug("[QQ官方] access_token 已刷新")
                    return self._token
                else:
                    logger.error(f"[QQ官方] 获取 token 失败: {data}")
        except Exception as e:
            logger.error(f"[QQ官方] 获取 token 异常: {e}")

        return None

    @staticmethod
    def verify_signature(raw_body: bytes, signature: str, secret: str) -> bool:
        """验证 QQ 回调签名"""
        mac = hmac.HMAC(secret.encode(), raw_body, hashlib.sha256)
        expected = mac.hexdigest()
        return hmac.compare_digest(expected, signature)

    @staticmethod
    def _debug_signature(raw_body: bytes, secret: str) -> str:
        """计算签名用于调试"""
        mac = hmac.HMAC(secret.encode(), raw_body, hashlib.sha256)
        return mac.hexdigest()

    def parse_callback(self, body: dict) -> PlatformMessage | None:
        """解析 QQ 开放平台回调为 PlatformMessage"""
        try:
            t = body.get("t", "")
            if t != "MESSAGE_CREATE":
                return None

            data = body.get("d", {})
            content = data.get("content", "").strip()
            if not content:
                return None

            msg = PlatformMessage(
                platform=Platform.QQ,
                msg_id=data.get("id", ""),
                user_id=data.get("author", {}).get("id", ""),
                group_id=data.get("group_openid"),
                content=content,
                msg_type=MessageType.TEXT,
                raw_data=data,
                metadata={
                    "openid": data.get("author", {}).get("member_openid", ""),
                    "group_openid": data.get("group_openid", ""),
                    "msg_id": data.get("id", ""),
                },
            )
            return msg
        except Exception as e:
            logger.error(f"[QQ官方] 解析回调失败: {e}")
            return None
