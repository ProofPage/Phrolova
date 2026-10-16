"""RPLAY video identity and explicitly imported, API-scoped sessions."""
from __future__ import annotations

import base64
import json
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from yt_dlp.utils import ExtractorError

from app.core.config import get_settings

ORIGIN = 'https://rplay.live'
API = 'https://api.rplay.live/content'
HOSTS = {'rplay.live', 'www.rplay.live'}
MEDIA_HOSTS = {'api.rplay.live', 'pb.rplay.live', 'pb2.rplay.live', 'pb3.rplay.live', 'pb.sbcloudsec.net'}


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
    """Accept a small explicit export, never browser storage or a refresh token."""
    try:
        if len(content) > 16 * 1024:
            raise ValueError
        data = json.loads(content.decode('utf-8-sig'))
        if not isinstance(data, dict):
            raise ValueError
        token = data.get('accessToken')
        oid = data.get('requestorOid')
        login_type = data.get('loginType', 'rplay')
        if (not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9._~+/=-]{16,8192}', token)
                or not isinstance(oid, str) or not re.fullmatch(r'[a-fA-F0-9]{24}', oid)
                or not isinstance(login_type, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,32}', login_type)):
            raise ValueError
        return {'accessToken': token, 'requestorOid': oid.lower(), 'loginType': login_type}
    except (ValueError, UnicodeError):
        raise ValueError('accessToken과 requestorOid가 포함된 알플레이 세션 JSON 파일을 선택하세요.') from None


def session_expired(session: dict) -> bool:
    # This is a local expiry hint, not JWT signature verification; RPLAY validates the token.
    try:
        payload = session['accessToken'].split('.')[1]
        data = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
        return float(data['exp']) <= time.time()
    except (KeyError, IndexError, ValueError, TypeError):
        return False


def read_session() -> dict[str, str] | None:
    source = get_settings().rplay_session_file
    if not source:
        return None
    try:
        with Path(source).open('rb') as stream:
            return parse_session(stream.read(16 * 1024 + 1))
    except (OSError, ValueError):
        raise ExtractorError('알플레이 세션 파일을 읽지 못했습니다. 설정에서 다시 등록하세요.', expected=True) from None


def session_status() -> dict:
    configured = bool(get_settings().rplay_session_file)
    try:
        session = read_session()
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
    session = read_session()
    if session:
        if session_expired(session):
            raise ExtractorError('알플레이 로그인 세션이 만료되었습니다. 설정에서 세션 파일을 갱신하세요.', expected=True)
        headers['Authorization'] = session['accessToken']
        params.update(requestorOid=session['requestorOid'], loginType=session['loginType'])
    try:
        # Account authorization must never follow a redirect or reach a media CDN.
        with httpx.Client(timeout=20, follow_redirects=False) as client:
            response = client.get(API, params=params, headers=headers)
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
