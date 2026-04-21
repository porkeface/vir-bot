"""MCP 工具管理 API"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from vir_bot.main import _get_app_state
from vir_bot.core.mcp import ToolCall

router = APIRouter()


class ToolCallRequest(BaseModel):
    name: str
    arguments: dict


@router.get("/")
async def list_tools():
    state = _get_app_state()
    if state.mcp_registry is None:
        return []
    tools = state.mcp_registry.list_tools()
    return [
        {
            "name": t.name,
            "description": t.description,
            "parameters": t.parameters,
            "is_async": t.is_async,
        }
        for t in tools
    ]


@router.post("/call")
async def call_tool(req: ToolCallRequest):
    state = _get_app_state()
    if state.mcp_registry is None:
        raise HTTPException(status_code=503, detail="MCP 系统未初始化")
    call = ToolCall(id="api_call", name=req.name, arguments=req.arguments)
    result = await state.mcp_registry.execute_tool_call(call)
    return {
        "success": result.success,
        "result": result.result,
        "error": result.error,
    }