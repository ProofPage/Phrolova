"""
Rookery: Platforms API Router
멀티 플랫폼 채널 관리 및 플랫폼별 설정 엔드포인트.

기존 /api/stream 라우터는 Chzzk 전용으로 하위 호환 유지.
이 라우터는 멀티 플랫폼 통합 관리를 담당한다.
"""

from __future__ import annotations

from typing import Optional

from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import Field

from app.core.config import get_settings
from app.core.utils import (
    extract_x_id,
    extract_youtube_id,
    update_env_file as _update_env_file,
)
from app.engine.base import Platform
from app.api.download_options import ChannelDownloadOptions

router = APIRouter(prefix="/api/platforms", tags=["Platforms"])


# ── 요청 스키마 ──────────────────────────────────────────

class AddPlatformChannelRequest(ChannelDownloadOptions):
    """멀티 플랫폼 채널 추가 요청."""

    platform: str = Field(..., description="플랫폼 (chzzk, x_spaces, youtube)")
    channel_id: str = Field(..., description="채널 ID (플랫폼별 사용자 ID)")
    auto_record: bool = Field(True, description="방송 시작 시 자동 녹화 여부")




# ── 채널 관리 ────────────────────────────────────────────

@router.post("/channels", summary="멀티 플랫폼 채널 추가")
async def add_platform_channel(req: AddPlatformChannelRequest):
    """플랫폼과 채널 ID를 지정하여 감시 채널을 등록합니다."""
    from app.main import get_recorder_service

    try:
        platform = Platform(req.platform)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"지원하지 않는 플랫폼: '{req.platform}'. 사용 가능: chzzk, x_spaces, youtube",
        )

    # URL로 입력해도 ID만 추출
    channel_id = req.channel_id
    if platform == Platform.X_SPACES:
        channel_id = extract_x_id(channel_id)
    elif platform == Platform.YOUTUBE:
        channel_id = extract_youtube_id(channel_id)

    service = get_recorder_service()
    if platform != Platform.CHZZK and req.download_condition is not None:
        raise HTTPException(status_code=400, detail="같이보기 조건은 치지직에서 지원합니다.")
    return service.add_platform_channel(
        channel_id=channel_id,
        platform=platform,
        auto_record=req.auto_record,
        download_condition=req.download_condition,
        watchalong_tags=req.watchalong_tags,
    )


@router.delete("/channels/{platform}/{channel_id:path}", summary="플랫폼 채널 제거")
async def remove_platform_channel(platform: str, channel_id: str):
    """지정 플랫폼의 채널을 감시 목록에서 제거합니다."""
    from app.main import get_recorder_service

    try:
        platform_enum = Platform(platform)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"지원하지 않는 플랫폼: '{platform}'")

    service = get_recorder_service()
    composite_key = f"{platform_enum.value}:{channel_id}"
    return await service.remove_platform_channel(composite_key)


@router.get("/channels", summary="전체 채널 목록 조회")
async def list_platform_channels():
    """등록된 모든 플랫폼의 채널 목록과 상태를 조회합니다."""
    from app.main import get_recorder_service

    service = get_recorder_service()
    return service.get_channels()


@router.put("/channels/{platform}/{channel_id:path}/download-options", summary="채널 다운로드 설정 수정")
async def update_download_options(platform: str, channel_id: str, req: ChannelDownloadOptions):
    from app.main import get_recorder_service
    try:
        platform_enum = Platform(platform)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="지원하지 않는 플랫폼입니다.") from exc
    if platform_enum != Platform.CHZZK and req.download_condition is not None:
        raise HTTPException(status_code=400, detail="같이보기 조건은 치지직에서 지원합니다.")
    try:
        get_recorder_service().set_download_options(
            f"{platform_enum.value}:{channel_id}", req.auto_record,
            req.download_condition, req.watchalong_tags,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"message": "채널 다운로드 설정이 저장되었습니다.", **req.model_dump()}


@router.patch("/channels/{platform}/{channel_id:path}/auto-record", summary="자동 녹화 토글")
async def toggle_platform_auto_record(platform: str, channel_id: str):
    """채널의 자동 녹화 설정을 ON/OFF 토글합니다."""
    from app.main import get_recorder_service

    try:
        platform_enum = Platform(platform)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"지원하지 않는 플랫폼: '{platform}'")

    service = get_recorder_service()
    composite_key = f"{platform_enum.value}:{channel_id}"
    return await service.toggle_auto_record(composite_key)


@router.post("/scan-now", summary="즉시 스캔")
async def trigger_scan_now(composite_key: Optional[str] = None):
    """설정된 폴링 주기를 무시하고 모든 채널(또는 특정 채널)을 즉시 스캔합니다."""
    from app.main import get_recorder_service

    service = get_recorder_service()
    service.scan_now(composite_key)
    target = composite_key or "전체"
    return {"message": f"즉시 스캔 요청됨: {target}"}


# ── 플랫폼 엔진 상태 ─────────────────────────────────────

@router.get("/status", summary="플랫폼 엔진 활성화 상태 조회")
async def get_platform_status():
    """각 플랫폼 엔진의 설정 완료 여부를 반환합니다."""
    settings = get_settings()
    return {
        "chzzk": {
            "enabled": True,
            "authenticated": bool(settings.nid_aut and settings.nid_ses),
        },
        "x_spaces": {
            "enabled": True,
            "authenticated": bool(settings.x_cookie_file),
            "cookie_file_set": bool(settings.x_cookie_file),
        },
        "youtube": {
            "enabled": True,
            "authenticated": True,
        },
    }


# ── 플랫폼 인증 설정 ─────────────────────────────────────



import sys as _sys
if getattr(_sys, "frozen", False):
    _COOKIE_SAVE_PATH = Path(_sys.executable).parent / "data" / "x_cookies.txt"
else:
    _COOKIE_SAVE_PATH = Path(__file__).resolve().parents[2] / "data" / "x_cookies.txt"


@router.post("/x/cookie", summary="X Spaces 쿠키 파일 업로드")
async def upload_x_cookie(file: UploadFile = File(...)):
    """Netscape 형식 쿠키 파일을 업로드하여 서버에 저장합니다."""
    save_path = _COOKIE_SAVE_PATH
    save_path.parent.mkdir(parents=True, exist_ok=True)

    content = await file.read()
    save_path.write_bytes(content)

    _update_env_file({"X_COOKIE_FILE": str(save_path)})
    get_settings.cache_clear()
    return {"message": "쿠키 파일 업로드 완료.", "path": str(save_path)}


@router.delete("/x/cookie", summary="X Spaces 쿠키 파일 삭제")
async def delete_x_cookie():
    """저장된 쿠키 파일을 삭제하고 설정을 초기화합니다."""
    save_path = _COOKIE_SAVE_PATH
    if save_path.exists():
        save_path.unlink()

    _update_env_file({"X_COOKIE_FILE": ""})
    get_settings.cache_clear()
    return {"message": "쿠키 파일 삭제 완료."}


@router.get("/youtube/cookie")
async def youtube_cookie_status():
    source = get_settings().youtube_cookie_file
    return {"configured": bool(source and Path(source).is_file())}


@router.post("/youtube/cookie")
async def upload_youtube_cookie(file: UploadFile = File(...)):
    import http.cookiejar
    import tempfile

    content = await file.read(1024 * 1024 + 1)
    if len(content) > 1024 * 1024:
        raise HTTPException(400, "쿠키 파일은 1MB 이하여야 합니다.")
    destination = _COOKIE_SAVE_PATH.with_name("youtube_cookies.txt")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as directory:
        temporary = Path(directory) / "cookies.txt"
        try:
            lines = content.decode("utf-8-sig").splitlines()
        except UnicodeError:
            raise HTTPException(400, "Netscape 형식의 유튜브 쿠키 파일을 선택해 주세요.")
        # Browser exporters use 0 for session cookies; CookieJar expects an empty expiry.
        normalized = []
        for line in lines:
            fields = line.split("\t")
            if len(fields) == 7 and fields[4] == "0":
                fields[4] = ""
                line = "\t".join(fields)
            normalized.append(line)
        temporary.write_text("\n".join(normalized) + "\n", encoding="utf-8")
        jar = http.cookiejar.MozillaCookieJar(str(temporary))
        try:
            jar.load(ignore_discard=True, ignore_expires=False)
        except (OSError, ValueError, UnicodeError):
            raise HTTPException(400, "Netscape 형식의 유튜브 쿠키 파일을 선택해 주세요.")
        for cookie in list(jar):
            domain = cookie.domain.lstrip(".").lower()
            if not any(domain == allowed or domain.endswith("." + allowed)
                       for allowed in ("youtube.com", "google.com")):
                jar.clear(cookie.domain, cookie.path, cookie.name)
        if not len(jar):
            raise HTTPException(400, "사용 가능한 유튜브 로그인 쿠키가 없습니다.")
        jar.save(ignore_discard=True)
        temporary.replace(destination)
    _update_env_file({"YOUTUBE_COOKIE_FILE": str(destination)})
    get_settings.cache_clear()
    return {"configured": True}


@router.delete("/youtube/cookie")
async def delete_youtube_cookie():
    _COOKIE_SAVE_PATH.with_name("youtube_cookies.txt").unlink(missing_ok=True)
    _update_env_file({"YOUTUBE_COOKIE_FILE": ""})
    get_settings.cache_clear()
    return {"configured": False}
