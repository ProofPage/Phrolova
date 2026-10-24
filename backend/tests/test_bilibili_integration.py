import asyncio
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.engine.media_http_compat import install_media_http_compat

install_media_http_compat()

from app.core.config import get_settings
from app.core.logger import get_media_logger
from app.engine.base import Platform
from app.engine.conductor import Conductor
from app.engine.platform_auth import platform_cookie_jar
from app.engine.platform_media import media_platform
from app.engine.bilibili_support import resolve_bilibili_video_url
from app.engine.preview_proxy import PreviewProxy
from app.engine.vod import VodDownloadTask, VodEngine
from app.engine.vod_preparation import canonical_prepared_url, quality_options
from tests.test_new_platforms import local_hls


VIDEO = 'https://www.bilibili.com/video/BV1cSec6tEux/'


def test_api_registration_cookie_isolation_and_download_capabilities(monkeypatch, tmp_path):
    import app.main
    from app.api import platforms, stream, vod

    added = Mock(return_value={'status': 'added'})
    monkeypatch.setattr(app.main, 'get_recorder_service', lambda: SimpleNamespace(add_platform_channel=added))
    monkeypatch.setattr(platforms, '_COOKIE_SAVE_PATH', tmp_path/'data/platform.txt')
    app = FastAPI()
    app.include_router(platforms.router)
    app.include_router(vod.router)
    with TestClient(app) as client:
        response = client.post('/api/platforms/channels', json={
            'platform': 'bilibili', 'channel_id': 'https://live.bilibili.com/1726019661?hotRank=0',
            'recording_quality': 'qn_10000',
        })
        assert response.status_code == 200
        assert added.call_args.kwargs['channel_id'] == '1726019661'
        assert added.call_args.kwargs['recording_quality'] == 'qn_10000'
        assert 'bilibili' in {s['id'] for s in client.get('/api/vod/capabilities').json()['sources']}
        data = (b'# Netscape HTTP Cookie File\n'
                b'.bilibili.com\tTRUE\t/\tTRUE\t0\tSESSDATA\tfixture-secret\n'
                b'.evil.example\tTRUE\t/\tTRUE\t0\tSESSDATA\tother-secret\n')
        response = client.post('/api/platforms/bilibili/cookie', files={'file': ('cookies.txt', data)})
        assert response.status_code == 200 and response.json()['valid']
        assert 'fixture-secret' not in response.text
        session = requests.Session()
        session.cookies.update(platform_cookie_jar('bilibili'))
        assert 'fixture-secret' in session.prepare_request(requests.Request('GET', 'https://api.bilibili.com/')).headers['Cookie']
        for host in ('https://b23.tv/', 'https://cdn.bilivideo.com/', 'https://evil.example/'):
            assert 'Cookie' not in session.prepare_request(requests.Request('GET', host)).headers
        session.close()
        assert client.get('/api/platforms/status').json()['bilibili']['enabled']
        assert client.delete('/api/platforms/bilibili/cookie').status_code == 200
    assert stream._to_composite_key('bilibili:1726019661') == 'bilibili:1726019661'
    from app.engine.bilibili import BilibiliLiveEngine
    assert isinstance(Conductor()._get_engine(Platform.BILIBILI), BilibiliLiveEngine)
    assert get_media_logger(VIDEO).name.endswith('bilibili')


@pytest.mark.parametrize('source', ['auto', 'bilibili'])
def test_prepared_bilibili_part_and_tracking_normalization(source):
    url = VIDEO+'?p=2&spm_id_from=tracking'
    assert canonical_prepared_url(url, source) == VIDEO+'?p=2'
    assert canonical_prepared_url(VIDEO+'?p=1', source) == VIDEO
    assert media_platform('https://live.bilibili.com/1726019661') == 'bilibili'
    with pytest.raises(ValueError):
        canonical_prepared_url('https://live.bilibili.com/1726019661', source)


@pytest.mark.asyncio
@pytest.mark.parametrize('target', [VIDEO+'?p=2&spm_id_from=tracking', 'http://127.0.0.1/private',
                                         'https://www.bilibili.com.evil.example/video/BV1cSec6tEux/',
                                         'https://live.bilibili.com/1726019661'])
async def test_shortlink_follows_only_valid_bilibili_video_redirect(monkeypatch, target):
    original = httpx.AsyncClient
    calls = []
    def route(request):
        calls.append(str(request.url))
        assert 'cookie' not in request.headers
        return httpx.Response(302, headers={'location': target})
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(route), **kw))
    if target.startswith(VIDEO):
        assert await resolve_bilibili_video_url('https://b23.tv/AbC123') == VIDEO+'?p=2'
    else:
        with pytest.raises(ValueError):
            await resolve_bilibili_video_url('https://b23.tv/AbC123')
    assert calls == ['https://b23.tv/AbC123']


def test_native_quality_tier_keeps_real_cropped_dimensions_and_audio():
    info = {'url': VIDEO, 'formats': [
        {'format_id': '30080', 'height': 886, 'width': 1920, 'vcodec': 'avc1', 'format': '1080P 高清'},
        {'format_id': '30077', 'height': 886, 'width': 1920, 'vcodec': 'hevc', 'format': '1080P 高清'},
        {'format_id': '30280', 'vcodec': 'none', 'acodec': 'mp4a'},
    ]}
    options = quality_options(info)
    assert options == [{'value': '886p', 'label': '1080p · 1920×886', 'height': 886,
                        'width': 1920, 'fps': None, 'tier_height': 1080}]
    engine = VodEngine()
    task = VodDownloadTask(url=VIDEO, prepared=True, quality='886p')
    opts = engine._build_ytdlp_options(task)
    assert '[height=886]+bestaudio' in opts['format']
    for quality in ('best', 'worst'):
        task.quality = quality
        audio = '+bestaudio' if quality == 'best' else '+worstaudio'
        assert audio in engine._build_ytdlp_options(task)['format']
    assert opts['noplaylist'] and opts['http_headers']['Referer'] == VIDEO


@pytest.mark.asyncio
async def test_cropped_1080_tier_does_not_report_quality_fallback(monkeypatch):
    engine = VodEngine()
    task = VodDownloadTask(url=VIDEO, prepared=True, quality='1080p')
    engine._tasks[task.task_id] = task
    monkeypatch.setattr(engine, 'get_video_info', AsyncMock(return_value={
        'url': VIDEO, 'formats': [{'format_id': '30080', 'height': 886, 'width': 1920,
                                  'vcodec': 'avc1', 'format': '1080P 高清'}],
    }))
    try:
        await engine._prepare_metadata(task)
        assert task.phase == 'ready' and task.quality == '886p'
        assert not task.metadata.get('quality_fallback')
    finally:
        await engine.shutdown()


def test_bilibili_preview_cdn_scope_and_signed_url_rewrite():
    proxy = PreviewProxy()
    origin = 'https://a.bilivideo.com/live/index.m3u8?token=secret'
    token = proxy.register('bilibili:1726019661', 'bilibili', origin)
    body = proxy.rewrite(proxy.nodes[token], '#EXTM3U\nhttps://b.bilivideo.cn/live/1.ts?token=secret\n')
    assert 'secret' not in body and '/api/stream/preview-media/' in body
    assert not proxy.allowed('https://b.bilivideo.cn/1.ts', {'cdn.example'}, 'twitch')


@pytest.mark.asyncio
@pytest.mark.parametrize('prepared,quality', [(False, 'best'), (True, '720p')])
async def test_actual_split_video_and_audio_download_and_inspection(local_hls, monkeypatch, prepared, quality):
    import yt_dlp
    from yt_dlp.extractor.common import InfoExtractor
    from app.engine.media_inspection import probe_media

    base, directory = local_hls
    for filename, mapping in [('video.mp4', ['-an']), ('audio.m4a', ['-vn'])]:
        subprocess.run([shutil.which('ffmpeg'), '-v', 'error', '-i', str(directory/'720/index.m3u8'),
                        *mapping, '-c', 'copy', str(directory/filename)], check=True)
    class BilibiliFixtureIE(InfoExtractor):
        _VALID_URL = r'https://www\.bilibili\.com/video/(?P<id>BV[A-Za-z0-9]{10})/'
        def _real_extract(self, url):
            return {'id': self._match_id(url), 'title': 'Bilibili split track fixture', 'duration': 3,
                    'uploader': 'Fixture', 'formats': [
                        {'format_id': '30064', 'url': base+'/video.mp4', 'ext': 'mp4', 'height': 720,
                         'width': 1280, 'vcodec': 'avc1', 'acodec': 'none', 'format': '720P 准高清'},
                        {'format_id': '30280', 'url': base+'/audio.m4a', 'ext': 'm4a',
                         'vcodec': 'none', 'acodec': 'mp4a'},
                    ]}
    def factory(url, opts):
        ydl = yt_dlp.YoutubeDL(opts, auto_init=False)
        ydl.add_info_extractor(BilibiliFixtureIE())
        return ydl
    monkeypatch.setattr('app.engine.vod.platform_ydl', factory)
    get_settings().bilibili_cookie_file = None
    output = directory/'download'
    output.mkdir()
    engine = VodEngine()
    task = VodDownloadTask(url=VIDEO+'?p=2', prepared=prepared, quality=quality, output_dir=str(output))
    engine._tasks[task.task_id] = task
    try:
        info = await engine.get_video_info(task.url)
        assert info['url'].endswith('?p=2') and len(info['formats']) == 2
        await engine._download_external(task.task_id, task)
        assert task.state.value == 'completed' and task.inspection_state == 'passed'
        assert probe_media(task.output_path)['streams'] == {'video', 'audio'}
        assert engine.get_task_status(task.task_id)['platform'] == 'bilibili'
    finally:
        await engine.shutdown()
