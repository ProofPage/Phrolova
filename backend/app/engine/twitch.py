"""Twitch 채널 감시와 Streamlink 기반 라이브 화질 조회."""
from __future__ import annotations

import asyncio
import re
import time
from urllib.parse import parse_qs, unquote, urlsplit

import httpx

from app.engine.base import LiveStatus
from app.engine.platform_auth import get_platform_cookies, platform_cookie_jar
from app.engine.recording_errors import RecordingError

HOSTS = {'twitch.tv', 'www.twitch.tv', 'm.twitch.tv', 'go.twitch.tv'}
VIDEO_HOSTS = HOSTS | {'clips.twitch.tv', 'player.twitch.tv'}
RESERVED = {'directory', 'downloads', 'settings', 'login', 'signup', 'videos', 'clip',
            'clips', 'collections', 'subscriptions', 'search', 'inventory', 'wallet', 'turbo'}
CHANNEL = r'[A-Za-z0-9_]{1,25}'
CLIP = r'[A-Za-z0-9_-]{1,200}'


def _parts(value: str):
    parts = urlsplit(str(value).strip())
    if (parts.scheme not in ('http', 'https') or parts.hostname not in VIDEO_HOSTS
            or parts.username is not None or parts.password is not None
            or parts.port not in (None, 80 if parts.scheme == 'http' else 443)):
        raise ValueError
    return parts


def _channel(value: str) -> str:
    if not re.fullmatch(CHANNEL, value) or value.lower() in RESERVED:
        raise ValueError
    return value.lower()


def normalize_twitch_channel_id(value: str) -> str:
    try:
        raw = str(value or '').strip()
        if '://' in raw:
            parts = _parts(raw)
            match = re.fullmatch(r'/([^/]+)/?', unquote(parts.path))
            if parts.hostname not in HOSTS or not match:
                raise ValueError
            raw = match[1]
        return _channel(raw)
    except ValueError:
        raise ValueError('올바른 Twitch 채널 ID 또는 채널 링크를 입력하세요.') from None


def canonical_twitch_video_url(value: str) -> str:
    try:
        parts = _parts(value)
        path = unquote(parts.path)
        if parts.hostname in HOSTS:
            vod = re.fullmatch(r'/(?:videos/|[^/]+/v(?:ideo)?/)(\d+)/?', path)
            if vod:
                return f'https://www.twitch.tv/videos/{vod[1]}'
            clip = re.fullmatch(rf'/(?:{CHANNEL}/)?clip/({CLIP})/?', path)
            if clip:
                return f'https://clips.twitch.tv/{clip[1]}'
        elif parts.hostname == 'clips.twitch.tv':
            ids = parse_qs(parts.query).get('clip', []) if path.rstrip('/') == '/embed' else [path.strip('/')]
            if len(ids) == 1 and re.fullmatch(CLIP, ids[0]):
                return f'https://clips.twitch.tv/{ids[0]}'
        elif parts.hostname == 'player.twitch.tv' and path in ('', '/'):
            ids = parse_qs(parts.query).get('video', [])
            if len(ids) == 1 and re.fullmatch(r'v?\d+', ids[0]):
                return f'https://www.twitch.tv/videos/{ids[0].removeprefix("v")}'
        raise ValueError
    except ValueError:
        raise ValueError('올바른 Twitch 다시보기 또는 클립 링크를 입력하세요.') from None


def twitch_api_headers() -> dict[str, str]:
    token = get_platform_cookies('twitch', 'https://gql.twitch.tv/gql').get('auth-token', '')
    return {'Authorization': f'OAuth {token}'} if re.fullmatch(r'[A-Za-z0-9_-]{1,512}', token) else {}


def twitch_access_error(error: Exception) -> RecordingError | None:
    if isinstance(error, RecordingError):
        return error
    status = getattr(getattr(error, 'response', None), 'status_code', None)
    text = re.sub(r'https?://\S+', '[url]', str(error).lower())
    if 'client-integrity' in text or 'client integrity' in text:
        return RecordingError('twitch_integrity', 'Twitch 클라이언트 확인에 실패했습니다. Streamlink 버전과 서버 접속 환경을 확인하세요.')
    if status == 429 or '429' in text or 'too many requests' in text:
        return RecordingError('twitch_rate_limit', 'Twitch 요청 한도에 도달했습니다. 잠시 후 다시 시도하세요.', retryable=True)
    if status in (401, 403) or re.search(r'\b(?:401|403)\b|subscribers.only|subscriber.only|unauthorized|forbidden', text):
        return RecordingError('twitch_access', 'Twitch 시청 권한을 확인하지 못했습니다. 콘텐츠 공개 상태와 설정의 Twitch 쿠키를 확인하세요.')
    if status == 404 or 'does not exist' in text or 'no longer available' in text:
        return RecordingError('twitch_not_found', 'Twitch 채널이나 영상을 조회할 수 없습니다. 주소·공개 상태와 서버의 접속 지역을 확인하세요.')
    return None


class TwitchLiveEngine:
    def __init__(self):
        self._cache: dict[str, tuple[float, dict]] = {}

    def get_stream_url(self, channel_id: str) -> str:
        return f'https://www.twitch.tv/{normalize_twitch_channel_id(channel_id)}'

    async def check_live_status(self, channel_id: str) -> LiveStatus:
        from streamlink.plugins.twitch import TwitchAPI
        cid = normalize_twitch_channel_id(channel_id)
        cached = self._cache.get(cid)
        if cached and time.monotonic() - cached[0] < 8:
            return cached[1]
        query = '''query PhrolovaChannel($login: String!) {
          user(login: $login) {
            id login displayName profileImageURL(width: 300) lastBroadcast { title }
            stream { id type createdAt viewersCount game { name } }
          }
        }'''
        try:
            async with httpx.AsyncClient(timeout=12) as client:
                response = await client.post('https://gql.twitch.tv/gql',
                    headers={'Client-ID': TwitchAPI.CLIENT_ID, **twitch_api_headers()},
                    json={'query': query, 'variables': {'login': cid}})
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise twitch_access_error(error) or RuntimeError('Twitch 방송 정보를 불러오지 못했습니다.') from None
        if not isinstance(payload, dict) or payload.get('errors') or not isinstance(payload.get('data'), dict) or 'user' not in payload['data']:
            raise RuntimeError('Twitch 방송 정보 형식이 변경되었거나 요청이 거부되었습니다.')
        user = payload['data']['user']
        if user is None:
            raise RecordingError('twitch_not_found', 'Twitch 채널이나 영상을 조회할 수 없습니다. 주소·공개 상태와 서버의 접속 지역을 확인하세요.')
        if not isinstance(user, dict) or not user.get('id') or 'stream' not in user or user['stream'] is not None and not isinstance(user['stream'], dict):
            raise RuntimeError('Twitch 방송 정보 형식이 변경되었습니다.')
        live = user['stream'] or {}
        status = LiveStatus(channel_id=cid, channel_name=user.get('displayName') or cid,
            is_live=bool(live), title=(user.get('lastBroadcast') or {}).get('title') or '',
            category=(live.get('game') or {}).get('name') or '',
            viewer_count=max(0, int(live.get('viewersCount') or 0)),
            profile_image_url=user.get('profileImageURL') or '',
            thumbnail_url=f'https://static-cdn.jtvnw.net/previews-ttv/live_user_{cid}-640x360.jpg' if live else '',
            live_started_at=live.get('createdAt'))
        self._cache[cid] = (time.monotonic(), status)
        return status

    async def _streams(self, channel_id: str) -> list[dict]:
        def resolve():
            from streamlink import Streamlink
            from streamlink.options import Options
            session = Streamlink()
            session.set_option('http-timeout', 12)
            session.set_option('no-plugin-cache', True)
            session.set_option('webbrowser', False)
            session.http.cookies.update(platform_cookie_jar('twitch'))
            from app.engine.streamlink_support import configure_streamlink_session
            configure_streamlink_session(session, "twitch", self.get_stream_url(channel_id))
            from app.engine.twitch_proxy import configure_twitch_proxy
            configure_twitch_proxy(session, twitch_api_headers().get("Authorization", "").removeprefix("OAuth "))
            try:
                from app.core.config import get_settings
                stream_opts = {
                    'api-header': list(twitch_api_headers().items()),
                    'supported-codecs': ['h264', 'h265', 'av1'],
                }
                if get_settings().twitch_ttv_ab_enabled:
                    stream_opts['access-token-param'] = [('playerType', 'popout'), ('platform', 'site')]
                # 인증은 Twitch API 전용 옵션으로 넘겨 CDN에 OAuth가 유출되지 않게 한다.
                streams = session.streams(self.get_stream_url(channel_id), options=Options(stream_opts))
                variants = []
                for name, stream in streams.items():
                    match = re.fullmatch(r'(\d+)p(?:(\d+(?:\.\d+)?))?', name)
                    if not match:
                        continue
                    url = stream.to_url()
                    playlists = getattr(getattr(stream, 'multivariant', None), 'playlists', [])
                    info = next((item.stream_info for item in playlists if item.uri == url), None)
                    size = getattr(info, 'resolution', None)
                    variants.append({'value': name, 'label': name, 'url': url,
                        'width': getattr(size, 'width', None),
                        'height': getattr(size, 'height', None) or int(match[1]),
                        'fps': getattr(info, 'framerate', None) or (float(match[2]) if match[2] else 0)})
                if streams and not variants:
                    raise RuntimeError('Twitch 라이브 화질 정보를 가져오지 못했습니다.')
                return variants
            except Exception as error:
                raise twitch_access_error(error) or error from None
            finally:
                session.http.close()
        variants = await asyncio.to_thread(resolve)
        if not variants:
            # The preceding monitor poll may have cached "live" just before
            # the playlist disappeared. Only a fresh API result can prove EOF.
            self._cache.pop(normalize_twitch_channel_id(channel_id), None)
            if (await self.check_live_status(channel_id))['is_live']:
                raise RecordingError('twitch_stream_unavailable',
                    'Twitch 방송 중이지만 재생 주소를 가져오지 못했습니다. 시청 권한과 서버 접속 상태를 확인하세요.', retryable=True)
        return variants

    async def get_qualities(self, channel_id: str) -> list[dict]:
        return [{key: value for key, value in item.items() if key != 'url'} for item in
                sorted(await self._streams(channel_id), key=lambda item: (item['height'], item['fps']), reverse=True)]

    async def resolve_stream_spec(self, channel_id: str, quality: str = 'best') -> dict:
        variants = await self._streams(channel_id)
        if not variants:
            raise RecordingError('broadcast_ended', 'Twitch API에서 방송 종료를 확인했습니다.')
        rank = lambda item: (item['height'], item['fps'])
        selected = next((item for item in variants if item['value'] == quality), None)
        if selected is None:
            target = re.fullmatch(r'(\d+)p(?:(\d+(?:\.\d+)?))?', quality)
            eligible = [item for item in variants if target and item['height'] <= int(target[1])
                        and (not target[2] or item['fps'] <= float(target[2]))]
            selected = (min(variants, key=rank) if quality == 'worst' or target and not eligible
                        else max(eligible or variants, key=rank))
        return {**selected, "headers": {'Origin': 'https://www.twitch.tv', 'Referer': self.get_stream_url(channel_id)}, "cookies": None}

    async def resolve_stream(self, channel_id: str, quality: str = 'best') -> tuple[str, dict, None]:
        spec = await self.resolve_stream_spec(channel_id, quality)
        return spec["url"], spec["headers"], spec["cookies"]

    async def get_preview_url(self, channel_id: str) -> str:
        return (await self.resolve_stream(channel_id, '720p'))[0]
