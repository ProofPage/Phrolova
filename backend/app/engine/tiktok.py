"""TikTok 채널 상태와 Streamlink FLV 라이브 입력을 연결한다."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import re
import time
from urllib.parse import unquote, urlsplit

import httpx

from app.core.http import USER_AGENT
from app.engine.base import LiveStatus
from app.engine.platform_auth import platform_cookie_jar
from app.engine.recording_errors import RecordingError

HOSTS = {'tiktok.com', 'www.tiktok.com', 'm.tiktok.com'}
SHORT_HOSTS = {'vm.tiktok.com', 'vt.tiktok.com'}
VIDEO_HOSTS = HOSTS | SHORT_HOSTS
USERNAME = r'[A-Za-z0-9_.]{1,24}'


def _parts(value: str):
    parts = urlsplit(str(value).strip())
    if (parts.scheme not in ('http', 'https') or parts.hostname not in VIDEO_HOSTS
            or parts.username is not None or parts.password is not None
            or parts.port not in (None, 80 if parts.scheme == 'http' else 443)):
        raise ValueError
    return parts


def _username(value: str) -> str:
    if not re.fullmatch(USERNAME, value) or value.endswith('.') or not re.search(r'[A-Za-z0-9_]', value):
        raise ValueError
    return value.lower()


def normalize_tiktok_channel_id(value: str) -> str:
    try:
        raw = str(value or '').strip()
        if '://' in raw:
            parts = _parts(raw)
            match = re.fullmatch(r'/@([^/]+)(?:/live)?/?', unquote(parts.path))
            if parts.hostname not in HOSTS or not match:
                raise ValueError
            raw = match[1]
        else:
            raw = raw.removeprefix('@')
        return _username(raw)
    except ValueError:
        raise ValueError('올바른 TikTok 사용자 이름 또는 라이브 채널 링크를 입력하세요.') from None


def canonical_tiktok_video_url(value: str) -> str:
    try:
        parts = _parts(value)
        path = unquote(parts.path)
        if parts.hostname in SHORT_HOSTS:
            match = re.fullmatch(r'/([A-Za-z0-9]{1,64})/?', path)
            if match:
                return f'https://{parts.hostname}/{match[1]}/'
        else:
            short = re.fullmatch(r'/t/([A-Za-z0-9]{1,64})/?', path)
            if short:
                return f'https://www.tiktok.com/t/{short[1]}/'
            video = re.fullmatch(r'/@([^/]+)/video/(\d+)/?', path)
            if video:
                return f'https://www.tiktok.com/@{_username(video[1])}/video/{video[2]}'
            embed = re.fullmatch(r'/(?:embed/(?:v2/)?|share/video/)(\d+)/?', path)
            mobile = re.fullmatch(r'/v/(\d+)\.html', path) if parts.hostname == 'm.tiktok.com' else None
            if embed or mobile:
                return f'https://www.tiktok.com/@_/video/{(embed or mobile)[1]}'
        raise ValueError
    except ValueError:
        raise ValueError('올바른 TikTok 동영상 또는 공유 링크를 입력하세요.') from None


def tiktok_access_error(error: Exception) -> RecordingError | None:
    if isinstance(error, RecordingError):
        return error
    status = getattr(getattr(error, 'response', None), 'status_code', None)
    text = re.sub(r'https?://\S+', '[url]', str(error).lower())
    if status == 429 or re.search(r'\b429\b|too many requests', text):
        return RecordingError('tiktok_rate_limit', 'TikTok 요청 한도에 도달했습니다. 잠시 후 다시 시도하세요.', retryable=True)
    if status in (401, 403) or re.search(r'\b(?:401|403)\b|login|log.in|sign.in|captcha|challenge|private|restricted', text):
        return RecordingError('tiktok_access', 'TikTok 접근이 제한되었습니다. 콘텐츠 공개 상태·서버 접속 환경과 설정의 TikTok 쿠키를 확인하세요.')
    if 'requested format is not available' in text:
        return RecordingError('tiktok_quality', '선택한 TikTok 화질을 사용할 수 없습니다. 영상 정보를 새로 조회하고 화질을 다시 선택하세요.')
    if status == 404 or re.search(r'not found|not available|unavailable|does not exist', text):
        return RecordingError('tiktok_not_found', 'TikTok 동영상이나 채널을 조회할 수 없습니다. 주소·공개 상태와 서버 접속 지역을 확인하세요.')
    return None


def tiktok_headers(channel_id: str) -> dict[str, str]:
    return {'User-Agent': USER_AGENT, 'Origin': 'https://www.tiktok.com',
            'Referer': f'https://www.tiktok.com/@{normalize_tiktok_channel_id(channel_id)}/live'}


def _sdk_metadata(room: dict, name: str) -> dict:
    codec, _, quality = name.partition('_')
    key = 'hevcStreamData' if codec == 'h265' else 'streamData'
    try:
        raw = json.loads(room[key]['pull_data']['stream_data'])['data'][quality]['main']['sdk_params']
        params = json.loads(raw)
        match = re.fullmatch(r'(\d+)x(\d+)', str(params.get('resolution') or ''), re.I)
        return {'width': int(match[1]) if match else None, 'height': int(match[2]) if match else None,
                'bitrate': int(params.get('vbitrate') or 0) or None}
    except (KeyError, TypeError, ValueError):
        return {'width': None, 'height': None, 'bitrate': None}


class TikTokLiveEngine:
    def __init__(self):
        self._cache: dict[str, tuple[float, dict]] = {}
        self._stream_cache: dict[str, tuple[float, list[dict]]] = {}

    def get_stream_url(self, channel_id: str) -> str:
        return f'https://www.tiktok.com/@{normalize_tiktok_channel_id(channel_id)}/live'

    async def _metadata(self, channel_id: str) -> dict:
        cid = normalize_tiktok_channel_id(channel_id)
        cached = self._cache.get(cid)
        if cached and time.monotonic() - cached[0] < 8:
            return cached[1]
        async with httpx.AsyncClient(timeout=12, headers=tiktok_headers(cid), cookies=platform_cookie_jar('tiktok')) as client:
            response = await client.get('https://www.tiktok.com/api-live/user/room',
                params={'aid':1988, 'sourceType':54, 'staleTime':600000, 'uniqueId':cid})
        try:
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPStatusError, ValueError) as error:
            raise tiktok_access_error(error) or RuntimeError('TikTok 방송 정보를 읽지 못했습니다.') from None
        if not isinstance(payload, dict) or payload.get('statusCode') != 0:
            message = str(payload.get('message') or payload.get('statusMsg') or '') if isinstance(payload, dict) else ''
            raise tiktok_access_error(RuntimeError(message)) or RuntimeError('TikTok 방송 정보 요청이 거부되었습니다.')
        data = payload.get('data')
        if not isinstance(data, dict) or not isinstance(data.get('liveRoom'), dict) or data['liveRoom'].get('status') not in (2, 4):
            raise RuntimeError('TikTok 방송 정보 형식이 변경되었습니다.')
        self._cache[cid] = (time.monotonic(), data)
        return data

    async def check_live_status(self, channel_id: str) -> LiveStatus:
        cid = normalize_tiktok_channel_id(channel_id)
        data = await self._metadata(cid)
        room = data['liveRoom']
        user = data.get('user') or {}
        live = room['status'] == 2
        try:
            viewers = max(0, int((room.get('liveRoomStats') or {}).get('userCount') or 0))
            started = datetime.fromtimestamp(int(room.get('startTime') or 0), timezone.utc).isoformat() if live and room.get('startTime') else None
        except (ValueError, TypeError, OverflowError, OSError):
            viewers, started = 0, None
        return LiveStatus(channel_id=cid, is_live=live, channel_name=user.get('nickname') or cid,
            title=room.get('title') or '', category='', viewer_count=viewers if live else 0,
            thumbnail_url=room.get('coverUrl') or '',
            profile_image_url=user.get('avatarMedium') or user.get('avatarThumb') or '', live_started_at=started)

    async def _streams(self, channel_id: str) -> list[dict]:
        cid = normalize_tiktok_channel_id(channel_id)
        cached = self._stream_cache.get(cid)
        if cached and time.monotonic()-cached[0] < 4:
            return [dict(item) for item in cached[1]]
        room = (await self._metadata(cid))['liveRoom']
        if room['status'] == 4:
            return []
        def resolve():
            from streamlink import Streamlink
            from streamlink.plugins.tiktok import TikTok
            session = Streamlink()
            session.set_option('http-timeout', 12)
            session.set_option('no-plugin-cache', True)
            session.set_option('webbrowser', False)
            session.http.headers.update(tiktok_headers(cid))
            session.http.cookies.update(platform_cookie_jar('tiktok'))
            from app.engine.streamlink_support import configure_streamlink_session
            configure_streamlink_session(session, "tiktok", self.get_stream_url(cid))
            try:
                variants = []
                for name, stream in session.streams(self.get_stream_url(cid)).items():
                    match = re.fullmatch(r'(h264|h265)_([a-z0-9_]+)', name)
                    if not match or match[2] == 'ao':
                        continue
                    url = stream.to_url()
                    parts = urlsplit(url)
                    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
                        raise RuntimeError('TikTok 라이브 재생 주소가 올바르지 않습니다.')
                    dimensions = _sdk_metadata(room, name)
                    size = f" · {dimensions['width']}×{dimensions['height']}" if dimensions['width'] and dimensions['height'] else ''
                    codec = 'H.264' if match[1] == 'h264' else 'H.265'
                    variants.append({'value':name, 'label':f'{match[2].upper()}{size} · {codec}',
                        'url':url, 'weight':TikTok.stream_weight(name)[0], 'fps':60 if match[2].endswith('_60') else None, **dimensions})
                if not variants:
                    raise RecordingError('tiktok_stream_unavailable',
                        'TikTok 방송 중이지만 재생 주소를 가져오지 못했습니다. 쿠키와 서버 접속 상태를 확인하세요.', retryable=True)
                return variants
            except Exception as error:
                raise tiktok_access_error(error) or error from None
            finally:
                session.http.close()
        variants = await asyncio.to_thread(resolve)
        self._stream_cache[cid] = (time.monotonic(), variants)
        return [dict(item) for item in variants]

    @staticmethod
    def _rank(item):
        # 원본에는 FPS 메타데이터가 없기도 해, 같은 해상도의 저비트레이트 60fps 변형이 원본보다 앞서면 안 된다.
        return (min(item.get('width') or 0, item.get('height') or 0), item['weight'], item.get('fps') or 0)

    async def get_qualities(self, channel_id: str) -> list[dict]:
        options = {}
        for item in sorted(await self._streams(channel_id), key=self._rank, reverse=True):
            edge = min(item.get('width') or 0, item.get('height') or 0)
            if not edge:
                continue
            value = f"{edge}p" + (str(item['fps']) if item.get('fps') else '')
            if value not in options:
                options[value] = {key:val for key,val in item.items() if key not in ('url','weight')}
                options[value]['value'] = value
        return list(options.values())

    async def resolve_stream(self, channel_id: str, quality: str = 'best') -> tuple[str, dict, None]:
        variants = await self._streams(channel_id)
        if not variants:
            raise ValueError('TikTok 채널이 오프라인입니다.')
        selected = next((item for item in variants if item['value'] == quality), None)
        if selected is None:
            target = re.fullmatch(r'(\d+)p(?:(\d+(?:\.\d+)?))?', quality)
            eligible = [item for item in variants if target and 0 < self._rank(item)[0] <= int(target[1])
                        and (not target[2] or (item.get('fps') or 0) <= float(target[2]))]
            selected = (min(variants, key=self._rank) if quality == 'worst' or target and not eligible
                        else max(eligible or variants, key=self._rank))
        return selected['url'], tiktok_headers(channel_id), None

    async def get_preview_url(self, channel_id: str) -> str:
        return (await self.resolve_preview_stream(channel_id))[0]

    async def resolve_preview_stream(self, channel_id: str) -> tuple[str, dict, None]:
        variants = sorted(await self._streams(channel_id), key=self._rank, reverse=True)
        if not variants:
            raise ValueError('TikTok 채널이 오프라인입니다.')
        # 웹 브라우저 미리보기는 H.264(AVC) 코덱이어야 mpegts.js로 정상 디코딩됩니다.
        # H.265(HEVC) FLV는 브라우저 MSE에서 미지원되므로 H.264 변형을 우선 공급합니다.
        h264_variants = [v for v in variants if v.get('codec') == 'H.264' or v.get('value', '').startswith('h264_')]
        chosen = h264_variants[0] if h264_variants else variants[0]
        return chosen['url'], tiktok_headers(channel_id), None
