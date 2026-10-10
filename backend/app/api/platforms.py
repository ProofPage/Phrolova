"""
Phrolova: Platforms API Router
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
    extract_youtube_id,
    update_env_file as _update_env_file,
)
from app.engine.base import Platform
from app.api.download_options import ChannelDownloadOptions

router = APIRouter(prefix="/api/platforms", tags=["Platforms"])

# ── 요청 스키마 ──────────────────────────────────────────

class AddPlatformChannelRequest(ChannelDownloadOptions):
    """멀티 플랫폼 채널 추가 요청."""

    platform: str = Field(..., description="플랫폼 (chzzk, youtube, soop, cime)")
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
            detail="지원하지 않는 플랫폼입니다. 사용 가능: chzzk, youtube, soop, cime",
        )

    # URL로 입력해도 ID만 추출
    channel_id = req.channel_id
    if platform == Platform.YOUTUBE:
        channel_id = extract_youtube_id(channel_id)
    elif platform in (Platform.SOOP, Platform.CIME):
        from app.engine.soop import normalize_soop_channel_id
        from app.engine.cime import normalize_cime_channel_id
        try:
            channel_id = (normalize_soop_channel_id if platform == Platform.SOOP else normalize_cime_channel_id)(channel_id)
        except ValueError as error:
            raise HTTPException(400, str(error)) from None

    service = get_recorder_service()
    if platform != Platform.CHZZK and req.download_condition is not None:
        raise HTTPException(status_code=400, detail="같이보기 조건은 치지직에서 지원합니다.")
    return service.add_platform_channel(
        channel_id=channel_id,
        platform=platform,
        auto_record=req.auto_record,
        download_condition=req.download_condition,
        watchalong_tags=req.watchalong_tags,
        **({'recording_quality': req.recording_quality} if req.recording_quality is not None else {}),
            **({'output_format':req.output_format,'output_format_provided':True} if 'output_format' in req.model_fields_set else {}),
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
            **({'recording_quality': req.recording_quality} if req.recording_quality is not None else {}),
            **({'output_format':req.output_format,'output_format_provided':True} if 'output_format' in req.model_fields_set else {}),
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
        "youtube": {
            "enabled": True,
            "authenticated": True,
        },
        "soop": {"enabled": True, "authenticated": bool(settings.soop_cookie_file)},
        "cime": {"enabled": True, "authenticated": bool(settings.cime_cookie_file)},
    }


# ── 플랫폼 인증 설정 ─────────────────────────────────────



import sys as _sys
if getattr(_sys, "frozen", False):
    _COOKIE_SAVE_PATH = Path(_sys.executable).parent / "data" / "platform_cookies.txt"
else:
    _COOKIE_SAVE_PATH = Path(__file__).resolve().parents[2] / "data" / "platform_cookies.txt"






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

@router.get('/{platform}/{channel_id}/qualities', summary='현재 라이브 화질 조회')
async def platform_qualities(platform: str, channel_id: str):
    from app.main import get_recorder_service
    if platform not in ('soop', 'cime'):
        raise HTTPException(400, '지원하지 않는 플랫폼입니다.')
    try:
        engine = get_recorder_service()._conductor._get_engine(Platform(platform))
        status = await engine.check_live_status(channel_id)
        if not status['is_live']:
            return {'qualities': [], 'live': False, 'message': '방송 중일 때 이용 가능한 화질을 확인할 수 있습니다.'}
        return {'qualities': await engine.get_qualities(channel_id), 'live': True}
    except Exception as error:
        from app.engine.platform_auth import redact_media_error
        raise HTTPException(502, redact_media_error(error)) from None

@router.get('/{platform}/cookie', summary='플랫폼 쿠키 파일 상태')
async def platform_cookie_status_api(platform: str):
    from app.engine.platform_auth import platform_cookie_status
    if platform not in ('soop', 'cime'): raise HTTPException(400, '지원하지 않는 플랫폼입니다.')
    return platform_cookie_status(platform)

@router.post('/{platform}/cookie', summary='플랫폼 쿠키 파일 등록')
async def platform_cookie_upload(platform: str, file: UploadFile = File(...)):
    import tempfile
    import os
    from app.engine.platform_auth import read_cookie_jar
    if platform not in ('soop', 'cime'): raise HTTPException(400, '지원하지 않는 플랫폼입니다.')
    content = await file.read(1024 * 1024 + 1)
    if len(content) > 1024 * 1024: raise HTTPException(400, '쿠키 파일은 1MB 이하여야 합니다.')
    destination = _COOKIE_SAVE_PATH.with_name(f'{platform}_cookies.txt')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as directory:
        temporary = Path(directory) / 'cookies.txt'
        temporary.write_bytes(content)
        try:
            jar = read_cookie_jar(temporary, platform, include_expired=True)
            if not len(jar): raise ValueError
            jar.save(str(temporary), ignore_discard=True, ignore_expires=True)
        except (OSError, UnicodeError, ValueError):
            raise HTTPException(400, '해당 플랫폼의 Netscape 형식 쿠키 파일을 선택하세요.') from None
        os.chmod(temporary, 0o600)
        temporary.replace(destination)
    _update_env_file({f'{platform.upper()}_COOKIE_FILE': str(destination)})
    get_settings.cache_clear()
    setattr(get_settings(), f'{platform}_cookie_file', str(destination))
    return await platform_cookie_status_api(platform)

@router.delete('/{platform}/cookie', summary='플랫폼 쿠키 파일 제거')
async def platform_cookie_delete(platform: str):
    if platform not in ('soop', 'cime'): raise HTTPException(400, '지원하지 않는 플랫폼입니다.')
    _COOKIE_SAVE_PATH.with_name(f'{platform}_cookies.txt').unlink(missing_ok=True)
    _update_env_file({f'{platform.upper()}_COOKIE_FILE': ''})
    get_settings.cache_clear()
    setattr(get_settings(), f'{platform}_cookie_file', None)
    return {'configured': False, 'valid': False, 'expired': False, 'message': '쿠키 파일을 제거했습니다.'}
