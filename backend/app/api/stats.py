"""
Phrolova: Stats API Router
라이브 녹화 및 VOD 다운로드 통계를 집계하여 반환한다.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter

from app.core.config import get_settings
from app.store.repositories import LiveHistoryRepository, VodRepository

router = APIRouter(prefix="/api/stats", tags=["Stats"])


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

    # 채널별 집계
    channel_live: dict[str, dict] = {}
    for entry in live_history:
        cid = entry.get("channel_id", "unknown")
        if cid not in channel_live:
            channel_live[cid] = {
                "channel_id": cid,
                "channel_name": entry.get("channel_name", cid),
                "session_count": 0,
                "total_duration_seconds": 0,
                "total_size_bytes": 0,
            }
        channel_live[cid]["session_count"] += 1
        channel_live[cid]["total_duration_seconds"] += entry.get("duration_seconds", 0)
        channel_live[cid]["total_size_bytes"] += entry.get("file_size_bytes", 0)

    # 라이브 감지 횟수 (최근 30일, 하루 1회) 병합
    live_detections: dict[str, int] = {}
    if conductor is not None:
        live_detections = conductor.get_live_detections()

    for cid, ch in channel_live.items():
        ch["live_detected_count"] = live_detections.get(cid, 0)

    # 라이브 채널 목록에 없지만 감지 기록이 있는 채널도 포함
    for cid, count in live_detections.items():
        if cid not in channel_live:
            channel_live[cid] = {
                "channel_id": cid,
                "channel_name": cid,
                "session_count": 0,
                "total_duration_seconds": 0,
                "total_size_bytes": 0,
                "live_detected_count": count,
            }

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
        "used_bytes": 0,
        "total_bytes": 0,
        "free_bytes": 0,
    }

    download_path = Path(settings.effective_live_download_dir)
    if download_path.exists():
        try:
            usage = shutil.disk_usage(str(download_path))
            storage["used_bytes"] = usage.used
            storage["total_bytes"] = usage.total
            storage["free_bytes"] = usage.free
        except Exception:
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
