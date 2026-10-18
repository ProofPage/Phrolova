"""RPLAY grants, session isolation and the real video download pipeline."""
import base64
import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from yt_dlp.utils import ExtractorError

from app.core.config import get_settings
from app.engine import rplay
from app.engine.platform_media import canonical_platform_video, media_platform, platform_ydl
from app.engine.rplay_extractor import RplayIE
from app.engine.vod_preparation import canonical_prepared_url
from tests.test_new_platforms import local_hls as local_hls

OID = '6a8edff1f1781bc93acb28cf'
URL = f'https://rplay.live/play/{OID}'
MEDIA = 'https://api.rplay.live/content/hlsstream?contentOid=' + OID
SESSION = {'accessToken': 'test-access-token-PRIVATE', 'requestorOid': 'a' * 24, 'loginType': 'rplay'}


def metadata(**changes):
    return {'_id': OID, 'title': 'RPLAY integration fixture', 'nickname': 'Test creator',
            'length': 3.0, 'canView': {'canView': True, 'url': MEDIA}, 'drm': False,
            'publishedAt': '2026-10-16T00:00:00Z', **changes}


def mock_api(monkeypatch, data=None, status=200, headers=None):
    calls = []
    original = httpx.Client
    def route(request):
        calls.append(request)
        return httpx.Response(status, json=metadata() if data is None else data, headers=headers)
    monkeypatch.setattr(httpx, 'Client', lambda **kw: original(transport=httpx.MockTransport(route), **kw))
    return calls


@pytest.fixture(autouse=True)
def no_real_session(monkeypatch):
    monkeypatch.setattr(get_settings(), 'rplay_session_file', None)


@pytest.mark.parametrize('value', [URL, URL + '/?share=1#top', URL.replace('https://', 'http://www.').upper()])
def test_canonical_video_identity(value):
    # URL scheme and hostname are case insensitive; route case is not.
    if '/PLAY/' in value:
        value = value.replace('/PLAY/', '/play/')
    assert canonical_platform_video(value) == URL
    assert canonical_prepared_url(value, 'rplay') == URL
    assert media_platform(value) == 'rplay'
    with platform_ydl(URL, {'quiet': True}) as ydl:
        assert isinstance(ydl._ies['Rplay'], RplayIE)


@pytest.mark.parametrize('value', [URL + '/extra', URL.replace('.live/', '.live.evil/'), URL.replace('rplay.live', 'u:p@rplay.live'),
    URL.replace('.live/', '.live:444/'), URL.replace('/play/', '/live/'), URL[:-1], 'file:///play/' + OID])
def test_reject_bad_video_links(value):
    with pytest.raises(ValueError):
        rplay.canonical_rplay_video_url(value)


@pytest.mark.parametrize('change', [{'_id': 'b' * 24}, {'canView': {'canView': False, 'url': MEDIA}},
    {'canView': {'canView': 'true', 'url': MEDIA}}, {'canView': None}, {'deleted': True}, {'drm': True},
    {'canView': {'canView': True, 'url': 'https://evil.example/video.mp4'}},
    {'canView': {'canView': True, 'url': 'https://api.rplay.live/drm_video.m3u8'}},
    {'canView': {'canView': False, 'url': 'https://api2.rplay.live/content/hlsstream'}},
    {'drm': True, 'canView': {'canView': True, 'url': 'https://api2.rplay.live/content/hlsstream'}},
    {'canView': {'canView': True, 'url': 'https://api2.rplay.live/drm_video.m3u8'}}])
def test_denied_grant_is_never_playable(monkeypatch, change):
    calls = mock_api(monkeypatch, metadata(**change))
    with pytest.raises(ExtractorError):
        rplay.video_metadata(URL)
    assert len(calls) == 1


@pytest.mark.parametrize('status', [401, 403, 404, 410, 444, 999, 500, 302])
def test_api_errors_no_redirect_or_credential_echo(monkeypatch, tmp_path, status):
    session = tmp_path / 'session.json'; session.write_text(json.dumps(SESSION))
    get_settings().rplay_session_file = str(session)
    calls = mock_api(monkeypatch, status=status, headers={'location': 'https://evil.example/'})
    with pytest.raises(ExtractorError) as caught:
        rplay.video_metadata(URL)
    assert len(calls) == 1 and calls[0].url.host == 'api.rplay.live'
    assert SESSION['accessToken'] not in str(caught.value)


@pytest.mark.parametrize('media', [MEDIA, MEDIA.replace('api.rplay.live', 'api2.rplay.live')])
def test_session_is_api_only_and_missing_grant_is_denied(monkeypatch, tmp_path, media):
    session = tmp_path / 'session.json'; session.write_text(json.dumps(SESSION))
    get_settings().rplay_session_file = str(session)
    data = metadata(canView={'canView': True, 'url': media})
    calls = mock_api(monkeypatch, data)
    ie = RplayIE()
    monkeypatch.setattr(ie, '_extract_m3u8_formats', lambda *a, **kw: [{'url': media, 'format_id': '720', 'height': 720}])
    info = ie._real_extract(URL)
    assert calls[0].headers['authorization'] == SESSION['accessToken']
    assert calls[0].url.params['requestorOid'] == SESSION['requestorOid']
    assert 'PRIVATE' not in json.dumps(info) and SESSION['requestorOid'] not in json.dumps(info)
    assert info['http_headers'] == {'Origin': rplay.ORIGIN, 'Referer': URL}
    data['canView'] = {'canView': False}
    with pytest.raises(ExtractorError, match='시청 권한'):
        rplay.video_metadata(URL)


@pytest.mark.parametrize('payload', [[], {}, {'accessToken': 'short', 'requestorOid': 'a' * 24},
    {**SESSION, 'accessToken': 'x' * 16 + '\r\nsecret'}, {**SESSION, 'requestorOid': '../../secret'},
    {**SESSION, 'loginType': 'rplay\n'}, {**SESSION, 'accessToken': 'x' * 17000}])
def test_invalid_session_not_imported(payload):
    with pytest.raises(ValueError):
        rplay.parse_session(json.dumps(payload).encode())


def test_expired_session_no_network(monkeypatch, tmp_path):
    jwt_payload = base64.urlsafe_b64encode(b'{"exp":1}').decode().rstrip('=')
    session = tmp_path / 'session.json'
    session.write_text(json.dumps({**SESSION, 'accessToken': f'header.{jwt_payload}.signature'}))
    get_settings().rplay_session_file = str(session)
    assert rplay.session_status() == {'configured': True, 'valid': False, 'expired': True}
    calls = mock_api(monkeypatch)
    with pytest.raises(ExtractorError, match='만료'):
        rplay.video_metadata(URL)
    assert not calls


@pytest.mark.parametrize('url', ['https://api.rplay.live.evil/video.mp4', 'http://pb3.rplay.live/video.mp4',
    'https://user@api.rplay.live/video.mp4', 'https://api.rplay.live:8443/video.mp4',
    'https://127.0.0.1/video.mp4', 'https://api.rplay.live\\@evil.example/video.mp4',
    'https://api2.rplay.live.evil/video.mp4', 'http://api2.rplay.live/video.mp4',
    'https://user@api2.rplay.live/video.mp4', 'https://api2.rplay.live:8443/video.mp4',
    'https://api2.rplay.live@evil.example/video.mp4', 'https://api2.rplay.live\\@evil.example/video.mp4',
    'https://api2.rplay.live/content/hlsstream\r\nAuthorization: secret'])
def test_media_boundary(url):
    assert not rplay.valid_media_url(url)


def test_video_retry_uses_refreshed_account_parameters(monkeypatch):
    monkeypatch.setattr(rplay, 'read_session', lambda **kw: {**SESSION, 'refreshToken': 'r' * 32})
    updated = {**SESSION, 'accessToken': 'new-access-token-PRIVATE', 'loginType': 'plax'}
    monkeypatch.setattr(rplay, 'refresh_session_token', lambda old: updated)
    calls = []
    original = httpx.Client
    def route(request):
        calls.append(request)
        return httpx.Response(401 if len(calls) == 1 else 200, json=metadata())
    monkeypatch.setattr(httpx, 'Client', lambda **kw: original(transport=httpx.MockTransport(route), **kw))
    assert rplay.video_metadata(URL)['_id'] == OID
    assert len(calls) == 2
    assert calls[1].headers['authorization'] == updated['accessToken']
    assert calls[1].url.params['loginType'] == updated['loginType']


def test_session_upload_status_delete_and_capabilities(monkeypatch, tmp_path):
    from app.api import platforms, vod
    from app.engine.base import Platform
    monkeypatch.setattr(platforms, '_COOKIE_SAVE_PATH', tmp_path / 'platform_cookies.txt')
    app = FastAPI(); app.include_router(platforms.router); app.include_router(vod.router)
    with TestClient(app) as client:
        assert not client.get('/api/platforms/rplay/session').json()['configured']
        valid_refresh = 'r' * 32
        result = client.post('/api/platforms/rplay/session', files={'file': ('session.json', json.dumps({**SESSION, 'refreshToken': valid_refresh}))})
        assert result.status_code == 200 and result.json()['valid']
        assert 'PRIVATE' not in result.text and valid_refresh in (tmp_path / 'rplay_session.json').read_text()
        saved = (tmp_path / 'rplay_session.json').read_bytes()
        assert client.post('/api/platforms/rplay/session', files={'file': ('bad.json', b'not json')}).status_code == 400
        assert (tmp_path / 'rplay_session.json').read_bytes() == saved
        sources = [s['id'] for s in client.get('/api/vod/capabilities').json()['sources']]
        assert len(sources) == 18 and 'rplay' in sources and 'pandalive' not in sources
        assert 'rplay' in [p.value for p in Platform]
        assert not client.delete('/api/platforms/rplay/session').json()['configured']
        assert not (tmp_path / 'rplay_session.json').exists()


def test_session_auto_refresh_on_expiration(monkeypatch, tmp_path):
    # Expired access token with a valid refresh token triggers /rplay/account/refresh-token
    jwt_expired = base64.urlsafe_b64encode(b'{"exp":1}').decode().rstrip('=')
    jwt_fresh = base64.urlsafe_b64encode(b'{"exp":9999999999}').decode().rstrip('=')
    fresh_access = f'header.{jwt_fresh}.signature'
    fresh_refresh = 'new_refresh_' + 'x' * 32

    session_path = tmp_path / 'rplay_session.json'
    initial_session = {
        'accessToken': f'header.{jwt_expired}.signature',
        'requestorOid': SESSION['requestorOid'],
        'loginType': 'rplay',
        'refreshToken': 'old_refresh_' + 'x' * 32,
    }
    session_path.write_text(json.dumps(initial_session), encoding='utf-8')
    get_settings().rplay_session_file = str(session_path)

    refresh_called = []

    def mock_post(self, url, **kwargs):
        if url == rplay.REFRESH_API:
            refresh_called.append(kwargs)
            assert kwargs['headers']['refresh-token'] == initial_session['refreshToken']
            assert kwargs['json']['requestorOid'] == SESSION['requestorOid']
            return httpx.Response(200, json={'accessToken': fresh_access, 'refreshToken': fresh_refresh},
                                  request=httpx.Request('POST', url))
        return httpx.Response(404, request=httpx.Request('POST', url))

    monkeypatch.setattr(httpx.Client, 'post', mock_post)

    status = rplay.session_status()
    assert status['configured'] and status['valid'] and not status['expired']
    assert len(refresh_called) == 1

    # Check that disk file was atomically persisted with new credentials
    reloaded = json.loads(session_path.read_text(encoding='utf-8'))
    assert reloaded['accessToken'] == fresh_access
    assert reloaded['refreshToken'] == fresh_refresh


@pytest.mark.asyncio
@pytest.mark.parametrize('height', [1080, 720])
async def test_real_hls_quality_download_inspection_restore(local_hls, monkeypatch, tmp_path, height):
    from app.engine import rplay_extractor
    from app.engine.vod import VodEngine, VodDownloadTask, VodDownloadState
    from app.engine.vod_preparation import quality_options
    base, _ = local_hls
    calls = mock_api(monkeypatch, metadata(canView={'canView': True, 'url': base + '/master.m3u8'}))
    # Replace only the HTTPS production boundary with an isolated local media fixture.
    allowed = lambda value: isinstance(value, str) and value.startswith(base + '/')
    monkeypatch.setattr(rplay, 'valid_media_url', allowed)
    monkeypatch.setattr(rplay_extractor, 'valid_media_url', allowed)
    get_settings().vod_format = 'mp4'
    engine = VodEngine()
    info = await engine.get_video_info(URL)
    assert [q['value'] for q in quality_options(info)] == ['1080p', '720p', '480p']
    task = VodDownloadTask(url=URL, output_dir=str(tmp_path / '영상 폴더'), quality=f'{height}p', prepared=True)
    engine._tasks[task.task_id] = task; Path(task.output_dir).mkdir()
    try:
        await engine._download_external(task.task_id, task)
        assert task.state == VodDownloadState.COMPLETED and task.inspection_state == 'passed'
        assert Path(task.output_path).stat().st_size > 0
        import shutil
        import subprocess
        probe = json.loads(subprocess.check_output([shutil.which('ffprobe'), '-v', 'error', '-show_streams', '-of', 'json', task.output_path]))
        assert next(s for s in probe['streams'] if s['codec_type'] == 'video')['height'] == height
        engine._save_history()
        restored = VodEngine()
        assert restored.get_task_status(task.task_id)['platform'] == 'rplay'
        await restored.shutdown()
        assert len(calls) >= 2
    finally:
        await engine.shutdown()
