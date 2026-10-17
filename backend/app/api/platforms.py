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

    platform: str = Field(..., description="플랫폼 (chzzk, youtube, cime, kick, twitch, tiktok, bilibili, pandalive, popkontv, rplay)")
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
            detail="지원하지 않는 플랫폼입니다. 사용 가능: chzzk, youtube, cime, kick, twitch, tiktok, bilibili, pandalive, popkontv, rplay",
        )

    # URL로 입력해도 ID만 추출
    channel_id = req.channel_id
    if platform == Platform.YOUTUBE:
        channel_id = extract_youtube_id(channel_id)
    elif platform == Platform.RPLAY:
        from app.engine.rplay_live import normalize_rplay_channel_id
        try:
            channel_id = normalize_rplay_channel_id(channel_id)
        except ValueError as error:
            raise HTTPException(400, str(error)) from None
    elif platform == Platform.POPKONTV:
        from app.engine.popkontv import normalize_popkontv_channel_id
        try:
            channel_id = normalize_popkontv_channel_id(channel_id)
        except ValueError as error:
            raise HTTPException(400, str(error)) from None
    elif platform == Platform.PANDALIVE:
        from app.engine.pandalive import normalize_pandalive_channel_id
        try:
            channel_id = normalize_pandalive_channel_id(channel_id)
        except ValueError as error:
            raise HTTPException(400, str(error)) from None
    elif platform == Platform.BILIBILI:
        from app.engine.bilibili import normalize_bilibili_channel_id
        try:
            channel_id = normalize_bilibili_channel_id(channel_id)
        except ValueError as error:
            raise HTTPException(400, str(error)) from None
    elif platform == Platform.TIKTOK:
        from app.engine.tiktok import normalize_tiktok_channel_id
        try:
            channel_id = normalize_tiktok_channel_id(channel_id)
        except ValueError as error:
            raise HTTPException(400, str(error)) from None
    elif platform == Platform.TWITCH:
        from app.engine.twitch import normalize_twitch_channel_id
        try:
            channel_id = normalize_twitch_channel_id(channel_id)
        except ValueError as error:
            raise HTTPException(400, str(error)) from None
    elif platform == Platform.KICK:
        from app.engine.kick import normalize_kick_channel_id
        try:
            channel_id = normalize_kick_channel_id(channel_id)
        except ValueError as error:
            raise HTTPException(400, str(error)) from None
    elif platform == Platform.CIME:
        from app.engine.cime import normalize_cime_channel_id
        try:
            channel_id = normalize_cime_channel_id(channel_id)
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
    from app.engine.rplay import session_status
    return {
        "chzzk": {
            "enabled": True,
            "authenticated": bool(settings.nid_aut and settings.nid_ses),
        },
        "youtube": {
            "enabled": True,
            "authenticated": True,
        },
        "cime": {"enabled": True, "authenticated": bool(settings.cime_cookie_file)},
        "kick": {"enabled": True, "authenticated": bool(settings.kick_cookie_file)},
        "twitch": {"enabled": True, "authenticated": bool(settings.twitch_cookie_file)},
        "tiktok": {"enabled": True, "authenticated": bool(settings.tiktok_cookie_file)},
        "bilibili": {"enabled": True, "authenticated": bool(settings.bilibili_cookie_file)},
        "pandalive": {"enabled": True, "authenticated": bool(settings.pandalive_cookie_file)},
        "popkontv": {"enabled": True, "authenticated": bool(settings.popkontv_cookie_file)},
        "hearheart": {"enabled": True, "authenticated": bool(settings.hearheart_cookie_file)},
        "rplay": {"enabled": True, "authenticated": session_status()["valid"]},
    }


# ── 플랫폼 인증 설정 ─────────────────────────────────────



import sys as _sys
if getattr(_sys, "frozen", False):
    _COOKIE_SAVE_PATH = Path(_sys.executable).parent / "data" / "platform_cookies.txt"
else:
    _COOKIE_SAVE_PATH = Path(__file__).resolve().parents[2] / "data" / "platform_cookies.txt"






def _save_credential(destination: Path, content: bytes | None, field: str):
    """Commit the owned credential file and its configuration, or restore the old file."""
    import os
    import tempfile
    destination.parent.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix='.credential-', dir=destination.parent))
    temporary, backup = directory / 'new', directory / 'previous'
    changed = False
    committed = False
    try:
        if destination.exists():
            destination.replace(backup)
            changed = True
        if content is not None:
            temporary.write_bytes(content)
            os.chmod(temporary, 0o600)
            temporary.replace(destination)
            changed = True
        _update_env_file({field.upper(): str(destination) if content is not None else ''}, raise_on_error=True)
        committed = True
    except Exception:
        try:
            if backup.exists():
                backup.replace(destination)
            elif changed:
                destination.unlink(missing_ok=True)
        except OSError:
            # Preserve the backup for manual recovery rather than deleting the last good credentials.
            raise HTTPException(500, f'인증 설정을 복구하지 못했습니다. 복구 파일 위치: {backup}') from None
        raise HTTPException(500, '인증 설정을 저장하지 못했습니다. 저장 위치의 권한과 여유 공간을 확인하세요.') from None
    finally:
        try:
            temporary.unlink(missing_ok=True)
            if committed:
                backup.unlink(missing_ok=True)
            if not backup.exists():
                directory.rmdir()
        except OSError:
            pass
    get_settings.cache_clear()
    setattr(get_settings(), field, str(destination) if content is not None else None)


@router.get("/youtube/cookie")
async def youtube_cookie_status():
    from app.engine.platform_auth import cookie_file_status
    source = get_settings().youtube_cookie_file
    return cookie_file_status(Path(source) if source else None, "youtube")


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
        _save_credential(destination, temporary.read_bytes(), "youtube_cookie_file")
    return await youtube_cookie_status()


@router.delete("/youtube/cookie")
async def delete_youtube_cookie():
    _save_credential(_COOKIE_SAVE_PATH.with_name("youtube_cookies.txt"), None, "youtube_cookie_file")
    return await youtube_cookie_status()


@router.get("/chzzk/cookie", summary="치지직 쿠키 등록 상태")
async def chzzk_cookie_status():
    settings = get_settings()
    configured = bool(settings.nid_aut and settings.nid_ses)
    return {
        "configured": configured, "valid": None if configured else False,
        "expired": False,
        "message": "쿠키가 등록되었습니다. 상태 확인으로 로그인 여부를 확인하세요."
        if configured else "쿠키가 등록되지 않았습니다.",
    }


@router.post("/chzzk/cookie", summary="치지직 쿠키 파일 등록")
async def upload_chzzk_cookie(file: UploadFile = File(...)):
    import tempfile
    from app.engine.platform_auth import read_cookie_jar, chzzk_login_values
    from app.main import get_recorder_service

    content = await file.read(1024 * 1024 + 1)
    if len(content) > 1024 * 1024:
        raise HTTPException(400, "쿠키 파일은 1MB 이하여야 합니다.")
    with tempfile.TemporaryDirectory(prefix="phrolova_chzzk_cookie_") as directory:
        temporary = Path(directory) / "cookies.txt"
        temporary.write_bytes(content)
        try:
            values = chzzk_login_values(read_cookie_jar(temporary, "chzzk"))
        except (OSError, UnicodeError, ValueError):
            raise HTTPException(400, "사용 가능한 치지직 로그인 쿠키가 포함된 Netscape 형식 파일을 선택하세요.") from None
    # Reuse the existing authentication path for Streamlink, live detection and VOD.
    try:
        get_recorder_service().update_cookies(values["NID_AUT"], values["NID_SES"])
    except OSError:
        raise HTTPException(500, "인증 설정을 저장하지 못했습니다. 저장 위치의 권한과 여유 공간을 확인하세요.") from None
    return await chzzk_cookie_status()


@router.post("/chzzk/cookie/check", summary="치지직 로그인 상태 확인")
async def check_chzzk_cookie():
    from app.api.settings.auth import test_cookies
    status = await chzzk_cookie_status()
    if not status["configured"]:
        return status
    try:
        result = await test_cookies()
    except HTTPException:
        raise HTTPException(502, "치지직 로그인 상태를 확인하지 못했습니다. 잠시 후 다시 확인하세요.") from None
    user = result.get("user_status") or {}
    # An HTTP 200 response with empty/anonymous content is not a logged-in user.
    valid = bool(result.get("valid") and user and user.get("loggedIn") is not False)
    return {"configured": True, "valid": valid, "expired": not valid,
            "message": "로그인 상태가 확인되었습니다." if valid else "쿠키가 만료되었거나 유효하지 않습니다. 쿠키 파일을 갱신하세요."}


@router.delete("/chzzk/cookie", summary="치지직 쿠키 제거")
async def delete_chzzk_cookie():
    from app.main import get_recorder_service
    try:
        get_recorder_service().update_cookies("", "")
    except OSError:
        raise HTTPException(500, "인증 설정을 저장하지 못했습니다. 저장 위치의 권한과 여유 공간을 확인하세요.") from None
    return await chzzk_cookie_status()

@router.get('/{platform}/{channel_id}/qualities', summary='현재 라이브 화질 조회')
async def platform_qualities(platform: str, channel_id: str):
    from app.main import get_recorder_service
    if platform not in ('cime', 'kick', 'twitch', 'tiktok', 'bilibili', 'pandalive', 'popkontv', 'rplay'):
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
    if platform not in ('cime', 'kick', 'twitch', 'tiktok', 'bilibili', 'pandalive', 'popkontv', 'tvchak', 'hearheart'): raise HTTPException(400, '지원하지 않는 플랫폼입니다.')
    return platform_cookie_status(platform)


@router.get('/rplay/session', summary='알플레이 세션 파일 등록 상태')
async def rplay_session_status():
    from app.engine.rplay import session_status
    return session_status()


@router.post('/rplay/session', summary='알플레이 세션 JSON 파일 등록')
async def rplay_session_upload(file: UploadFile = File(...)):
    import json
    import os
    import tempfile
    from app.engine.rplay import parse_session
    try:
        session = parse_session(await file.read(16 * 1024 + 1))
    except ValueError as error:
        raise HTTPException(400, str(error)) from None
    destination = _COOKIE_SAVE_PATH.with_name('rplay_session.json')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as directory:
        temporary = Path(directory) / 'session.json'
        temporary.write_text(json.dumps(session), encoding='utf-8')
        os.chmod(temporary, 0o600)
        _save_credential(destination, temporary.read_bytes(), 'rplay_session_file')
    return await rplay_session_status()


@router.delete('/rplay/session', summary='알플레이 등록 세션 제거')
async def rplay_session_delete():
    # An environment-configured external file belongs to the user. Only remove our own copy.
    _save_credential(_COOKIE_SAVE_PATH.with_name('rplay_session.json'), None, 'rplay_session_file')
    return await rplay_session_status()

@router.post('/{platform}/cookie', summary='플랫폼 쿠키 파일 등록')
async def platform_cookie_upload(platform: str, file: UploadFile = File(...)):
    import tempfile
    import os
    from app.engine.platform_auth import read_cookie_jar
    if platform not in ('cime', 'kick', 'twitch', 'tiktok', 'bilibili', 'pandalive', 'popkontv', 'tvchak', 'hearheart'): raise HTTPException(400, '지원하지 않는 플랫폼입니다.')
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
        _save_credential(destination, temporary.read_bytes(), f'{platform}_cookie_file')
    return await platform_cookie_status_api(platform)

@router.delete('/{platform}/cookie', summary='플랫폼 쿠키 파일 제거')
async def platform_cookie_delete(platform: str):
    if platform not in ('cime', 'kick', 'twitch', 'tiktok', 'bilibili', 'pandalive', 'popkontv', 'tvchak', 'hearheart'): raise HTTPException(400, '지원하지 않는 플랫폼입니다.')
    _save_credential(_COOKIE_SAVE_PATH.with_name(f'{platform}_cookies.txt'), None, f'{platform}_cookie_file')
    return {'configured': False, 'valid': False, 'expired': False, 'message': '쿠키 파일을 제거했습니다.'}
