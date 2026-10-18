"""팬더티비의 공식 웹 API와 Streamlink HLS 녹화·미리보기를 연결한다."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import re
import time
from urllib.parse import unquote, urljoin, urlsplit

import httpx

from app.core.http import USER_AGENT
from app.engine.base import LiveStatus
from app.engine.platform_auth import platform_cookie_jar
from app.engine.recording_errors import RecordingError

ORIGIN = 'https://www.pandalive.co.kr'
API = 'https://api.pandalive.co.kr/v1'
HOSTS = {'pandalive.co.kr', 'www.pandalive.co.kr'}
CHANNEL = r'[A-Za-z0-9][A-Za-z0-9_-]{0,99}'


def normalize_pandalive_channel_id(value: str) -> str:
    try:
        raw = str(value or '').strip()
        if re.search(r'[\x00-\x20\\]', raw):
            raise ValueError
        if '://' in raw:
            parts = urlsplit(raw)
            if (parts.scheme not in ('https', 'http') or parts.hostname not in HOSTS
                    or parts.username is not None or parts.password is not None
                    or parts.port not in (None, 443 if parts.scheme == 'https' else 80)):
                raise ValueError
            match = re.fullmatch(r'/play/('+CHANNEL+r')/?', unquote(parts.path))
            if not match:
                raise ValueError
            raw = match[1]
        if not re.fullmatch(CHANNEL, raw):
            raise ValueError
        return raw.lower()
    except ValueError:
        raise ValueError('올바른 팬더티비 채널 ID 또는 방송 링크를 입력하세요.') from None


def pandalive_headers(channel_id: str) -> dict[str, str]:
    return {'User-Agent': USER_AGENT, 'Origin': ORIGIN,
            'Referer': ORIGIN+'/play/'+normalize_pandalive_channel_id(channel_id)}


def _media_url(value):
    try:
        parts = urlsplit(value)
        host = parts.hostname or ''
        return (parts.scheme == 'https' and parts.port in (None,443)
                and parts.username is None and parts.password is None and not parts.fragment
                and any(host == domain or host.endswith('.'+domain)
                        for domain in ('pandalive.co.kr','live-video.net')))
    except (ValueError, TypeError):
        return False


def _error(message: str) -> RecordingError:
    if any(word in message for word in ('본인인증','본인 인증','성인인증','성인 인증','로그인')):
        return RecordingError('pandalive_authentication',
            '팬더티비 본인인증 또는 로그인이 필요합니다. 사이트에서 인증을 완료한 계정의 쿠키를 설정 → 인증에 등록하세요.')
    if any(word in message for word in ('비밀번호','암호')):
        return RecordingError('pandalive_password', '비밀번호로 보호된 팬더티비 방송은 지원하지 않습니다.')
    return RecordingError('pandalive_access', '팬더티비 방송의 시청 권한과 사이트 접속 상태를 확인하세요.')


def _cache(cache, key, data):
    cache.pop(key, None)
    while len(cache) >= 128:
        cache.pop(next(iter(cache)))
    cache[key] = (time.monotonic(), data)


class PandaliveLiveEngine:
    def __init__(self):
        self._cache = {}
        self._stream_cache = {}

    def get_stream_url(self, channel_id: str) -> str:
        return ORIGIN+'/play/'+normalize_pandalive_channel_id(channel_id)

    async def _api(self, client, path, data):
        try:
            response = await client.post(API+path, data=data)
            if response.status_code == 429:
                raise RecordingError('pandalive_rate_limit', '팬더티비 요청 한도에 도달했습니다. 잠시 후 다시 시도하세요.', retryable=True)
            if response.status_code in (401,403):
                raise _error('로그인')
            if response.status_code == 404:
                raise RecordingError('pandalive_not_found', '팬더티비 채널을 찾을 수 없습니다. 방송 링크를 확인하세요.')
            # 본인인증이 필요한 방송도 HTTP 400의 정상 JSON 오류로 응답한다.
            if response.status_code != 400:
                response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError:
            raise RecordingError('pandalive_connection', '팬더티비 서버에 연결하지 못했습니다. 잠시 후 다시 시도하세요.', retryable=True) from None
        except ValueError:
            raise RecordingError('pandalive_response', '팬더티비 방송 정보 응답을 읽지 못했습니다.') from None
        if not isinstance(payload, dict) or type(payload.get('result')) is not bool:
            raise RecordingError('pandalive_response', '팬더티비 방송 정보 형식이 변경되었습니다.')
        return payload

    async def _metadata(self, channel_id):
        cid = normalize_pandalive_channel_id(channel_id)
        cached = self._cache.get(cid)
        if cached and time.monotonic()-cached[0] < 8:
            return cached[1]
        async with httpx.AsyncClient(timeout=12, headers=pandalive_headers(cid),
                cookies=platform_cookie_jar('pandalive'), follow_redirects=False) as client:
            profile = await self._api(client, '/member/bj', {'userId':cid})
            if not profile['result']:
                raise RecordingError('pandalive_not_found', '팬더티비 채널을 찾을 수 없습니다. 방송 링크를 확인하세요.')
            member = profile.get('bjInfo')
            if (not isinstance(member,dict) or str(member.get('id','')).lower() != cid
                    or type(member.get('idx')) is not int or member['idx'] <= 0):
                raise RecordingError('pandalive_response', '팬더티비 채널 식별 정보가 다릅니다.')
            playback = await self._api(client, '/live/play', {'action':'watch','userId':member['idx']})
        media = playback.get('media')
        if not playback['result']:
            message = str(playback.get('message') or '')
            if any(text in message for text in ('방송이 종료','방송종료','방송 중이 아닙','방송중이 아닙','방송중인 미디어가 없')):
                media = {'isLive':False, 'userId':cid}
            else:
                raise _error(message)
        if (not isinstance(media,dict) or type(media.get('isLive')) is not bool
                or str(media.get('userId','')).lower() != cid):
            raise RecordingError('pandalive_response', '팬더티비 방송 식별 정보가 다릅니다.')
        if media.get('isPw'):
            raise _error('비밀번호')
        if playback.get('adultOut') or any(isinstance(playback.get(key),dict) and playback[key].get('enable')
                for key in ('roomBanInfo','roomBlindInfo','roomFreezeInfo')):
            raise _error('본인인증' if playback.get('adultOut') else '')
        data = dict(member=member, media=media, playback=playback)
        _cache(self._cache,cid,data)
        return data

    async def check_live_status(self, channel_id: str) -> LiveStatus:
        cid = normalize_pandalive_channel_id(channel_id)
        data = await self._metadata(cid)
        media, member = data['media'], data['member']
        started = None
        try:
            if media['isLive'] and media.get('startTime'):
                started = datetime.strptime(media['startTime'],'%Y-%m-%d %H:%M:%S').replace(
                    tzinfo=timezone(timedelta(hours=9))).isoformat()
        except (TypeError,ValueError):
            pass
        viewers = media.get('user')
        return LiveStatus(channel_id=cid,is_live=media['isLive'],channel_name=member.get('nick') or cid,
            title=media.get('title') or '',category=media.get('category') or '',
            viewer_count=max(0,viewers) if type(viewers) is int and media['isLive'] else 0,
            thumbnail_url=media.get('thumbUrl') or '', profile_image_url=member.get('thumbUrl') or '',
            live_started_at=started)

    async def _streams(self, channel_id):
        cid = normalize_pandalive_channel_id(channel_id)
        cached = self._stream_cache.get(cid)
        if cached and time.monotonic()-cached[0] < 4:
            return [dict(item) for item in cached[1]]
        data = await self._metadata(cid)
        if not data['media']['isLive']:
            return []
        playlist = data['playback'].get('PlayList')
        if not isinstance(playlist,dict):
            raise _error('')
        urls = []
        for key in ('hls','hls2','hls3'):
            items = playlist.get(key) or []
            if not isinstance(items,list) or len(items)>32:
                raise RecordingError('pandalive_response','팬더티비 재생 목록 형식이 변경되었습니다.')
            for item in items:
                url = item.get('url') if isinstance(item,dict) else None
                if _media_url(url) and url not in urls:
                    urls.append(url)
        if not urls:
            raise RecordingError('pandalive_stream', '팬더티비 방송에서 지원되는 HLS 재생 주소를 찾지 못했습니다.')
        def resolve():
            from streamlink import Streamlink
            from streamlink.stream.hls import HLSStream
            session = Streamlink(plugins_builtin=False)
            session.set_option('http-timeout',12)
            session.http.cookies.update(platform_cookie_jar('pandalive'))
            from app.engine.streamlink_support import configure_streamlink_session
            configure_streamlink_session(session, "pandalive", self.get_stream_url(cid))
            headers = pandalive_headers(cid)
            def redirect_guard(response, *args, **kwargs):
                if response.is_redirect and not _media_url(urljoin(response.url,response.headers.get('Location',''))):
                    raise RecordingError('pandalive_stream', '팬더티비 재생 서버의 이동 주소가 허용되지 않습니다.')
            session.http.hooks['response'].append(redirect_guard)
            try:
                last_error = None
                for url in urls:
                    try:
                        variants = []
                        streams = HLSStream.parse_variant_playlist(session,url,headers=headers)
                        for name,stream in streams.items():
                            match = re.fullmatch(r'(\d+)p(?:(\d+(?:\.\d+)?))?',name)
                            if not match:
                                continue
                            target = stream.to_url()
                            if not _media_url(target):
                                raise RecordingError('pandalive_stream','팬더티비 화질별 재생 주소가 허용되지 않습니다.')
                            info = next((p.stream_info for p in getattr(getattr(stream,'multivariant',None),'playlists',[]) if p.uri == target),None)
                            size = getattr(info,'resolution',None)
                            variants.append(dict(value=name,label=name,url=target,
                                height=getattr(size,'height',None) or int(match[1]),width=getattr(size,'width',None),
                                fps=getattr(info,'framerate',None) or (float(match[2]) if match[2] else None),
                                bitrate=getattr(info,'bandwidth',None)))
                        if variants:
                            return variants
                    except RecordingError:
                        raise
                    except Exception:
                        last_error = True
                raise RecordingError('pandalive_stream', '팬더티비 라이브 화질 정보를 가져오지 못했습니다.',retryable=bool(last_error))
            finally:
                session.http.close()
        variants = await asyncio.to_thread(resolve)
        _cache(self._stream_cache,cid,variants)
        return [dict(item) for item in variants]

    async def get_qualities(self, channel_id):
        variants = await self._streams(channel_id)
        return [{k:v for k,v in item.items() if k != 'url'} for item in sorted(
            variants,key=lambda item:(item['height'],item['fps'] or 0),reverse=True)]

    async def resolve_stream(self, channel_id, quality='best'):
        variants = await self._streams(channel_id)
        if not variants:
            raise ValueError('팬더티비 채널이 오프라인입니다.')
        order = lambda item:(item['height'],item['fps'] or 0,item['bitrate'] or 0)
        selected = next((item for item in variants if item['value']==quality),None)
        if selected is None:
            if quality not in ('best','worst'):
                raise RecordingError('pandalive_quality','선택한 팬더티비 화질이 제공되지 않습니다. 현재 화질 목록을 새로 조회하세요.')
            selected = (min if quality=='worst' else max)(variants,key=order)
        return selected['url'],pandalive_headers(channel_id),None

    async def get_preview_url(self, channel_id):
        return (await self.resolve_stream(channel_id,'best'))[0]
