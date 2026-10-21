from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.logger import get_media_logger
from app.engine.base import Platform, PlatformEngine
from app.engine.conductor import Conductor
from app.engine.platform_auth import get_platform_cookies, platform_cookie_file, platform_cookie_status
from app.engine.platform_media import canonical_platform_video, media_platform
from app.engine.recording_errors import RecordingError
from app.engine.twitch import (TwitchLiveEngine, canonical_twitch_video_url,
    normalize_twitch_channel_id, twitch_access_error, twitch_api_headers)
from app.engine.vod import VodDownloadTask, VodEngine, NonRetryableDownloadError
from app.engine.vod_preparation import canonical_prepared_url
from tests.test_new_platforms import local_hls

VOD = 'https://www.twitch.tv/videos/123456789'
CLIP = 'https://clips.twitch.tv/FaintLightGullWholeWheat'


@pytest.mark.parametrize('value', ['Alice', 'alice_1', 'https://twitch.tv/Alice', 'https://m.twitch.tv/alice/?ref=share'])
def test_channel_inputs(value):
    assert normalize_twitch_channel_id(value) == ('alice_1' if value == 'alice_1' else 'alice')


@pytest.mark.parametrize('value', ['https://twitch.tv.evil/alice', 'https://u:p@twitch.tv/alice',
    'https://twitch.tv:444/alice', VOD, CLIP, 'directory', '@alice', 'https://twitch.tv/alice/videos', 'a' * 26])
def test_invalid_channels(value):
    with pytest.raises(ValueError): normalize_twitch_channel_id(value)


@pytest.mark.parametrize('value,expected', [(VOD + '?t=1m#x', VOD),
    ('https://m.twitch.tv/alice/v/123456789', VOD),
    ('https://player.twitch.tv/?video=v123456789&parent=example.com', VOD),
    ('https://www.twitch.tv/alice/clip/FaintLightGullWholeWheat?ref=share', CLIP),
    ('https://clips.twitch.tv/embed?clip=FaintLightGullWholeWheat&parent=example.com', CLIP)])
def test_video_normalization(value, expected):
    assert canonical_twitch_video_url(value) == expected
    assert canonical_platform_video(value) == expected
    assert canonical_prepared_url(value, 'twitch') == expected
    assert canonical_prepared_url(value, 'auto') == expected
    assert media_platform(value) == 'twitch'
    assert get_media_logger(value).name == 'phrolova.twitch'


@pytest.mark.parametrize('value', ['https://twitch.tv/alice', 'https://twitch.tv/videos/nope',
    'https://clips.twitch.tv/embed?clip=a&clip=b', 'https://twitch.tv.evil/videos/1',
    'https://clips.twitch.tv/a/b', 'https://player.twitch.tv/?channel=alice'])
def test_invalid_video_inputs(value):
    with pytest.raises(ValueError): canonical_twitch_video_url(value)


def cookies(tmp_path):
    path = tmp_path / 'twitch.txt'
    path.write_text('# Netscape HTTP Cookie File\n.twitch.tv\tTRUE\t/\tTRUE\t0\tauth-token\tfixture-token\n'
        '.evil.example\tTRUE\t/\tTRUE\t0\tauth-token\twrong\n')
    get_settings().twitch_cookie_file = str(path)
    return path


def test_cookies_are_scoped_and_temporary(tmp_path):
    source = cookies(tmp_path)
    assert twitch_api_headers() == {'Authorization': 'OAuth fixture-token'}
    assert platform_cookie_status('twitch')['valid']
    assert get_platform_cookies('twitch', 'https://video-edge.ttvnw.net/a') == {}
    with platform_cookie_file('twitch') as copy:
        assert Path(copy).exists() and Path(copy) != source
        assert 'wrong' not in Path(copy).read_text()
    assert not Path(copy).exists() and source.exists()


def mock_http(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *a, **kw: original(*a, **kw, transport=httpx.MockTransport(handler)))


@pytest.mark.asyncio
@pytest.mark.parametrize('live', [None, {'id':'live1','createdAt':'2026-10-14T12:00:00Z','viewersCount':12,'game':{'name':'Games'}}])
async def test_metadata_live_offline_and_cache(monkeypatch, tmp_path, live):
    cookies(tmp_path)
    calls = []
    def respond(request):
        calls.append(request)
        assert request.url.host == 'gql.twitch.tv'
        assert request.headers['Authorization'] == 'OAuth fixture-token'
        return httpx.Response(200, json={'data':{'user':{'id':'1','displayName':'Alice','lastBroadcast':{'title':'Broadcast'},'stream':live}}})
    mock_http(monkeypatch, respond)
    engine = TwitchLiveEngine()
    result = await engine.check_live_status('Alice')
    assert result['is_live'] == bool(live)
    assert result['viewer_count'] == (12 if live else 0)
    assert result['channel_name'] == 'Alice'
    await engine.check_live_status('alice')
    assert len(calls) == 1 and isinstance(engine, PlatformEngine)


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [{'errors':[{'message':'denied'}]}, {'data':{}}, {'data':{'user':{'id':'1'}}}, {'data':{'user':None}}])
async def test_bad_metadata_never_becomes_offline(monkeypatch, payload):
    mock_http(monkeypatch, lambda _: httpx.Response(200, json=payload))
    with pytest.raises(RuntimeError): await TwitchLiveEngine().check_live_status('alice')


@pytest.mark.asyncio
@pytest.mark.parametrize('code,expected', [(403,'twitch_access'), (404,'twitch_not_found'), (429,'twitch_rate_limit')])
async def test_http_errors(monkeypatch, code, expected):
    mock_http(monkeypatch, lambda _: httpx.Response(code))
    with pytest.raises(RecordingError) as caught: await TwitchLiveEngine().check_live_status('alice')
    assert caught.value.code == expected


@pytest.mark.asyncio
async def test_streamlink_api_auth_quality_and_close(monkeypatch, tmp_path):
    import streamlink
    cookies(tmp_path)
    sessions = []
    class Session:
        def __init__(self):
            self.http = requests.Session()
            self.http.close = Mock()
            self.options = {}
            sessions.append(self)
        def set_option(self, key, value): self.options[key] = value
        def streams(self, url, options):
            assert url == 'https://www.twitch.tv/alice'
            assert dict(options.get('api-header')) == twitch_api_headers()
            assert options.get('supported-codecs') == ['h264', 'h265', 'av1']
            cdn = self.http.prepare_request(requests.Request('GET','https://cdn.ttvnw.net/a'))
            assert 'Authorization' not in cdn.headers and 'Cookie' not in cdn.headers
            def stream(h): return SimpleNamespace(to_url=lambda: f'https://cdn.ttvnw.net/{h}.m3u8')
            return {'1080p60':stream(1080),'720p30':stream(720),'best':stream(1080),'audio_only':stream(0)}
    monkeypatch.setattr(streamlink, 'Streamlink', Session)
    engine = TwitchLiveEngine()
    assert [q['value'] for q in await engine.get_qualities('alice')] == ['1080p60','720p30']
    for quality, height in [('best',1080),('worst',720),('1080p',1080),('1080p30',720)]:
        url, headers, cookie = await engine.resolve_stream('alice', quality)
        assert url.endswith(f'/{height}.m3u8') and cookie is None
        assert 'Authorization' not in headers
    assert all(s.options['no-plugin-cache'] and not s.options['webbrowser'] and s.http.close.called for s in sessions)


@pytest.mark.asyncio
async def test_stream_failure_closes_and_stays_visible(monkeypatch):
    import streamlink
    session = SimpleNamespace(set_option=Mock(), http=requests.Session(), streams=Mock(side_effect=RuntimeError('client-integrity token unavailable')))
    session.http.close = Mock()
    monkeypatch.setattr(streamlink, 'Streamlink', lambda: session)
    with pytest.raises(RecordingError) as caught: await TwitchLiveEngine().get_qualities('alice')
    assert caught.value.code == 'twitch_integrity'
    session.http.close.assert_called_once()


@pytest.mark.asyncio
async def test_no_streams_while_live_is_not_offline(monkeypatch):
    import streamlink
    session = SimpleNamespace(set_option=Mock(), http=requests.Session(), streams=Mock(return_value={}))
    monkeypatch.setattr(streamlink, 'Streamlink', lambda: session)
    engine = TwitchLiveEngine()
    monkeypatch.setattr(engine, 'check_live_status', AsyncMock(return_value={'is_live':True}))
    with pytest.raises(RecordingError) as caught: await engine.get_qualities('alice')
    assert caught.value.code == 'twitch_stream_unavailable'


@pytest.mark.asyncio
async def test_empty_streams_refresh_cached_live_before_confirming_end(monkeypatch):
    import streamlink
    import time
    session = SimpleNamespace(set_option=Mock(), http=requests.Session(), streams=Mock(return_value={}))
    monkeypatch.setattr(streamlink, 'Streamlink', lambda: session)
    calls = []
    def offline(request):
        calls.append(request)
        return httpx.Response(200, json={'data': {'user': {
            'id': '1', 'displayName': 'Alice', 'stream': None}}})
    mock_http(monkeypatch, offline)
    engine = TwitchLiveEngine()
    engine._cache['alice'] = (time.monotonic(), {'is_live': True})
    with pytest.raises(RecordingError) as caught:
        await engine.resolve_stream('Alice')
    assert caught.value.code == 'broadcast_ended' and not caught.value.retryable
    assert len(calls) == 1
    assert engine._cache['alice'][1]['is_live'] is False


@pytest.mark.asyncio
@pytest.mark.parametrize('error', [
    RuntimeError('status response unavailable'),
    RecordingError('twitch_access', 'access denied'),
])
async def test_failed_status_refresh_is_never_treated_as_broadcast_end(monkeypatch, error):
    import streamlink
    session = SimpleNamespace(set_option=Mock(), http=requests.Session(), streams=Mock(return_value={}))
    monkeypatch.setattr(streamlink, 'Streamlink', lambda: session)
    engine = TwitchLiveEngine()
    monkeypatch.setattr(engine, 'check_live_status', AsyncMock(side_effect=error))
    with pytest.raises(type(error)) as caught:
        await engine.resolve_stream('alice')
    assert caught.value is error


def test_conductor_and_public_api_support_twitch(monkeypatch, tmp_path):
    import app.main
    from app.api import platforms, vod
    conductor = Conductor()
    assert isinstance(conductor._get_engine(Platform.TWITCH), TwitchLiveEngine)
    added = Mock(return_value={'status':'added'})
    monkeypatch.setattr(app.main, 'get_recorder_service', lambda: SimpleNamespace(add_platform_channel=added))
    monkeypatch.setattr(platforms, '_COOKIE_SAVE_PATH', tmp_path / 'data/platform.txt')
    app = FastAPI(); app.include_router(platforms.router); app.include_router(vod.router)
    with TestClient(app) as client:
        response = client.post('/api/platforms/channels', json={'platform':'twitch','channel_id':'https://twitch.tv/Alice','auto_record':False})
        assert response.status_code == 200 and added.call_args.kwargs['channel_id'] == 'alice'
        assert any(s['id'] == 'twitch' for s in client.get('/api/vod/capabilities').json()['sources'])
        response = client.post('/api/platforms/twitch/cookie', files={'file':('twitch.txt', b'# Netscape HTTP Cookie File\n.twitch.tv\tTRUE\t/\tTRUE\t0\tauth-token\tfixture-token\n')})
        assert response.status_code == 200 and response.json()['valid']
        assert 'fixture-token' not in response.text
        assert client.get('/api/platforms/status').json()['twitch']['authenticated']
        assert client.delete('/api/platforms/twitch/cookie').status_code == 200


@pytest.mark.asyncio
async def test_download_uses_registered_twitch_cookie_and_nonretryable_denial(tmp_path, monkeypatch):
    cookies(tmp_path)
    engine = VodEngine()
    async def denied(task_id, task, cookie_file):
        assert 'fixture-token' in Path(cookie_file).read_text()
        raise RuntimeError('HTTP Error 403: Forbidden')
    monkeypatch.setattr(engine, '_download_with_ytdlp', denied)
    with pytest.raises(NonRetryableDownloadError, match='Twitch'):
        await engine._download_external('id', VodDownloadTask(url=VOD))
    assert twitch_access_error(RuntimeError('client-integrity')).code == 'twitch_integrity'


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['vod', 'clip'])
async def test_actual_extractor_download_and_inspection_with_local_media(local_hls, monkeypatch, kind):
    import shutil
    import subprocess
    from yt_dlp.extractor.twitch import TwitchVodIE, TwitchClipsIE
    from app.engine.media_inspection import probe_media
    base, directory = local_hls
    get_settings().twitch_cookie_file = None
    get_settings().vod_format = 'mp4'
    if kind == 'vod':
        monkeypatch.setattr(TwitchVodIE, '_download_info', lambda *a, **kw: {
            'id':'123456789','title':'Fixture VOD','lengthSeconds':3,
            'owner':{'displayName':'Fixture','login':'fixture'}})
        monkeypatch.setattr(TwitchVodIE, '_download_access_token', lambda *a, **kw: {'value':'fixture','signature':'fixture'})
        monkeypatch.setattr(TwitchVodIE, '_extract_twitch_m3u8_formats', lambda self, *a, **kw:
            self._extract_m3u8_formats(base + '/master.m3u8', '123456789', 'mp4', m3u8_id='hls'))
    else:
        subprocess.run([shutil.which('ffmpeg'), '-v','error','-i', str(directory/'720/index.m3u8'),
            '-c','copy',str(directory/'clip.mp4')], check=True)
        monkeypatch.setattr(TwitchClipsIE, '_download_gql', lambda *a, **kw: [{'data':{'clip':{
            'id':'123','title':'Fixture Clip','durationSeconds':3,
            'playbackAccessToken':{'signature':'fixture','value':'fixture'},
            'assets':[{'videoQualities':[{'quality':'720','frameRate':5,'sourceURL':base+'/clip.mp4'}]}],
            'broadcaster':{'displayName':'Fixture'},'curator':{'displayName':'Fixture'},
        }}}])
    engine = VodEngine()
    url = VOD if kind == 'vod' else CLIP
    info = await engine.get_video_info(url)
    assert info['duration'] == 3 and info['formats']
    task = VodDownloadTask(url=url, quality='720p', prepared=True, output_dir=str(directory/'download'))
    Path(task.output_dir).mkdir()
    engine._tasks[task.task_id] = task
    await engine._download_external(task.task_id, task)
    assert task.state.value == 'completed' and task.inspection_state == 'passed'
    assert probe_media(task.output_path)['streams'] == {'video','audio'}
    assert engine.get_task_status(task.task_id)['platform'] == 'twitch'
    await engine.shutdown()


def test_pipeline_uses_twitch_hls_reader(local_hls):
    from app.engine.pipeline import YtdlpLivePipeline
    from streamlink.plugins.twitch import TwitchHLSStream
    base, _ = local_hls
    session, stream = YtdlpLivePipeline._create_streamlink_stream(base+'/720/index.m3u8', {}, None,
        0, False, '720p', source_page_url='https://www.twitch.tv/fixture')
    try:
        assert isinstance(stream, TwitchHLSStream)
    finally:
        session.http.close()


def test_twitch_auth_cookie_is_redacted_in_logs():
    from app.core.logger import _redact_log_secrets
    assert 'fixture-secret' not in _redact_log_secrets('auth-token=fixture-secret; other=value')


@pytest.mark.asyncio
async def test_automatic_recording_resolves_with_streamlink_engine(monkeypatch):
    from app.engine.pipeline import YtdlpLivePipeline, RecordingState
    conductor = Conductor()
    conductor.add_channel('alice', platform=Platform.TWITCH, recording_quality='720p')
    conductor._running = True
    engine = conductor._get_engine(Platform.TWITCH)
    resolve = AsyncMock(return_value=('https://cdn.ttvnw.net/live.m3u8', {}, None))
    monkeypatch.setattr(engine, 'resolve_stream', resolve)
    async def start(pipeline, **kwargs):
        assert kwargs['stream_obj'] == 'https://www.twitch.tv/alice'
        assert kwargs['cookie_str'] is None
        assert await kwargs['source_resolver'](kwargs['quality']) == resolve.return_value
        pipeline._state = RecordingState.RECORDING
    monkeypatch.setattr(YtdlpLivePipeline, 'start_recording', start)
    await conductor._start_recording('twitch:alice', is_retry=True, automatic=True)
    resolve.assert_awaited_once_with('alice', '720p')
    assert conductor._channels['twitch:alice'].pipeline.state == RecordingState.RECORDING
