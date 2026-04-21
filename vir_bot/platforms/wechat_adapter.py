"""微信平台适配器（预留：企业微信 / Hook）"""
from __future__ import annotations

from typing import AsyncIterator

from vir_bot.core.pipeline import Platform, PlatformMessage, PlatformResponse, MessageType
from vir_bot.platforms.base_adapter import PlatformAdapter
from vir_bot.utils.logger import logger


class WeChatAdapter(PlatformAdapter):
    """
    微信适配器（预留实现）。
    当前支持两种接入方式：
    1. 企业微信（wechat_work）：通过企业微信 API
    2. 个人微信 Hook：通过 Hook 捕获消息（需额外依赖）

    具体实现取决于你的接入方式。
    """

    @property
    def platform(self) -> Platform:
        return Platform.WECHAT

    async def connect(self) -> None:
        logger.warning("[WeChat] 适配器尚未实现，请配置 wechat.enabled: false 或实现具体逻辑")
        raise NotImplementedError("微信适配器需要根据你的接入方式实现")

    async def disconnect(self) -> None:
        pass

    async def _receive_loop(self):
        """占位，不实现"""
        if False:
            yield  # 使其成为生成器

    async def send_message(self, response: PlatformResponse) -> None:
        pass


class WeChatWorkAdapter(WeChatAdapter):
    """企业微信适配器（基础框架）"""

    def __init__(self, pipeline, config):
        super().__init__(pipeline, config)
        self.config = config.wechat_work

    async def connect(self) -> None:
        import aiohttp

        # 获取 access_token
        url = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
        params = {"corpid": self.config.corp_id, "corpsecret": self.config.corp_secret}
        async with aiohttp.ClientSession() as client:
            async with client.get(url, params=params) as resp:
                data = await resp.json()
                if data.get("errcode", 0) != 0:
                    logger.error(f"[WeChat] 获取 access_token 失败: {data}")
                    return
                self._access_token = data["access_token"]
                logger.info("[WeChat] 企业微信连接成功")

    async def disconnect(self) -> None:
        pass

    async def _receive_loop(self):
        # 企业微信使用回调模式，此处为占位
        logger.info("[WeChat] 请配置企业微信回调地址")
        while False:
            yield

    async def send_message(self, response: PlatformResponse) -> None:
        import aiohttp

        if not hasattr(self, "_access_token"):
            return

        url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={self._access_token}"
        payload = {
            "touser": response.msg_id,
            "msgtype": "text",
            "agentid": self.config.agent_id,
            "text": {"content": response.content},
        }
        async with aiohttp.ClientSession() as client:
            async with client.post(url, json=payload) as resp:
                data = await resp.json()
                if data.get("errcode", 0) != 0:
                    logger.error(f"[WeChat] 发送失败: {data}")