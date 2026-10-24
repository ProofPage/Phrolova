"""Kick 공개 채널 상태와 HLS 녹화 주소를 별도로 조회한다."""
from __future__ import annotations

import asyncio
import re
import time
from urllib.parse import parse_qs, unquote, urlsplit

import httpx

from app.core.http import USER_AGENT
from app.engine.base import LiveStatus
from app.engine.recording_errors import RecordingError
from app.engine.platform_auth import get_platform_cookies, platform_cookie_jar

ORIGIN = 'https://kick.com'
HOSTS = {'kick.com', 'www.kick.com'}
SLUG = r'[A-Za-z0-9_][A-Za-z0-9_-]{0,99}'
VIDEO_ID = r'[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}'
RESERVED = {'api', 'auth', 'browse', 'categories', 'clips', 'following', 'login',
            'privacy', 'search', 'settings', 'signup', 'subscriptions', 'terms', 'video', 'videos'}


def _parts(value: str):
    parts = urlsplit(value.strip())
    if (parts.scheme not in ('http', 'https') or parts.hostname not in HOSTS
            or parts.username is not None or parts.password is not None
            or parts.port not in (None, 80 if parts.scheme == 'http' else 443)):
        raise ValueError
    return parts


def _slug(value: str) -> str:
    if not re.fullmatch(SLUG, value) or value.lower() in RESERVED:
        raise ValueError
    return value.lower()


def normalize_kick_channel_id(value: str) -> str:
    try:
        raw = str(value or '').strip()
        if '://' in raw:
            parts = _parts(raw)
            match = re.fullmatch(rf'/({SLUG})/?', unquote(parts.path))
            # 클립 URL을 채널로 등록하면 사용자가 고른 콘텐츠와 다른 방송을 녹화하게 된다.
            if not match or 'clip' in parse_qs(parts.query):
                raise ValueError
            raw = match[1]
        return _slug(raw)
    except ValueError:
        raise ValueError('올바른 Kick 채널 ID 또는 채널 링크를 입력하세요.') from None


def canonical_kick_video_url(value: str) -> str:
    try:
        parts = _parts(value)
        path = unquote(parts.path)
        vod = re.fullmatch(rf'/({SLUG})/videos/({VIDEO_ID})/?', path)
        if vod:
            return f'{ORIGIN}/{_slug(vod[1])}/videos/{vod[2].lower()}'
        clip = re.fullmatch(rf'/({SLUG})/clips/(clip_[A-Za-z0-9_-]+)/?', path)
        if clip:
            return f'{ORIGIN}/{_slug(clip[1])}/clips/{clip[2]}'
        channel = re.fullmatch(rf'/({SLUG})/?', path)
        ids = parse_qs(parts.query).get('clip', [])
        if channel and len(ids) == 1 and re.fullmatch(r'clip_[A-Za-z0-9_-]+', ids[0]):
            return f'{ORIGIN}/{_slug(channel[1])}/clips/{ids[0]}'
        raise ValueError
    except ValueError:
        raise ValueError('올바른 Kick 다시보기 또는 클립 링크를 입력하세요.') from None


def kick_access_error(error: Exception) -> RecordingError | None:
    if isinstance(error, RecordingError):
        return error
    status = getattr(getattr(error, 'response', None), 'status_code', None)
    text = re.sub(r'https?://\S+', '[url]', str(error).lower())
    if status in (401, 403) or re.search(r'\b(?:401|403)\b', text):
        return RecordingError('kick_access', 'Kick이 이 서버의 접속을 거부했습니다. 서버 네트워크와 콘텐츠 공개 상태를 확인하세요.')
    if status == 429 or 'too many requests' in text or re.search(r'\b429\b', text):
        return RecordingError('kick_rate_limit', 'Kick 요청 한도에 도달했습니다. 잠시 후 다시 시도하세요.', retryable=True)
    if status == 404 or 'http error 404' in text:
        return RecordingError('kick_not_found', 'Kick 채널이나 영상을 찾을 수 없습니다. 주소와 삭제 여부를 확인하세요.')
    if 'requested format is not available' in text:
        return RecordingError('kick_quality', '선택한 Kick 화질이 제공되지 않습니다. 등록한 쿠키와 현재 화질 목록을 확인하세요.')
    return None


def kick_api_headers(url: str) -> dict[str, str]:
    parts = urlsplit(url)
    if parts.scheme != 'https' or parts.hostname not in HOSTS or not parts.path.startswith('/api/'):
        return {}
    token = unquote(get_platform_cookies('kick', url).get('session_token', ''))
    return {'Authorization': f'Bearer {token}'} if token and not any(c in token for c in '\r\n') else {}


def kick_headers(channel_id: str) -> dict[str, str]:
    return {'User-Agent': USER_AGENT, 'Origin': ORIGIN, 'Referer': f'{ORIGIN}/{channel_id}'}


class KickLiveEngine:
    def __init__(self):
        self._cache: dict[str, tuple[float, dict]] = {}

    def get_stream_url(self, channel_id: str) -> str:
        return f'{ORIGIN}/{normalize_kick_channel_id(channel_id)}'

    async def _metadata(self, channel_id: str) -> dict:
        cid = normalize_kick_channel_id(channel_id)
        cached = self._cache.get(cid)
        if cached and time.monotonic() - cached[0] < 8:
            return cached[1]
        api_url = f'{ORIGIN}/api/v2/channels/{cid}'
        async with httpx.AsyncClient(timeout=12, headers=kick_headers(cid), cookies=platform_cookie_jar('kick')) as client:
            response = await client.get(api_url, headers=kick_api_headers(api_url))
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as error:
                raise kick_access_error(error) or error from None
            try:
                data = response.json()
            except ValueError:
                raise RuntimeError('Kick 방송 정보 응답을 읽지 못했습니다.') from None
        # 차단 페이지나 스키마 변경을 오프라인으로 저장하지 않는다.
        if not isinstance(data, dict) or 'livestream' not in data or not data.get('id'):
            raise RuntimeError('Kick 방송 정보 형식이 변경되었습니다.')
        if data.get('is_banned'):
            raise RecordingError('kick_access', 'Kick이 이 서버의 접속을 거부했습니다. 서버 네트워크와 콘텐츠 공개 상태를 확인하세요.')
        if data['livestream'] is not None and not isinstance(data['livestream'], dict):
            raise RuntimeError('Kick 방송 정보 형식이 변경되었습니다.')
        self._cache[cid] = (time.monotonic(), data)
        return data

    async def check_live_status(self, channel_id: str) -> LiveStatus:
        cid = normalize_kick_channel_id(channel_id)
        data = await self._metadata(cid)
        live = data.get('livestream') or {}
        user = data.get('user') if isinstance(data.get('user'), dict) else {}
        category = next((item for item in live.get('categories') or data.get('recent_categories') or []
                         if isinstance(item, dict)), {})
        thumbnail = live.get('thumbnail') or {}
        try:
            viewers = max(0, int(live.get('viewer_count') or live.get('viewers') or 0))
        except (ValueError, TypeError):
            viewers = 0
        return LiveStatus(channel_id=cid, is_live=bool(live), channel_name=user.get('username') or cid,
                          title=live.get('session_title') or '', category=category.get('name') or '',
                          viewer_count=viewers if live else 0,
                          thumbnail_url=(thumbnail.get('url') or thumbnail.get('src') or '') if isinstance(thumbnail, dict) else str(thumbnail),
                          profile_image_url=user.get('profile_pic') or '',
                          live_started_at=live.get('start_time') or live.get('created_at'))

    async def _streams(self, channel_id: str) -> tuple[list[dict], dict]:
        cid = normalize_kick_channel_id(channel_id)
        def resolve():
            from streamlink import Streamlink
            session = Streamlink()
            session.set_option('http-timeout', 12)
            # 별도 Streamlink 실행에서 저장한 쿠키가 앱의 등록·삭제 상태를 덮어쓰지 않게 한다.
            session.set_option('no-plugin-cache', True)
            # 서버에서 채널 감시 중 브라우저를 자동 실행하지 않는다.
            session.set_option('webbrowser', False)
            session.http.cookies.update(platform_cookie_jar('kick'))
            # 세션 토큰은 Kick API 요청에만 넣는다. HLS/CDN 요청에는 Authorization을 보내지 않는다.
            def authorize(request):
                request.headers.pop('Authorization', None)
                request.headers.pop('Cookie', None)
                request.prepare_cookies(session.http.cookies)
                request.headers.update(kick_api_headers(request.url))
                return request
            session.http.auth = authorize
            from app.engine.streamlink_support import configure_streamlink_session
            configure_streamlink_session(session, "kick", self.get_stream_url(cid))
            try:
                streams = session.streams(self.get_stream_url(cid))
                variants = []
                for name, stream in streams.items():
                    match = re.fullmatch(r'(\d+)p(?:(\d+(?:\.\d+)?))?', name)
                    if not match:
                        continue
                    url = stream.to_url()
                    playlists = getattr(getattr(stream, 'multivariant', None), 'playlists', [])
                    playlist = next((item for item in playlists if item.uri == url), None)
                    info = getattr(playlist, 'stream_info', None)
                    resolution = getattr(info, 'resolution', None)
                    variants.append({'value': name, 'label': name, 'url': url,
                                     'height': getattr(resolution, 'height', None) or int(match[1]),
                                     'width': getattr(resolution, 'width', None),
                                     'fps': getattr(info, 'framerate', None) or (float(match[2]) if match[2] else None),
                                     'bitrate': getattr(info, 'bandwidth', None)})
                if streams and not variants:
                    raise RuntimeError('Kick 라이브 화질 정보를 가져오지 못했습니다.')
                headers = kick_headers(cid)
                headers['User-Agent'] = session.http.headers.get('User-Agent', USER_AGENT)
                return variants, headers
            except Exception as error:
                raise kick_access_error(error) or error from None
            finally:
                session.http.close()
        return await asyncio.to_thread(resolve)

    async def get_qualities(self, channel_id: str) -> list[dict]:
        variants, _ = await self._streams(channel_id)
        return [{key: value for key, value in variant.items() if key != 'url'}
                for variant in sorted(variants, key=lambda item: (item['height'], item['fps'] or 0), reverse=True)]

    async def resolve_stream_spec(self, channel_id: str, quality: str = 'best') -> dict:
        variants, headers = await self._streams(channel_id)
        if not variants:
            raise ValueError('Kick 채널이 오프라인입니다.')
        order = lambda item: (item['height'], item['fps'] or 0, item['bitrate'] or 0)
        selected = next((item for item in variants if item['value'] == quality), None)
        if selected is None:
            target = re.fullmatch(r'(\d+)p(?:(\d+(?:\.\d+)?))?', quality)
            eligible = [item for item in variants if target and item['height'] <= int(target[1])
                        and (not target[2] or (item['fps'] or 0) <= float(target[2]))]
            selected = (min(variants, key=order) if quality == 'worst' or target and not eligible
                        else max(eligible or variants, key=order))
            if target and int(target[1]) >= 1080 and (selected['height'] < int(target[1]) or target[2] and (selected['fps'] or 0) > float(target[2])):
                raise RecordingError('kick_quality', '선택한 Kick 화질이 제공되지 않습니다. 등록한 쿠키와 현재 화질 목록을 확인하세요.')
        return {**selected, "headers": headers, "cookies": None}

    async def resolve_stream(self, channel_id: str, quality: str = 'best') -> tuple[str, dict, None]:
        spec = await self.resolve_stream_spec(channel_id, quality)
        return spec["url"], spec["headers"], spec["cookies"]

    async def get_preview_url(self, channel_id: str) -> str:
        return (await self.resolve_stream(channel_id, '720p'))[0]
