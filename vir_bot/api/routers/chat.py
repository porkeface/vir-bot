"""对话测试 API（Web 控制台直接对话）"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from vir_bot.core.pipeline import PlatformMessage, Platform, PlatformResponse
from vir_bot.main import _get_app_state

router = APIRouter()


class ChatRequest(BaseModel):
    content: str
    user_id: str = "web_user"
    user_name: str = "Web用户"


@router.post("/")
async def chat(req: ChatRequest):
    app_state = _get_app_state()
    if app_state.pipeline is None:
        return {"error": "Pipeline 未初始化, app_state_id=" + str(id(app_state))}

    msg = PlatformMessage(
        platform=Platform.API,
        msg_id="web_test",
        user_id=req.user_id,
        user_name=req.user_name,
        content=req.content,
    )
    response = await app_state.pipeline.process(msg)
    if response:
        return {"reply": response.content}
    return {"reply": "[无回复]"}