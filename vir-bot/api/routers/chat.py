"""对话测试 API（Web 控制台直接对话）"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from vir_bot.main import get_app_state, AppState
from vir_bot.core.pipeline import PlatformMessage, Platform, PlatformResponse

router = APIRouter()


class ChatRequest(BaseModel):
    content: str
    user_id: str = "web_user"
    user_name: str = "Web用户"


@router.post("/")
async def chat(req: ChatRequest, state: AppState = Depends(get_app_state)):
    if state.pipeline is None:
        return {"error": "Pipeline 未初始化"}

    msg = PlatformMessage(
        platform=Platform.API,
        msg_id="web_test",
        user_id=req.user_id,
        user_name=req.user_name,
        content=req.content,
    )
    response = await state.pipeline.process(msg)
    if response:
        return {"reply": response.content}
    return {"reply": "[无回复]"}