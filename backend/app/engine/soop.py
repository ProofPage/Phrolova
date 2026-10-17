"""SOOP live metadata and the official Streamlink SOOP stream resolver."""
from __future__ import annotations
import asyncio
import re
import time
from urllib.parse import urlsplit, unquote
import httpx
from app.core.config import get_settings
from app.core.http import USER_AGENT
from app.engine.base import LiveStatus
from app.engine.platform_auth import (PlatformAuthenticationError, get_platform_cookies,
                                       platform_cookie_jar, platform_cookie_status)

ORIGIN = 'https://play.sooplive.com'
CHANNEL_API = 'https://live.sooplive.com/afreeca/player_live_api.php'
CHANNEL_HOSTS = {'play.sooplive.com', 'play.sooplive.co.kr', 'play.afreecatv.com',
                 'www.sooplive.com', 'www.sooplive.co.kr', 'bj.afreecatv.com', 'station.sooplive.com'}
VOD_HOSTS = {'vod.sooplive.com', 'vod.sooplive.co.kr', 'vod.afreecatv.com'}


def normalize_soop_channel_id(value: str) -> str:
    raw = str(value or '').strip()
    if '://' in raw:
        try:
            p = urlsplit(raw)
            if p.scheme not in ('http', 'https') or p.hostname not in CHANNEL_HOSTS or p.username or p.password or p.port not in (None, 80 if p.scheme == 'http' else 443):
                raise ValueError
            pattern = r'/([A-Za-z0-9_]+)(?:/\d+)?/?' if p.hostname.startswith('play.') else r'/(?:station/)?([A-Za-z0-9_]+)/?'
            match = re.fullmatch(pattern, unquote(p.path))
            if not match:
                raise ValueError
            raw = match[1]
        except ValueError:
            raise ValueError('올바른 숲 채널 ID 또는 채널 링크를 입력하세요.') from None
    if not re.fullmatch(r'[A-Za-z0-9_]{1,100}', raw):
        raise ValueError('올바른 숲 채널 ID 또는 채널 링크를 입력하세요.')
    return raw.lower()

def normalize_soop_vod_url(value: str) -> str:
    try:
        p = urlsplit(str(value).strip())
        if p.scheme not in ('http', 'https') or p.hostname not in VOD_HOSTS or p.username or p.password or p.port not in (None, 80 if p.scheme == 'http' else 443):
            raise ValueError
        m = re.fullmatch(r'/player/(\d+)(?:/(catch|catchstory))?/?', p.path)
        if not m:
            raise ValueError
        return f'https://vod.sooplive.com/player/{m[1]}' + (f'/{m[2]}' if m[2] else '')
    except ValueError:
        raise ValueError('올바른 숲 다시보기 또는 클립 링크를 입력하세요.') from None


class SoopLiveEngine:
    def __init__(self):
        self._cache: dict[str, tuple[float, dict, dict]] = {}

    def get_stream_url(self, channel_id: str) -> str:
        return f'{ORIGIN}/{normalize_soop_channel_id(channel_id)}'

    async def _metadata(self, channel_id: str) -> tuple[dict, dict]:
        cid = normalize_soop_channel_id(channel_id)
        cached = self._cache.get(cid)
        if cached and time.monotonic() - cached[0] < 8:
            return cached[1], cached[2]
        headers = {'User-Agent': USER_AGENT, 'Referer': self.get_stream_url(cid), 'Origin': ORIGIN}
        requires_cookie = False
        soop_proxy = get_settings().soop_proxy
        async with httpx.AsyncClient(timeout=12, headers=headers, proxy=soop_proxy) as client:
            response = await client.post(CHANNEL_API, data={'bid': cid, 'type': 'live', 'player_type': 'html5', 'stream_type': 'common', 'mode': 'landing'})
            data = response.json() if response.status_code == 200 else {}
            channel = data.get('CHANNEL') if isinstance(data, dict) else None
            if channel is None: channel = {}
            if not isinstance(channel, dict): raise RuntimeError('숲 방송 정보 형식이 변경되었습니다.')
            if response.status_code in (401, 403) or channel.get('RESULT') in (-6, '-6'):
                requires_cookie = True
                cookies = get_platform_cookies('soop', CHANNEL_API)
                if not cookies:
                    raise PlatformAuthenticationError('soop', expired=platform_cookie_status('soop')['expired'])
                response = await client.post(CHANNEL_API, data={'bid': cid, 'type': 'live', 'player_type': 'html5', 'stream_type': 'common', 'mode': 'landing'}, cookies=cookies)
                channel = (response.json().get('CHANNEL') or {}) if response.status_code == 200 else {}
                if response.status_code in (401, 403) or channel.get('RESULT') in (-6, '-6'):
                    raise PlatformAuthenticationError('soop', permission_denied=True)
            if response.status_code != 200 or not isinstance(channel, dict) or 'RESULT' not in channel:
                raise RuntimeError('숲 방송 정보를 가져오지 못했습니다.')
            station = {}
            if str(channel.get('RESULT')) == '1':
                # Station totals do not contain current viewers. The official
                # channel API supplies broad.current_sum_viewer for this live.
                try:
                    info = await client.get(f'https://chapi.sooplive.com/api/{cid}/station')
                    if info.status_code == 200:
                        body = info.json()
                        if isinstance(body, dict):
                            station = body.get('DATA') or body
                            if not isinstance(station, dict): station = {}
                except (httpx.HTTPError, ValueError):
                    # Optional display metadata must not block live detection
                    # or the independent Streamlink recording resolver.
                    pass
        self._cache[cid] = (time.monotonic(), channel, station)
        channel['_requires_cookie'] = requires_cookie
        return channel, station

    async def check_live_status(self, channel_id: str) -> LiveStatus:
        cid = normalize_soop_channel_id(channel_id)
        c, s = await self._metadata(cid)
        live = str(c.get('RESULT')) == '1' and bool(c.get('BNO'))
        def count(value):
            if value is None or isinstance(value, bool): return None
            try: return max(0, int(value))
            except (ValueError, TypeError, OverflowError): return None
        broad = s.get('broad') if isinstance(s.get('broad'), dict) else {}
        station_info = s.get('station') if isinstance(s.get('station'), dict) else {}
        current = count(broad.get('current_sum_viewer')) if str(broad.get('broad_no')) == str(c.get('BNO')) else None
        if current is None:
            current = next((parsed for value in (c.get('VIEW_CNT'), c.get('CURRENT_VIEW_CNT'), s.get('view_cnt'))
                            if (parsed := count(value)) is not None), 0)
        return LiveStatus(channel_id=cid, is_live=live, channel_name=c.get('BJNICK') or s.get('station_name') or cid,
            title=c.get('TITLE') or s.get('station_title') or '', category=c.get('CATE') or s.get('category_name') or '',
            viewer_count=current if live else 0,
            thumbnail_url=c.get('THUMB') or s.get('broad_thumb') or '',
            profile_image_url=s.get('profile_image') or '', live_started_at=s.get('broad_start') or station_info.get('broad_start'))

    async def get_qualities(self, channel_id: str) -> list[dict]:
        channel, _ = await self._metadata(channel_id)
        values = []
        for item in channel.get('VIEWPRESET') or []:
            if not isinstance(item, dict) or item.get('name') == 'auto': continue
            resolution = str(item.get('label_resolution') or item.get('label') or '')
            dimensions = re.search(r'(\d+)\s*[xX]\s*(\d+)', resolution)
            height = int(dimensions[2]) if dimensions else int(re.search(r'(\d+)p', resolution)[1]) if re.search(r'(\d+)p', resolution) else 0
            if not height: continue
            try: bitrate = float(item.get('bps') or 0) * 1000
            except (TypeError, ValueError): bitrate = 0
            values.append({'value': f'{height}p', 'label': f'{height}p', 'height': height,
                           'width': int(dimensions[1]) if dimensions else None, 'bitrate': bitrate or None})
        return sorted({v['value']: v for v in values}.values(), key=lambda v: v['height'], reverse=True)

    async def resolve_stream(self, channel_id: str, quality: str = 'best', *, for_preview: bool = False) -> tuple[str, dict, str | None]:
        cid = normalize_soop_channel_id(channel_id)
        channel, _ = await self._metadata(cid)
        if str(channel.get('RESULT')) != '1' or not channel.get('BNO'):
            raise ValueError('숲 채널이 오프라인입니다.')
        bno = str(channel.get("BNO"))
        page = f'{self.get_stream_url(cid)}/{bno}'

        def resolve(authenticated: bool):
            from streamlink import Streamlink
            from streamlink.plugins.soop import Soop
            # 그리드(P2P) 및 국내 540p 강제 제한을 우회하기 위해 글로벌 무그리드 CDN(gcp_cdn) 매핑 적용
            try:
                Soop.CDN_TYPE_MAPPING = {
                    "gs_cdn": "gcp_cdn",
                    "lg_cdn": "gcp_cdn",
                }
            except Exception:
                pass
            session = Streamlink()
            session.set_option('http-timeout', 15)
            session.set_option('ffmpeg-ffmpeg', get_settings().resolve_ffmpeg_path())
            if authenticated:
                session.http.cookies.update(platform_cookie_jar('soop'))
            try:
                streams = session.streams(page)
                ranked = [(int(m[1]), name, stream) for name, stream in streams.items()
                          if (m := re.search(r'(\d+)p', name)) and name not in ('best','worst')]
                if quality == 'best': stream = streams.get('best')
                elif quality == 'worst': stream = streams.get('worst')
                else:
                    match = re.match(r'(\d+)p', quality)
                    limited = [s for s in ranked if match and s[0] <= int(match[1])]
                    stream = max(limited or ranked, key=lambda s:s[0])[2] if ranked else None
                if not stream: return None
                url = stream.to_url()
                cookie = '; '.join(f'{k}={v}' for k,v in get_platform_cookies('soop', url).items()) if authenticated else None
                return url, {'User-Agent': USER_AGENT, 'Referer': page, 'Origin': ORIGIN}, cookie
            finally:
                session.http.close()

        try:
            result = await asyncio.to_thread(resolve, False)
        except Exception:
            result = None
        if result:
            return result
        denied = channel.get('_requires_cookie', False)
        if not denied:
            soop_proxy = get_settings().soop_proxy
            async with httpx.AsyncClient(timeout=12, headers={'User-Agent': USER_AGENT, 'Referer': page}, proxy=soop_proxy) as client:
                response = await client.post(CHANNEL_API, data={'bid':cid, 'bno':str(channel['BNO']), 'type':'aid', 'quality':'master', 'stream_type':'common', 'player_type':'html5'})
                info = response.json().get('CHANNEL') or {} if response.status_code == 200 else {}
                denied = response.status_code in (401,403) or info.get('RESULT') in (-6,'-6')
        if not denied:
            raise RuntimeError('숲 라이브 스트림을 연결하지 못했습니다. 잠시 후 다시 시도하세요.')
        if len(platform_cookie_jar('soop')):
            try:
                result = await asyncio.to_thread(resolve, True)
            except Exception:
                result = None
            if result:
                return result
            raise PlatformAuthenticationError('soop', permission_denied=True)
        raise PlatformAuthenticationError('soop', expired=platform_cookie_status('soop')['expired'])

    async def get_preview_url(self, channel_id: str) -> str:
        return (await self.resolve_stream(channel_id, '1080p', for_preview=True))[0]
