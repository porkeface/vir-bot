"""日志查看 API"""
from __future__ import annotations

import os
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from vir_bot.config import get_config

router = APIRouter()


@router.get("/")
async def list_log_files():
    config = get_config()
    log_dir = Path(config.app.log_dir)
    if not log_dir.exists():
        return []
    files = sorted(log_dir.glob("vir-bot-*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [
        {"name": f.name, "size": f.stat().st_size, "modified": f.stat().st_mtime}
        for f in files[:20]
    ]


@router.get("/{filename}")
async def read_log(filename: str, lines: int = 200):
    config = get_config()
    log_path = Path(config.app.log_dir) / filename
    if not log_path.exists():
        raise HTTPException(status_code=404, detail="日志文件不存在")
    with open(log_path, encoding="utf-8") as f:
        all_lines = f.readlines()
    return {"lines": all_lines[-lines:], "total": len(all_lines)}


@router.get("/{filename}/download")
async def download_log(filename: str):
    config = get_config()
    log_path = Path(config.app.log_dir) / filename
    if not log_path.exists():
        raise HTTPException(status_code=404, detail="日志文件不存在")
    return FileResponse(log_path, filename=filename, media_type="text/plain")