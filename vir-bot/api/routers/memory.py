"""记忆管理 API"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from vir_bot.main import get_app_state, AppState

router = APIRouter()


def get_memory_manager(state: AppState = Depends(get_app_state)):
    return state.memory_manager


@router.get("/")
async def get_memory_stats(state: AppState = Depends(get_app_state)):
    if state.memory_manager is None:
        return {"short_term": 0, "long_term": 0}
    return {
        "short_term": state.memory_manager.short_term_count,
        "long_term": await state.memory_manager.long_term_count(),
    }


@router.get("/recent")
async def get_recent_memory(limit: int = 10, state: AppState = Depends(get_app_state)):
    if state.memory_manager is None:
        return []
    entries = state.memory_manager.short_term.get_recent(limit)
    return [{"role": e.role, "content": e.content, "timestamp": e.timestamp} for e in entries]


@router.get("/search")
async def search_memory(query: str, top_k: int = 5, state: AppState = Depends(get_app_state)):
    if state.memory_manager is None:
        return []
    results = await state.memory_manager.search_long_term(query, top_k)
    return [{"id": r.id, "content": r.content, "metadata": r.metadata} for r in results]


class AddMemoryRequest(BaseModel):
    content: str
    metadata: dict | None = None


@router.post("/")
async def add_memory(req: AddMemoryRequest, state: AppState = Depends(get_app_state)):
    if state.memory_manager is None:
        raise HTTPException(status_code=503, detail="记忆系统未初始化")
    if state.memory_manager.long_term:
        await state.memory_manager.long_term.add(req.content, req.metadata)
    return {"status": "ok"}


@router.delete("/")
async def clear_memory(state: AppState = Depends(get_app_state)):
    if state.memory_manager is None:
        raise HTTPException(status_code=503, detail="记忆系统未初始化")
    await state.memory_manager.clear_all()
    return {"status": "ok", "message": "所有记忆已清空"}