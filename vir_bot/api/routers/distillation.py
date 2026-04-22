"""
Distillation web router

Provides endpoints to:
- upload chat export files
- start a distillation job (background)
- query job status and result
- download generated artifacts (markdown / json)
- websocket for realtime job updates

This is a lightweight implementation suitable for "方案二" (实时交互式界面).
Jobs are tracked in-memory and persisted as simple metadata JSON files under
data/distillation/jobs/ for basic survivability across restarts (best-effort).

Note: This module uses the application's `app_state` (from vir_bot.main) to access
AI provider and global config. It also uses the distillation pipeline via
`vir_bot.core.distillation.create_pipeline`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from vir_bot.config import get_config
from vir_bot.core.distillation import create_pipeline

# Access global app_state (initialized in vir_bot.main)
from vir_bot.main import app_state

logger = logging.getLogger(__name__)

router = APIRouter()

# Where to store uploads and job metadata relative to config.app.data_dir
_config = get_config()
DATA_DIR = Path(_config.app.data_dir)
CHAT_DIR = DATA_DIR / "chat_records"
JOBS_DIR = DATA_DIR / "distillation" / "jobs"
ARTIFACTS_DIR = DATA_DIR / "wiki" / "characters"

for d in (CHAT_DIR, JOBS_DIR, ARTIFACTS_DIR):
    os.makedirs(d, exist_ok=True)

# In-memory job store. Persist minimal metadata to disk per job.
JOBS: Dict[str, Dict[str, Any]] = {}


# -----------------------
# Pydantic models
# -----------------------
class UploadResp(BaseModel):
    file_id: str
    filename: str


class StartRequest(BaseModel):
    file_id: str
    name: str
    parser: Optional[str] = Field(
        default=None, description="force parser (generic/wechat/qq/discord)"
    )
    evaluate: bool = Field(default=False)
    dry_run: bool = Field(default=False)
    timeout: int = Field(default=120)


class StartResp(BaseModel):
    job_id: str


class JobStatusResp(BaseModel):
    job_id: str
    status: str
    progress: float
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    name: Optional[str] = None
    file_id: Optional[str] = None
    metrics: Optional[Dict[str, float]] = None
    error: Optional[str] = None


# -----------------------
# Helpers
# -----------------------
def _job_meta_path(job_id: str) -> Path:
    return JOBS_DIR / f"{job_id}.json"


def _save_job_meta(job_id: str) -> None:
    meta = JOBS.get(job_id)
    if not meta:
        return
    try:
        with _job_meta_path(job_id).open("w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    except Exception:
        logger.exception("Failed to persist job metadata for %s", job_id)


def _load_job_meta(job_id: str) -> Optional[Dict[str, Any]]:
    p = _job_meta_path(job_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Failed to load job metadata %s", job_id)
        return None


def _create_job_record(file_id: str, name: str) -> str:
    job_id = uuid4().hex
    now = datetime.utcnow().isoformat() + "Z"
    JOBS[job_id] = {
        "job_id": job_id,
        "file_id": file_id,
        "name": name,
        "status": "queued",
        "progress": 0.0,
        "logs": [],
        "created_at": now,
        "updated_at": now,
        "result": None,
        "markdown_path": None,
        "metrics": {},
        "error": None,
    }
    _save_job_meta(job_id)
    return job_id


def _append_log(job_id: str, msg: str) -> None:
    rec = JOBS.get(job_id)
    now = datetime.utcnow().isoformat() + "Z"
    entry = {"ts": now, "msg": msg}
    if rec is not None:
        rec.setdefault("logs", []).append(entry)
        rec["updated_at"] = now
        # keep logs bounded
        if len(rec["logs"]) > 2000:
            rec["logs"] = rec["logs"][-2000:]
        _save_job_meta(job_id)


def _set_progress(job_id: str, progress: float) -> None:
    rec = JOBS.get(job_id)
    if rec is None:
        return
    rec["progress"] = float(max(0.0, min(1.0, progress)))
    rec["updated_at"] = datetime.utcnow().isoformat() + "Z"
    _save_job_meta(job_id)


def _set_status(job_id: str, status: str) -> None:
    rec = JOBS.get(job_id)
    if rec is None:
        return
    rec["status"] = status
    rec["updated_at"] = datetime.utcnow().isoformat() + "Z"
    _save_job_meta(job_id)


def _set_result(job_id: str, result: Dict[str, Any], markdown_path: Optional[str] = None) -> None:
    rec = JOBS.get(job_id)
    if rec is None:
        return
    rec["result"] = result
    rec["markdown_path"] = markdown_path
    rec["metrics"] = result.get("metrics") if isinstance(result, dict) else {}
    rec["updated_at"] = datetime.utcnow().isoformat() + "Z"
    _save_job_meta(job_id)


def _set_error(job_id: str, err: str) -> None:
    rec = JOBS.get(job_id)
    if rec is None:
        return
    rec["status"] = "failed"
    rec["error"] = err
    rec["updated_at"] = datetime.utcnow().isoformat() + "Z"
    _save_job_meta(job_id)


# -----------------------
# Background job runner
# -----------------------
async def _run_distillation_job(
    job_id: str,
    input_path: str,
    name: str,
    parser: Optional[str],
    evaluate: bool,
    dry_run: bool,
    timeout: int,
) -> None:
    """
    Orchestrate the distillation pipeline in background, updating JOBS metadata.
    Progress heuristics:
        parse -> 0.15
        extract -> 0.60
        generate -> 0.85
        done -> 1.0
    """
    try:
        _set_status(job_id, "running")
        _set_progress(job_id, 0.05)
        _append_log(job_id, f"Job started: input={input_path} name={name}")

        # Create pipeline instance using global ai provider and config
        ai_provider = getattr(app_state, "ai_provider", None)
        cfg = getattr(app_state, "config", get_config())

        if not ai_provider:
            raise RuntimeError("AI provider not initialized")

        pipeline = create_pipeline(
            ai_provider,
            config=cfg,
            parser_name=(parser or None),
            wiki_output_dir=str(ARTIFACTS_DIR),
        )

        _append_log(job_id, "Pipeline instance created")
        _set_progress(job_id, 0.15)

        # Run the pipeline (this may perform LLM calls)
        _append_log(job_id, "Parsing and analyzing...")
        result = await pipeline.run(
            input_path=input_path,
            name=name,
            evaluate=evaluate,
            dry_run=dry_run,
            timeout_seconds=timeout,
        )

        _append_log(job_id, "Distillation pipeline completed")
        _set_progress(job_id, 0.9)

        # result is expected to be a DistillationResult dataclass-like or dict
        try:
            res_dict = (
                result.to_dict()
                if hasattr(result, "to_dict")
                else (result if isinstance(result, dict) else asdict(result))
            )
        except Exception:
            # best effort fallback
            try:
                res_dict = json.loads(
                    json.dumps(
                        result, default=lambda o: getattr(o, "__dict__", str(o)), ensure_ascii=False
                    )
                )
            except Exception:
                res_dict = {"raw": str(result)}

        markdown_path = None
        if isinstance(result, dict):
            markdown_path = result.get("markdown_path") or result.get("markdown")
        else:
            # try attribute
            markdown_path = getattr(result, "markdown_path", None) or getattr(
                result, "markdown", None
            )

        # normalize markdown_path to a string path if it's a Path object
        if isinstance(markdown_path, Path):
            markdown_path = str(markdown_path)

        _set_result(job_id, res_dict, markdown_path=markdown_path)
        _set_progress(job_id, 1.0)
        _set_status(job_id, "done")
        _append_log(job_id, "Job finished successfully")
    except Exception as e:
        logger.exception("Distillation job %s failed: %s", job_id, e)
        _set_error(job_id, str(e))
        _append_log(job_id, f"Job failed: {e}")


# -----------------------
# API endpoints
# -----------------------
@router.post("/upload", response_model=UploadResp)
async def upload_chat(file: UploadFile = File(...)):
    """
    Upload a chat export file. Supported: .json, .ndjson, .txt, .log, .chat, .html etc.
    Returns a generated file_id which can be used to start a distillation job.
    """
    try:
        ext = Path(file.filename).suffix or ".json"
        file_id = uuid4().hex
        safe_name = f"{file_id}{ext}"
        target = CHAT_DIR / safe_name
        content = await file.read()
        target.write_bytes(content)
        logger.info("Saved uploaded chat file: %s", target)
        return UploadResp(file_id=file_id, filename=str(target.relative_to(DATA_DIR)))
    except Exception as e:
        logger.exception("Upload failed: %s", e)
        raise HTTPException(status_code=500, detail=f"upload failed: {e}")


@router.post("/start", response_model=StartResp)
async def start_distillation(req: StartRequest, background_tasks: BackgroundTasks):
    """
    Start a distillation job for a previously uploaded file (file_id).
    """
    # find file path by file_id
    # assume filename starts with file_id in CHAT_DIR
    matches = list(CHAT_DIR.glob(f"{req.file_id}*"))
    if not matches:
        raise HTTPException(status_code=404, detail="file_id not found")
    input_path = str(matches[0])

    job_id = _create_job_record(req.file_id, req.name)
    _append_log(job_id, f"Enqueued job for file {input_path}")

    # Schedule background run
    # Use BackgroundTasks to ensure it runs in the background of the request
    background_tasks.add_task(
        lambda: asyncio.create_task(
            _run_distillation_job(
                job_id, input_path, req.name, req.parser, req.evaluate, req.dry_run, req.timeout
            )
        )
    )
    return StartResp(job_id=job_id)


@router.get("/status/{job_id}", response_model=JobStatusResp)
async def job_status(job_id: str):
    rec = JOBS.get(job_id) or _load_job_meta(job_id)
    if not rec:
        raise HTTPException(status_code=404, detail="job not found")
    return JobStatusResp(
        job_id=job_id,
        status=rec.get("status", "unknown"),
        progress=rec.get("progress", 0.0),
        created_at=rec.get("created_at"),
        updated_at=rec.get("updated_at"),
        name=rec.get("name"),
        file_id=rec.get("file_id"),
        metrics=rec.get("metrics"),
        error=rec.get("error"),
    )


@router.get("/result/{job_id}")
async def job_result(job_id: str):
    rec = JOBS.get(job_id) or _load_job_meta(job_id)
    if not rec:
        raise HTTPException(status_code=404, detail="job not found")
    if rec.get("status") != "done":
        return JSONResponse({"status": rec.get("status"), "progress": rec.get("progress")})
    # Return machine-readable persona + metrics + logs summary
    return {
        "job_id": job_id,
        "status": rec.get("status"),
        "progress": rec.get("progress"),
        "metrics": rec.get("metrics"),
        "markdown_path": rec.get("markdown_path"),
        "result": rec.get("result"),
        "logs": rec.get("logs", [])[-100:],  # return a slice for brevity
    }


@router.get("/download/{job_id}")
async def download_artifact(job_id: str, typ: str = "markdown"):
    """
    Download generated artifact.
    typ: 'markdown' or 'json' (machine-readable)
    """
    rec = JOBS.get(job_id) or _load_job_meta(job_id)
    if not rec:
        raise HTTPException(status_code=404, detail="job not found")
    if rec.get("status") != "done":
        raise HTTPException(status_code=400, detail="job not completed")

    # markdown_path may be full path or relative; try to resolve
    mp = rec.get("markdown_path")
    if not mp:
        raise HTTPException(status_code=404, detail="no artifact available")

    mpath = Path(str(mp))
    if not mpath.exists():
        # try relative to artifacts dir
        mp2 = ARTIFACTS_DIR / mpath.name
        if mp2.exists():
            mpath = mp2
        else:
            raise HTTPException(status_code=404, detail="artifact not found on disk")

    if typ == "markdown":
        return FileResponse(path=str(mpath), filename=mpath.name, media_type="text/markdown")
    elif typ == "json":
        # try to serve job result json
        # create a temporary json file from job.result if needed
        result = rec.get("result")
        if result is None:
            raise HTTPException(status_code=404, detail="no result JSON available")
        tmp_path = JOBS_DIR / f"{job_id}_result.json"
        tmp_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return FileResponse(
            path=str(tmp_path), filename=tmp_path.name, media_type="application/json"
        )
    else:
        raise HTTPException(status_code=400, detail="unknown artifact type")


@router.get("/jobs")
async def list_jobs():
    # merge in-disk persisted ones
    # load persisted job files and ensure in-memory store contains them
    for p in JOBS_DIR.glob("*.json"):
        try:
            j = json.loads(p.read_text(encoding="utf-8"))
            jid = j.get("job_id")
            if jid and jid not in JOBS:
                JOBS[jid] = j
        except Exception:
            continue
    # list jobs with brief metadata
    out = []
    for jid, rec in JOBS.items():
        out.append(
            {
                "job_id": jid,
                "name": rec.get("name"),
                "status": rec.get("status"),
                "progress": rec.get("progress"),
                "created_at": rec.get("created_at"),
                "updated_at": rec.get("updated_at"),
            }
        )
    # sort by created_at desc
    out.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return out


# -----------------------
# WebSocket for realtime updates
# -----------------------
@router.websocket("/ws/{job_id}")
async def ws_job_updates(websocket: WebSocket, job_id: str):
    """
    WebSocket connection to receive realtime job updates (status/progress/logs).
    The server will push an update every second while the job is running and a final
    message when it finishes. Client should close the socket on receiving final state.
    """
    await websocket.accept()
    try:
        # ensure job loaded into memory from disk if necessary
        if job_id not in JOBS:
            meta = _load_job_meta(job_id)
            if meta:
                JOBS[job_id] = meta

        if job_id not in JOBS:
            await websocket.send_json({"error": "job not found"})
            await websocket.close()
            return

        # send initial state
        await websocket.send_json(
            {
                "type": "init",
                "job_id": job_id,
                "status": JOBS[job_id].get("status"),
                "progress": JOBS[job_id].get("progress"),
                "name": JOBS[job_id].get("name"),
            }
        )

        # push updates periodically until terminal state
        while True:
            rec = JOBS.get(job_id) or _load_job_meta(job_id)
            if not rec:
                await websocket.send_json({"error": "job disappeared"})
                break
            # send small payload
            payload = {
                "type": "update",
                "job_id": job_id,
                "status": rec.get("status"),
                "progress": rec.get("progress"),
                "logs_tail": rec.get("logs", [])[-50:],
                "metrics": rec.get("metrics", {}),
                "updated_at": rec.get("updated_at"),
            }
            await websocket.send_json(payload)
            if rec.get("status") in ("done", "failed"):
                # final send and close
                await websocket.send_json(
                    {
                        "type": "final",
                        "job_id": job_id,
                        "status": rec.get("status"),
                        "result": rec.get("result"),
                    }
                )
                break
            try:
                await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                break
    except WebSocketDisconnect:
        logger.debug("WebSocket disconnected for job %s", job_id)
    except Exception:
        logger.exception("WebSocket error for job %s", job_id)
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
