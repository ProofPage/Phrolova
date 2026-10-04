"""
Rookery: Archive API Router
TwitCasting 아카이브 목록 조회 및 아카이브 다운로드 엔드포인트.
X Spaces m3u8 URL 조회 및 다운로드 엔드포인트 포함.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.engine.twitcasting import TwitcastingEngine

router = APIRouter(prefix="/api/archive", tags=["Archive"])


# ── 요청 스키마 ──────────────────────────────────────────

class ArchiveDownloadRequest(BaseModel):
    """아카이브 다운로드 요청."""

    url: str = Field(..., description="아카이브 URL (TwitCasting 아카이브 또는 X Spaces m3u8/URL)")
    quality: str = Field("best", description="화질 (best, worst, format_id)")
    output_dir: Optional[str] = Field(None, description="저장 디렉토리 (기본: settings)")


class SpacesM3u8ClearRequest(BaseModel):
    """X Spaces m3u8 URL 초기화 요청."""

    composite_key: str = Field(..., description="채널 복합 키 (x_spaces:username)")


# ── 엔드포인트 ───────────────────────────────────────────

@router.get("/twitcasting/{channel_id}", summary="TwitCasting 아카이브 목록 조회")
async def get_twitcasting_archives(
    channel_id: str,
    offset: int = Query(0, ge=0, le=1000, description="페이지 오프셋"),
    limit: int = Query(20, ge=1, le=50, description="한 번에 가져올 개수"),
):
    """TwitCasting 채널의 과거 방송 아카이브 목록을 조회합니다."""
    engine = TwitcastingEngine()
    try:
        result = await engine.get_movie_list(channel_id, offset=offset, limit=limit)
        return result
    except PermissionError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/download", summary="아카이브 다운로드 시작")
async def download_archive(req: ArchiveDownloadRequest):
    """TwitCasting 아카이브 또는 X Spaces 아카이브 다운로드를 시작합니다.
    기존 VOD 엔진(yt-dlp)을 재사용하며, task_id를 반환합니다."""
    from app.main import get_recorder_service

    service = get_recorder_service()
    try:
        task_id = await service.download_vod(
            url=req.url,
            quality=req.quality,
            output_dir=req.output_dir,
        )
        return {
            "task_id": task_id,
            "message": "아카이브 다운로드가 시작되었습니다.",
            "url": req.url,
            "quality": req.quality,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── X Spaces m3u8 캡처 관련 ────────────────────────────────────

@router.get("/spaces/captured", summary="캡처된 X Spaces m3u8 URL 목록 조회")
async def list_captured_spaces():
    """등록된 X Spaces 채널 중 m3u8 URL이 캡처된 항목 목록을 반환합니다."""
    from app.main import get_recorder_service

    service = get_recorder_service()
    channels = service.get_channels()
    result = [
        {
            "composite_key": ch["composite_key"],
            "channel_id": ch["channel_id"],
            "channel_name": ch.get("channel_name") or ch["channel_id"],
            "title": ch.get("title", ""),
            "captured_m3u8_url": ch.get("captured_m3u8_url"),
            "captured_m3u8_at": ch.get("captured_m3u8_at"),
        }
        for ch in channels
        if ch.get("platform") == "x_spaces" and ch.get("captured_m3u8_url")
    ]
    return {"spaces": result, "total": len(result)}


@router.post("/spaces/download-captured", summary="캡처된 m3u8 URL로 X Spaces 다운로드")
async def download_captured_space(req: SpacesM3u8ClearRequest):
    """캡처된 m3u8 URL을 사용하여 X Spaces 아카이브 다운로드를 시작합니다."""
    from app.main import get_recorder_service

    service = get_recorder_service()
    channels = service.get_channels()
    target = next(
        (ch for ch in channels if ch["composite_key"] == req.composite_key),
        None,
    )
    if target is None:
        raise HTTPException(status_code=404, detail=f"채널을 찾을 수 없습니다: {req.composite_key}")

    m3u8_url = target.get("captured_m3u8_url")
    if not m3u8_url:
        raise HTTPException(
            status_code=404,
            detail=f"'{req.composite_key}' 채널에 캡처된 m3u8 URL이 없습니다. Space가 라이브 중일 때 자동으로 캡처됩니다.",
        )

    try:
        task_id = await service.download_vod(url=m3u8_url)
        return {
            "task_id": task_id,
            "message": "X Spaces 다운로드가 시작되었습니다.",
            "composite_key": req.composite_key,
            "m3u8_url": m3u8_url,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/spaces/captured/{composite_key:path}", summary="캡처된 m3u8 URL 초기화")
async def clear_captured_space(composite_key: str):
    """다운로드 완료 후 캡처된 m3u8 URL을 초기화합니다."""
    from app.main import get_recorder_service
    from app.engine.base import Platform

    service = get_recorder_service()
    conductor = service._conductor

    # composite_key로 채널 직접 접근
    task = conductor._channels.get(composite_key)
    if task is None:
        raise HTTPException(status_code=404, detail=f"채널을 찾을 수 없습니다: {composite_key}")

    task.captured_m3u8_url = None
    task.captured_m3u8_at = None
    conductor._save_persistence()

    return {"message": f"'{composite_key}' m3u8 URL 초기화 완료."}
