"""Bilibili 공개 방 정보와 Streamlink의 HLS 라이브 전송을 연결한다."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import re
import time
from urllib.parse import parse_qs, unquote, urlsplit

import httpx

from app.core.http import USER_AGENT
from app.engine.base import LiveStatus
from app.engine.platform_auth import platform_cookie_jar
from app.engine.recording_errors import RecordingError

ORIGIN = 'https://live.bilibili.com'
API = 'https://api.live.bilibili.com'
VIDEO_HOSTS = {'bilibili.com', 'www.bilibili.com', 'm.bilibili.com'}
QUALITY_NAMES = {80: 'Low', 150: 'High', 250: 'Super HD', 400: 'Blu-ray',
                 10000: 'Original', 15000: '2K', 20000: '4K', 30000: 'Dolby'}
QUALITY_RANK = {quality: rank for rank, quality in enumerate(QUALITY_NAMES)}


def _parts(value: str, hosts: set[str]):
    parts = urlsplit(str(value).strip())
    if (parts.scheme not in ('http', 'https') or parts.hostname not in hosts
            or parts.username is not None or parts.password is not None
            or parts.port not in (None, 80 if parts.scheme == 'http' else 443)):
        raise ValueError
    return parts


def normalize_bilibili_channel_id(value: str) -> str:
    try:
        raw = str(value or '').strip()
        if '://' in raw:
            parts = _parts(raw, {'live.bilibili.com'})
            match = re.fullmatch(r'/(?:blanc/)?([0-9]{1,20})/?', unquote(parts.path))
            if not match:
                raise ValueError
            raw = match[1]
        if not re.fullmatch(r'[0-9]{1,20}', raw) or int(raw) <= 0:
            raise ValueError
        return str(int(raw))
    except ValueError:
        raise ValueError('올바른 Bilibili 라이브 방 번호 또는 라이브 링크를 입력하세요.') from None


def canonical_bilibili_video_url(value: str) -> str:
    try:
        raw = str(value or '').strip()
        if re.fullmatch(r'BV[A-Za-z0-9]{10}|av[0-9]{1,20}', raw):
            raw = f'https://www.bilibili.com/video/{raw}'
        parts = _parts(raw, VIDEO_HOSTS | {'b23.tv'})
        path = unquote(parts.path)
        if parts.hostname == 'b23.tv':
            short = re.fullmatch(r'/([A-Za-z0-9]{1,64})/?', path)
            if not short:
                raise ValueError
            return f'https://b23.tv/{short[1]}'
        match = re.fullmatch(r'/video/(BV[A-Za-z0-9]{10}|av[0-9]{1,20})/?', path)
        if not match or match[1].startswith('av') and int(match[1][2:]) <= 0:
            raise ValueError
        query = parse_qs(parts.query, keep_blank_values=True)
        page = query.get('p', ['1'])
        if len(page) != 1 or not re.fullmatch(r'[0-9]{1,10}', page[0]) or not 1 <= int(page[0]) <= 2**31-1:
            raise ValueError
        # 재생목록의 회차 선택만 남겨 같은 영상이 추적 인자별로 중복 등록되지 않게 한다.
        suffix = f'?p={int(page[0])}' if int(page[0]) > 1 else ''
        video_id = f'av{int(match[1][2:])}' if match[1].startswith('av') else match[1]
        return f'https://www.bilibili.com/video/{video_id}/{suffix}'
    except ValueError:
        raise ValueError('올바른 Bilibili 동영상 또는 공유 링크를 입력하세요.') from None


def bilibili_access_error(error: Exception) -> RecordingError | None:
    if isinstance(error, RecordingError):
        return error
    status = getattr(getattr(error, 'response', None), 'status_code', None)
    text = re.sub(r'https?://\S+', '[url]', str(error).lower())
    http_status = lambda code: bool(re.search(rf'\b(?:http(?: error| status)?[: ]+{code}|{code} (?:client error|forbidden|not found|too many requests))\b', text))
    if status == 429 or http_status(429) or 'too many requests' in text:
        return RecordingError('bilibili_rate_limit', 'Bilibili 요청 한도에 도달했습니다. 잠시 후 다시 시도하세요.', retryable=True)
    if status in (401, 403, 412) or any(http_status(code) for code in (401, 403, 412)):
        return RecordingError('bilibili_access', 'Bilibili 접속이 제한되었습니다. 서버 접속 환경과 설정의 Bilibili 쿠키를 확인하세요.')
    if status == 404 or http_status(404):
        return RecordingError('bilibili_not_found', 'Bilibili 방송이나 영상을 찾을 수 없습니다. 주소와 공개 상태를 확인하세요.')
    if 'requested format is not available' in text:
        return RecordingError('bilibili_quality', '선택한 Bilibili 화질이 제공되지 않습니다. 영상 정보를 새로 조회하고 쿠키의 시청 권한을 확인하세요.')
    return None


def bilibili_headers(channel_id: str) -> dict[str, str]:
    return {'User-Agent': USER_AGENT, 'Origin': ORIGIN,
            'Referer': f'{ORIGIN}/{normalize_bilibili_channel_id(channel_id)}'}


def _integer(value: object, default: int = 0) -> int:
    try:
        return max(0, int(value)) if not isinstance(value, bool) else default
    except (ValueError, TypeError, OverflowError):
        return default


def _cache_put(cache: dict, key: str, value: dict | list) -> None:
    cache.pop(key, None)
    while len(cache) >= 128:
        cache.pop(next(iter(cache)))
    cache[key] = (time.monotonic(), value)


class BilibiliLiveEngine:
    def __init__(self):
        self._cache: dict[str, tuple[float, dict]] = {}
        self._stream_cache: dict[str, tuple[float, list[dict]]] = {}

    def get_stream_url(self, channel_id: str) -> str:
        return f'{ORIGIN}/{normalize_bilibili_channel_id(channel_id)}'

    async def _api(self, client, path: str, params: dict) -> dict:
        try:
            response = await client.get(f'{API}/{path}', params=params)
            response.raise_for_status()
            payload = response.json()
        except Exception as error:
            raise bilibili_access_error(error) or RuntimeError('Bilibili 방송 정보를 읽지 못했습니다.') from None
        if not isinstance(payload, dict) or not isinstance(payload.get('code'), int):
            raise RuntimeError('Bilibili 방송 정보 형식이 변경되었습니다.')
        code = payload['code']
        if code in (-101, -403, -352, -412):
            raise RecordingError('bilibili_access', 'Bilibili 접속이 제한되었습니다. 서버 접속 환경과 설정의 Bilibili 쿠키를 확인하세요.')
        if code in (-404, 19002003, 60004):
            raise RecordingError('bilibili_not_found', 'Bilibili 라이브 방을 찾을 수 없습니다. 방 번호와 공개 상태를 확인하세요.')
        if code != 0 or not isinstance(payload.get('data'), dict):
            raise RuntimeError('Bilibili 방송 정보 요청이 거부되었거나 응답 형식이 변경되었습니다.')
        return payload['data']

    async def _metadata(self, channel_id: str) -> dict:
        cid = normalize_bilibili_channel_id(channel_id)
        cached = self._cache.get(cid)
        if cached and time.monotonic()-cached[0] < 8:
            return cached[1]
        async with httpx.AsyncClient(timeout=12, headers=bilibili_headers(cid), cookies=platform_cookie_jar('bilibili')) as client:
            initial = await self._api(client, 'room/v1/Room/room_init', {'id': cid})
            real_id = _integer(initial.get('room_id'))
            if not real_id or initial.get('live_status') not in (0, 1, 2):
                raise RuntimeError('Bilibili 라이브 방 정보 형식이 변경되었습니다.')
            if initial.get('is_locked') or initial.get('encrypted') and not initial.get('pwd_verified'):
                raise RecordingError('bilibili_access', 'Bilibili 방송의 시청 권한이 필요합니다. 공개 상태와 등록한 쿠키를 확인하세요.')
            # 짧은 방 번호를 실제 방 번호로 바꿔야 상태 조회와 Streamlink 입력이 같은 방송을 가리킨다.
            room = await self._api(client, 'room/v1/Room/get_info', {'room_id': real_id})
            if _integer(room.get('room_id')) != real_id or room.get('live_status') not in (0, 1, 2):
                raise RuntimeError('Bilibili 방송 정보 형식이 변경되었습니다.')
            try:
                anchor = await self._api(client, 'live_user/v1/UserInfo/get_anchor_in_room', {'roomid': real_id})
            except Exception:
                # 아바타 API 오류 때문에 정상 방송을 오프라인으로 판정하지 않는다.
                anchor = {}
        data = {'room': room, 'anchor': anchor.get('info') if isinstance(anchor.get('info'), dict) else {},
                'room_id': str(real_id), 'initial': initial}
        _cache_put(self._cache, cid, data)
        return data

    async def check_live_status(self, channel_id: str) -> LiveStatus:
        cid = normalize_bilibili_channel_id(channel_id)
        data = await self._metadata(cid)
        room, anchor = data['room'], data['anchor']
        live = room['live_status'] == 1
        started = None
        if live:
            try:
                stamp = _integer(data['initial'].get('live_time'))
                if stamp:
                    started = datetime.fromtimestamp(stamp, timezone.utc).isoformat()
                elif room.get('live_time') and room['live_time'] != '0000-00-00 00:00:00':
                    started = datetime.strptime(room['live_time'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone(timedelta(hours=8))).isoformat()
            except (ValueError, TypeError, OverflowError, OSError):
                pass
        return LiveStatus(channel_id=cid, real_room_id=data['room_id'], is_live=live,
            channel_name=anchor.get('uname') or cid, title=room.get('title') or '',
            category=room.get('area_name') or room.get('parent_area_name') or '',
            viewer_count=_integer(room.get('online')) if live else 0, viewer_count_type='popularity',
            thumbnail_url=room.get('keyframe') or room.get('user_cover') or '',
            profile_image_url=anchor.get('face') or '', live_started_at=started,
            broadcast_tags=[tag.strip() for tag in str(room.get('tags') or '').split(',') if tag.strip()])

    async def _streams(self, channel_id: str) -> list[dict]:
        cid = normalize_bilibili_channel_id(channel_id)
        cached = self._stream_cache.get(cid)
        if cached and time.monotonic()-cached[0] < 4:
            return [dict(item) for item in cached[1]]
        metadata = await self._metadata(cid)
        if metadata['room']['live_status'] != 1:
            return []
        def resolve():
            from streamlink import Streamlink
            from streamlink.plugins.bilibili import Bilibili
            session = Streamlink()
            session.set_option('http-timeout', 12)
            session.set_option('no-plugin-cache', True)
            session.set_option('webbrowser', False)
            session.http.headers.update(bilibili_headers(cid))
            session.http.cookies.update(platform_cookie_jar('bilibili'))
            try:
                # 기본 best는 FLV이고 대체 HLS에는 fMP4도 있어 공식 플러그인의 전송 형식을 유지해 고른다.
                streams = Bilibili(session, self.get_stream_url(metadata['room_id']))._get_api_v2_playinfo(metadata['room_id'])
                variants = {}
                for item in streams or []:
                    if not isinstance(item, dict) or item.get('protocol_name') != 'http_hls':
                        continue
                    for fmt in item.get('format') or []:
                        container = fmt.get('format_name')
                        if container not in ('ts', 'fmp4'):
                            continue
                        for codec in fmt.get('codec') or []:
                            if codec.get('codec_name') != 'avc':
                                continue
                            qn = _integer(codec.get('current_qn'))
                            key = f'qn_{qn}' if qn else 'best'
                            for info in codec.get('url_info') or []:
                                url = f"{info.get('host', '')}{codec.get('base_url', '')}{info.get('extra', '')}"
                                parts = urlsplit(url)
                                if (parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password
                                        or parts.port not in (None, 80 if parts.scheme == 'http' else 443)):
                                    continue
                                source = (url, container)
                                variant = {'value': key, 'label': f"{QUALITY_NAMES.get(qn, 'Original')} · HLS",
                                    'url': url, 'height': None, 'width': None, 'fps': None, 'bitrate': None,
                                    'quality_id': qn or None, 'transport': 'hls', 'container': container, 'codec': 'avc',
                                    '_sources': (source,)}
                                previous = variants.get(key)
                                if previous is None:
                                    variants[key] = variant
                                elif source not in previous['_sources']:
                                    sources = tuple(sorted((*previous['_sources'], source), key=lambda item: item[1] != 'ts'))[:4]
                                    previous['_sources'] = sources
                                    previous['url'], previous['container'] = sources[0]
                if not variants:
                    raise RecordingError('bilibili_stream_unavailable',
                        'Bilibili 방송 중이지만 HLS 재생 주소를 가져오지 못했습니다. 서버 접속 상태와 쿠키의 시청 권한을 확인하세요.', retryable=True)
                return list(variants.values())
            except Exception as error:
                raise bilibili_access_error(error) or error from None
            finally:
                session.http.close()
        variants = await asyncio.to_thread(resolve)
        _cache_put(self._stream_cache, cid, variants)
        return [dict(item) for item in variants]

    @staticmethod
    def _rank(item: dict) -> tuple:
        return (QUALITY_RANK.get(item.get('quality_id'), -1), item.get('container') == 'ts')

    async def get_qualities(self, channel_id: str) -> list[dict]:
        return [{key: value for key, value in item.items() if key != 'url' and not key.startswith('_')} for item in
                sorted(await self._streams(channel_id), key=self._rank, reverse=True)]

    def _probe_hls(self, channel_id: str, selected: dict) -> tuple[str, str]:
        from streamlink import Streamlink
        session = Streamlink(plugins_builtin=False)
        session.http.headers.update(bilibili_headers(channel_id))
        session.http.cookies.update(platform_cookie_jar('bilibili'))
        errors = []
        try:
            # 첫 CDN만 느리거나 차단되어도 같은 공개 방송의 대체 CDN으로 연결할 수 있어야 한다.
            for url, container in selected.get('_sources', ((selected['url'], selected['container']),)):
                try:
                    response = session.http.get(url, timeout=(2, 3), retries=0)
                    text = response.text.lstrip('\ufeff \r\n')
                    if not text.startswith('#EXTM3U') or len(text) > 1024*1024:
                        raise RuntimeError('Bilibili HLS 재생 목록 형식이 올바르지 않습니다.')
                    actual = 'fmp4' if '#EXT-X-MAP:' in text else container
                    return url, actual
                except Exception as error:
                    errors.append(error)
            access_error = next((mapped for error in errors if (mapped := bilibili_access_error(error))), None)
            if access_error:
                raise access_error
            raise RecordingError('bilibili_connection',
                'Bilibili 라이브 CDN에 연결하지 못했습니다. 서버의 접속 지역과 네트워크 상태를 확인하세요.', retryable=True)
        finally:
            session.http.close()

    async def resolve_stream(self, channel_id: str, quality: str = 'best') -> tuple[str, dict, None]:
        variants = await self._streams(channel_id)
        if not variants:
            raise ValueError('Bilibili 채널이 오프라인입니다.')
        selected = next((item for item in variants if item['value'] == quality), None)
        if selected is None:
            if quality.startswith('qn_'):
                raise RecordingError('bilibili_quality',
                    '선택한 Bilibili 라이브 화질이 제공되지 않습니다. 화질 목록을 새로 조회하세요.')
            selected = (min if quality == 'worst' else max)(variants, key=self._rank)
        if time.monotonic()-selected.get('_verified_at', 0) < 4:
            url = selected['url']
        else:
            try:
                url, container = await asyncio.to_thread(self._probe_hls, channel_id, selected)
            except Exception:
                self._stream_cache.pop(normalize_bilibili_channel_id(channel_id), None)
                raise
            cached = self._stream_cache.get(normalize_bilibili_channel_id(channel_id))
            if cached:
                for item in cached[1]:
                    if item['value'] == selected['value']:
                        item.update(url=url, container=container, _verified_at=time.monotonic())
        return url, bilibili_headers(channel_id), None

    async def get_preview_url(self, channel_id: str) -> str:
        return (await self.resolve_stream(channel_id))[0]
