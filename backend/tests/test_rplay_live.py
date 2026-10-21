"""RPLAY live identity, viewer/UHD grants, Streamlink capture and preview."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.engine import rplay_live as rp
from app.engine.base import Platform, PlatformEngine
from app.engine.conductor import Conductor
from app.engine.preview_proxy import PreviewProxy
from app.engine.recording_errors import RecordingError
from tests.test_new_platforms import local_hls as local_hls

CID = '6a56030961df0d415aa5b5d5'
PAGE = f'https://rplay.live/live/{CID}'
MEDIA = f'https://livestream.rplay.live/live/{CID}/abr.m3u8'
SESSION = {'accessToken': 'FIXTURE-SESSION-PRIVATE', 'requestorOid': 'a' * 24, 'loginType': 'rplay'}


def metadata(**changes):
    return {'creatorOid': CID, 'creatorMetadata': {'_id': CID, 'nickname': 'RPLAY fixture'},
            'streamState': 'live', 'streamStartTime': '2026-10-16T10:31:26Z', 'title': 'Integration fixture',
            'accessible': True, 'useBytePlusStream': True, 'bytePlusPlaybackUrl': MEDIA, **changes}


def mock_api(monkeypatch, item=None, auth=200, uhd=200, status=200):
    calls = []
    original = httpx.AsyncClient
    def route(request):
        calls.append(request)
        if request.url.path.endswith('/play'):
            return httpx.Response(status, json=metadata() if item is None else item)
        return httpx.Response(uhd if request.url.params.get('resolution') == 'ud' else auth, json={})
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(route), **kw))
    return calls


def mock_streamlink(monkeypatch):
    from streamlink.stream.hls import HLSStream
    calls = []
    def playlist(session, url, **kwargs):
        calls.append((url, kwargs))
        return {f'{h}p': HLSStream(session, f'https://livestream.rplay.live/live/{CID}/{h}/index.m3u8') for h in (1080, 720, 480)}
    monkeypatch.setattr(HLSStream, 'parse_variant_playlist', playlist)
    return calls


@pytest.fixture(autouse=True)
def isolated_rplay_account(monkeypatch):
    monkeypatch.setattr(get_settings(), 'rplay_session_file', None)


@pytest.mark.parametrize('value', [CID, CID.upper(), PAGE, PAGE + '/?share=1#top', PAGE.replace('https://', 'http://www.')])
def test_live_url_roundtrip(value):
    assert rp.normalize_rplay_channel_id(value) == CID
    assert rp.RplayLiveEngine().get_stream_url(value) == PAGE


def test_handle_url_resolution(monkeypatch):
    rp._HANDLE_CACHE.clear()
    class MockResponse:
        def __init__(self, status_code, text):
            self.status_code = status_code
            self.text = text
    def mock_get(url, **kwargs):
        if '/c/hitsu' in url:
            return MockResponse(200, '<meta property="og:image" content="https://pb3.rplay.live/profilePhoto/68c13a59130df63bab93c23c-small?t=1">')
        if '/c/seldea' in url:
            return MockResponse(200, '<script type="application/ld+json">{"image":"https://pb3.rplay.live/profilePhoto/64d483add2c96306099ef734-small"}</script>')
        return MockResponse(404, 'Not Found')

    monkeypatch.setattr('httpx.Client.get', lambda self, url, **kwargs: mock_get(url, **kwargs))

    assert rp.normalize_rplay_channel_id('https://rplay.live/c/hitsu') == '68c13a59130df63bab93c23c'
    assert rp.normalize_rplay_channel_id('https://rplay.live/c/seldea?page=creator-home#main') == '64d483add2c96306099ef734'
    # Cached lookup works without client.get
    monkeypatch.setattr('httpx.Client.get', lambda self, url, **kwargs: MockResponse(500, 'Error'))
    assert rp.normalize_rplay_channel_id('https://rplay.live/c/hitsu') == '68c13a59130df63bab93c23c'

    with pytest.raises(ValueError, match='알플레이 크리에이터 또는 채널을 찾을 수 없습니다'):
        rp.normalize_rplay_channel_id('https://rplay.live/c/unknown_handle')


@pytest.mark.parametrize('value', [PAGE + '/extra', PAGE.replace('/live/', '/play/'), PAGE.replace('.live/', '.live.evil/'),
    PAGE.replace('rplay.live', 'u:p@rplay.live'), PAGE.replace('.live/', '.live:8443/'), CID[:-1], CID + '\nX', ''])
def test_bad_live_url(value):
    with pytest.raises(ValueError):
        rp.normalize_rplay_channel_id(value)


@pytest.mark.asyncio
async def test_denied_live_is_not_recordable_and_media_not_used(monkeypatch):
    calls = mock_api(monkeypatch, metadata(accessible=False))
    stream_calls = mock_streamlink(monkeypatch)
    engine = rp.RplayLiveEngine()
    status = await engine.check_live_status(CID)
    assert not status['is_live'] and status['channel_id'] == CID and status['channel_name'] == 'RPLAY fixture'
    with pytest.raises(RecordingError) as caught:
        await engine.get_qualities(CID)
    assert caught.value.code == 'rplay_authentication' and len(calls) == 1 and not stream_calls


@pytest.mark.asyncio
@pytest.mark.parametrize('change', [{'creatorOid': 'b' * 24}, {'creatorMetadata': {'_id': 'b' * 24}}, {'streamState': None}])
async def test_invalid_response_not_reported_as_offline(monkeypatch, change):
    mock_api(monkeypatch, metadata(**change))
    with pytest.raises(RecordingError):
        await rp.RplayLiveEngine().check_live_status(CID)


@pytest.mark.asyncio
async def test_offline_never_requests_playback_grants(monkeypatch):
    calls = mock_api(monkeypatch, metadata(streamState='offline'))
    engine = rp.RplayLiveEngine()
    assert not (await engine.check_live_status(CID))['is_live']
    assert await engine.get_qualities(CID) == [] and len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('status,retryable', [(401, False), (403, False), (404, False), (444, False), (999, False), (429, True), (503, True), (302, False)])
async def test_api_error_policy(monkeypatch, status, retryable):
    calls = mock_api(monkeypatch, status=status)
    with pytest.raises(RecordingError) as caught:
        await rp.RplayLiveEngine().check_live_status(CID)
    assert caught.value.retryable is retryable and len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('uhd,expected', [(200, [1080, 720, 480]), (403, [720, 480])])
async def test_uhd_permission_and_safe_media_headers(monkeypatch, uhd, expected):
    calls = mock_api(monkeypatch, uhd=uhd)
    stream_calls = mock_streamlink(monkeypatch)
    monkeypatch.setattr(rp, 'account_session', lambda: SESSION)
    engine = rp.RplayLiveEngine()
    qualities = await engine.get_qualities(CID)
    assert [q['height'] for q in qualities] == expected
    assert 'PRIVATE' not in json.dumps(qualities) and all('url' not in q for q in qualities)
    url, headers, cookies = await engine.resolve_stream(CID, f'{expected[0]}p')
    assert url.endswith(f'/{expected[0]}/index.m3u8') and not cookies
    assert 'Authorization' not in headers and 'Cookie' not in headers
    assert len(calls) == 3 and all(r.url.host == 'api.rplay.live' for r in calls)
    assert all(r.headers['authorization'] == SESSION['accessToken'] for r in calls)
    assert len(stream_calls) == 1 and 'token=FIXTURE-SESSION-PRIVATE' in stream_calls[0][0]
    assert 'Authorization' not in stream_calls[0][1]['headers']
    if uhd != 200:
        with pytest.raises(RecordingError, match='화질'):
            await engine.resolve_stream(CID, '1080p')
    assert all(r.method == 'GET' for r in calls)  # Never purchase or donate for UHD.


@pytest.mark.asyncio
async def test_no_manifest_before_bytdance_grant(monkeypatch):
    mock_api(monkeypatch, auth=403)
    stream_calls = mock_streamlink(monkeypatch)
    with pytest.raises(RecordingError):
        await rp.RplayLiveEngine().get_qualities(CID)
    assert not stream_calls


@pytest.mark.asyncio
async def test_empty_non_200_response_is_not_a_grant(monkeypatch):
    mock_api(monkeypatch, auth=204)
    stream_calls = mock_streamlink(monkeypatch)
    with pytest.raises(RecordingError):
        await rp.RplayLiveEngine().get_qualities(CID)
    assert not stream_calls


@pytest.mark.asyncio
async def test_viewer_token_query_is_redacted_in_http_logs(monkeypatch, caplog):
    mock_api(monkeypatch)
    caplog.set_level('INFO', logger='httpx')
    await rp.RplayLiveEngine()._api('/bytedance/auth', {'creatorId': CID, 'token': SESSION['accessToken']}, SESSION)
    assert 'PRIVATE' not in caplog.text


@pytest.mark.asyncio
async def test_media_server_authentication_error_is_safe_and_not_retried(monkeypatch):
    import requests
    from streamlink.stream.hls import HLSStream
    mock_api(monkeypatch)
    def denied(*args, **kwargs):
        response = requests.Response(); response.status_code = 403
        raise requests.HTTPError('403 https://livestream.rplay.live/a?token=PRIVATE', response=response)
    monkeypatch.setattr(HLSStream, 'parse_variant_playlist', denied)
    with pytest.raises(RecordingError) as caught:
        await rp.RplayLiveEngine().get_qualities(CID)
    assert caught.value.code == 'rplay_authentication' and not caught.value.retryable
    assert 'PRIVATE' not in str(caught.value)


def test_cdn_boundary_and_opaque_preview():
    proxy = PreviewProxy(); token = proxy.register('rplay:' + CID, 'rplay', MEDIA)
    body = proxy.rewrite(proxy.nodes[token], '#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="key?token=PRIVATE"\npart.ts?token=PRIVATE\n')
    assert 'PRIVATE' not in body and '/api/stream/preview-media/' in body
    for url in ['https://evil.example/a.m3u8', 'https://livestream.rplay.live.evil/a.m3u8', 'http://livestream.rplay.live/a', 'https://127.0.0.1/a', 'https://u:p@livestream.rplay.live/a', 'https://livestream.rplay.live:8443/a']:
        assert not rp.media_allowed(url) and not proxy.allowed(url, {''}, 'rplay')


@pytest.mark.asyncio
@pytest.mark.parametrize('uhd,expected', [(200, [1080, 720, 540]), (403, [720, 540])])
async def test_byteplus_missing_separators_real_streamlink_parser(monkeypatch, uhd, expected):
    import requests
    mock_api(monkeypatch, uhd=uhd)
    monkeypatch.setattr(rp, 'account_session', lambda: dict(SESSION))
    entries = []
    for height, width, tier in [(1080, 1920, 'ud'), (720, 1280, 'hd'), (540, 960, 'sd')]:
        entries.append(f'#EXT-X-STREAM-INF:BANDWIDTH=3200000,RESOLUTION={width}x{height}\n'
                       f'/live/{CID}_abr{tier}/index.m3u8?token=FIXTURE-SESSION-PRIVATE')
    body = '#EXTM3U\n#EXT-X-VERSION:3\n' + ''.join(entries)
    def send(adapter, request, **kwargs):
        response = requests.Response()
        response.status_code = 200
        response.url = request.url
        response.request = request
        response._content = body.encode()
        return response
    monkeypatch.setattr(requests.adapters.HTTPAdapter, 'send', send)
    engine = rp.RplayLiveEngine()
    assert [q['height'] for q in await engine.get_qualities(CID)] == expected
    from urllib.parse import parse_qs, urlsplit
    target, headers, _ = await engine.resolve_stream(CID, '720p')
    assert urlsplit(target).path == f'/live/{CID}_abrhd/index.m3u8'
    assert not urlsplit(target).fragment
    assert parse_qs(urlsplit(target).query)['token'] == [SESSION['accessToken']]
    assert 'Authorization' not in headers


@pytest.mark.asyncio
async def test_refresh_updates_viewer_query_and_caller_session(monkeypatch):
    from app.engine import rplay
    session = {**SESSION, 'refreshToken': 'r' * 32}
    fresh = {**session, 'accessToken': 'new-access-token-PRIVATE'}
    monkeypatch.setattr(rplay, 'refresh_session_token', lambda old: fresh)
    calls = []
    original = httpx.AsyncClient
    def route(request):
        calls.append(request)
        return httpx.Response(401 if len(calls) == 1 else 200, json={})
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(route), **kw))
    assert await rp.RplayLiveEngine()._api('/bytedance/auth',
        {'creatorId': CID, 'userId': SESSION['requestorOid'], 'token': SESSION['accessToken']}, session)
    assert len(calls) == 2
    assert calls[1].headers['authorization'] == fresh['accessToken']
    assert calls[1].url.params['token'] == fresh['accessToken']
    assert session['accessToken'] == fresh['accessToken']


def test_master_repair_does_not_change_other_servers_or_media():
    import requests
    body = b'#EXTM3U\npart.ts?value=#EXT-X-STREAM-INF:x'
    for url in ['https://evil.example/abr.m3u8', MEDIA.replace('abr.m3u8', 'index.m3u8')]:
        response = requests.Response()
        response.status_code = 200
        response.url = url
        response._content = body
        rp.normalize_rplay_master(response)
        assert response.content == body


def test_api_channel_registration_status_and_key(monkeypatch):
    import app.main
    from app.api import platforms, stream
    service = SimpleNamespace(add_platform_channel=Mock(return_value={'status': 'added'}))
    monkeypatch.setattr(app.main, 'get_recorder_service', lambda: service)
    app = FastAPI(); app.include_router(platforms.router)
    with TestClient(app) as client:
        result = client.post('/api/platforms/channels', json={'platform': 'rplay', 'channel_id': PAGE, 'recording_quality': '720p'})
        assert result.status_code == 200 and service.add_platform_channel.call_args.kwargs['channel_id'] == CID
        assert client.get('/api/platforms/status').json()['rplay'] == {'enabled': True, 'authenticated': False}
    assert stream._to_composite_key('rplay:' + CID) == 'rplay:' + CID
    assert isinstance(Conductor()._get_engine(Platform.RPLAY), rp.RplayLiveEngine)
    assert isinstance(rp.RplayLiveEngine(), PlatformEngine)


@pytest.mark.asyncio
async def test_real_streamlink_qualities_capture_finalizer_and_frame(local_hls, monkeypatch):
    from app.engine.pipeline import YtdlpLivePipeline
    from app.engine.media_inspection import probe_media
    from app.engine.recording_finalizer import RecordingFinalizer
    from app.engine.preview_frames import FramePreviewService
    from tests.test_recording_finalization import terminal
    base, directory = local_hls
    mock_api(monkeypatch, metadata(useBytePlusStream=False, playUrl=base + '/master.m3u8'))
    monkeypatch.setattr(rp, 'media_allowed', lambda u: isinstance(u, str) and u.startswith(base + '/'))
    from app.engine import rplay_stream
    monkeypatch.setattr(rplay_stream, 'media_allowed', rp.media_allowed)
    engine = rp.RplayLiveEngine()
    assert [q['height'] for q in await engine.get_qualities(CID)] == [1080, 720, 480]
    frame, width, height = await FramePreviewService().get_frame('rplay:' + CID, 'rplay', CID, engine)
    assert frame and (width, height) == (1920, 1080)
    pipeline = YtdlpLivePipeline(CID); manager = RecordingFinalizer()
    try:
        await pipeline.start_recording(stream_obj=PAGE, output_dir=str(directory / 'rplay'), quality='1080p', source_resolver=lambda q: engine.resolve_stream(CID, q))
        await asyncio.wait_for(asyncio.shield(pipeline._feeder_task), 15)
        await pipeline.stop_recording()
        job_id = manager.register_capture('rplay:' + CID, pipeline, SimpleNamespace(platform=Platform.RPLAY, channel_id=CID, channel_name='RPLAY'), {'output_format': 'mkv', 'keep_source_ts': True})
        await manager.capture_finished(job_id, pipeline); job = await terminal(manager, job_id)
        assert job['state'] == 'completed' and job['inspection_state'] == 'passed'
        media = probe_media(job['output_path'])
        assert media['streams'] == {'video', 'audio'} and media['duration'] > 1
        assert next(s for s in media['tracks'] if s['codec_type'] == 'video')['height'] == 1080
    finally:
        await pipeline.stop_recording(); await manager.close()
