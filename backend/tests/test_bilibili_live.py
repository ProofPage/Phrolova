"""Bilibili 방 식별, 상태 오류와 Streamlink HLS 전송 선택을 검증한다."""
import http.cookiejar
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import requests

from app.engine.base import PlatformEngine
from app.engine.bilibili import (BilibiliLiveEngine, _cache_put, bilibili_access_error,
    canonical_bilibili_video_url, normalize_bilibili_channel_id)
from app.engine.recording_errors import RecordingError


@pytest.mark.parametrize('value', ['1726019661', '001726019661',
    'https://live.bilibili.com/1726019661?hotRank=0&live_from=81003',
    'https://live.bilibili.com/blanc/1726019661/'])
def test_live_room_normalization(value):
    assert normalize_bilibili_channel_id(value) == '1726019661'


@pytest.mark.parametrize('value', ['0', '-2', '123.0', '1e6', '１２３',
    'https://live.bilibili.com.evil.test/12', 'https://user@live.bilibili.com/12',
    'https://live.bilibili.com:444/12', 'https://www.bilibili.com/video/BV1cSec6tEux',
    'https://live.bilibili.com/12/other', 'file://live.bilibili.com/12'])
def test_invalid_live_inputs(value):
    with pytest.raises(ValueError):
        normalize_bilibili_channel_id(value)


@pytest.mark.parametrize('value,expected', [
    ('https://www.bilibili.com/video/BV1cSec6tEux/?trackid=x&p=2&spm_id_from=x#reply',
     'https://www.bilibili.com/video/BV1cSec6tEux/?p=2'),
    ('https://m.bilibili.com/video/av123?p=1', 'https://www.bilibili.com/video/av123/'),
    ('https://bilibili.com/video/BV1cSec6tEux?p=0003', 'https://www.bilibili.com/video/BV1cSec6tEux/?p=3'),
    ('https://b23.tv/Abc1234?share_source=copy', 'https://b23.tv/Abc1234'),
    ('BV1cSec6tEux', 'https://www.bilibili.com/video/BV1cSec6tEux/'),
    ('av000123', 'https://www.bilibili.com/video/av123/')])
def test_video_part_selection_and_tracking_removal(value, expected):
    assert canonical_bilibili_video_url(value) == expected


@pytest.mark.parametrize('value', ['https://bilibili.com/video/bv1cSec6tEux',
    'https://www.bilibili.com/video/BV1cSec6tEux?p=0',
    'https://www.bilibili.com/video/BV1cSec6tEux?p=1&p=2',
    'https://www.bilibili.com/video/BV1cSec6tEux?p=',
    'https://www.bilibili.com/video/av0', 'https://live.bilibili.com/1726019661',
    'https://bilibili.com.evil/video/BV1cSec6tEux', 'https://b23.tv/abc/extra',
    'https://user:secret@bilibili.com/video/BV1cSec6tEux'])
def test_invalid_video_inputs(value):
    with pytest.raises(ValueError):
        canonical_bilibili_video_url(value)


def mock_api(monkeypatch, *, status=1, api_code=0, anchor_code=0):
    import app.engine.bilibili as module
    monkeypatch.setattr(module, 'platform_cookie_jar', lambda _: http.cookiejar.MozillaCookieJar())
    original = httpx.AsyncClient
    calls = []
    def respond(request):
        calls.append(request)
        if request.url.path.endswith('/room_init'):
            assert request.url.params['id'] == '196'
            data = {'room_id': 33989, 'live_status': status, 'live_time': 1700000000}
            return httpx.Response(200, json={'code': api_code, 'data': data})
        if request.url.path.endswith('/get_info'):
            assert request.url.params['room_id'] == '33989'
            data = {'room_id': 33989, 'live_status': status, 'title': 'Live title', 'area_name': 'Game',
                    'online': 321, 'user_cover': 'https://i0.hdslb.com/cover.jpg', 'tags': 'games, talk'}
        else:
            assert request.url.params['roomid'] == '33989'
            return httpx.Response(200, json={'code': anchor_code, 'data': {'info': {'uname': 'Anchor', 'face': 'https://i0.hdslb.com/avatar.jpg'}}})
        return httpx.Response(200, json={'code': 0, 'data': data})
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *a, **kw: original(*a, **kw, transport=httpx.MockTransport(respond)))
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [0, 1, 2])
async def test_real_room_resolution_metadata_and_short_cache(monkeypatch, status):
    calls = mock_api(monkeypatch, status=status)
    engine = BilibiliLiveEngine()
    assert isinstance(engine, PlatformEngine)
    live = await engine.check_live_status('196')
    assert live['channel_id'] == '196' and live['real_room_id'] == '33989'
    assert live['is_live'] is (status == 1)
    assert live['viewer_count'] == (321 if status == 1 else 0)
    assert live['viewer_count_type'] == 'popularity'
    assert live['channel_name'] == 'Anchor' and live['category'] == 'Game'
    assert live['profile_image_url'].endswith('avatar.jpg')
    assert live['broadcast_tags'] == ['games', 'talk']
    assert live['live_started_at'] == ('2023-11-14T22:13:20+00:00' if status == 1 else None)
    await engine.check_live_status('196')
    assert len(calls) == 3
    assert all('cookie' not in request.headers for request in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize('code,reason', [(-352, 'bilibili_access'), (-101, 'bilibili_access'),
    (-404, 'bilibili_not_found'), (60004, 'bilibili_not_found')])
async def test_api_failure_is_not_saved_as_offline(monkeypatch, code, reason):
    calls = mock_api(monkeypatch, api_code=code)
    engine = BilibiliLiveEngine()
    with pytest.raises(RecordingError) as caught:
        await engine.check_live_status('196')
    assert caught.value.code == reason and engine._cache == {}
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_optional_avatar_failure_keeps_live_status(monkeypatch):
    mock_api(monkeypatch, anchor_code=-352)
    status = await BilibiliLiveEngine().check_live_status('196')
    assert status['is_live'] and status['channel_name'] == '196'


def stream_payload(*formats):
    return [{'protocol_name': 'http_hls', 'format': list(formats)}]


def media_format(container, *, quality=10000, codec='avc', host='https://cn.example.test', extra='?secret=fixture'):
    return {'format_name': container, 'codec': [{'codec_name': codec, 'current_qn': quality,
        'base_url': f'/{container}/{quality}/index.m3u8', 'url_info': [{'host': host, 'extra': extra}]}]}


def mock_streamlink(monkeypatch, payload):
    import app.engine.bilibili as module
    import streamlink
    import streamlink.plugins.bilibili as plugin
    sessions = []
    class Session:
        def __init__(self, *args, **kwargs):
            self.http = requests.Session()
            self.http.get = lambda *a, **kw: SimpleNamespace(text='#EXTM3U\n#EXT-X-TARGETDURATION:2\n#EXTINF:2,\nsegment.ts\n')
            self.options = {}
            self.closed = False
            close = self.http.close
            def closed():
                self.closed = True
                close()
            self.http.close = closed
            sessions.append(self)
        def set_option(self, key, value):
            self.options[key] = value
    class Plugin:
        def __init__(self, session, url):
            assert url == 'https://live.bilibili.com/33989'
            assert 'Cookie' not in session.http.headers and 'Authorization' not in session.http.headers
        def _get_api_v2_playinfo(self, room_id):
            assert room_id == '33989'
            return payload
    monkeypatch.setattr(module, 'platform_cookie_jar', lambda _: http.cookiejar.MozillaCookieJar())
    monkeypatch.setattr(streamlink, 'Streamlink', Session)
    monkeypatch.setattr(plugin, 'Bilibili', Plugin)
    engine = BilibiliLiveEngine()
    monkeypatch.setattr(engine, '_metadata', AsyncMock(return_value={'room_id': '33989', 'room': {'live_status': 1}}))
    return engine, sessions


@pytest.mark.asyncio
async def test_official_streamlink_hls_prefers_ts_and_hides_signed_urls(monkeypatch):
    engine, sessions = mock_streamlink(monkeypatch, stream_payload(media_format('fmp4'), media_format('ts'), media_format('ts', codec='hevc')))
    choices = await engine.get_qualities('196')
    assert len(choices) == 1
    assert choices[0]['value'] == 'qn_10000' and choices[0]['label'] == 'Original · HLS'
    assert choices[0]['transport'] == 'hls' and choices[0]['container'] == 'ts'
    assert choices[0]['height'] is None and choices[0]['fps'] is None
    assert 'secret' not in str(choices) and 'url' not in choices[0]
    choices[0]['label'] = 'mutated'
    url, headers, cookies = await engine.resolve_stream('196')
    assert '/ts/' in url and 'secret=fixture' in url
    assert headers['Referer'] == 'https://live.bilibili.com/196' and cookies is None
    assert (await engine.get_qualities('196'))[0]['label'] == 'Original · HLS'
    assert len(sessions) == 2 and all(session.closed for session in sessions)
    assert sessions[0].options == {'http-timeout': 12, 'no-plugin-cache': True, 'webbrowser': False}


@pytest.mark.asyncio
async def test_only_fmp4_reports_actual_container(monkeypatch):
    engine, _ = mock_streamlink(monkeypatch, stream_payload(media_format('fmp4')))
    assert (await engine.get_qualities('196'))[0]['container'] == 'fmp4'


@pytest.mark.asyncio
async def test_missing_explicit_platform_quality_is_not_silently_replaced(monkeypatch):
    engine, _ = mock_streamlink(monkeypatch, stream_payload(media_format('ts')))
    with pytest.raises(RecordingError) as caught:
        await engine.resolve_stream('196', 'qn_250')
    assert caught.value.code == 'bilibili_quality'


@pytest.mark.asyncio
async def test_quality_order_uses_platform_quality_ids(monkeypatch):
    engine, _ = mock_streamlink(monkeypatch, stream_payload(media_format('ts', quality=250), media_format('ts', quality=10000)))
    assert [item['value'] for item in await engine.get_qualities('196')] == ['qn_10000', 'qn_250']
    assert 'qn_250' == (await engine._streams('196'))[0]['value']
    url, _, _ = await engine.resolve_stream('196', 'qn_250')
    assert '/ts/250/' in url


def test_manifest_probe_tries_alternate_cdn_and_closes_session(monkeypatch):
    import streamlink
    engine, sessions = mock_streamlink(monkeypatch, [])
    factory = streamlink.Streamlink
    calls = []
    def create(*args, **kwargs):
        session = factory(*args, **kwargs)
        def get(url, **options):
            calls.append((url, options))
            if len(calls) == 1:
                raise requests.ReadTimeout('fixture timeout')
            return SimpleNamespace(text='#EXTM3U\n#EXT-X-MAP:URI="init.mp4"\n#EXTINF:2,\nseg.m4s\n')
        session.http.get = get
        return session
    monkeypatch.setattr(streamlink, 'Streamlink', create)
    selected = {'url': 'https://cdn-a.test/live.m3u8', 'container': 'ts',
                '_sources': (('https://cdn-a.test/live.m3u8', 'ts'), ('https://cdn-b.test/index.m3u8', 'fmp4'))}
    url, container = engine._probe_hls('196', selected)
    assert url == 'https://cdn-b.test/index.m3u8' and container == 'fmp4'
    assert len(calls) == 2 and all(
        options['retries'] == 0 and all(0 < value < float('inf') for value in options['timeout'])
        for _, options in calls)
    assert all(session.closed for session in sessions)


@pytest.mark.asyncio
async def test_all_cdn_failures_invalidate_signed_url_cache(monkeypatch):
    engine, _ = mock_streamlink(monkeypatch, stream_payload(media_format('ts')))
    def failed(*args):
        raise RecordingError('bilibili_connection', 'fixture', retryable=True)
    monkeypatch.setattr(engine, '_probe_hls', failed)
    with pytest.raises(RecordingError) as caught:
        await engine.resolve_stream('196')
    assert caught.value.retryable and engine._stream_cache == {}


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [None, [], stream_payload(media_format('ts', codec='hevc')),
    stream_payload(media_format('ts', host='file://host')), stream_payload(media_format('ts', host='https://user:secret@host'))])
async def test_empty_or_unsafe_streams_are_not_offline(monkeypatch, payload):
    engine, sessions = mock_streamlink(monkeypatch, payload)
    with pytest.raises(RecordingError) as caught:
        await engine.resolve_stream('196')
    assert caught.value.code == 'bilibili_stream_unavailable' and caught.value.retryable
    assert sessions[0].closed and engine._stream_cache == {}


@pytest.mark.asyncio
async def test_offline_status_does_not_open_streamlink(monkeypatch):
    engine = BilibiliLiveEngine()
    monkeypatch.setattr(engine, '_metadata', AsyncMock(return_value={'room': {'live_status': 0}}))
    assert await engine.get_qualities('196') == []
    with pytest.raises(ValueError, match='오프라인'):
        await engine.resolve_stream('196')


@pytest.mark.parametrize('status,code', [(401, 'bilibili_access'), (403, 'bilibili_access'), (412, 'bilibili_access'),
    (404, 'bilibili_not_found'), (429, 'bilibili_rate_limit')])
def test_http_errors_are_actionable(status, code):
    response = httpx.Response(status, request=httpx.Request('GET', 'https://api.live.bilibili.com/room'))
    with pytest.raises(httpx.HTTPStatusError) as caught:
        response.raise_for_status()
    assert bilibili_access_error(caught.value).code == code


def test_media_numbers_and_signed_urls_do_not_become_authentication_errors():
    assert bilibili_access_error(RuntimeError('Invalid NAL size 403 or https://cdn.test/file?code=403')) is None


def test_cache_has_fixed_channel_limit():
    cache = {}
    for index in range(300):
        _cache_put(cache, str(index), {'index': index})
    assert len(cache) == 128 and '0' not in cache and cache['299'][1] == {'index': 299}
