"""RPLAY viewer grants and Streamlink HLS recording/preview support."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit

import httpx
from yt_dlp.utils import ExtractorError

from app.core.http import USER_AGENT
from app.engine.base import LiveStatus
from app.engine.recording_errors import RecordingError
from app.engine.rplay import HOSTS, ORIGIN, read_session, session_expired
from app.engine.preview_transport import SafeMediaLogFilter

# HTTPX logs complete URLs at INFO, including the viewer token query used by RPLAY.
_http_logger = logging.getLogger('httpx')
if not any(isinstance(f, SafeMediaLogFilter) for f in _http_logger.filters):
    _http_logger.addFilter(SafeMediaLogFilter())

API = 'https://api.rplay.live/live'
_HANDLE_CACHE: dict[str, str] = {}


def _resolve_handle_creator_id(handle: str) -> str:
    handle_clean = handle.strip().lower()
    if handle_clean in _HANDLE_CACHE:
        return _HANDLE_CACHE[handle_clean]
    try:
        url = f'{ORIGIN}/c/{handle_clean}'
        with httpx.Client(timeout=8, follow_redirects=True) as client:
            response = client.get(url, headers={'User-Agent': USER_AGENT, 'Referer': ORIGIN + '/'})
        if response.status_code != 200:
            raise ValueError
        match = re.search(r'https://pb3\.rplay\.live/profilePhoto/([a-fA-F0-9]{24})(?=[-?"/<\s]|$)', response.text)
        if not match or match.group(1) == '0' * 24:
            raise ValueError
        cid = match.group(1).lower()
        _HANDLE_CACHE[handle_clean] = cid
        return cid
    except (httpx.HTTPError, ValueError):
        raise ValueError('알플레이 크리에이터를 찾을 수 없습니다.') from None


def normalize_rplay_channel_id(value: str) -> str:
    raw = value.strip()
    if '://' in raw:
        parts = urlsplit(raw)
        if (parts.scheme not in ('http', 'https') or parts.hostname not in HOSTS
                or parts.username is not None or parts.password is not None
                or parts.port not in (None, 443 if parts.scheme == 'https' else 80)):
            raise ValueError('올바른 알플레이 채널 ID 또는 라이브 링크를 입력하세요.')
        match = re.fullmatch(r'/(?:live|creatorhome)/([a-fA-F0-9]{24})/?', parts.path)
        if match:
            raw = match[1]
        else:
            handle_match = re.fullmatch(r'/c/([^/?#]+)/?', parts.path)
            if handle_match:
                raw = _resolve_handle_creator_id(handle_match[1])
            else:
                raise ValueError('올바른 알플레이 채널 ID 또는 라이브 링크를 입력하세요.')
    if not re.fullmatch(r'[a-fA-F0-9]{24}', raw):
        raise ValueError('올바른 알플레이 채널 ID 또는 라이브 링크를 입력하세요.')
    return raw.lower()


def media_allowed(value):
    try:
        p = urlsplit(value)
        return (p.scheme == 'https' and p.port in (None, 443) and not p.username and not p.password
                and not p.fragment and not any(c in value for c in '\r\n\\')
                and (p.hostname == 'livestream.rplay.live' or p.hostname == 'live-video.net'
                     or (p.hostname or '').endswith('.live-video.net')))
    except (TypeError, ValueError):
        return False


def live_headers(channel_id):
    return {'User-Agent': USER_AGENT, 'Origin': ORIGIN,
            'Referer': ORIGIN + '/live/' + normalize_rplay_channel_id(channel_id)}


def normalize_rplay_master(response):
    """Repair the missing separators in RPLAY's BytePlus master, not media URLs."""
    parts = urlsplit(response.url)
    if (response.status_code == 200 and parts.hostname == 'livestream.rplay.live'
            and parts.path.endswith('/abr.m3u8')):
        response._content = re.sub(
            rb'(?<=[^\r\n])#EXT-X-STREAM-INF:', b'\n#EXT-X-STREAM-INF:', response.content)


def account_session():
    try:
        session = read_session(auto_refresh=True)
        if session and session_expired(session):
            raise ExtractorError('알플레이 세션이 만료되었습니다. 설정 → 인증에서 세션 파일을 갱신하세요.')
        return session
    except ExtractorError:
        raise RecordingError('rplay_authentication', '알플레이 세션 파일을 확인하세요. 설정 → 인증에서 등록하거나 갱신하세요.') from None


class RplayLiveEngine:
    def __init__(self):
        self._cache = {}
        self._stream_cache = {}

    def get_stream_url(self, channel_id):
        return ORIGIN + '/live/' + normalize_rplay_channel_id(channel_id)

    async def _api(self, path, params, session, *, optional_permission=False):
        headers = {'Origin': ORIGIN, 'Referer': ORIGIN + '/', 'platform-type': 'rplay', 'User-Agent': USER_AGENT}
        params = {**params, 'platformType': 'rplay'}
        if session:
            headers['Authorization'] = session['accessToken']
            params.update(requestorOid=session['requestorOid'], loginType=session.get('loginType') or 'plax')
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
                response = await client.get(API + path, params=params, headers=headers)
            if response.status_code == 401 and session and session.get('refreshToken'):
                from app.engine.rplay import refresh_session_token
                try:
                    updated = await asyncio.to_thread(refresh_session_token, session)
                    session.update(updated)
                    headers['Authorization'] = session['accessToken']
                    params.update(requestorOid=session['requestorOid'], loginType=session.get('loginType') or 'plax')
                    if 'token' in params:
                        params.update(token=session['accessToken'], userId=session['requestorOid'])
                    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
                        response = await client.get(API + path, params=params, headers=headers)
                except Exception:
                    pass
            if response.status_code in (401, 403, 444, 999):
                if optional_permission:
                    return None
                raise RecordingError('rplay_authentication', '알플레이 로그인 또는 방송 시청 권한이 필요합니다. 설정 → 인증의 세션 파일을 확인하세요.')
            if response.status_code == 404:
                raise RecordingError('rplay_not_found', '알플레이 채널을 찾을 수 없습니다. 라이브 링크를 확인하세요.')
            if response.status_code == 429:
                raise RecordingError('rplay_rate_limit', '알플레이 요청 한도에 도달했습니다. 잠시 후 다시 시도하세요.', retryable=True)
            if response.is_redirect:
                raise RecordingError('rplay_access', '알플레이 API 이동 주소에 인증 정보를 전송하지 않았습니다.')
            response.raise_for_status()
            if path == '/bytedance/auth':
                if response.status_code != 200:
                    raise RecordingError('rplay_access', '알플레이에서 라이브 재생 권한을 확인하지 못했습니다.')
                # The official viewer uses the HTTP 200 grant, including empty responses.
                try:
                    if response.json().get('authorized') is False:
                        return None
                except (ValueError, AttributeError):
                    pass
                return True
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError
            return result
        except httpx.HTTPError:
            raise RecordingError('rplay_connection', '알플레이 서버에 연결하지 못했습니다. 잠시 후 다시 시도하세요.', retryable=True) from None
        except ValueError:
            raise RecordingError('rplay_response', '알플레이 방송 정보 형식을 확인하지 못했습니다.') from None

    async def _metadata(self, channel_id, session):
        cid = normalize_rplay_channel_id(channel_id)
        fingerprint = hashlib.sha256((session or {}).get('accessToken', '').encode()).hexdigest()
        key = (cid, fingerprint)
        cached = self._cache.get(key)
        if cached and time.monotonic() - cached[0] < 5:
            return cached[1]
        item = await self._api('/play', {'creatorOid': cid}, session)
        creator = item.get('creatorMetadata')
        if item.get('creatorOid') != cid or not isinstance(creator, dict) or creator.get('_id') != cid:
            raise RecordingError('rplay_response', '알플레이 방송의 채널 식별 정보가 다릅니다.')
        if not isinstance(item.get('streamState'), str):
            raise RecordingError('rplay_response', '알플레이 방송 상태를 확인하지 못했습니다.')
        while len(self._cache) >= 128:
            self._cache.pop(next(iter(self._cache)))
        self._cache[key] = (time.monotonic(), item)
        return item

    async def check_live_status(self, channel_id) -> LiveStatus:
        cid = normalize_rplay_channel_id(channel_id)
        session = account_session()
        item = await self._metadata(cid, session)
        creator = item['creatorMetadata']
        live = item.get('streamState') == 'live'
        if live and item.get('accessible') is not True:
            live = False
        return LiveStatus(channel_id=cid, is_live=live, channel_name=creator.get('nickname') or cid,
            title=item.get('title') or '', category='', viewer_count=0,
            thumbnail_url='', profile_image_url=creator.get('channelImage') or '',
            broadcast_tags=item.get('hashtags') if isinstance(item.get('hashtags'), list) else [],
            live_started_at=item.get('streamStartTime') if live else None)

    async def _streams(self, channel_id):
        cid = normalize_rplay_channel_id(channel_id)
        session = account_session()
        key = (cid, hashlib.sha256((session or {}).get('accessToken', '').encode()).hexdigest())
        cached = self._stream_cache.get(key)
        if cached and time.monotonic() - cached[0] < 3:
            return cached[1]
        item = await self._metadata(cid, session)
        if item['streamState'] != 'live':
            return []
        if item.get('accessible') is not True:
            raise RecordingError('rplay_authentication' if not session else 'rplay_access',
                '알플레이 로그인이 필요합니다. 설정 → 인증에 세션 파일을 등록하세요.' if not session else
                '알플레이 방송 시청 권한이 없습니다. 구독·성인 인증·입장권 상태를 확인하세요.')
        byteplus = item.get('useBytePlusStream') is True
        media = item.get('bytePlusPlaybackUrl') if byteplus else (item.get('livestreamUrl') or item.get('playUrl'))
        if not media_allowed(media) or not urlsplit(media).path.endswith('.m3u8'):
            raise RecordingError('rplay_stream', '알플레이에서 지원되는 HLS 재생 주소를 제공하지 않았습니다.')
        uhd = True
        if byteplus:
            params = {'creatorId': cid, 'watching': '0'}
            if session:
                params.update(userId=session['requestorOid'], token=session['accessToken'])
            if await self._api('/bytedance/auth', params, session) is not True:
                raise RecordingError('rplay_access', '알플레이에서 라이브 재생을 허용하지 않았습니다.')
            uhd = await self._api('/bytedance/auth', {**params, 'resolution': 'ud'}, session, optional_permission=True) is True
            # Only the official RPLAY delivery host receives the viewer token used by its web player.
            if urlsplit(media).hostname != 'livestream.rplay.live':
                raise RecordingError('rplay_stream', '알플레이 라이브 인증 서버 주소가 다릅니다.')
            query = dict(parse_qsl(urlsplit(media).query))
            query.update({k: v for k, v in params.items() if k != 'watching'})
            media = urlsplit(media)._replace(query=urlencode(query)).geturl()
        def resolve():
            from streamlink import Streamlink
            from streamlink.stream.hls import HLSStream
            sl = Streamlink(plugins_builtin=False)
            sl.set_option('http-timeout', 15)
            from app.engine.streamlink_support import configure_streamlink_session
            configure_streamlink_session(sl, "rplay", media)
            headers = live_headers(cid)
            def guard(response, *args, **kwargs):
                if response.is_redirect and not media_allowed(urljoin(response.url, response.headers.get('Location', ''))):
                    raise RecordingError('rplay_stream', '알플레이 재생 서버 이동 주소가 허용되지 않습니다.')
                normalize_rplay_master(response)
            sl.http.hooks['response'].append(guard)
            try:
                streams = HLSStream.parse_variant_playlist(sl, media, headers=headers)
                variants = []
                for name, stream in streams.items():
                    target = stream.to_url()
                    if not media_allowed(target):
                        raise RecordingError('rplay_stream', '알플레이 화질별 재생 주소가 허용되지 않습니다.')
                    info = next((p.stream_info for p in getattr(getattr(stream, 'multivariant', None), 'playlists', []) if p.uri == target), None)
                    size = getattr(info, 'resolution', None)
                    match = re.match(r'(\d+)p', name)
                    height = getattr(size, 'height', None) or (int(match[1]) if match else None)
                    if not height or (height > 720 and not uhd):
                        continue
                    variants.append(dict(value=name, label=name, height=height, width=getattr(size, 'width', None),
                        fps=getattr(info, 'framerate', None), bitrate=getattr(info, 'bandwidth', None), url=target))
                if not variants:
                    raise RecordingError('rplay_stream', '알플레이에서 이용 가능한 HLS 화질을 찾지 못했습니다.')
                return variants
            except RecordingError:
                raise
            except Exception as error:
                from app.engine.recording_errors import classify_recording_error
                if classify_recording_error(error).code == 'authentication':
                    raise RecordingError('rplay_authentication', '알플레이 재생 서버에서 인증을 거부했습니다. 로그인 세션과 시청 권한을 확인하세요.') from None
                raise RecordingError('rplay_stream', '알플레이 HLS 재생 목록을 불러오지 못했습니다. 세션과 방송 연결 상태를 확인하세요.', retryable=True) from None
            finally:
                sl.http.close()
        variants = await asyncio.to_thread(resolve)
        while len(self._stream_cache) >= 128:
            self._stream_cache.pop(next(iter(self._stream_cache)))
        self._stream_cache[key] = (time.monotonic(), variants)
        return variants

    async def get_qualities(self, channel_id):
        variants = await self._streams(channel_id)
        return [{k: v for k, v in item.items() if k != 'url'} for item in sorted(variants, key=lambda v: v['height'], reverse=True)]

    async def resolve_stream(self, channel_id, quality='best', *, force_refresh=False):
        if force_refresh:
            cid = normalize_rplay_channel_id(channel_id)
            for cache in (self._cache, self._stream_cache):
                for key in list(cache):
                    if key[0] == cid:
                        del cache[key]
        variants = await self._streams(channel_id)
        if not variants:
            raise RecordingError('broadcast_ended', '알플레이 API에서 방송 종료를 확인했습니다.')
        selected = next((v for v in variants if v['value'] == quality), None)
        if selected is None:
            if quality not in ('best', 'worst'):
                raise RecordingError('rplay_quality', '선택한 알플레이 화질의 이용 권한 또는 제공 상태를 확인하세요.')
            selected = (min if quality == 'worst' else max)(variants, key=lambda v: (v['height'], v['fps'] or 0, v['bitrate'] or 0))
        return selected['url'], live_headers(channel_id), None

    async def get_preview_url(self, channel_id):
        return (await self.resolve_stream(channel_id))[0]
