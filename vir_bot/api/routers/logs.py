"""日志查看 API"""
from __future__ import annotations

import os
import re
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from vir_bot.config import get_config

router = APIRouter()


def _validate_log_filename(filename: str, log_dir: Path) -> Path | None:
    """校验日志文件名，防止路径遍历攻击。返回 None 表示校验通过，否则返回错误响应。"""
    # 1. 文件名必须只包含安全字符且以 .log 结尾
    if not re.match(r'^[\w\-\.]+\.log$', filename) or '..' in filename:
        return JSONResponse(status_code=400, content={"detail": "文件名无效"})
    # 2. 最终路径必须在 log_dir 内
    log_path = (log_dir / filename).resolve()
    if not log_path.is_relative_to(log_dir.resolve()):
        return JSONResponse(status_code=400, content={"detail": "文件名无效"})
    return log_path


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
    log_dir = Path(config.app.log_dir)
    # 校验文件名防止路径遍历
    validation_result = _validate_log_filename(filename, log_dir)
    if isinstance(validation_result, JSONResponse):
        return validation_result
    log_path = validation_result
    if not log_path.exists():
        raise HTTPException(status_code=404, detail="日志文件不存在")
    with open(log_path, encoding="utf-8") as f:
        all_lines = f.readlines()
    return {"lines": all_lines[-lines:], "total": len(all_lines)}


@router.get("/{filename}/download")
async def download_log(filename: str):
    config = get_config()
    log_dir = Path(config.app.log_dir)
    # 校验文件名防止路径遍历
    validation_result = _validate_log_filename(filename, log_dir)
    if isinstance(validation_result, JSONResponse):
        return validation_result
    log_path = validation_result
    if not log_path.exists():
        raise HTTPException(status_code=404, detail="日志文件不存在")
    return FileResponse(log_path, filename=filename, media_type="text/plain")