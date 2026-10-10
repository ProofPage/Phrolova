"""Post-recording queue, output policy and registered final files."""

from pathlib import Path
from typing import Literal
import asyncio, os, shutil
from fastapi import APIRouter, HTTPException
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
    return {"jobs": manager().list_jobs()}


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


def output(job_id):
    try:
        job = manager().get(job_id)
    except ValueError:
        raise HTTPException(404, "녹화 작업을 찾을 수 없습니다.") from None
    path = Path(job.get("output_path") or job["source_paths"][0])
    if not path.is_file():
        raise HTTPException(404, "녹화 파일을 찾을 수 없습니다.")
    return path


@router.get("/{job_id}/file")
async def open_file(job_id: str):
    try:
        job = manager().get(job_id)
    except ValueError:
        raise HTTPException(404, "녹화 작업을 찾을 수 없습니다.") from None
    if job["state"] not in ("completed", "failed", "attention"):
        raise HTTPException(409, "파일 처리 종료 후 열 수 있습니다.")
    path = output(job_id)
    return FileResponse(path, filename=path.name, content_disposition_type="inline")


@router.post("/{job_id}/open-location")
async def open_location(job_id: str):
    folder = output(job_id).parent
    if os.name == "nt":
        await asyncio.to_thread(os.startfile, str(folder))
        return {"message": "저장 폴더를 열었습니다.", "path": str(folder)}
    command = shutil.which("xdg-open")
    if command and (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        proc = await asyncio.create_subprocess_exec(
            command,
            str(folder),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(proc.wait(), 10)
        except asyncio.TimeoutError:
            if proc.returncode is None:
                proc.kill()
            await proc.wait()
        if proc.returncode == 0:
            return {"message": "저장 폴더를 열었습니다.", "path": str(folder)}
    return {"message": f"저장 위치: {folder}", "path": str(folder)}
