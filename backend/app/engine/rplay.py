"""RPLAY video identity and explicitly imported, API-scoped sessions."""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
import logging
import re
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from yt_dlp.utils import ExtractorError

from app.core.config import get_settings

ORIGIN = 'https://rplay.live'
API = 'https://api.rplay.live/content'
LOGIN_API = 'https://api.rplay.live/rplay/account/login'
REFRESH_API = 'https://api.rplay.live/rplay/account/refresh-token'
HOSTS = {'rplay.live', 'www.rplay.live'}
MEDIA_HOSTS = {'api.rplay.live', 'api2.rplay.live', 'pb.rplay.live', 'pb2.rplay.live', 'pb3.rplay.live', 'pb.sbcloudsec.net'}

_log = logging.getLogger(__name__)
_refresh_lock = threading.Lock()


def canonical_rplay_video_url(value: str) -> str:
    try:
        parts = urlsplit(value.strip())
        match = re.fullmatch(r'/play/([a-fA-F0-9]{24})/?', parts.path)
        if (parts.scheme not in ('http', 'https') or parts.hostname not in HOSTS
                or parts.username or parts.password or parts.port not in (None, 80, 443) or not match):
            raise ValueError
        return f'{ORIGIN}/play/{match[1].lower()}'
    except ValueError:
        raise ValueError('알플레이 영상 링크(rplay.live/play/영상 ID)를 입력하세요.') from None


def parse_session(content: bytes) -> dict[str, str]:
    """Accept an explicit export with access token and optional refresh token for auto-renewal."""
    try:
        if len(content) > 16 * 1024:
            raise ValueError
        data = json.loads(content.decode('utf-8-sig'))
        if not isinstance(data, dict):
            raise ValueError
        token = data.get('accessToken') or data.get('token')
        oid = data.get('requestorOid') or data.get('oid') or data.get('_id')
        login_type = data.get('loginType') or data.get('accountType') or 'plax'
        refresh_token = data.get('refreshToken')
        if (not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9._~+/=-]{16,8192}', token)
                or not isinstance(oid, str) or not re.fullmatch(r'[a-fA-F0-9]{24}', oid)
                or not isinstance(login_type, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,32}', login_type)):
            raise ValueError
        result = {'accessToken': token, 'requestorOid': oid.lower(), 'loginType': login_type}
        if refresh_token is not None:
            if not isinstance(refresh_token, str) or not re.fullmatch(r'[A-Za-z0-9._~+/=-]{16,8192}', refresh_token):
                raise ValueError
            result['refreshToken'] = refresh_token
        return result
    except (ValueError, UnicodeError):
        raise ValueError('accessToken과 requestorOid가 포함된 알플레이 세션 JSON 파일을 선택하세요.') from None


def login_with_credentials(email: str, password: str) -> dict[str, str]:
    """알플레이 계정 이메일과 비밀번호로 로그인하여 세션 정보를 발급받는다."""
    email = email.strip()
    if not email or not password:
        raise ValueError('이메일과 비밀번호를 모두 입력하세요.')

    headers = {
        'Content-Type': 'application/json',
        'Origin': ORIGIN,
        'Referer': ORIGIN + '/',
        'platform-type': 'rplay',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
    }
    body = {
        'accountType': 'plax',
        'email': email,
        'password': password,
        'platformType': 'rplay',
    }
    try:
        with httpx.Client(timeout=15, follow_redirects=False) as client:
            resp = client.post(LOGIN_API, json=body, headers=headers)
        if resp.status_code == 403:
            raise ValueError('가입되지 않은 이메일 주소입니다.')
        if resp.status_code == 401 or resp.status_code != 200:
            raise ValueError('이메일 또는 비밀번호가 올바르지 않습니다.')
        data = resp.json()
        token = data.get('token') or data.get('accessToken')
        user = data.get('user') or {}
        oid = data.get('oid') or user.get('oid') or user.get('_id') or data.get('_id')
        refresh_token = data.get('refreshToken')
        if not token or not oid:
            raise ValueError('로그인 사용자 세션 정보를 확인할 수 없습니다.')
        session = {
            'accessToken': str(token),
            'requestorOid': str(oid).lower(),
            'loginType': data.get('accountType') or data.get('loginType') or 'plax',
        }
        if refresh_token:
            session['refreshToken'] = str(refresh_token)
        return session
    except httpx.HTTPError as err:
        raise ValueError(f'알플레이 서버 연결에 실패했습니다: {err}') from None


def session_token_exp(session: dict) -> float | None:
    try:
        payload = session['accessToken'].split('.')[1]
        data = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
        return float(data['exp'])
    except (KeyError, IndexError, ValueError, TypeError):
        return None


def session_needs_refresh(session: dict, margin_seconds: float = 300.0) -> bool:
    """True if token is expired or within 5 minutes of expiring."""
    exp = session_token_exp(session)
    if exp is None:
        return False
    return exp - time.time() <= margin_seconds


def session_expired(session: dict) -> bool:
    # This is a local expiry hint, not JWT signature verification; RPLAY validates the token.
    exp = session_token_exp(session)
    if exp is None:
        return False
    return exp <= time.time() + 30


def refresh_session_token(session: dict) -> dict[str, str]:
    """Exchange refreshToken for a fresh accessToken and atomically update the session file.
    Matches RPLAY web player behavior (POST /rplay/account/refresh-token)."""
    with _refresh_lock:
        current = read_session()
        if current:
            if current.get('requestorOid') != session.get('requestorOid'):
                raise ExtractorError('알플레이 계정이 변경되었습니다. 최신 세션으로 다시 시도하세요.', expected=True)
            if current.get('accessToken') != session.get('accessToken') and not session_expired(current):
                return current
            session = current
        return _refresh_session_token(session)


def _refresh_session_token(session: dict) -> dict[str, str]:
    refresh_token = session.get('refreshToken')
    if not refresh_token:
        raise ExtractorError('알플레이 세션이 만료되었습니다. 설정에서 세션 파일을 갱신하세요.', expected=True)
    headers = {
        'Origin': ORIGIN,
        'Referer': ORIGIN + '/',
        'platform-type': 'rplay',
        'refresh-token': refresh_token,
        'User-Agent': 'Mozilla/5.0',
    }
    payload = {'requestorOid': session['requestorOid']}
    try:
        with httpx.Client(timeout=15, follow_redirects=False) as client:
            response = client.post(REFRESH_API, json=payload, headers=headers)
        if response.status_code in (401, 403):
            raise ExtractorError('알플레이 리프레시 토큰이 만료되었거나 거부되었습니다. 설정에서 세션 파일을 다시 등록하세요.', expected=True)
        response.raise_for_status()
        data = response.json()
        new_access = data.get('accessToken')
        if not isinstance(new_access, str) or not re.fullmatch(r'[A-Za-z0-9._~+/=-]{16,8192}', new_access):
            raise ExtractorError('알플레이 토큰 갱신 응답 형식이 올바르지 않습니다.', expected=True)
        updated = dict(session)
        updated['accessToken'] = new_access
        new_refresh = data.get('refreshToken')
        if isinstance(new_refresh, str) and re.fullmatch(r'[A-Za-z0-9._~+/=-]{16,8192}', new_refresh):
            updated['refreshToken'] = new_refresh
        _persist_session(updated)
        return updated
    except httpx.HTTPError as err:
        raise ExtractorError(f'알플레이 토큰 갱신 서버 연결에 실패했습니다: {err}', expected=True) from None
    except ValueError:
        raise ExtractorError('알플레이 토큰 갱신 응답 형식이 올바르지 않습니다.', expected=True) from None


def _persist_session(session: dict[str, str]) -> None:
    source = get_settings().rplay_session_file
    if not source:
        return
    path = Path(source)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(session, indent=2, ensure_ascii=False).encode('utf-8')
        with tempfile.NamedTemporaryFile('wb', dir=path.parent, delete=False) as tmp:
            tmp.write(raw)
            tmp_path = Path(tmp.name)
        tmp_path.replace(path)
    except OSError as err:
        _log.warning('알플레이 세션 파일 자동 저장 실패: %s', err)


def read_session(*, auto_refresh: bool = False) -> dict[str, str] | None:
    source = get_settings().rplay_session_file
    if not source:
        return None
    try:
        with Path(source).open('rb') as stream:
            session = parse_session(stream.read(16 * 1024 + 1))
    except (OSError, ValueError):
        raise ExtractorError('알플레이 세션 파일을 읽지 못했습니다. 설정에서 다시 등록하세요.', expected=True) from None

    if auto_refresh and session.get('refreshToken') and session_needs_refresh(session):
        try:
            return refresh_session_token(session)
        except Exception as err:
            _log.warning('알플레이 세션 사전 갱신 실패 (기존 토큰 계속 시도): %s', err)

    return session


def session_status() -> dict:
    configured = bool(get_settings().rplay_session_file)
    try:
        session = read_session(auto_refresh=True)
        expired = bool(session and session_expired(session))
        return {'configured': configured, 'valid': bool(session and not expired), 'expired': expired}
    except ExtractorError:
        return {'configured': configured, 'valid': False, 'expired': False}


def valid_media_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parts = urlsplit(value)
        return (parts.scheme == 'https' and parts.hostname in MEDIA_HOSTS
                and not parts.username and not parts.password and parts.port in (None, 443)
                and not any(c in value for c in '\r\n\\'))
    except ValueError:
        return False


def video_metadata(url: str) -> dict:
    canonical = canonical_rplay_video_url(url)
    oid = canonical.rsplit('/', 1)[-1]
    params = {'contentOid': oid, 'status': 'published', 'omitComments': 'true', 'requestCanView': 'true'}
    headers = {'Origin': ORIGIN, 'Referer': canonical, 'platform-type': 'rplay'}
    session = read_session(auto_refresh=True)
    if session:
        if session_expired(session):
            raise ExtractorError('알플레이 로그인 세션이 만료되었습니다. 설정에서 세션 파일을 갱신하세요.', expected=True)
        headers['Authorization'] = session['accessToken']
        params.update(requestorOid=session['requestorOid'], loginType=session['loginType'])
    try:
        # Account authorization must never follow a redirect or reach a media CDN.
        with httpx.Client(timeout=20, follow_redirects=False) as client:
            response = client.get(API, params=params, headers=headers)
        if response.status_code == 401 and session and session.get('refreshToken'):
            try:
                session = refresh_session_token(session)
                headers['Authorization'] = session['accessToken']
                params.update(requestorOid=session['requestorOid'], loginType=session['loginType'])
                with httpx.Client(timeout=20, follow_redirects=False) as client:
                    response = client.get(API, params=params, headers=headers)
            except Exception:
                pass
        if response.status_code == 401:
            raise ExtractorError('알플레이 로그인 세션이 유효하지 않습니다. 설정에서 다시 등록하세요.', expected=True)
        if response.status_code in (403, 444, 999):
            raise ExtractorError('알플레이에서 이 요청을 제한했습니다. 계정의 시청 권한과 접속 환경을 확인하세요.', expected=True)
        if response.status_code in (404, 410):
            raise ExtractorError('알플레이 영상이 삭제되었거나 공개되지 않았습니다.', expected=True)
        if response.is_redirect:
            raise ExtractorError('알플레이 API가 다른 주소로 이동했습니다. 인증 정보를 전송하지 않았습니다.', expected=True)
        response.raise_for_status()
        item = response.json()
    except httpx.TimeoutException:
        raise ExtractorError('알플레이 영상 정보 요청 시간이 초과되었습니다.', expected=True) from None
    except (httpx.HTTPError, ValueError):
        raise ExtractorError('알플레이 영상 정보를 불러오지 못했습니다. 잠시 후 다시 시도하세요.', expected=True) from None
    if not isinstance(item, dict) or item.get('_id') != oid:
        raise ExtractorError('알플레이 영상 식별 정보가 다릅니다.', expected=True)
    if item.get('deleted') is True or item.get('blocked') is True:
        raise ExtractorError('알플레이 영상이 삭제되었거나 공개되지 않았습니다.', expected=True)
    grant = item.get('canView')
    if not isinstance(grant, dict) or grant.get('canView') is not True:
        if not session:
            raise ExtractorError('알플레이 로그인이 필요한 영상입니다. 설정 → 인증에서 알플레이 세션 파일을 등록하세요.', expected=True)
        raise ExtractorError('알플레이 계정에 이 영상의 시청 권한이 없습니다. 구독·구매·성인 인증 상태를 확인하세요.', expected=True)
    media = grant.get('url')
    if item.get('drm') or (isinstance(media, str) and '/drm_' in urlsplit(media).path):
        raise ExtractorError('알플레이 DRM 보호 영상은 다운로드할 수 없습니다.', expected=True)
    if not valid_media_url(media):
        raise ExtractorError('알플레이에서 지원하는 재생 주소를 제공하지 않았습니다.', expected=True)
    return item
