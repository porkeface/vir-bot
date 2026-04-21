"""视觉感知模块（预留接口）"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from vir_bot.utils.logger import logger


class CameraProvider(ABC):
    """摄像头抽象接口"""

    @abstractmethod
    async def capture(self) -> bytes:
        """抓拍一帧，返回图片字节"""
        ...

    @abstractmethod
    async def start_stream(self):
        """启动持续流"""
        ...

    @abstractmethod
    async def stop_stream(self):
        """停止流"""
        ...


class ESP32CameraProvider(CameraProvider):
    """ESP32 硬件摄像头"""

    def __init__(self, url: str):
        self.url = url

    async def capture(self) -> bytes:
        import aiohttp
        async with aiohttp.ClientSession() as client:
            async with client.get(self.url, timeout=aiohttp.ClientTimeout(10)) as resp:
                return await resp.read()

    async def start_stream(self):
        logger.info(f"ESP32 camera stream started: {self.url}")

    async def stop_stream(self):
        pass


class CV2CameraProvider(CameraProvider):
    """本地 OpenCV 摄像头（开发/测试用）"""

    def __init__(self, device: int = 0):
        self.device = device
        self._cap = None

    async def capture(self) -> bytes:
        import cv2
        if self._cap is None:
            self._cap = cv2.VideoCapture(self.device)
        ret, frame = self._cap.read()
        if not ret:
            return b""
        _, png = cv2.imencode(".png", frame)
        return png.tobytes()

    async def start_stream(self):
        logger.info("CV2 camera stream started")

    async def stop_stream(self):
        if self._cap:
            self._cap.release()


class VisionLLMProvider(ABC):
    """视觉 LLM 描述器"""

    @abstractmethod
    async def describe(self, image_bytes: bytes, query: str = "描述这张图片") -> str:
        """用视觉 LLM 描述图片"""
        ...


class OpenAIVisionProvider(VisionLLMProvider):
    """OpenAI 风格视觉 API（Qwen-VL / GPT-4V 等）"""

    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url
        self.api_key = api_key
        self.model = model

    async def describe(self, image_bytes: bytes, query: str = "描述这张图片") -> str:
        import aiohttp
        import base64

        b64 = base64.b64encode(image_bytes).decode()
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": query},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    ],
                }
            ],
            "max_tokens": 512,
        }
        async with aiohttp.ClientSession() as client:
            async with client.post(
                f"{self.base_url}/chat/completions", json=payload, headers=headers
            ) as resp:
                data = await resp.json()
                return data["choices"][0]["message"]["content"]


class VisualModule:
    """视觉模块：整合摄像头 + 视觉 LLM"""

    def __init__(self, camera: CameraProvider, vision_llm: VisionLLMProvider):
        self.camera = camera
        self.vision_llm = vision_llm
        self._stream_task = None

    async def capture_and_describe(self, query: str = "描述这张图片") -> str:
        """抓拍 + 描述"""
        img_bytes = await self.camera.capture()
        if not img_bytes:
            return "[无法获取图像]"
        return await self.vision_llm.describe(img_bytes, query)

    async def start_auto_capture(self, interval: int = 10):
        """启动自动抓拍（定时描述）"""
        import asyncio

        async def loop():
            while True:
                try:
                    desc = await self.capture_and_describe()
                    logger.debug(f"[Visual] 自动抓拍: {desc[:100]}")
                except Exception as e:
                    logger.error(f"[Visual] 自动抓拍失败: {e}")
                await asyncio.sleep(interval)

        self._stream_task = asyncio.create_task(loop())

    async def stop(self):
        if self._stream_task:
            self._stream_task.cancel()


def create_visual_module(config) -> VisualModule | None:
    """根据配置创建视觉模块"""
    if not config.enabled:
        return None

    # 摄像头
    if config.camera.provider == "esp32":
        camera = ESP32CameraProvider(config.camera.esp32_url)
    elif config.camera.provider == "cv2":
        camera = CV2CameraProvider()
    else:
        camera = None

    if not camera:
        return None

    # 视觉 LLM
    if config.vision.provider == "openai":
        vision = OpenAIVisionProvider(
            base_url=config.vision.base_url,
            api_key="",  # 从环境变量读取
            model=config.vision.model,
        )
    else:
        vision = None

    if not vision:
        return None

    return VisualModule(camera, vision)