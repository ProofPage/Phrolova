"""다운로드·VOD·채팅 설정."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException

from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.utils import update_env_file as _update_env_file

from app.api.settings._shared import SETTINGS_PREFIX, SETTINGS_TAGS, VALID_FORMATS, VALID_QUALITIES


# ── 요청 스키마 ──────────────────────────────────────────

router = APIRouter(prefix=SETTINGS_PREFIX, tags=SETTINGS_TAGS)


class DownloadSettingsUpdateRequest(BaseModel):
    """라이브 녹화 설정 업데이트 요청."""

    # /settings/download를 사용하는 구버전 앱 호환 필드. 신규 클라이언트는
    # VOD 설정 API를 통해 이 값을 저장한다.
    keep_download_parts: Optional[bool] = Field(None, description="구버전 클라이언트 호환 필드")
    max_record_retries: int = Field(..., ge=0, le=100, description="라이브 녹화 자동 재시도 횟수")
    chzzk_stream_mode: Optional[str] = Field(
        None,
        pattern=r"^(standard|request-timemachine|force-timemachine)$",
        description="치지직 라이브 스트림 획득 방식",
    )
    chzzk_time_machine_enabled: Optional[bool] = Field(None, description="구버전 치지직 타임머신 설정 호환")
    chzzk_time_machine_offset: Optional[int] = Field(None, ge=0, le=86400, description="스트림 시작 기준 오프셋(초)")
    chzzk_time_machine_shift: Optional[int] = Field(None, ge=0, le=86400, description="구버전 타임머신 설정 호환")
    save_live_preview: Optional[bool] = Field(None, description="치지직 라이브 미리보기 이미지 저장 여부")
    live_filename_template: Optional[str] = Field(
        None,
        max_length=240,
        pattern=r"^[^\r\n]*$",
        description="라이브 녹화 파일명 형식",
    )


class VodSettingsUpdateRequest(BaseModel):
    """VOD 다운로드 설정 업데이트 요청."""

    vod_max_concurrent: Optional[int] = Field(None, ge=1, le=10, description="동시 다운로드 최대 개수")
    vod_default_quality: Optional[str] = Field(None, description="기본 화질 (best, 1080p, 720p, 480p)")
    vod_max_speed: Optional[int] = Field(None, ge=0, le=1000, description="최대 다운로드 속도 (MB/s, 0=무제한)")
    vod_format: Optional[str] = Field(None, description="VOD 다운로드 포맷 (mp4, mkv, ts)")
    keep_download_parts: Optional[bool] = Field(None, description="VOD 다운로드 중단 시 .part 파일 유지 여부")


class ChatSettingsUpdateRequest(BaseModel):
    """채팅 아카이빙 설정 업데이트 요청."""

    chat_archive_enabled: bool = Field(..., description="녹화 시 채팅 자동 아카이빙 여부")


@router.put("/live", summary="라이브 녹화 설정 업데이트")
@router.put("/download", summary="라이브 녹화 설정 업데이트", include_in_schema=False)
async def update_download_settings(req: DownloadSettingsUpdateRequest):
    """라이브 녹화 설정을 업데이트합니다. /download는 구버전 호환 경로입니다."""
    settings = get_settings()
    if req.keep_download_parts is not None:
        settings.keep_download_parts = req.keep_download_parts
    settings.max_record_retries = req.max_record_retries
    stream_mode = req.chzzk_stream_mode
    if stream_mode is None and req.chzzk_time_machine_enabled is not None:
        stream_mode = "force-timemachine" if req.chzzk_time_machine_enabled else "standard"
    if stream_mode is not None:
        settings.chzzk_stream_mode = stream_mode
        settings.chzzk_time_machine_enabled = None
    time_machine_offset = req.chzzk_time_machine_offset
    if time_machine_offset is None:
        time_machine_offset = req.chzzk_time_machine_shift
    if time_machine_offset is not None:
        settings.chzzk_time_machine_offset = time_machine_offset
        settings.chzzk_time_machine_shift = None
    if req.save_live_preview is not None:
        settings.save_live_preview = req.save_live_preview
    if req.live_filename_template is not None:
        settings.live_filename_template = req.live_filename_template

    env_updates = {"MAX_RECORD_RETRIES": str(req.max_record_retries)}
    if req.keep_download_parts is not None:
        env_updates["KEEP_DOWNLOAD_PARTS"] = str(req.keep_download_parts).lower()
    if stream_mode is not None:
        env_updates["CHZZK_STREAM_MODE"] = stream_mode
    if time_machine_offset is not None:
        env_updates["CHZZK_TIME_MACHINE_OFFSET"] = str(time_machine_offset)
    if req.save_live_preview is not None:
        env_updates["SAVE_LIVE_PREVIEW"] = str(req.save_live_preview).lower()
    if req.live_filename_template is not None:
        env_updates["LIVE_FILENAME_TEMPLATE"] = req.live_filename_template

    try:
        _update_env_file(env_updates)
    except Exception as e:
        print(f"설정 파일 저장 실패: {e}")

    return {
        "message": "라이브 녹화 설정이 업데이트되었습니다.",
        "settings": {
            "keep_download_parts": settings.keep_download_parts,
            "max_record_retries": settings.max_record_retries,
            "chzzk_stream_mode": settings.effective_chzzk_stream_mode,
            "chzzk_time_machine_enabled": settings.effective_chzzk_stream_mode != "standard",
            "chzzk_time_machine_offset": settings.effective_chzzk_time_machine_offset,
            "chzzk_time_machine_shift": settings.effective_chzzk_time_machine_offset,
            "save_live_preview": settings.save_live_preview,
            "live_filename_template": settings.live_filename_template,
        },
    }


@router.put("/vod", summary="VOD 다운로드 설정 업데이트")
async def update_vod_settings(req: VodSettingsUpdateRequest):
    """VOD 다운로드 설정을 업데이트합니다."""
    settings = get_settings()
    env_updates: dict[str, str] = {}

    if req.keep_download_parts is not None:
        settings.keep_download_parts = req.keep_download_parts
        env_updates["KEEP_DOWNLOAD_PARTS"] = str(req.keep_download_parts).lower()

    # ── vod_max_concurrent ──
    if req.vod_max_concurrent is not None:
        settings.vod_max_concurrent = req.vod_max_concurrent
        env_updates["VOD_MAX_CONCURRENT"] = str(req.vod_max_concurrent)

    # ── vod_default_quality ──
    if req.vod_default_quality is not None:
        quality = req.vod_default_quality.lower()
        if quality not in VALID_QUALITIES:
            raise HTTPException(
                status_code=400,
                detail=f"지원하지 않는 품질입니다. 사용 가능: {', '.join(VALID_QUALITIES)}",
            )
        settings.vod_default_quality = quality
        env_updates["VOD_DEFAULT_QUALITY"] = quality

    # ── vod_max_speed ──
    if req.vod_max_speed is not None:
        settings.vod_max_speed = req.vod_max_speed
        env_updates["VOD_MAX_SPEED"] = str(req.vod_max_speed)

    # ── vod_format ──
    if req.vod_format is not None:
        fmt = req.vod_format.lower()
        if fmt not in VALID_FORMATS:
            raise HTTPException(
                status_code=400,
                detail=f"지원하지 않는 포맷입니다. 사용 가능: {', '.join(VALID_FORMATS)}",
            )
        settings.vod_format = fmt
        env_updates["VOD_FORMAT"] = fmt

    # .env 영구 저장
    if env_updates:
        try:
            _update_env_file(env_updates)
        except Exception as e:
            print(f"설정 파일 저장 실패: {e}")

    # VodEngine의 세마포어를 업데이트하려면 재시작이 필요
    # 현재는 런타임 중 반영 불가 (재시작 필요 안내)
    return {
        "message": "VOD 설정이 업데이트되었습니다. 일부 설정은 서버 재시작 후 적용됩니다.",
        "settings": {
            "vod_max_concurrent": settings.vod_max_concurrent,
            "vod_default_quality": settings.vod_default_quality,
            "vod_max_speed": settings.vod_max_speed,
            "vod_format": settings.vod_format,
            "keep_download_parts": settings.keep_download_parts,
        },
    }


@router.put("/chat", summary="채팅 아카이빙 설정 업데이트")
async def update_chat_settings(req: ChatSettingsUpdateRequest):
    """채팅 아카이빙 설정을 업데이트합니다."""
    settings = get_settings()
    settings.chat_archive_enabled = req.chat_archive_enabled

    try:
        _update_env_file({
            "CHAT_ARCHIVE_ENABLED": str(req.chat_archive_enabled).lower(),
        })
    except Exception as e:
        print(f"설정 파일 저장 실패: {e}")

    return {
        "message": "채팅 아카이빙 설정이 업데이트되었습니다.",
        "settings": {
            "chat_archive_enabled": settings.chat_archive_enabled,
        },
    }
