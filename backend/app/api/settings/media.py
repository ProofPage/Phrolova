"""라이브 녹화 및 VOD 다운로드 설정."""

from __future__ import annotations

from typing import Literal, Optional
import json
import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException

from pydantic import BaseModel, Field, field_validator

from app.core.config import get_settings
from app.api.download_options import DefaultDownloadOptions
from app.core.utils import update_env_file as _update_env_file

from app.api.settings._shared import SETTINGS_PREFIX, SETTINGS_TAGS, VALID_FORMATS, VALID_QUALITIES


# ── 요청 스키마 ──────────────────────────────────────────

router = APIRouter(prefix=SETTINGS_PREFIX, tags=SETTINGS_TAGS)


async def validate_directory(value: str, label: str) -> str:
    value = value.strip()
    if not value:
        raise HTTPException(400, f"{label}를 입력하세요.")
    try:
        await asyncio.to_thread(Path(value).mkdir, parents=True, exist_ok=True)
    except OSError:
        raise HTTPException(400, f"{label}를 사용할 수 없습니다. 경로와 접근 권한을 확인하세요.") from None
    return value


class DownloadSettingsUpdateRequest(BaseModel):
    """라이브 녹화 설정 업데이트 요청."""
    live_download_dir: Optional[str] = Field(None, max_length=4096)
    monitor_interval: Optional[int] = Field(None, ge=5, le=300)

    # /settings/download를 사용하는 구버전 앱 호환 필드. 신규 클라이언트는
    # VOD 설정 API를 통해 이 값을 저장한다.
    keep_download_parts: Optional[bool] = Field(None, description="구버전 클라이언트 호환 필드")
    chzzk_live_cdn: Optional[Literal["default", "akamai"]] = None
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
    recording_quality: Optional[str] = Field(None, description="라이브 녹화 품질 (best, 1080p, 720p, 480p)")
    soop_proxy: Optional[str] = Field(None, max_length=1024, description="SOOP API 우회 프록시 URL")


class VodSettingsUpdateRequest(BaseModel):
    """VOD 다운로드 설정 업데이트 요청."""
    vod_download_dir: Optional[str] = Field(None, max_length=4096)

    vod_filename_template: Optional[str] = Field(None, max_length=240)

    @field_validator("vod_filename_template")
    @classmethod
    def validate_filename_template(cls, value: Optional[str]) -> Optional[str]:
        from app.core.vod_filename import validate_vod_template
        return validate_vod_template(value) if value is not None else None

    vod_max_concurrent: Optional[int] = Field(None, ge=1, le=10, description="동시 다운로드 최대 개수")
    vod_default_quality: Optional[str] = Field(None, description="기본 화질 (best, 1080p, 720p, 480p)")
    vod_max_speed: Optional[int] = Field(None, ge=0, le=1000, description="최대 다운로드 속도 (MB/s, 0=무제한)")
    chzzk_vod_cdn: Optional[Literal["default", "akamai"]] = None
    vod_format: Optional[str] = Field(None, description="VOD 다운로드 포맷 (mp4, mkv, ts)")
    keep_download_parts: Optional[bool] = Field(None, description="VOD 다운로드 중단 시 .part 파일 유지 여부")




@router.put("/live-condition", summary="자동 라이브 다운로드 기본 조건")
async def update_live_condition(req: DefaultDownloadOptions):
    from app.main import get_recorder_service

    settings = get_settings()
    _update_env_file({
        "LIVE_DOWNLOAD_CONDITION": req.live_download_condition,
        "WATCHALONG_TAGS": req.watchalong_tags,
    }, raise_on_error=True)
    settings.live_download_condition = req.live_download_condition
    settings.watchalong_tags = req.watchalong_tags
    get_recorder_service().scan_now()
    return {"message": "기본 다운로드 조건이 저장되었습니다.", **req.model_dump()}


@router.put("/live", summary="라이브 녹화 설정 업데이트")
@router.put("/download", summary="라이브 녹화 설정 업데이트 (구버전 호환)")
async def update_download_settings(req: DownloadSettingsUpdateRequest):
    """라이브 녹화 설정을 업데이트합니다. /download는 구버전 호환 경로입니다."""
    settings = get_settings()
    updates = req.model_dump(exclude_none=True)
    if "live_download_dir" in updates:
        updates["live_download_dir"] = await validate_directory(updates["live_download_dir"], "라이브 저장 위치")
    legacy_mode = updates.pop("chzzk_time_machine_enabled", None)
    if "chzzk_stream_mode" not in updates and legacy_mode is not None:
        updates["chzzk_stream_mode"] = "force-timemachine" if legacy_mode else "standard"
    legacy_offset = updates.pop("chzzk_time_machine_shift", None)
    if "chzzk_time_machine_offset" not in updates and legacy_offset is not None:
        updates["chzzk_time_machine_offset"] = legacy_offset
    if "recording_quality" in updates:
        quality = updates["recording_quality"].lower()
        if quality not in VALID_QUALITIES:
            raise HTTPException(400, "지원하지 않는 녹화 화질입니다.")
        updates["recording_quality"] = quality
    env_updates = {
        key.upper(): str(value).lower() if isinstance(value, bool) else str(value)
        for key, value in updates.items()
    }
    try:
        _update_env_file(env_updates, raise_on_error=True)
    except OSError as exc:
        raise HTTPException(500, "라이브 녹화 설정을 저장하지 못했습니다.") from exc
    for key, value in updates.items():
        setattr(settings, key, value)
    if "chzzk_stream_mode" in updates:
        settings.chzzk_time_machine_enabled = None
    if "chzzk_time_machine_offset" in updates:
        settings.chzzk_time_machine_shift = None

    return {
        "message": "라이브 녹화 설정이 업데이트되었습니다.",
        "settings": {
            "keep_download_parts": settings.keep_download_parts,
            "max_record_retries": settings.max_record_retries,
            "chzzk_live_cdn": settings.chzzk_live_cdn,
            "chzzk_stream_mode": settings.effective_chzzk_stream_mode,
            "chzzk_time_machine_enabled": settings.effective_chzzk_stream_mode != "standard",
            "chzzk_time_machine_offset": settings.effective_chzzk_time_machine_offset,
            "chzzk_time_machine_shift": settings.effective_chzzk_time_machine_offset,
            "save_live_preview": settings.save_live_preview,
            "live_filename_template": settings.live_filename_template,
            "recording_quality": settings.recording_quality,
            "live_download_dir": settings.effective_live_download_dir,
            "monitor_interval": settings.monitor_interval,
            "soop_proxy": settings.soop_proxy,
        },
    }


@router.put("/vod", summary="VOD 다운로드 설정 업데이트")
async def update_vod_settings(req: VodSettingsUpdateRequest):
    """VOD 다운로드 설정을 업데이트합니다."""
    settings = get_settings()
    updates = req.model_dump(exclude_none=True)
    if "vod_download_dir" in updates:
        updates["vod_download_dir"] = await validate_directory(updates["vod_download_dir"], "영상 저장 위치")
    for key, allowed in (("vod_default_quality", VALID_QUALITIES), ("vod_format", VALID_FORMATS)):
        if key in updates:
            value = updates[key].lower()
            if value not in allowed:
                raise HTTPException(status_code=400, detail=f"지원하지 않는 설정입니다: {key}")
            updates[key] = value
    env_updates = {
        key.upper(): str(value).lower() if isinstance(value, bool) else str(value)
        for key, value in updates.items()
    }
    if env_updates:
        try:
            _update_env_file(env_updates, raise_on_error=True)
        except OSError as exc:
            raise HTTPException(status_code=500, detail="VOD 설정 파일을 저장하지 못했습니다.") from exc
    for key, value in updates.items():
        setattr(settings, key, value)

    if req.vod_max_concurrent is not None:
        from app.main import get_recorder_service
        get_recorder_service().set_vod_concurrency(req.vod_max_concurrent)
    return {
        "message": "영상 다운로드 설정이 저장되었습니다. 동시 다운로드 개수는 즉시 적용됩니다.",
        "settings": {
            "vod_max_concurrent": settings.vod_max_concurrent,
            "vod_download_dir": settings.vod_download_dir or settings.download_dir,
            "vod_default_quality": settings.vod_default_quality,
            "vod_max_speed": settings.vod_max_speed,
            "vod_format": settings.vod_format,
            "chzzk_vod_cdn": settings.chzzk_vod_cdn,
            "vod_filename_template": settings.vod_filename_template,
            "keep_download_parts": settings.keep_download_parts,
        },
    }
