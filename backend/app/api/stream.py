"""
Rookery: Stream API Router
라이브 채널 관리 및 녹화 제어 엔드포인트.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import Field

from app.core.utils import extract_channel_id
from app.engine.base import Platform
from app.engine.conductor import Conductor
from app.api.download_options import ChannelDownloadOptions

router = APIRouter(prefix="/api/stream", tags=["Stream"])


def _to_composite_key(raw: str) -> str:
    """URL 경로에서 받은 channel_id를 composite_key로 변환한다.

    - 이미 'platform:channel_id' 형식이면 그대로 반환 (멀티플랫폼 키)
    - ':' 없는 레거시 순수 ID면 chzzk composite_key로 감싼다
    - chzzk URL 형식도 extract_channel_id로 ID만 추출 후 chzzk 키로 변환
    """
    # 알려진 플랫폼 접두사가 있으면 composite_key로 간주
    for prefix in ("chzzk:", "x_spaces:"):
        if raw.startswith(prefix):
            return raw
    # 레거시: 순수 chzzk ID 또는 chzzk URL
    channel_id = extract_channel_id(raw)
    return Conductor.make_composite_key(Platform.CHZZK, channel_id)


# ── 요청 스키마 ──────────────────────────────────────────

class AddChannelRequest(ChannelDownloadOptions):
    """채널 추가 요청."""

    channel_id: str = Field(..., description="치지직 채널 ID")
    auto_record: bool = Field(True, description="방송 시작 시 자동 녹화 여부")


# ── 채널 관리 ────────────────────────────────────────────

@router.post("/channels", summary="감시 채널 추가")
async def add_channel(req: AddChannelRequest):
    """감시할 채널을 등록합니다."""
    from app.main import get_recorder_service

    service = get_recorder_service()

    channel_id = extract_channel_id(req.channel_id)
    return service.add_platform_channel(
        channel_id, platform=Platform.CHZZK, auto_record=req.auto_record,
        download_condition=req.download_condition, watchalong_tags=req.watchalong_tags,
    )


@router.put("/channels/{channel_id}/download-options", summary="채널 다운로드 설정 수정")
async def update_channel_download_options(channel_id: str, req: ChannelDownloadOptions):
    from app.main import get_recorder_service

    service = get_recorder_service()
    key = Conductor.make_composite_key(Platform.CHZZK, extract_channel_id(channel_id))
    try:
        service.set_download_options(key, req.auto_record, req.download_condition, req.watchalong_tags)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"message": "채널 다운로드 설정이 저장되었습니다.", **req.model_dump()}


@router.delete("/channels/{channel_id:path}", summary="채널 제거")
async def remove_channel(channel_id: str):
    """채널을 감시 목록에서 제거합니다."""
    from app.main import get_recorder_service

    service = get_recorder_service()

    channel_id = extract_channel_id(channel_id)
    return await service.remove_channel(channel_id)


@router.get("/channels", summary="채널 목록 조회")
async def list_channels():
    """등록된 모든 채널과 상태를 조회합니다."""
    from app.main import get_recorder_service

    service = get_recorder_service()
    return service.get_channels()


@router.patch("/channels/{channel_id:path}/auto-record", summary="자동 녹화 토글")
async def toggle_auto_record(channel_id: str):
    """채널의 자동 녹화 설정을 ON/OFF 토글합니다."""
    from app.main import get_recorder_service

    service = get_recorder_service()

    channel_id = extract_channel_id(channel_id)
    # 레거시 라우터는 순수 ID로 오므로 chzzk composite key로 변환
    composite_key = Conductor.make_composite_key(Platform.CHZZK, channel_id)

    try:
        return await service.toggle_auto_record(composite_key)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── 녹화 제어 ────────────────────────────────────────────

@router.get("/preview/{channel_id:path}", summary="라이브 미리보기 주소 조회")
async def live_preview(channel_id: str):
    from app.main import get_recorder_service
    from fastapi.responses import JSONResponse

    platform, identifier = Conductor.parse_composite_key(channel_id)
    key = Conductor.make_composite_key(platform, identifier)
    try:
        url = await get_recorder_service().get_live_preview_url(key)
    except KeyError:
        raise HTTPException(404, "채널을 찾을 수 없습니다.") from None
    except ValueError as exc:
        message = str(exc)
        if message not in ("오프라인", "이 채널은 영상 미리보기를 지원하지 않습니다."):
            message = "미리보기를 불러올 수 없습니다."
        raise HTTPException(409, message) from None
    except Exception:
        # Resolver errors may contain signed URLs or upstream credentials.
        raise HTTPException(502, "미리보기를 불러올 수 없습니다. 잠시 후 다시 시도해 주세요.") from None
    return JSONResponse({"url": url}, headers={"Cache-Control": "no-store"})

@router.post("/record/{channel_id:path}/start", summary="수동 녹화 시작")
async def start_recording(channel_id: str):
    """특정 채널의 녹화를 수동으로 시작합니다."""
    from app.main import get_recorder_service

    service = get_recorder_service()

    # composite_key 형식(platform:id)이면 그대로 사용, 레거시 순수 ID면 chzzk으로 처리
    composite_key = _to_composite_key(channel_id)

    try:
        return await service.start_recording(composite_key)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/record/{channel_id:path}/stop", summary="녹화 중지")
async def stop_recording(channel_id: str):
    """특정 채널의 녹화를 중지합니다."""
    from app.main import get_recorder_service

    service = get_recorder_service()

    # composite_key 형식(platform:id)이면 그대로 사용, 레거시 순수 ID면 chzzk으로 처리
    composite_key = _to_composite_key(channel_id)

    try:
        return await service.stop_recording(composite_key)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/record/stop-all", summary="모든 녹화 중지")
async def stop_all_recordings():
    """현재 진행 중인 모든 채널의 녹화를 중지합니다."""
    from app.main import get_recorder_service

    service = get_recorder_service()
    try:
        return await service.stop_all_recordings()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Conductor 제어 ───────────────────────────────────────

@router.post("/monitor/start", summary="전체 감시 시작")
async def start_monitoring():
    """등록된 모든 채널의 감시를 시작합니다."""
    from app.main import get_recorder_service

    service = get_recorder_service()
    return await service.start_monitoring()


@router.post("/monitor/stop", summary="전체 감시 중지")
async def stop_monitoring():
    """모든 감시 및 녹화를 중지합니다."""
    from app.main import get_recorder_service

    service = get_recorder_service()
    return await service.stop_monitoring()
