"""CDN isolation, requests, persistence and non-destructive media checks."""
import asyncio
import io
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import yt_dlp
from yt_dlp.networking import Request, Response

from app.core.config import Settings, get_settings
from app.engine.chzzk_cdn import AKAMAI_HOST, DEFAULT_HOST, ChzzkCdnYoutubeDL, akamai_url
from app.engine.vod import VodEngine, VodDownloadTask, VodDownloadState

URL = 'https://chzzk.naver.com/video/123'


def test_default_settings_and_api_schema():
    from app.api.vod import VodDownloadRequest, VodRetryRequest
    assert Settings(_env_file=None).chzzk_vod_cdn == 'default'
    assert VodDownloadRequest(url=URL).cdn == VodRetryRequest().cdn == 'default'


@pytest.mark.parametrize('url', [
    'https://example.test/segment.ts', f'https://{DEFAULT_HOST}.evil.test/a.ts',
    f'https://user:secret@{DEFAULT_HOST}/a.ts', f'https://{DEFAULT_HOST}:9999/a.ts',
    f'https://{DEFAULT_HOST}/a.ts?Signature=host-bound', f'https://{DEFAULT_HOST}/a.ts?X-Amz-Signature=a',
    '//'+DEFAULT_HOST+'/a.ts', 'https://[broken/', 'file:///segment.ts',
])
def test_unknown_or_unsafe_urls_are_not_rewritten(url):
    assert akamai_url(url) == url


def test_path_query_and_encoding_preserved():
    url = f'https://{DEFAULT_HOST}/vod/a%2Fb/%EC%98%81.ts?token=a%2Fb%3D&token=x+z#part'
    assert akamai_url(url) == url.replace(DEFAULT_HOST, AKAMAI_HOST)


@pytest.mark.parametrize('cdn,host', [('default', DEFAULT_HOST), ('akamai', AKAMAI_HOST)])
def test_request_routing_preserves_range_and_scopes_credentials(monkeypatch, cdn, host):
    seen = []
    def send(self, request):
        seen.append(request)
        return Response(io.BytesIO(b'ok'), request.url, {})
    monkeypatch.setattr(yt_dlp.YoutubeDL, 'urlopen', send)
    original = Request(f'https://{DEFAULT_HOST}/a.ts?token=x',
                       headers={'Range':'bytes=0-99', 'Referer':URL, 'Cookie':'secret',
                                'Authorization':'secret', 'Host':DEFAULT_HOST, 'User-Agent':'test'})
    with ChzzkCdnYoutubeDL({'quiet':True}, cdn=cdn) as ydl:
        with ydl.urlopen(original) as response:
            assert response.read() == b'ok'
        assert ydl.cdn_applied == (cdn == 'akamai')
    request = seen[0]
    assert request.url == f'https://{host}/a.ts?token=x'
    assert request.headers['Range'] == 'bytes=0-99'
    assert request.headers['Referer'] == URL
    assert request.headers['User-Agent'] == 'test'
    if cdn == 'akamai':
        assert 'Cookie' not in request.headers and 'Authorization' not in request.headers and 'Host' not in request.headers
    assert original.headers['Cookie'] == 'secret'
    assert original.url.startswith(f'https://{DEFAULT_HOST}/')


@pytest.mark.asyncio
async def test_jobs_snapshot_cdn_and_retry_uses_new_files(tmp_path, monkeypatch):
    engine = VodEngine()
    monkeypatch.setattr(engine, '_run_download', AsyncMock())
    get_settings().chzzk_vod_cdn = 'akamai'
    default_id = await engine.download(URL, str(tmp_path))
    selected_id = await engine.download(URL, str(tmp_path), cdn='akamai')
    await asyncio.gather(*(t.download_task for t in engine._tasks.values()))
    assert engine._tasks[default_id].cdn == 'default'
    assert engine._tasks[selected_id].cdn == 'akamai'
    get_settings().chzzk_vod_cdn = 'default'
    assert engine._tasks[selected_id].cdn == 'akamai'
    old = engine._tasks[default_id]
    old.state = VodDownloadState.COMPLETED
    old.resolved_filename = str(tmp_path/'old.mp4')
    Path(old.resolved_filename).write_bytes(b'original')
    new_id = await engine.retry_download(default_id, cdn='akamai')
    await engine._tasks[new_id].download_task
    assert new_id != default_id
    assert engine._tasks[new_id].resolved_filename is None
    assert engine._tasks[new_id].expected_part_file is None
    assert Path(old.resolved_filename).read_bytes() == b'original'
    engine._save_history()
    loaded = VodEngine()
    assert loaded._tasks[new_id].cdn == 'akamai'


def test_settings_api_persists_and_rejects_bad_values(api_client, tmp_path):
    import app.core.utils as utils
    response = api_client.put('/api/settings/vod', json={'chzzk_vod_cdn':'akamai'})
    assert response.status_code == 200
    assert api_client.get('/api/settings').json()['chzzk_vod_cdn'] == 'akamai'
    assert Settings(_env_file=utils._get_env_path()).chzzk_vod_cdn == 'akamai'
    assert api_client.put('/api/settings/vod', json={'chzzk_vod_cdn':'auto'}).status_code == 422
    assert api_client.post('/api/vod/download', json={'url':URL,'cdn':'auto'}).status_code == 422


def test_settings_failure_is_atomic(api_client, monkeypatch):
    from app.api.settings import media
    old = get_settings().model_dump()
    def denied(*a, **kw): raise PermissionError('read-only')
    monkeypatch.setattr(media, '_update_env_file', denied)
    response = api_client.put('/api/settings/vod', json={'chzzk_vod_cdn':'akamai','vod_max_speed':13})
    assert response.status_code == 500
    assert get_settings().model_dump() == old


@pytest.mark.asyncio
@pytest.mark.parametrize('live_status', ['is_live', 'post_live', 'is_upcoming'])
async def test_live_duration_is_not_compared(tmp_path, monkeypatch, live_status):
    engine = VodEngine(); task = VodDownloadTask(url=URL)
    monkeypatch.setattr(engine, '_probe_media_info', lambda _: {'duration':1,'format_name':'mp4','streams':{'video','audio'}})
    await engine._inspect_chzzk_download(task, {'duration':600,'live_status':live_status}, 'unused')
    assert task.warning_message is None


@pytest.mark.asyncio
async def test_duration_and_missing_track_warn_without_deleting_file(tmp_path, monkeypatch):
    engine = VodEngine(); task = VodDownloadTask(url=URL)
    path = tmp_path/'video.mp4'; path.write_bytes(b'keep original bytes')
    monkeypatch.setattr(engine, '_probe_media_info', lambda _: {'duration':30,'format_name':'mp4','streams':{'video'}})
    await engine._inspect_chzzk_download(task, {'duration':600,'formats':[{'vcodec':'h264','acodec':'aac'}]}, str(path))
    assert 'Akamai CDN' in task.warning_message and '음성' in task.warning_message
    assert path.read_bytes() == b'keep original bytes'
    assert task.media_duration == 30


@pytest.mark.asyncio
async def test_missing_probe_warns_without_failing(monkeypatch):
    engine = VodEngine(); task = VodDownloadTask(url=URL)
    def missing(_): raise RuntimeError('missing ffprobe')
    monkeypatch.setattr(engine, '_probe_media_info', missing)
    await engine._inspect_chzzk_download(task, {'duration':600}, 'unused')
    assert task.inspection_state == 'failed'
    assert task.inspection_message == '파일 정보를 확인하지 못했습니다.'
    assert 'missing ffprobe' in task.inspection_diagnostics['detail']


@pytest.mark.asyncio
@pytest.mark.parametrize('cdn', ['default','akamai'])
async def test_retries_never_switch_cdn(tmp_path, monkeypatch, cdn):
    engine = VodEngine(); task = VodDownloadTask(url=URL, cdn=cdn, output_dir=str(tmp_path), max_retries=2)
    engine._tasks[task.task_id] = task; attempts=[]
    async def fails(*a):
        attempts.append(task.cdn)
        raise RuntimeError('HTTP 503')
    async def no_delay(*a): pass
    monkeypatch.setattr(engine, '_download_external', fails)
    monkeypatch.setattr('app.engine.vod.asyncio.sleep', no_delay)
    await engine._run_download(task.task_id)
    assert attempts == [cdn,cdn]
    assert task.state == VodDownloadState.ERROR


def test_non_chzzk_query_cannot_enable_cdn_or_naver_cookies():
    assert not VodEngine()._is_chzzk_url('https://example.test/?url=chzzk.naver.com')


def test_unsupported_hls_does_not_delegate_to_ffmpeg(monkeypatch):
    info = {'url':f'https://{DEFAULT_HOST}/list.m3u8','protocol':'m3u8_native',
            'hls_media_playlist_data':'#EXTM3U\n#EXT-X-KEY:METHOD=SAMPLE-AES\nsegment.ts\n'}
    with ChzzkCdnYoutubeDL({'quiet':True}, cdn='akamai') as ydl:
        with pytest.raises(yt_dlp.utils.DownloadError, match='HLS'):
            ydl.process_info(info)

@pytest.fixture
def mock_media_server(tmp_path, monkeypatch):
    """Real HTTP/FFmpeg/yt-dlp; only route virtual CDN DNS to loopback."""
    import functools
    import http.server
    import shutil
    import subprocess
    import threading
    from urllib.parse import urlsplit, urlunsplit
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('FFmpeg/FFprobe required for synthetic media integration')
    media = tmp_path/'media'; media.mkdir()
    source = media/'sample.mp4'
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i','testsrc=size=160x90:rate=10',
                    '-f','lavfi','-i','sine=frequency=440','-t','2','-c:v','libx264','-threads','1',
                    '-pix_fmt','yuv420p','-c:a','aac',str(source)], check=True, timeout=30)
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-i',str(source),'-c','copy',
                    '-f','hls','-hls_time','1','-hls_list_size','0',str(media/'list.m3u8')],check=True,timeout=30)
    key = media/'key.bin'; key.write_bytes(bytes(range(16)))
    key_info = media/'key-info.txt'
    key_info.write_text(f'https://{DEFAULT_HOST}/key.bin?token=key%2Ftoken\n{key}\n')
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-i',str(source),'-c','copy',
                    '-f','hls','-hls_time','1','-hls_list_size','0','-hls_key_info_file',str(key_info),
                    str(media/'encrypted.m3u8')],check=True,timeout=30)
    # Mix relative and absolute media URLs to exercise both resolution paths.
    playlist=(media/'list.m3u8').read_text()
    playlist=playlist.replace('list0.ts',f'https://{DEFAULT_HOST}/list0.ts?token=test%2Fvalue')
    (media/'list.m3u8').write_text(playlist)
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-i',str(source),'-c','copy',
                    '-f','dash',str(media/'sample.mpd')],check=True,timeout=30,cwd=media)
    mpd=(media/'sample.mpd').read_text(); mpd=mpd.replace('<Period ',f'<BaseURL>https://{DEFAULT_HOST}/</BaseURL>\n\t<Period ',1)
    (media/'sample.mpd').write_text(mpd)
    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self,*a): pass
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Handler,directory=str(media)))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    real=yt_dlp.YoutubeDL.urlopen;seen=[]
    def route(self,req):
        if isinstance(req,str): req=Request(req)
        parts=urlsplit(req.url)
        if parts.hostname not in (DEFAULT_HOST,AKAMAI_HOST,'apis.naver.com'):
            return real(self,req)
        seen.append(req.url)
        local=req.copy(); local.url=urlunsplit(('http',f'127.0.0.1:{server.server_port}',parts.path,parts.query,''))
        response=real(self,local)
        response.url=req.url
        return response
    monkeypatch.setattr(yt_dlp.YoutubeDL,'urlopen',route)
    monkeypatch.setattr('app.core.config.Settings.resolve_ffmpeg_path',lambda _:shutil.which('ffmpeg'))
    yield seen
    server.shutdown();server.server_close();thread.join(timeout=3)


@pytest.mark.asyncio
@pytest.mark.parametrize('cdn', ['default','akamai'])
@pytest.mark.parametrize('protocol', ['hls','dash','encrypted_hls'])
async def test_actual_manifest_segments_audio_video_and_merge(mock_media_server, tmp_path, monkeypatch, cdn, protocol):
    from yt_dlp.extractor.common import InfoExtractor
    engine=VodEngine();get_settings().vod_format='mkv' if protocol=='dash' else 'mp4'
    def extract(self, url, download=False):
        ie=InfoExtractor(self)
        if protocol=='dash':
            formats=ie._extract_mpd_formats('https://apis.naver.com/sample.mpd','123')
        else:
            playlist = 'encrypted.m3u8' if protocol == 'encrypted_hls' else 'list.m3u8'
            formats=ie._extract_m3u8_formats(f'https://{DEFAULT_HOST}/{playlist}','123','mp4')
        return {'id':'123','title':'synthetic','uploader':'test','formats':formats,
                'extractor':'chzzk:video','extractor_key':'CHZZKVideo','webpage_url':URL,'duration':2}
    monkeypatch.setattr(yt_dlp.YoutubeDL,'extract_info',extract)
    task=VodDownloadTask(url=URL,cdn=cdn,output_dir=str(tmp_path/'downloads'))
    engine._tasks[task.task_id]=task
    await engine._download_with_ytdlp(task.task_id,task,None)
    assert task.state==VodDownloadState.COMPLETED
    assert Path(task.output_path).is_file()
    media=engine._probe_media_info(task.output_path)
    assert media['streams']=={'audio','video'}
    assert 1.8 <= media['duration'] <= 2.5
    assert task.warning_message is None
    from urllib.parse import urlsplit
    requests=[u for u in mock_media_server if urlsplit(u).hostname!='apis.naver.com']
    assert requests
    host=AKAMAI_HOST if cdn=='akamai' else DEFAULT_HOST
    assert all(urlsplit(u).hostname==host for u in requests)
    assert any('.ts' in u or '.m4s' in u for u in requests)
    if protocol=='dash':
        assert any('init-' in u for u in requests)
        assert Path(task.output_path).suffix=='.mkv'
    elif protocol == 'hls':
        assert any('token=test%2Fvalue' in u for u in requests)
    else:
        assert any('/key.bin?token=key%2Ftoken' in u for u in requests)
    assert task.cdn_applied==(cdn=='akamai')

@pytest.mark.parametrize('status', [403,404,429,500,503])
def test_selected_cdn_http_failure_never_falls_back(monkeypatch, status):
    from yt_dlp.networking.exceptions import HTTPError
    seen=[]
    def fail(self, request):
        seen.append(request.url)
        raise HTTPError(Response(io.BytesIO(b''),request.url,{},status=status))
    monkeypatch.setattr(yt_dlp.YoutubeDL,'urlopen',fail)
    with ChzzkCdnYoutubeDL({'quiet':True},cdn='akamai') as ydl:
        for _ in range(2):
            with pytest.raises(HTTPError):
                ydl.urlopen(Request(f'https://{DEFAULT_HOST}/a.ts'))
    assert seen==[f'https://{AKAMAI_HOST}/a.ts']*2


def test_connection_timeout_never_falls_back(monkeypatch):
    from yt_dlp.networking.exceptions import TransportError
    seen=[]
    def fail(self, request):
        seen.append(request.url)
        raise TransportError('timeout')
    monkeypatch.setattr(yt_dlp.YoutubeDL,'urlopen',fail)
    with ChzzkCdnYoutubeDL({'quiet':True},cdn='akamai') as ydl:
        with pytest.raises(TransportError):
            ydl.urlopen(Request(f'https://{DEFAULT_HOST}/a.ts'))
    assert seen==[f'https://{AKAMAI_HOST}/a.ts']


@pytest.mark.parametrize('url', ['https://chzzk.naver.com/live/123','https://chzzk.naver.com/clips/123','https://example.test/video/123'])
def test_cdn_option_does_not_apply_to_live_or_other_routes(url):
    from app.engine.chzzk_cdn import is_chzzk_vod_url
    assert not is_chzzk_vod_url(url)


def test_live_engine_is_still_streamlink():
    from app.engine.pipeline.ytdlp import YtdlpLivePipeline
    # Public factory and concrete pipeline retain their Streamlink implementation.
    import inspect
    assert 'streamlink' in inspect.getsource(YtdlpLivePipeline._create_streamlink_stream)


@pytest.mark.asyncio
async def test_cancel_after_media_prevents_completed_state(tmp_path, monkeypatch):
    engine=VodEngine();task=VodDownloadTask(url=URL,output_dir=str(tmp_path))
    engine._tasks[task.task_id]=task
    def extract(self,*a,**kw):
        return {'id':'123','title':'test','ext':'mp4','url':'https://example.test/test.mp4',
                'extractor':'chzzk:video','extractor_key':'CHZZKVideo'}
    def finish(self,info,download=True):
        path=tmp_path/'finished.mp4';path.write_bytes(b'preserve completed bytes')
        task.cancel_flag=True
        return {'filepath':str(path)}
    monkeypatch.setattr(yt_dlp.YoutubeDL,'extract_info',extract)
    monkeypatch.setattr(yt_dlp.YoutubeDL,'process_ie_result',finish)
    monkeypatch.setattr('app.core.config.Settings.resolve_ffmpeg_path',lambda _:'ffmpeg')
    from app.engine.vod import DownloadCancelledError
    with pytest.raises(DownloadCancelledError):
        await engine._download_with_ytdlp(task.task_id,task,None)
    assert task.state!=VodDownloadState.COMPLETED


@pytest.mark.asyncio
async def test_selected_audio_format_does_not_warn_about_unselected_video(monkeypatch):
    engine=VodEngine();task=VodDownloadTask(url=URL)
    monkeypatch.setattr(engine,'_probe_media_info',lambda _: {'duration':60,'format_name':'m4a','streams':{'audio'}})
    await engine._inspect_chzzk_download(task,{'duration':60,'vcodec':'none','acodec':'aac',
                                             'formats':[{'vcodec':'h264','acodec':'aac'}]},'unused')
    assert task.warning_message is None

@pytest.mark.asyncio
async def test_api_download_and_retry_pass_cdn_to_service(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.vod import router
    import app.main as main
    service=SimpleNamespace(download_vod_batch=AsyncMock(return_value={'task_id':'new'}),
                            retry_vod=AsyncMock(return_value='retry'))
    monkeypatch.setattr(main,'get_recorder_service',lambda:service)
    app=FastAPI();app.include_router(router)
    with TestClient(app) as client:
        assert client.post('/api/vod/download',json={'url':URL,'cdn':'akamai'}).status_code==200
        assert service.download_vod_batch.await_args.kwargs['cdn']=='akamai'
        assert client.post('/api/vod/download',json={'url':URL}).status_code==200
        assert service.download_vod_batch.await_args.kwargs['cdn']=='default'
        assert client.post('/api/vod/old/retry',json={'cdn':'akamai'}).status_code==200
        assert service.retry_vod.await_args.kwargs['cdn']=='akamai'
        assert client.post('/api/vod/old/retry').status_code==200
        assert service.retry_vod.await_args.kwargs['cdn']=='default'


@pytest.mark.asyncio
async def test_format_change_cannot_overwrite_existing_file(tmp_path, monkeypatch):
    engine=VodEngine();get_settings().vod_format='mkv'
    task=VodDownloadTask(url=URL,output_dir=str(tmp_path))
    engine._tasks[task.task_id]=task
    def extract(self,*a,**kw):
        return {'id':'123','title':'test','ext':'mp4','url':'https://example.test/test.mp4',
                'extractor':'chzzk:video','extractor_key':'CHZZKVideo'}
    monkeypatch.setattr('app.core.config.Settings.resolve_ffmpeg_path',lambda _:'ffmpeg')
    info=extract(None)
    with yt_dlp.YoutubeDL(engine._build_ytdlp_options(task)) as ydl:
        expected=Path(ydl.prepare_filename(info))
    old=expected.with_suffix('.mkv');old.write_bytes(b'old original video')
    def finish(self,*a,**kw):
        new=Path(self.params['outtmpl']['default'].replace('%%','%')).with_suffix('.mkv')
        new.write_bytes(b'new video')
        return {'filepath':str(new)}
    monkeypatch.setattr(yt_dlp.YoutubeDL,'extract_info',extract)
    monkeypatch.setattr(yt_dlp.YoutubeDL,'process_ie_result',finish)
    await engine._download_with_ytdlp(task.task_id,task,None)
    assert task.output_path!=str(old)
    assert old.read_bytes()==b'old original video'
    assert Path(task.output_path).read_bytes()==b'new video'
