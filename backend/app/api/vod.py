"""
Rookery: VOD API Router
VOD/클립 다운로드 관련 엔드포인트.
"""

from __future__ import annotations

from typing import Annotated, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/vod", tags=["VOD"])


# ── 요청 스키마 ──────────────────────────────────────────

class VodInfoRequest(BaseModel):
    """VOD 정보 조회 요청."""

    url: str = Field(..., description="치지직 VOD/클립 URL 또는 유튜브 등 yt-dlp 지원 URL")


class VodDownloadRequest(BaseModel):
    """VOD 다운로드 요청."""

    url: str = Field(..., description="치지직 VOD/클립 URL 또는 유튜브 등 yt-dlp 지원 URL")
    quality: str = Field("best", description="화질 (best, worst, format_id)")
    output_dir: Optional[str] = Field(None, description="저장 디렉토리 (기본: settings)")
    cdn: Literal["default", "akamai"] = "default"


# ── 엔드포인트 ───────────────────────────────────────────

@router.post("/info", summary="VOD 메타데이터 조회")
async def get_vod_info(req: VodInfoRequest):
    """VOD/클립/유튜브 영상의 제목, 길이, 썸네일, 화질 옵션을 조회합니다."""
    from app.main import get_recorder_service

    service = get_recorder_service()
    try:
        return await service.get_vod_info(req.url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/download", summary="VOD 다운로드 시작")
async def download_vod(req: VodDownloadRequest):
    """영상 또는 YouTube 채널 다운로드를 시작합니다."""
    from app.main import get_recorder_service

    service = get_recorder_service()

    try:
        result = await service.download_vod_batch(
            url=req.url, quality=req.quality, output_dir=req.output_dir, cdn=req.cdn,
        )
        return {**result, "url": req.url, "quality": req.quality}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/status", summary="모든 다운로드 상태 조회")
async def get_all_vod_status():
    """활성 + 완료된 모든 VOD 다운로드 작업 목록을 조회합니다."""
    from app.main import get_recorder_service

    service = get_recorder_service()
    tasks = service.list_vod_tasks()

    return {
        "tasks": tasks,
        "imports": service.list_vod_imports(),
        "active_count": sum(
            1 for t in tasks if t["state"] in ["downloading", "paused"]
        ),
        "queued_count": sum(1 for t in tasks if t["state"] == "idle"),
        "total_count": len(tasks),
    }


@router.get("/status/{task_id}", summary="특정 작업 상태 조회")
async def get_vod_task_status(task_id: str):
    """특정 다운로드 작업의 상태를 조회합니다."""
    from app.main import get_recorder_service

    service = get_recorder_service()
    status = service.get_vod_task_status(task_id)

    if "error" in status:
        raise HTTPException(status_code=404, detail=status["error"])

    return status


@router.post("/{task_id}/cancel", summary="다운로드 취소")
async def cancel_vod_download(task_id: str):
    """특정 다운로드를 취소합니다."""
    from app.main import get_recorder_service

    service = get_recorder_service()
    result = service.cancel_vod(task_id)

    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    return result


@router.post("/{task_id}/pause", summary="다운로드 일시정지")
async def pause_vod_download(task_id: str):
    """특정 다운로드를 일시정지합니다."""
    from app.main import get_recorder_service

    service = get_recorder_service()
    result = service.pause_vod(task_id)

    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    return result


@router.post("/{task_id}/resume", summary="다운로드 재개")
async def resume_vod_download(task_id: str):
    """일시정지된 다운로드를 재개합니다."""
    from app.main import get_recorder_service

    service = get_recorder_service()
    result = service.resume_vod(task_id)

    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    return result


class VodRetryRequest(BaseModel):
    cdn: Literal["default", "akamai"] = "default"


@router.post("/{task_id}/retry", summary="다운로드 재시도")
async def retry_vod_download(task_id: str, req: Optional[VodRetryRequest] = None):
    """완료/에러 상태의 다운로드를 재시도합니다. 새 task_id를 반환합니다."""
    from app.main import get_recorder_service

    service = get_recorder_service()

    try:
        new_task_id = await service.retry_vod(task_id, cdn=req.cdn if req else "default")
        return {
            "message": "다운로드가 재시작되었습니다.",
            "old_task_id": task_id,
            "new_task_id": new_task_id,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))




class ReorderTasksRequest(BaseModel):
    """작업 순서 재정렬 요청."""

    task_ids: list[str] = Field(..., description="새로운 순서대로 정렬된 task_id 리스트")


@router.post("/reorder", summary="작업 순서 재정렬")
async def reorder_vod_tasks(req: ReorderTasksRequest):
    """드래그 앤 드롭으로 작업 순서를 변경합니다."""
    from app.main import get_recorder_service

    service = get_recorder_service()
    result = service.reorder_vod_tasks(req.task_ids)

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return result


@router.post("/clear-completed", summary="대기 및 완료 작업 정리")
async def clear_completed_vod_tasks(completed_only: bool = False):
    """대기, 완료, 오류 작업을 삭제하고 진행/일시정지 작업은 유지합니다."""
    from app.main import get_recorder_service

    service = get_recorder_service()
    result = service.clear_completed_vod_tasks(completed_only=True) if completed_only else service.clear_completed_vod_tasks()

    return result


@router.post("/{task_id}/open-location", summary="파일 위치 열기")
async def open_vod_file_location(task_id: str):
    """다운로드된 파일의 위치를 탐색기로 엽니다."""
    from app.main import get_recorder_service

    service = get_recorder_service()
    result = service.open_vod_file_location(task_id)

    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    return result


@router.post("/imports/{import_id}/cancel", summary="채널 영상 수집 중지 또는 알림 닫기")
async def cancel_channel_import(import_id: str):
    from app.main import get_recorder_service
    try:
        return get_recorder_service().cancel_vod_import(import_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


class VodPrepareRequest(BaseModel):
    urls: list[Annotated[str, Field(max_length=2048)]] = Field(..., min_length=1, max_length=100)


class VodQualityRequest(BaseModel):
    quality: str = Field(..., max_length=20)


class VodStartBatchRequest(BaseModel):
    task_ids: Optional[list[str]] = Field(None, max_length=1000)


def _preparation_service():
    from app.main import get_recorder_service
    return get_recorder_service()


@router.post('/prepare', summary='CHZZK VOD 준비 목록 등록')
async def prepare_vods(req: VodPrepareRequest):
    try:
        return _preparation_service().prepare_vods(req.urls)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@router.post('/start-prepared', summary='준비 완료 VOD 일괄 시작')
async def start_prepared_vods(req: VodStartBatchRequest):
    return _preparation_service().start_prepared_batch(req.task_ids)


@router.post('/{task_id}/metadata', summary='VOD 정보 다시 조회')
async def retry_vod_metadata(task_id: str):
    try:
        return _preparation_service().retry_metadata(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@router.patch('/{task_id}/quality', summary='준비 VOD 화질 변경')
async def update_prepared_quality(task_id: str, req: VodQualityRequest):
    try:
        return _preparation_service().set_prepared_quality(task_id, req.quality)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@router.post('/{task_id}/start', summary='준비 VOD 개별 시작')
async def start_prepared_vod(task_id: str):
    try:
        return _preparation_service().start_prepared(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@router.delete('/{task_id}', summary='VOD 작업 이력만 제거')
async def remove_vod_task(task_id: str):
    try:
        return _preparation_service().remove_vod_task(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
