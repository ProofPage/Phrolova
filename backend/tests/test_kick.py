"""Kick 등록, 인증 화질과 미디어 전달 경계의 회귀 검증."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.engine.base import Platform, PlatformEngine
from app.engine.kick import (KickLiveEngine, canonical_kick_video_url, kick_access_error,
                             kick_api_headers, normalize_kick_channel_id)
from app.engine.platform_auth import get_platform_cookies, platform_cookie_file, platform_cookie_status
from app.engine.platform_media import canonical_platform_video, media_platform
from app.engine.recording_errors import RecordingError, classify_recording_error
from app.engine.vod import NonRetryableDownloadError, VodDownloadTask, VodEngine
from app.engine.vod_preparation import canonical_prepared_url

VOD = 'https://kick.com/alice/videos/49d06353-e235-48c3-97fd-99c0d5e432c6'


def cookie_file(tmp_path, name='session_token', expiry='0'):
    path = tmp_path / 'kick.txt'
    path.write_text(f'# Netscape HTTP Cookie File\n.kick.com\tTRUE\t/\tTRUE\t{expiry}\t{name}\tfixture-token\n'
                    '.evil.example\tTRUE\t/\tTRUE\t0\tsession_token\twrong\n')
    get_settings().kick_cookie_file = str(path)
    return path


@pytest.mark.parametrize('value', ['Alice', 'alice_1', 'alice-name', 'https://kick.com/Alice', 'https://www.kick.com/alice/?ref=home'])
def test_channel_inputs(value):
    assert normalize_kick_channel_id(value) == ('alice_1' if value == 'alice_1' else 'alice-name' if value == 'alice-name' else 'alice')


@pytest.mark.parametrize('value', ['https://kick.com.evil/alice', 'https://user:pass@kick.com/alice',
    'https://kick.com:444/alice', VOD, 'https://kick.com/alice?clip=clip_x', 'search', 'api', '@alice', 'https://kick.com/alice/other'])
def test_invalid_channel_inputs(value):
    with pytest.raises(ValueError):
        normalize_kick_channel_id(value)


@pytest.mark.parametrize('value,expected', [(VOD+'?ref=share#t=1', VOD),
    ('https://www.kick.com/Alice?clip=clip_ABC&ref=share', 'https://kick.com/alice/clips/clip_ABC'),
    ('https://kick.com/alice/clips/clip_ABC/', 'https://kick.com/alice/clips/clip_ABC')])
def test_video_normalization_and_preparation(value, expected):
    assert canonical_kick_video_url(value) == expected
    assert canonical_platform_video(value) == expected
    assert canonical_prepared_url(value, 'kick') == expected
    assert canonical_prepared_url(value, 'auto') == expected
    assert media_platform(value) == 'kick'


@pytest.mark.parametrize('value', ['https://kick.com/alice', 'https://kick.com/alice/videos/invalid',
    'https://kick.com.evil/alice/videos/49d06353-e235-48c3-97fd-99c0d5e432c6',
    'https://kick.com/alice?clip=clip_a&clip=clip_b', 'https://kick.com/api/clips/clip_x'])
def test_invalid_video_routes(value):
    with pytest.raises(ValueError):
        canonical_kick_video_url(value)


def mock_http(monkeypatch, handler):
    client = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *a, **kw: client(*a, **kw, transport=httpx.MockTransport(handler)))


@pytest.mark.asyncio
@pytest.mark.parametrize('live', [None, {'session_title':'Live', 'viewer_count':13, 'thumbnail':{'url':'https://images.kick.com/test.jpg'}, 'categories':[{'name':'Games'}]}])
async def test_metadata_online_and_offline(monkeypatch, live):
    get_settings().kick_cookie_file = None
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={'id':1, 'user':{'username':'Alice', 'profile_pic':'https://files.kick.com/a.png'}, 'livestream':live})
    mock_http(monkeypatch, respond)
    engine = KickLiveEngine()
    assert isinstance(engine, PlatformEngine)
    status = await engine.check_live_status('alice')
    assert status['is_live'] is bool(live)
    assert status['viewer_count'] == (13 if live else 0)
    assert status['channel_name'] == 'Alice'
    await engine.check_live_status('alice')
    assert len(calls) == 1 and 'cookie' not in calls[0].headers


@pytest.mark.asyncio
@pytest.mark.parametrize('code,reason', [(403,'kick_access'), (404,'kick_not_found'), (429,'kick_rate_limit')])
async def test_failed_api_is_not_offline(monkeypatch, code, reason):
    mock_http(monkeypatch, lambda _: httpx.Response(code))
    with pytest.raises(RecordingError) as captured:
        await KickLiveEngine().check_live_status('alice')
    assert classify_recording_error(captured.value).code == reason


@pytest.mark.asyncio
async def test_invalid_api_is_not_offline(monkeypatch):
    mock_http(monkeypatch, lambda _: httpx.Response(200, json={'message':'challenge'}))
    with pytest.raises(RuntimeError):
        await KickLiveEngine().check_live_status('alice')


@pytest.mark.asyncio
async def test_metadata_uses_registered_kick_session_only(monkeypatch, tmp_path):
    cookie_file(tmp_path)
    def respond(request):
        assert request.headers['Authorization'] == 'Bearer fixture-token'
        assert 'fixture-token' in request.headers['Cookie'] and 'wrong' not in request.headers['Cookie']
        return httpx.Response(200, json={'id':1, 'livestream':None})
    mock_http(monkeypatch, respond)
    await KickLiveEngine().check_live_status('alice')
    for url in ('https://cdn.live-video.net/api/media.m3u8', 'https://kick.com.evil/api/test', 'https://kick.com/alice'):
        assert kick_api_headers(url) == {}
    assert get_platform_cookies('kick','https://cdn.live-video.net/media') == {}


def test_cookie_expiry_and_temporary_copy(tmp_path):
    original = cookie_file(tmp_path)
    assert platform_cookie_status('kick')['valid']
    with platform_cookie_file('kick') as copy:
        assert Path(copy).exists() and Path(copy) != original
        assert 'evil.example' not in Path(copy).read_text()
    assert not Path(copy).exists() and original.exists()
    cookie_file(tmp_path, expiry='1')
    assert platform_cookie_status('kick')['expired']


@pytest.mark.asyncio
async def test_streamlink_authenticated_qualities_and_selection(monkeypatch, tmp_path):
    import streamlink
    cookie_file(tmp_path)
    sessions = []
    class Session:
        def __init__(self):
            self.http = requests.Session()
            self.options = {}
            self.closed = False
            close = self.http.close
            def closed(): self.closed = True; close()
            self.http.close = closed
            sessions.append(self)
        def set_option(self, key, value): self.options[key] = value
        def streams(self, page):
            assert page == 'https://kick.com/alice'
            self.http.headers.update({'Authorization':'cached-secret','Cookie':'cached-secret'})
            api = self.http.prepare_request(requests.Request('GET','https://kick.com/api/v2/channels/alice/livestream'))
            cdn = self.http.prepare_request(requests.Request('GET','https://cdn.live-video.net/media.m3u8'))
            assert api.headers['Authorization'] == 'Bearer fixture-token'
            assert 'fixture-token' in api.headers['Cookie']
            assert 'Authorization' not in cdn.headers and 'Cookie' not in cdn.headers
            def stream(h):
                return SimpleNamespace(to_url=lambda:f'https://cdn.live-video.net/{h}.m3u8', multivariant=None)
            return {'1080p60':stream(1080), '720p':stream(720), 'best':stream(1080), 'audio_only':stream(0)}
    monkeypatch.setattr(streamlink, 'Streamlink', Session)
    engine = KickLiveEngine()
    qualities = await engine.get_qualities('alice')
    assert [v['value'] for v in qualities] == ['1080p60','720p']
    assert not any('url' in v for v in qualities)
    for quality, height in [('1080p',1080), ('best',1080), ('worst',720), ('1080p30',720)]:
        if quality == '1080p30':
            with pytest.raises(RecordingError, match='화질'): await engine.resolve_stream('alice', quality)
            continue
        url, headers, cookies = await engine.resolve_stream('alice', quality)
        assert url.endswith(f'/{height}.m3u8') and not cookies
        assert 'Authorization' not in headers and 'Cookie' not in headers
    assert all(s.closed and s.options['webbrowser'] is False and s.options['no-plugin-cache'] is True for s in sessions)


@pytest.mark.asyncio
async def test_1080_not_silently_replaced_with_720(monkeypatch):
    engine = KickLiveEngine()
    monkeypatch.setattr(engine, '_streams', AsyncMock(return_value=([{'value':'720p','height':720,'fps':30,'bitrate':1,'url':'https://cdn.live-video.net/720.m3u8'}],{})))
    with pytest.raises(RecordingError, match='화질'):
        await engine.resolve_stream('alice','1080p')
    assert (await engine.resolve_stream('alice','best'))[0].endswith('720.m3u8')


def test_video_1080_selector_does_not_allow_lower_quality():
    task = VodDownloadTask(url=VOD, quality='1080p')
    opts = VodEngine()._build_ytdlp_options(task)
    assert opts['format'] == 'bestvideo*[height=1080]+bestaudio/best[height=1080]'


@pytest.mark.asyncio
async def test_vod_metadata_and_download_borrow_registered_cookie(monkeypatch, tmp_path):
    from app.engine import vod
    original = cookie_file(tmp_path)
    seen = []
    class YDL:
        def __init__(self, options):
            assert Path(options['cookiefile']).exists() and Path(options['cookiefile']) != original
            seen.append(options['cookiefile'])
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def extract_info(self, url, download=False):
            return {'id':'1','title':'Video','formats':[{'height':1080,'width':1920,'format_id':'1080','vcodec':'h264'}]}
    monkeypatch.setattr(vod,'platform_ydl',lambda url, opts: YDL(opts))
    engine = VodEngine()
    info = await engine.get_video_info(VOD)
    assert info['formats'][0]['height'] == 1080 and not Path(seen[0]).exists()
    async def download(task_id, task, borrowed):
        assert Path(borrowed).exists() and Path(borrowed) != original
        seen.append(borrowed)
    monkeypatch.setattr(engine, '_download_with_ytdlp', download)
    await engine._download_external('task', VodDownloadTask(url=VOD))
    assert not Path(seen[-1]).exists() and original.exists()


def test_platform_api_registration_cookies_and_persistence(monkeypatch, tmp_path):
    from app.api import platforms, vod
    import app.main
    from app.engine.conductor import Conductor
    from app.services.recorder import RecorderService
    conductor = Conductor()
    service = RecorderService(conductor)
    monkeypatch.setattr(app.main, 'get_recorder_service', lambda: service)
    monkeypatch.setattr(platforms, '_COOKIE_SAVE_PATH', tmp_path/'data/platform.txt')
    get_settings().kick_cookie_file = None
    app = FastAPI()
    app.include_router(platforms.router); app.include_router(vod.router)
    with TestClient(app) as client:
        result = client.post('/api/platforms/channels', json={'platform':'kick','channel_id':'https://kick.com/Alice','auto_record':False})
        assert result.status_code == 200
        assert conductor._channels['kick:alice'].platform == Platform.KICK
        assert Conductor()._channels['kick:alice'].auto_record is False
        assert client.post('/api/platforms/channels', json={'platform':'kick','channel_id':'https://kick.com/api'}).status_code == 400
        assert any(x['id'] == 'kick' for x in client.get('/api/vod/capabilities').json()['sources'])
        body = '# Netscape HTTP Cookie File\n.kick.com\tTRUE\t/\tTRUE\t0\tsession_token\tprivate-fixture\n'
        result = client.post('/api/platforms/kick/cookie', files={'file':('cookies.txt',body)})
        assert result.status_code == 200 and result.json()['valid']
        assert 'private-fixture' not in result.text
        assert client.get('/api/platforms/status').json()['kick']['authenticated']
        assert not client.delete('/api/platforms/kick/cookie').json()['configured']
        assert not (tmp_path/'data/kick_cookies.txt').exists()


def test_kick_http_failures_keep_platform_reason():
    for text, code in [('403 Client Error: Forbidden','kick_access'), ('HTTP Error 429','kick_rate_limit'), ('Requested format is not available','kick_quality')]:
        assert classify_recording_error(kick_access_error(RuntimeError(text))).code == code
