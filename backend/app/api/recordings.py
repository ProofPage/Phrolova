"""Post-recording queue, output policy and registered final files."""

from pathlib import Path
from typing import Literal
import asyncio
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from app.engine.recording_finalizer import recording_policy, save_recording_policy

router = APIRouter(prefix="/api/recordings", tags=["Recordings"])


def manager():
    from app.main import get_recorder_service

    return get_recorder_service()._conductor.finalizer


class OutputSettings(BaseModel):
    output_format: Literal["mp4", "mkv", "ts"]
    keep_source_ts: bool = True
    max_concurrent: int = Field(default=1, ge=1, le=3)


class Retry(BaseModel):
    output_format: Literal["mp4", "mkv"] | None = None


class ClearHistory(BaseModel):
    job_ids: list[str] = Field(max_length=200)


@router.post('/history/clear')
async def clear_history(request: ClearHistory):
    await asyncio.to_thread(manager().clear_history, request.job_ids)
    return {'message':'이력을 목록에서 제거했습니다. 파일과 작업 기록은 보존됩니다.'}


@router.get("/settings")
async def get_output_settings():
    return recording_policy()


@router.put("/settings")
async def update_output_settings(request: OutputSettings):
    if request.output_format == "ts" and recording_policy()["output_format"] != "ts":
        raise HTTPException(422, "녹화 완료 후 저장 형식은 MKV 또는 MP4를 선택하세요.")
    values = request.model_dump()
    save_recording_policy(values)
    return values


@router.get("/jobs")
async def list_jobs():
    return {"jobs": await asyncio.to_thread(manager().list_jobs)}


@router.post("/{job_id}/retry")
async def retry_job(job_id: str, request: Retry):
    try:
        return await manager().retry(job_id, request.output_format)
    except ValueError as error:
        raise HTTPException(409, str(error)) from None


@router.post("/{job_id}/inspect")
async def inspect_job(job_id: str):
    try:
        return await manager().retry(job_id, inspect_only=True)
    except ValueError as error:
        raise HTTPException(409, str(error)) from None


def output(job_id, source=False):
    try:
        job = manager().get(job_id)
    except ValueError:
        raise HTTPException(404, "녹화 작업을 찾을 수 없습니다.") from None
    candidates = job["source_paths"] if source else [job.get("output_path"), *job["source_paths"]]
    path = None
    for candidate in candidates:
        try:
            if candidate and Path(candidate).is_file() and Path(candidate).stat().st_size > 0:
                path = Path(candidate)
                break
        except OSError:
            continue
    if path is None:
        raise HTTPException(404, "녹화 파일을 찾을 수 없습니다.")
    if not path.is_file() or path.stat().st_size == 0:
        raise HTTPException(404, "녹화 파일을 찾을 수 없습니다.")
    return path


@router.get("/{job_id}/file")
async def open_file(job_id: str, source: bool = False):
    try:
        job = manager().get(job_id)
    except ValueError:
        raise HTTPException(404, "녹화 작업을 찾을 수 없습니다.") from None
    if job["state"] not in ("completed", "failed", "attention"):
        raise HTTPException(409, "파일 처리 종료 후 열 수 있습니다.")
    path = output(job_id, source=source)
    return FileResponse(path, filename=path.name, content_disposition_type="inline")


@router.post("/{job_id}/open-location")
async def open_location(job_id: str, request: Request):
    folder = output(job_id).parent
    import ipaddress
    try:
        local = bool(request.client and ipaddress.ip_address(request.client.host).is_loopback)
    except ValueError:
        local = False
    if not local:
        return {'message': f'서버 저장 위치: {folder}. 원격 브라우저에서는 파일 열기를 사용하세요.', 'path': str(folder), 'opened': False}
    from app.core.file_browser import reveal
    if await asyncio.to_thread(reveal, folder):
        return {"message": "저장 폴더를 열었습니다.", "path": str(folder)}
    return {"message": f"저장 위치: {folder}", "path": str(folder)}
