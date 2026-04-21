"""硬件控制模块（MQTT / ESP32 — 预留）"""
from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from typing import Callable

from vir_bot.utils.logger import logger


class MQTTClient(ABC):
    """MQTT 抽象接口"""

    @abstractmethod
    async def connect(self) -> None:
        ...

    @abstractmethod
    async def subscribe(self, topic: str, handler: Callable[[str, bytes], None]) -> None:
        ...

    @abstractmethod
    async def publish(self, topic: str, payload: str | bytes) -> None:
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        ...


class PahoMQTTClient(MQTTClient):
    """基于 paho-mqtt 的 MQTT 客户端"""

    def __init__(self, broker_url: str, username: str = "", password: str = ""):
        self.broker_url = broker_url
        self.username = username
        self.password = password
        self._client = None
        self._handlers: dict[str, list[Callable]] = {}

    async def connect(self) -> None:
        import paho.mqtt.client as mqtt

        # 解析 broker URL
        # mqtt://host:port -> (host, port)
        host_port = self.broker_url.replace("mqtt://", "")
        host, port = host_port.rsplit(":", 1) if ":" in host_port else (host_port, 1883)

        self._client = mqtt.Client()
        if self.username:
            self._client.username_pw_set(self.username, self.password)

        @self._client.on_connect
        def on_connect(client, userdata, flags, rc):
            logger.info(f"[MQTT] Connected, rc={rc}")
            for topic in self._handlers:
                client.subscribe(topic)

        @self._client.on_message
        def on_message(client, userdata, msg):
            for pattern, handlers in self._handlers.items():
                if _topic_match(pattern, msg.topic):
                    for h in handlers:
                        h(msg.topic, msg.payload)

        self._client.connect(host, int(port), 60)
        self._client.loop_start()

    async def subscribe(self, topic: str, handler: Callable[[str, bytes], None]) -> None:
        if topic not in self._handlers:
            self._handlers[topic] = []
        self._handlers[topic].append(handler)
        if self._client and self._client.is_connected():
            self._client.subscribe(topic)

    async def publish(self, topic: str, payload: str | bytes) -> None:
        if self._client and self._client.is_connected():
            self._client.publish(topic, payload)

    async def disconnect(self) -> None:
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()


def _topic_match(pattern: str, topic: str) -> bool:
    """简单的 MQTT 主题匹配（支持 # 和 +）"""
    if pattern == "#":
        return True
    pattern_parts = pattern.split("/")
    topic_parts = topic.split("/")
    for i, part in enumerate(pattern_parts):
        if part == "#":
            return True
        if i >= len(topic_parts):
            return False
        if part != "+" and part != topic_parts[i]:
            return False
    return len(pattern_parts) == len(topic_parts)


# ============================================================================
# ESP32 控制协议
# ============================================================================


class ESP32Controller:
    """
    ESP32 控制器。
    通过 MQTT 发送 MCP 指令控制硬件（舵机、LED、电机等）。
    """

    def __init__(self, mqtt: MQTTClient):
        self.mqtt = mqtt
        self._base_topic = "vir-bot/esp32"

    async def initialize(self) -> None:
        await self.mqtt.connect()
        # 订阅 ESP32 上报
        await self.mqtt.subscribe(f"{self._base_topic}/status/#", self._handle_status)

    async def control_servo(self, servo_id: int, angle: int) -> None:
        """控制舵机角度 (0-180)"""
        payload = json.dumps({"action": "servo", "id": servo_id, "angle": angle})
        await self.mqtt.publish(f"{self._base_topic}/control/servo", payload)
        logger.info(f"[ESP32] Servo {servo_id} -> {angle}°")

    async def set_led(self, led_id: int, color: str, brightness: int = 255) -> None:
        """控制 LED 颜色和亮度"""
        payload = json.dumps({"action": "led", "id": led_id, "color": color, "brightness": brightness})
        await self.mqtt.publish(f"{self._base_topic}/control/led", payload)
        logger.info(f"[ESP32] LED {led_id} = {color}")

    async def set_expression(self, expression: str) -> None:
        """设置表情（OLED 显示）"""
        payload = json.dumps({"action": "expression", "name": expression})
        await self.mqtt.publish(f"{self._base_topic}/control/expression", payload)
        logger.info(f"[ESP32] Expression: {expression}")

    async def get_status(self) -> dict:
        """获取 ESP32 状态"""
        # 发送查询请求并等待响应
        import asyncio

        result = {}

        async def handler(topic: str, payload: bytes):
            result.update(json.loads(payload))

        await self.mqtt.subscribe(f"{self._base_topic}/status/response", handler)
        await self.mqtt.publish(f"{self._base_topic}/control/query", "{}")

        try:
            await asyncio.wait_for(asyncio.sleep(2), timeout=5.0)
        except asyncio.TimeoutError:
            pass

        return result

    async def _handle_status(self, topic: str, payload: bytes) -> None:
        """处理 ESP32 状态上报"""
        try:
            data = json.loads(payload)
            logger.debug(f"[ESP32] Status: {data}")
        except Exception:
            pass

    async def shutdown(self) -> None:
        await self.mqtt.disconnect()


def create_hardware_module(config) -> ESP32Controller | None:
    """根据配置创建硬件控制模块"""
    if not config.hardware.enabled:
        return None
    mqtt = PahoMQTTClient(
        broker_url=config.hardware.mqtt.broker_url,
        username=config.hardware.mqtt.username,
        password=config.hardware.mqtt.password,
    )
    return ESP32Controller(mqtt)