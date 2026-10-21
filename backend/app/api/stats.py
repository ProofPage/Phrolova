"""
Phrolova: Stats API Router
라이브 녹화 및 VOD 다운로드 통계를 집계하여 반환한다.
"""

from __future__ import annotations

import shutil
import os
from pathlib import Path

from fastapi import APIRouter

from app.core.config import get_settings
from app.store.repositories import LiveHistoryRepository, VodRepository

router = APIRouter(prefix="/api/stats", tags=["Stats"])


def _disk_volume_info(path: Path) -> dict[str, str]:
    """저장 위치의 볼륨 정보를 읽고, 확인할 수 없는 항목은 비워 둡니다."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        get_mount = kernel.GetVolumePathNameW
        get_mount.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        get_mount.restype = wintypes.BOOL
        get_info = kernel.GetVolumeInformationW
        get_info.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD,
                             ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
                             ctypes.POINTER(wintypes.DWORD), wintypes.LPWSTR, wintypes.DWORD]
        get_info.restype = wintypes.BOOL
        mount = ctypes.create_unicode_buffer(32768)
        if not get_mount(str(path.resolve()), mount, len(mount)):
            return {}
        filesystem = ctypes.create_unicode_buffer(256)
        get_info(mount.value, None, 0, None, None, None, filesystem, len(filesystem))
        return {"disk_mountpoint": mount.value, "disk_filesystem": filesystem.value}

    mount = path.resolve()
    while mount.parent != mount and not mount.is_mount():
        mount = mount.parent
    return {"disk_mountpoint": str(mount), "disk_filesystem": ""}


@router.get("", summary="통계 대시보드 데이터 조회")
@router.get("/", include_in_schema=False)
async def get_stats():
    """라이브 녹화 이력, VOD 다운로드 이력, 저장소 사용량을 집계하여 반환합니다."""
    from app.main import get_recorder_service

    settings = get_settings()

    # ── RecorderService에서 Conductor/VodEngine 접근 ──
    try:
        service = get_recorder_service()
        conductor = service._conductor
        vod_engine = service._vod_engine
    except RuntimeError:
        conductor = None
        vod_engine = None

    # ── 라이브 이력 집계 ──────────────────────────────

    live_history: list[dict] = []
    if conductor is not None:
        live_history = conductor.get_live_history()
    else:
        # 서버 미초기화 상태에서도 저장소에서 직접 읽는다.
        try:
            live_history = LiveHistoryRepository().list_sessions()
        except Exception:
            live_history = []

    def _normalize_stat_key(raw_key: str, raw_platform: str | None = None) -> tuple[str, str, str]:
        from app.core.utils import extract_youtube_id
        if ":" in raw_key:
            plat, cid = raw_key.split(":", 1)
        else:
            plat = raw_platform or "chzzk"
            cid = raw_key

        if plat == "youtube":
            clean_cid = extract_youtube_id(cid)
        elif plat == "rplay":
            from app.engine.rplay_live import normalize_rplay_channel_id
            try:
                clean_cid = normalize_rplay_channel_id(cid)
            except Exception:
                clean_cid = cid
        elif plat == "chzzk":
            from app.core.utils import extract_channel_id
            clean_cid = extract_channel_id(cid)
        else:
            clean_cid = cid

        norm_comp_key = f"{plat}:{clean_cid}" if plat != "chzzk" else clean_cid
        return norm_comp_key, plat, clean_cid

    registered_channels: dict[str, dict] = {}
    if conductor is not None:
        for st in conductor.get_all_status():
            k = st.get("composite_key") or st.get("channel_id")
            norm_k, _, _ = _normalize_stat_key(k, st.get("platform"))
            registered_channels[norm_k] = st

    # 채널별 집계
    channel_live: dict[str, dict] = {}
    for entry in live_history:
        entry_key = entry.get("composite_key") or entry.get("channel_id", "unknown")
        norm_key, plat, clean_cid = _normalize_stat_key(entry_key, entry.get("platform"))
        reg_info = registered_channels.get(norm_key) or {}
        ch_name = entry.get("channel_name") or reg_info.get("channel_name") or clean_cid
        if ch_name.startswith(f"{plat}:"):
            ch_name = reg_info.get("channel_name") or clean_cid

        if norm_key not in channel_live:
            channel_live[norm_key] = {
                "channel_id": clean_cid,
                "composite_key": norm_key,
                "platform": plat,
                "channel_name": ch_name,
                "session_count": 0,
                "total_duration_seconds": 0,
                "total_size_bytes": 0,
                "live_detected_count": 0,
            }
        elif channel_live[norm_key]["channel_name"] == clean_cid and ch_name != clean_cid:
            channel_live[norm_key]["channel_name"] = ch_name

        channel_live[norm_key]["session_count"] += 1
        channel_live[norm_key]["total_duration_seconds"] += entry.get("duration_seconds", 0)
        channel_live[norm_key]["total_size_bytes"] += entry.get("file_size_bytes", 0)

    # 라이브 감지 횟수 (최근 30일, 하루 1회) 병합
    live_detections: dict[str, int] = {}
    if conductor is not None:
        live_detections = conductor.get_live_detections()

    for raw_k, count in live_detections.items():
        norm_key, plat, clean_cid = _normalize_stat_key(raw_k)
        reg_info = registered_channels.get(norm_key) or {}
        ch_name = reg_info.get("channel_name") or clean_cid
        if norm_key not in channel_live:
            channel_live[norm_key] = {
                "channel_id": clean_cid,
                "composite_key": norm_key,
                "platform": plat,
                "channel_name": ch_name,
                "session_count": 0,
                "total_duration_seconds": 0,
                "total_size_bytes": 0,
                "live_detected_count": count,
            }
        else:
            channel_live[norm_key]["live_detected_count"] += count
            if channel_live[norm_key]["channel_name"] == clean_cid and ch_name != clean_cid:
                channel_live[norm_key]["channel_name"] = ch_name

    # 세션 수 기준 내림차순 정렬
    by_channel = sorted(
        channel_live.values(),
        key=lambda x: x["session_count"],
        reverse=True,
    )

    live_total_duration = sum(e.get("duration_seconds", 0) for e in live_history)
    live_total_size = sum(e.get("file_size_bytes", 0) for e in live_history)
    active_recordings = 0
    if conductor is not None:
        active_recordings = sum(
            1
            for status in conductor.get_all_status()
            if (status.get("recording") or {}).get("is_recording")
        )

    # 최근 10개 세션 (ended_at 기준 내림차순)
    recent_sessions = sorted(
        live_history,
        key=lambda x: x.get("ended_at") or "",
        reverse=True,
    )[:10]

    # ── VOD 이력 집계 ─────────────────────────────────

    try:
        vod_history: list[dict] = VodRepository().list_all()
    except Exception:
        vod_history = []

    completed_vod = [v for v in vod_history if v.get("state") == "completed"]
    vod_total_size = 0  # VOD 이력에는 file_size 없음

    # URL로 chzzk/external 분류
    chzzk_count = sum(1 for v in completed_vod if "chzzk.naver.com" in v.get("url", ""))
    external_count = len(completed_vod) - chzzk_count

    # ── 저장소 사용량 ─────────────────────────────────

    storage: dict = {
        "download_dir": settings.effective_live_download_dir,
        # 기존 필드는 유지하고 실제 녹화·다운로드 엔진이 쓰는 경로를 함께 제공한다.
        "live_download_dir": settings.effective_live_download_dir,
        "vod_download_dir": settings.effective_vod_download_dir(is_chzzk=False),
        "vod_chzzk_dir": settings.effective_vod_download_dir(is_chzzk=True),
        "used_bytes": 0,
        "total_bytes": 0,
        "free_bytes": 0,
        "usage_available": False,
        "disk_mountpoint": "",
        "disk_filesystem": "",
    }

    download_path = Path(settings.effective_live_download_dir)
    if download_path.exists():
        try:
            usage = shutil.disk_usage(str(download_path))
            storage["used_bytes"] = usage.used
            storage["total_bytes"] = usage.total
            storage["free_bytes"] = usage.free
            storage["usage_available"] = usage.total > 0
        except Exception:
            pass

    if storage["usage_available"]:
        try:
            storage.update(_disk_volume_info(download_path))
        except (OSError, ValueError):
            pass

    return {
        "live": {
            "total_duration_seconds": live_total_duration,
            "total_size_bytes": live_total_size,
            "total_sessions": len(live_history),
            "active_recordings": active_recordings,
            "by_channel": by_channel,
        },
        "vod": {
            "total_completed": len(completed_vod),
            "total_size_bytes": vod_total_size,
            "by_type": {
                "chzzk": chzzk_count,
                "external": external_count,
            },
        },
        "storage": storage,
        "recent_sessions": recent_sessions,
    }
