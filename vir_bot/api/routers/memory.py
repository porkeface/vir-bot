"""记忆管理 API"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from vir_bot.main import _get_app_state

router = APIRouter()


@router.get("/")
async def get_memory_stats():
    state = _get_app_state()
    if state.memory_manager is None:
        return {"short_term": 0, "long_term": 0, "semantic_count": 0}
    return await state.memory_manager.get_memory_stats()


@router.get("/recent")
async def get_recent_memory(limit: int = 10):
    state = _get_app_state()
    if state.memory_manager is None:
        return []
    entries = state.memory_manager.short_term.get_recent(limit)
    return [{"role": e.role, "content": e.content, "timestamp": e.timestamp} for e in entries]


@router.get("/search")
async def search_memory(query: str, top_k: int = 5):
    state = _get_app_state()
    if state.memory_manager is None:
        return []
    results = await state.memory_manager.search_long_term(query, top_k)
    return [{"id": r.id, "content": r.content, "metadata": r.metadata} for r in results]


@router.get("/semantic")
async def get_semantic_memory(user_id: str, namespace: str | None = None):
    state = _get_app_state()
    if state.memory_manager is None:
        return []

    namespaces = [namespace] if namespace else None
    records = state.memory_manager.list_semantic_memory(
        user_id=user_id,
        namespaces=namespaces,
    )
    return [
        {
            "memory_id": record.memory_id,
            "namespace": record.namespace,
            "predicate": record.predicate,
            "object": record.object,
            "confidence": record.confidence,
            "updated_at": record.updated_at,
            "source_text": record.source_text,
        }
        for record in records
    ]


@router.get("/semantic/search")
async def search_semantic_memory(query: str, user_id: str, top_k: int = 5):
    state = _get_app_state()
    if state.memory_manager is None:
        return []

    records = state.memory_manager.search_semantic_memory(
        user_id=user_id,
        query=query,
        top_k=top_k,
    )
    return [
        {
            "memory_id": record.memory_id,
            "namespace": record.namespace,
            "predicate": record.predicate,
            "object": record.object,
            "confidence": record.confidence,
            "updated_at": record.updated_at,
            "source_text": record.source_text,
        }
        for record in records
    ]


class AddMemoryRequest(BaseModel):
    content: str
    metadata: dict | None = None


@router.post("/")
async def add_memory(req: AddMemoryRequest):
    state = _get_app_state()
    if state.memory_manager is None:
        raise HTTPException(status_code=503, detail="记忆系统未初始化")
    if state.memory_manager.long_term:
        await state.memory_manager.long_term.add(req.content, req.metadata)
    return {"status": "ok"}


@router.delete("/")
async def clear_memory():
    state = _get_app_state()
    if state.memory_manager is None:
        raise HTTPException(status_code=503, detail="记忆系统未初始化")
    await state.memory_manager.clear_all()
    return {"status": "ok", "message": "所有记忆已清空"}
