"""MCP 工具协议"""
from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from vir_bot.utils.logger import logger


@dataclass
class ToolDefinition:
    """工具定义（JSON Schema 格式）"""
    name: str
    description: str
    parameters: dict  # JSON Schema
    is_async: bool = False


@dataclass
class ToolCall:
    """一次工具调用"""
    id: str
    name: str
    arguments: dict


@dataclass
class ToolResult:
    """工具执行结果"""
    id: str
    success: bool
    result: str = ""
    error: str = ""


class Tool(ABC):
    """MCP 工具基类"""

    @property
    @abstractmethod
    def definition(self) -> ToolDefinition:
        """返回工具定义（用于注册到 AI）"""
        ...

    async def execute(self, arguments: dict) -> str:
        """执行工具，子类实现具体逻辑"""
        raise NotImplementedError


class ToolRegistry:
    """工具注册表：动态发现 + 管理 MCP 工具"""

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.definition.name] = tool
        logger.debug(f"工具已注册: {tool.definition.name}")

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[ToolDefinition]:
        return [t.definition for t in self._tools.values()]

    def get_tools_schemas(self) -> list[dict]:
        """返回 AI API 所需的 tools 格式（OpenAI style）"""
        return [
            {
                "type": "function",
                "function": {
                    "name": td.name,
                    "description": td.description,
                    "parameters": td.parameters,
                },
            }
            for td in self.list_tools()
        ]

    async def execute_tool_call(self, call: ToolCall) -> ToolResult:
        """执行一次工具调用"""
        tool = self.get(call.name)
        if not tool:
            return ToolResult(id=call.id, success=False, error=f"Unknown tool: {call.name}")

        try:
            result = await tool.execute(call.arguments)
            return ToolResult(id=call.id, success=True, result=result)
        except Exception as e:
            logger.error(f"工具执行失败 {call.name}: {e}")
            return ToolResult(id=call.id, success=False, error=str(e))

    async def execute_all(self, calls: list[ToolCall]) -> list[ToolResult]:
        """批量执行工具调用"""
        return [await self.execute_tool_call(c) for c in calls]

    def parse_tool_calls_from_response(self, response_content: str, available_tools: list[dict]) -> list[ToolCall]:
        """
        从 AI 响应文本中解析工具调用。
        支持两种格式：
        1. OpenAI tool_calls 结构
        2. 文本中的 ```tool_name {args} ``` 代码块
        """
        calls = []

        # 尝试从 JSON 代码块解析
        pattern = r"```(?:json)?\s*\{[^`]*?\}\s*```"
        for match in re.finditer(pattern, response_content, re.DOTALL):
            try:
                block = match.group(0)
                # 提取 JSON 部分
                json_str = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", block, re.DOTALL)
                if json_str:
                    data = json.loads(json_str.group(0))
                    if "tool" in data or "name" in data:
                        calls.append(
                            ToolCall(
                                id=data.get("id", f"call_{len(calls)}"),
                                name=data.get("tool", data.get("name", "")),
                                arguments=data.get("arguments", data.get("args", {})),
                            )
                        )
            except (json.JSONDecodeError, KeyError):
                continue

        return calls

    def count(self) -> int:
        return len(self._tools)


# =============================================================================
# 内置工具实现
# =============================================================================


class CalculatorTool(Tool):
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="calculator",
            description="计算数学表达式的值。使用标准数学运算符：+、-、*、/、**、%等。",
            parameters={
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "数学表达式，例如：2 + 2, 10 * 5, (3 + 4) * 2",
                    }
                },
                "required": ["expression"],
            },
        )

    async def execute(self, arguments: dict) -> str:
        expr = arguments.get("expression", "")
        # 安全计算（只允许数字和运算符）
        safe_expr = re.sub(r"[^0-9+\-*/().% ]", "", expr)
        try:
            result = eval(safe_expr, {"__builtins__": {}}, {})  # noqa: S307
            return str(result)
        except Exception as e:
            return f"计算错误: {e}"


class MemoryQueryTool(Tool):
    def __init__(self, memory_manager: Any):
        self._memory = memory_manager

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="memory.query",
            description="查询长期记忆中的相关内容。",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索查询词",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "返回数量，默认5",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        )

    async def execute(self, arguments: dict) -> str:
        query = arguments.get("query", "")
        top_k = arguments.get("top_k", 5)
        results = await self._memory.search_long_term(query, top_k)
        if not results:
            return "没有找到相关记忆"
        return "\n".join(f"- {r.content}" for r in results)


class MemoryForgetTool(Tool):
    def __init__(self, memory_manager: Any):
        self._memory = memory_manager

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="memory.forget",
            description="删除长期记忆中的一条记录。",
            parameters={
                "type": "object",
                "properties": {
                    "record_id": {
                        "type": "string",
                        "description": "要删除的记忆记录ID",
                    },
                },
                "required": ["record_id"],
            },
        )

    async def execute(self, arguments: dict) -> str:
        record_id = arguments.get("record_id", "")
        if not record_id:
            return "错误：未提供 record_id"
        if self._memory.long_term:
            await self._memory.long_term.delete(record_id)
        return f"已删除记忆: {record_id}"


class CharacterUpdateTool(Tool):
    def __init__(self, character_card: Any):
        self._card = character_card

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="character.update",
            description="更新角色卡的描述或设定。谨慎使用。",
            parameters={
                "type": "object",
                "properties": {
                    "field": {
                        "type": "string",
                        "description": "要更新的字段名",
                        "enum": ["description", "personality", "world_info", "scenario"],
                    },
                    "value": {
                        "type": "string",
                        "description": "新内容",
                    },
                },
                "required": ["field", "value"],
            },
        )

    async def execute(self, arguments: dict) -> str:
        field = arguments.get("field", "")
        value = arguments.get("value", "")
        if hasattr(self._card, field):
            setattr(self._card, field, value)
            return f"已更新 {field}"
        return f"未知字段: {field}"


# =============================================================================
# 内置工具注册
# =============================================================================


def register_builtin_tools(registry: ToolRegistry, memory_manager: Any, character_card: Any) -> None:
    """注册所有内置工具"""
    registry.register(CalculatorTool())
    registry.register(MemoryQueryTool(memory_manager))
    registry.register(MemoryForgetTool(memory_manager))
    registry.register(CharacterUpdateTool(character_card))
    logger.info(f"内置工具注册完成: {registry.count()} 个")