"""일반 설정 — 저장 경로, 감시 주기, 녹화 형식, 그리고 전체 설정 조회."""

from __future__ import annotations

from pathlib import Path
from typing import Optional
import os
import platform
import string
import asyncio
import re
import subprocess
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version as package_version

from fastapi import APIRouter, HTTPException, Query

from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.utils import update_env_file as _update_env_file

from app.services.notifications import KIND_LABELS

from app.api.settings._shared import SETTINGS_PREFIX, SETTINGS_TAGS, VALID_FORMATS, VALID_QUALITIES, _csv_to_list


# ── 요청 스키마 ──────────────────────────────────────────

router = APIRouter(prefix=SETTINGS_PREFIX, tags=SETTINGS_TAGS)


def _streamlink_version() -> str | None:
    """현재 실행 환경에서 Streamlink 패키지 버전을 반환한다."""
    try:
        return package_version("streamlink")
    except PackageNotFoundError:
        try:
            import streamlink

            return getattr(streamlink, "__version__", "설치됨")
        except ImportError:
            return None


@lru_cache(maxsize=8)
def _read_ffmpeg_version(ffmpeg_path: str) -> str | None:
    """Read the FFmpeg version without blocking the async settings route."""
    try:
        result = subprocess.run(
            [ffmpeg_path, "-version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    output = result.stdout or result.stderr
    match = re.search(r"ffmpeg version\s+([^\s]+)", output, re.IGNORECASE)
    return match.group(1) if result.returncode == 0 and match else None


async def _get_ffmpeg_version(settings) -> str | None:
    try:
        path = settings.resolve_ffmpeg_path()
    except (OSError, FileNotFoundError):
        return None
    return await asyncio.to_thread(_read_ffmpeg_version, path)


class GeneralSettingsUpdateRequest(BaseModel):
    """일반 설정 업데이트 요청."""

    download_dir: Optional[str] = Field(None, description="녹화 저장 경로")
    live_download_dir: Optional[str] = Field(None, description="라이브 녹화 저장 경로")
    vod_download_dir: Optional[str] = Field(None, description="다시보기/VOD 저장 경로")
    monitor_interval: Optional[int] = Field(None, ge=5, le=300, description="감시 주기 (초)")
    live_format: Optional[str] = Field(None, description="라이브 녹화 포맷 (ts, mkv, mp4)")
    recording_quality: Optional[str] = Field(None, description="녹화 품질 (best, 1080p, 720p, 480p)")
    split_download_dirs: Optional[bool] = Field(None, description="분할 저장 경로 사용 여부")
    vod_chzzk_dir: Optional[str] = Field(None, description="치지직 VOD/클립 저장 경로 (빈 문자열=기본 경로 사용)")
    vod_external_dir: Optional[str] = Field(None, description="외부 URL 저장 경로 (빈 문자열=기본 경로 사용)")


@router.get("", summary="현재 설정 조회")
@router.get("/", include_in_schema=False)
async def get_current_settings():
    """현재 애플리케이션 설정을 조회합니다 (민감정보 마스킹)."""
    settings = get_settings()
    ffmpeg_version = await _get_ffmpeg_version(settings)
    return {
        "app_name": settings.app_name,
        "download_dir": settings.download_dir,
        "live_download_dir": settings.effective_live_download_dir,
        "vod_download_dir": settings.vod_download_dir or settings.download_dir,
        "ffmpeg_path": settings.ffmpeg_path,
        "ffmpeg_version": ffmpeg_version,
        "streamlink_version": _streamlink_version(),
        "monitor_interval": settings.monitor_interval,
        "host": settings.host,
        "port": settings.port,
        "authenticated": bool(settings.nid_aut and settings.nid_ses),
        "discord_bot_configured": bool(settings.discord_bot_token),
        "keep_download_parts": settings.keep_download_parts,
        "max_record_retries": settings.max_record_retries,
        "chzzk_stream_mode": settings.effective_chzzk_stream_mode,
        "chzzk_time_machine_enabled": settings.effective_chzzk_stream_mode != "standard",
        "chzzk_time_machine_offset": settings.effective_chzzk_time_machine_offset,
        "chzzk_time_machine_shift": settings.effective_chzzk_time_machine_offset,
        "save_live_preview": settings.save_live_preview,
        "live_filename_template": settings.live_filename_template,
        "vod_filename_template": settings.vod_filename_template,
        "live_download_condition": settings.live_download_condition,
        "watchalong_tags": settings.watchalong_tags,
        "live_format": settings.live_format,
        "vod_format": settings.vod_format,
        "recording_quality": settings.recording_quality,
        # VOD 설정
        "vod_max_concurrent": settings.vod_max_concurrent,
        "vod_default_quality": settings.vod_default_quality,
        "vod_max_speed": settings.vod_max_speed,
        # 채팅 설정
        "chat_archive_enabled": settings.chat_archive_enabled,
        # Discord 설정
        "discord_notification_channel_id": settings.discord_notification_channel_id,
        "discord_command_user_ids": settings.discord_command_user_ids,
        "discord_command_channel_id": settings.discord_command_channel_id,
        # 알림 설정 (Webhook URL은 토큰과 동등한 비밀값이므로 설정 여부만 노출)
        "discord_webhook_configured": bool(settings.discord_webhook_url),
        "discord_notify_events": _csv_to_list(settings.discord_notify_events) or ["all"],
        "discord_mention_events": _csv_to_list(settings.discord_mention_events),
        "discord_mention_target": settings.discord_mention_target,
        "discord_notify_ttl": settings.discord_notify_ttl,
        "notification_kinds": [
            {"value": kind.value, "label": label}
            for kind, label in KIND_LABELS.items()
        ],
        # 분할 저장 경로
        "split_download_dirs": settings.split_download_dirs,
        "vod_chzzk_dir": settings.vod_chzzk_dir,
        "vod_external_dir": settings.vod_external_dir,
        # X Spaces 인증
        "x_cookie_file": settings.x_cookie_file,
    }


@router.put("/general", summary="일반 설정 업데이트")
async def update_general_settings(req: GeneralSettingsUpdateRequest):
    """일반 설정(저장 경로, 감시 주기, 포맷, 품질)을 업데이트합니다."""
    settings = get_settings()
    env_updates: dict[str, str] = {}

    # 새 경로 설정은 각각 생성 가능 여부를 확인한 뒤 적용한다.
    for field_name, env_name, label in (
        ("live_download_dir", "LIVE_DOWNLOAD_DIR", "라이브 저장 경로"),
        ("vod_download_dir", "VOD_DOWNLOAD_DIR", "다시보기 저장 경로"),
    ):
        value = getattr(req, field_name)
        if value is None:
            continue
        try:
            Path(value).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise HTTPException(status_code=400, detail=f"{label}를 생성할 수 없습니다: {e}")
        setattr(settings, field_name, value)
        env_updates[env_name] = value

    # ── download_dir ──
    if req.download_dir is not None:
        dir_path = Path(req.download_dir)
        try:
            dir_path.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise HTTPException(
                status_code=400,
                detail=f"저장 경로를 생성할 수 없습니다: {e}",
            )
        settings.download_dir = req.download_dir
        env_updates["DOWNLOAD_DIR"] = req.download_dir

    # ── monitor_interval ──
    if req.monitor_interval is not None:
        settings.monitor_interval = req.monitor_interval
        env_updates["MONITOR_INTERVAL"] = str(req.monitor_interval)

    # ── live_format ──
    if req.live_format is not None:
        fmt = req.live_format.lower()
        if fmt not in VALID_FORMATS:
            raise HTTPException(
                status_code=400,
                detail=f"지원하지 않는 포맷입니다. 사용 가능: {', '.join(VALID_FORMATS)}",
            )
        settings.live_format = fmt
        env_updates["LIVE_FORMAT"] = fmt

    # ── recording_quality ──
    if req.recording_quality is not None:
        quality = req.recording_quality.lower()
        if quality not in VALID_QUALITIES:
            raise HTTPException(
                status_code=400,
                detail=f"지원하지 않는 품질입니다. 사용 가능: {', '.join(VALID_QUALITIES)}",
            )
        settings.recording_quality = quality
        env_updates["RECORDING_QUALITY"] = quality

    # ── split_download_dirs ──
    if req.split_download_dirs is not None:
        settings.split_download_dirs = req.split_download_dirs
        env_updates["SPLIT_DOWNLOAD_DIRS"] = str(req.split_download_dirs).lower()

    # ── vod_chzzk_dir ──
    if req.vod_chzzk_dir is not None:
        if req.vod_chzzk_dir:
            try:
                Path(req.vod_chzzk_dir).mkdir(parents=True, exist_ok=True)
            except OSError as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"치지직 다시보기 저장 경로를 생성할 수 없습니다: {e}",
                )
        settings.vod_chzzk_dir = req.vod_chzzk_dir
        env_updates["VOD_CHZZK_DIR"] = req.vod_chzzk_dir

    # ── vod_external_dir ──
    if req.vod_external_dir is not None:
        if req.vod_external_dir:
            try:
                Path(req.vod_external_dir).mkdir(parents=True, exist_ok=True)
            except OSError as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"외부 다운로드 저장 경로를 생성할 수 없습니다: {e}",
                )
        settings.vod_external_dir = req.vod_external_dir
        env_updates["VOD_EXTERNAL_DIR"] = req.vod_external_dir

    # .env 영구 저장
    if env_updates:
        try:
            _update_env_file(env_updates)
        except Exception as e:
            print(f"설정 파일 저장 실패: {e}")

    return {
        "message": "설정이 업데이트되었습니다.",
        "settings": {
            "download_dir": settings.download_dir,
            "live_download_dir": settings.effective_live_download_dir,
            "vod_download_dir": settings.vod_download_dir or settings.download_dir,
            "monitor_interval": settings.monitor_interval,
            "live_format": settings.live_format,
            "recording_quality": settings.recording_quality,
            "split_download_dirs": settings.split_download_dirs,
            "vod_chzzk_dir": settings.vod_chzzk_dir,
            "vod_external_dir": settings.vod_external_dir,
        },
    }


@router.get("/browse-dirs", summary="디렉토리 탐색")
async def browse_dirs(
    path: str = Query("", description="탐색할 디렉토리 경로. 비어있으면 드라이브 루트 목록 반환"),
):
    """서버 파일시스템의 디렉토리 목록을 반환합니다.

    - path가 비어있으면: Windows 드라이브 루트 목록 반환 (C:\\, D:\\ 등)
    - path가 주어지면: 해당 경로의 하위 폴더 목록 반환
    """
    if not path:
        if platform.system() == "Windows":
            drives = [
                f"{c}:\\"
                for c in string.ascii_uppercase
                if os.path.exists(f"{c}:\\")
            ]
            return {
                "current": "",
                "parent": None,
                "dirs": [{"name": d, "path": d} for d in drives],
            }
        else:
            # Linux/Docker: 가상 파일시스템 제외하고 실제 디렉토리만 탐색
            SKIP_DIRS = {"/proc", "/sys", "/dev", "/run", "/snap"}
            root = Path("/")
            dirs = []
            try:
                for entry in sorted(root.iterdir()):
                    if not entry.is_dir() or str(entry) in SKIP_DIRS:
                        continue
                    dirs.append({"name": entry.name, "path": str(entry)})
            except OSError:
                pass
            return {"current": "/", "parent": None, "dirs": dirs}

    target = Path(path).resolve()
    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=404, detail=f"디렉토리를 찾을 수 없습니다: {path}")

    # 상위 경로 계산:
    # Windows 드라이브 루트(C:\): parent가 자기 자신 → None 처리
    if target.parent == target:
        # 이미 드라이브 루트
        parent_path = None
    else:
        parent_path = str(target.parent)

    # 하위 폴더 목록 (접근 불가 폴더 스킵)
    sub_dirs = []
    try:
        for entry in sorted(target.iterdir()):
            if not entry.is_dir():
                continue
            sub_dirs.append({"name": entry.name, "path": str(entry)})
    except OSError:
        pass

    return {
        "current": str(target),
        "parent": parent_path,
        "dirs": sub_dirs,
    }
