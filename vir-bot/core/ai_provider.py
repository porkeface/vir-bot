"""AI Provider 策略模式：统一抽象 + 多后端实现"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, AsyncIterator

import aiohttp

if TYPE_CHECKING:
    from vir_bot.config import AIConfig


# =============================================================================
# 数据模型
# =============================================================================


@dataclass
class AIResponse:
    content: str
    model: str
    usage: dict = field(default_factory=dict)
    finish_reason: str = "stop"
    raw: dict = field(default_factory=dict)


@dataclass
class AIStreamChunk:
    delta: str
    finish_reason: str | None = None


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str


# =============================================================================
# 抽象基类
# =============================================================================


class AIProvider(ABC):
    """所有AI后端必须实现的接口"""

    def __init__(self, config: "AIConfig"):
        self.config = config

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        system: str | None = None,
        tools: list[dict] | None = None,
        stream: bool = False,
        **kwargs,
    ) -> AIResponse:
        """同步chat接口"""
        ...

    @abstractmethod
    async def chat_stream(
        self,
        messages: list[dict],
        system: str | None = None,
        tools: list[dict] | None = None,
        **kwargs,
    ) -> AsyncIterator[AIStreamChunk]:
        """流式chat接口"""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """健康检查"""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """返回当前模型名"""
        ...

    async def close(self) -> None:
        """清理资源，子类可重写"""
        pass


# =============================================================================
# Ollama 实现
# =============================================================================


class OllamaProvider(AIProvider):
    async def chat(
        self,
        messages: list[dict],
        system: str | None = None,
        tools: list[dict] | None = None,
        stream: bool = False,
        **kwargs,
    ) -> AIResponse:
        body = {
            "model": self.config.ollama.model,
            "messages": self._build_messages(messages, system),
            "stream": False,
            "options": {"temperature": 0.8, "num_predict": 4096, **kwargs},
        }
        if tools:
            body["tools"] = self._convert_tools(tools)

        async with aiohttp.ClientSession() as client:
            url = f"{self.config.ollama.base_url}/api/chat"
            async with client.post(url, json=body, timeout=aiohttp.ClientTimeout(self.config.ollama.timeout)) as resp:
                resp.raise_for_status()
                data = await resp.json()

        msg = data.get("message", {})
        return AIResponse(
            content=msg.get("content", ""),
            model=self.config.ollama.model,
            usage={"prompt_tokens": 0, "completion_tokens": 0},
            finish_reason=data.get("done_reason", "stop"),
            raw=data,
        )

    async def chat_stream(
        self,
        messages: list[dict],
        system: str | None = None,
        tools: list[dict] | None = None,
        **kwargs,
    ) -> AsyncIterator[AIStreamChunk]:
        body = {
            "model": self.config.ollama.model,
            "messages": self._build_messages(messages, system),
            "stream": True,
            "options": {"temperature": 0.8, **kwargs},
        }

        async with aiohttp.ClientSession() as client:
            url = f"{self.config.ollama.base_url}/api/chat"
            async with client.post(url, json=body, timeout=aiohttp.ClientTimeout(self.config.ollama.timeout)) as resp:
                resp.raise_for_status()
                async for line in resp.content:
                    if line:
                        chunk = json.loads(line)
                        msg = chunk.get("message", {})
                        yield AIStreamChunk(
                            delta=msg.get("content", ""),
                            finish_reason="stop" if chunk.get("done") else None,
                        )

    async def health_check(self) -> bool:
        try:
            async with aiohttp.ClientSession() as client:
                url = f"{self.config.ollama.base_url}/api/tags"
                async with client.get(url) as resp:
                    return resp.status == 200
        except Exception:
            return False

    @property
    def model_name(self) -> str:
        return self.config.ollama.model

    def _build_messages(self, messages: list[dict], system: str | None) -> list[dict]:
        result = []
        if system:
            result.append({"role": "system", "content": system})
        result.extend(messages)
        return result

    def _convert_tools(self, tools: list[dict]) -> list[dict]:
        """将标准工具格式转换为 Ollama 格式"""
        return tools


# =============================================================================
# OpenAI 兼容 API 实现（Qwen / DeepSeek 等）
# =============================================================================


class OpenAIProvider(AIProvider):
    def __init__(self, config: "AIConfig"):
        super().__init__(config)
        self._client: aiohttp.ClientSession | None = None

    async def _get_client(self) -> aiohttp.ClientSession:
        if self._client is None or self._client.closed:
            self._client = aiohttp.ClientSession()
        return self._client

    async def chat(
        self,
        messages: list[dict],
        system: str | None = None,
        tools: list[dict] | None = None,
        stream: bool = False,
        **kwargs,
    ) -> AIResponse:
        client = await self._get_client()
        all_messages = self._build_messages(messages, system)
        body: dict = {
            "model": self.config.openai.model,
            "messages": all_messages,
            "stream": False,
            **kwargs,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        headers = self._build_headers()
        url = f"{self.config.openai.base_url}/chat/completions"

        for attempt in range(self.config.openai.max_retries):
            try:
                async with client.post(
                    url, json=body, headers=headers, timeout=aiohttp.ClientTimeout(self.config.openai.timeout)
                ) as resp:
                    if resp.status == 429 and attempt < self.config.openai.max_retries - 1:
                        import asyncio

                        await asyncio.sleep(2 ** attempt)
                        continue
                    resp.raise_for_status()
                    data = await resp.json()
                    break
            except aiohttp.ClientError as e:
                if attempt == self.config.openai.max_retries - 1:
                    raise

        choice = data["choices"][0]
        msg = choice["message"]

        return AIResponse(
            content=msg.get("content", ""),
            model=self.config.openai.model,
            usage=data.get("usage", {}),
            finish_reason=choice.get("finish_reason", "stop"),
            raw=data,
        )

    async def chat_stream(
        self,
        messages: list[dict],
        system: str | None = None,
        tools: list[dict] | None = None,
        **kwargs,
    ) -> AsyncIterator[AIStreamChunk]:
        client = await self._get_client()
        all_messages = self._build_messages(messages, system)
        body: dict = {
            "model": self.config.openai.model,
            "messages": all_messages,
            "stream": True,
            **kwargs,
        }
        if tools:
            body["tools"] = tools

        headers = self._build_headers()
        url = f"{self.config.openai.base_url}/chat/completions"

        async with client.post(url, json=body, headers=headers, timeout=aiohttp.ClientTimeout(self.config.openai.timeout)) as resp:
            resp.raise_for_status()
            async for line in resp.content:
                if line:
                    line = line.decode("utf-8").strip()
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            yield AIStreamChunk(delta="", finish_reason="stop")
                            return
                        try:
                            data = json.loads(data_str)
                            delta = data["choices"][0]["delta"]
                            content = delta.get("content", "")
                            finish = data["choices"][0].get("finish_reason")
                            yield AIStreamChunk(delta=content, finish_reason=finish)
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue

    async def health_check(self) -> bool:
        try:
            client = await self._get_client()
            headers = self._build_headers()
            url = f"{self.config.openai.base_url}/models"
            async with client.get(url, headers=headers) as resp:
                return resp.status == 200
        except Exception:
            return False

    @property
    def model_name(self) -> str:
        return self.config.openai.model

    def _build_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.openai.api_key}",
            "Content-Type": "application/json",
        }

    def _build_messages(self, messages: list[dict], system: str | None) -> list[dict]:
        result = []
        if system:
            result.append({"role": "system", "content": system})
        result.extend(messages)
        return result


# =============================================================================
# 本地模型文件实现（llama.cpp server / vLLM 等）
# =============================================================================


class LocalModelProvider(AIProvider):
    async def chat(
        self,
        messages: list[dict],
        system: str | None = None,
        tools: list[dict] | None = None,
        stream: bool = False,
        **kwargs,
    ) -> AIResponse:
        client = aiohttp.ClientSession()
        try:
            all_messages = []
            if system:
                all_messages.append({"role": "system", "content": system})
            all_messages.extend(messages)

            body: dict = {
                "messages": all_messages,
                "stream": False,
            }
            if tools:
                body["tools"] = tools

            url = f"{self.config.local_model.base_url}/v1/chat/completions"
            async with client.post(
                url, json=body, timeout=aiohttp.ClientTimeout(self.config.local_model.timeout)
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()

            choice = data["choices"][0]
            msg = choice["message"]
            return AIResponse(
                content=msg.get("content", ""),
                model=self.config.local_model.model,
                usage=data.get("usage", {}),
                finish_reason=choice.get("finish_reason", "stop"),
                raw=data,
            )
        finally:
            await client.close()

    async def chat_stream(
        self,
        messages: list[dict],
        system: str | None = None,
        tools: list[dict] | None = None,
        **kwargs,
    ) -> AsyncIterator[AIStreamChunk]:
        client = aiohttp.ClientSession()
        try:
            all_messages = []
            if system:
                all_messages.append({"role": "system", "content": system})
            all_messages.extend(messages)

            body: dict = {
                "messages": all_messages,
                "stream": True,
            }
            if tools:
                body["tools"] = tools

            url = f"{self.config.local_model.base_url}/v1/chat/completions"
            async with client.post(
                url, json=body, timeout=aiohttp.ClientTimeout(self.config.local_model.timeout)
            ) as resp:
                resp.raise_for_status()
                async for line in resp.content:
                    if line:
                        line_text = line.decode("utf-8").strip()
                        if line_text.startswith("data: "):
                            data_str = line_text[6:]
                            if data_str == "[DONE]":
                                yield AIStreamChunk(delta="", finish_reason="stop")
                                return
                            try:
                                data = json.loads(data_str)
                                delta = data["choices"][0]["delta"]
                                content = delta.get("content", "")
                                finish = data["choices"][0].get("finish_reason")
                                yield AIStreamChunk(delta=content, finish_reason=finish)
                            except (json.JSONDecodeError, KeyError, IndexError):
                                continue
        finally:
            await client.close()

    async def health_check(self) -> bool:
        try:
            async with aiohttp.ClientSession() as client:
                url = f"{self.config.local_model.base_url}/v1/models"
                async with client.get(url) as resp:
                    return resp.status == 200
        except Exception:
            return False

    @property
    def model_name(self) -> str:
        return self.config.local_model.model


# =============================================================================
# 策略工厂
# =============================================================================


class AIProviderFactory:
    _registry: dict[str, type[AIProvider]] = {
        "ollama": OllamaProvider,
        "openai": OpenAIProvider,
        "local_model": LocalModelProvider,
    }

    @classmethod
    def create(cls, config: "AIConfig") -> AIProvider:
        provider_cls = cls._registry.get(config.provider)
        if not provider_cls:
            raise ValueError(f"Unknown AI provider: {config.provider}. Available: {list(cls._registry.keys())}")
        return provider_cls(config)

    @classmethod
    def register(cls, name: str, cls_: type[AIProvider]) -> None:
        cls._registry[name] = cls_

    @classmethod
    def available_providers(cls) -> list[str]:
        return list(cls._registry.keys())