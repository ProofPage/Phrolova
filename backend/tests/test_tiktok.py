import asyncio
import json
from pathlib import Path
import shutil
import subprocess
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
from app.engine.platform_auth import platform_cookie_status, platform_cookie_file, get_platform_cookies
from app.engine.platform_media import canonical_platform_video, media_platform
from app.engine.recording_errors import RecordingError
from app.engine.tiktok import TikTokLiveEngine, canonical_tiktok_video_url, normalize_tiktok_channel_id
from app.engine.vod import VodDownloadTask, VodEngine, NonRetryableDownloadError
from app.engine.vod_preparation import canonical_prepared_url
from tests.test_new_platforms import local_hls

VIDEO = 'https://www.tiktok.com/@alice/video/7100000000000000000'


@pytest.mark.parametrize('value', ['Alice', '@Alice', 'alice.name', 'https://tiktok.com/@Alice', 'https://m.tiktok.com/@alice/live?ref=share'])
def test_channel_inputs(value):
    assert normalize_tiktok_channel_id(value) == ('alice.name' if value == 'alice.name' else 'alice')


@pytest.mark.parametrize('value', ['https://tiktok.com.evil/@alice', 'https://u:p@tiktok.com/@alice',
    'https://tiktok.com:444/@alice', VIDEO, 'https://vt.tiktok.com/One/', '@@alice', 'alice.',
    'alice-name', 'a'*25, 'https://tiktok.com/alice'])
def test_invalid_channels(value):
    with pytest.raises(ValueError): normalize_tiktok_channel_id(value)


@pytest.mark.parametrize('value,expected', [(VIDEO+'?ref=share#x', VIDEO),
    ('https://m.tiktok.com/@Alice/video/7100000000000000000', VIDEO),
    ('https://www.tiktok.com/embed/v2/7100000000000000000','https://www.tiktok.com/@_/video/7100000000000000000'),
    ('https://vt.tiktok.com/AbC123/?lang=en','https://vt.tiktok.com/AbC123/'),
    ('https://vm.tiktok.com/AbC123','https://vm.tiktok.com/AbC123/'),
    ('https://tiktok.com/t/AbC123?ref=share','https://www.tiktok.com/t/AbC123/')])
def test_video_and_short_urls(value, expected):
    assert canonical_tiktok_video_url(value) == expected
    assert canonical_platform_video(value) == expected
    assert canonical_prepared_url(value, 'tiktok') == expected
    assert canonical_prepared_url(value, 'auto') == expected
    assert media_platform(value) == 'tiktok'
    assert get_media_logger(value).name == 'phrolova.tiktok'


@pytest.mark.parametrize('value', ['https://tiktok.com/@alice', 'https://tiktok.com/@alice/live',
    'https://tiktok.com/@alice/photo/123', 'https://vt.tiktok.com/one/two',
    'https://tiktok.com.evil/@alice/video/1','https://tiktok.com/@alice/video/nope'])
def test_invalid_videos(value):
    with pytest.raises(ValueError): canonical_tiktok_video_url(value)


def cookies(tmp_path):
    path = tmp_path/'tiktok.txt'
    path.write_text('# Netscape HTTP Cookie File\n.tiktok.com\tTRUE\t/\tTRUE\t0\tsessionid\tfixture-token\n'
        '.evil.example\tTRUE\t/\tTRUE\t0\tsessionid\twrong\n')
    get_settings().tiktok_cookie_file = str(path)
    return path


def test_scoped_cookies_and_temporary_copy(tmp_path):
    source = cookies(tmp_path)
    assert platform_cookie_status('tiktok')['valid']
    assert get_platform_cookies('tiktok','https://www.tiktok.com/api-live/user/room') == {'sessionid':'fixture-token'}
    assert get_platform_cookies('tiktok','https://cdn.example/stream') == {}
    with platform_cookie_file('tiktok') as copy:
        assert Path(copy).exists() and 'wrong' not in Path(copy).read_text()
    assert source.exists() and not Path(copy).exists()


def test_quality_failure_and_token_redaction():
    from app.core.logger import _redact_log_secrets
    from app.engine.platform_auth import redact_media_error
    from app.engine.tiktok import tiktok_access_error
    assert tiktok_access_error(RuntimeError('Requested format is not available')).code=='tiktok_quality'
    for name in ('sessionid','sessionid_ss','sid_tt','sid_guard','ttwid'):
        assert 'fixture-secret'not in _redact_log_secrets(f'{name}=fixture-secret')
        assert 'fixture-secret'not in redact_media_error(f'{name}=fixture-secret')


def metadata(status=2):
    sdk = lambda resolution: json.dumps({'resolution':resolution,'vbitrate':1000000})
    data = {'data':{q:{'main':{'sdk_params':sdk(res)}} for q,res in [('hd','720x1280'),('hd_60','720x1280'),('sd','540x960'),('ao','')]}}
    return {'statusCode':0,'data':{'user':{'nickname':'Alice','avatarMedium':'https://example.com/avatar.jpg'},
        'liveRoom':{'status':status,'title':'Live','startTime':1791845880,'liveRoomStats':{'userCount':12},
            'streamData':{'pull_data':{'stream_data':json.dumps(data)}},
            'hevcStreamData':{'pull_data':{'stream_data':json.dumps(data)}}}}}


def mock_http(monkeypatch, handler):
    client = httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda *a,**kw:client(*a,**kw,transport=httpx.MockTransport(handler)))


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [2,4])
async def test_online_offline_metadata_and_cache(monkeypatch, tmp_path, status):
    cookies(tmp_path)
    calls=[]
    def respond(request):
        calls.append(request)
        assert 'fixture-token' in request.headers['Cookie']
        return httpx.Response(200,json=metadata(status))
    mock_http(monkeypatch,respond)
    engine=TikTokLiveEngine()
    state=await engine.check_live_status('alice')
    assert isinstance(engine,PlatformEngine) and state['is_live'] == (status==2)
    assert state['viewer_count'] == (12 if status==2 else 0)
    await engine.check_live_status('alice')
    assert len(calls)==1


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [{}, {'statusCode':0,'data':{}}, {'statusCode':0,'data':{'liveRoom':{'status':99}}}, {'statusCode':1,'message':'challenge required'}])
async def test_bad_responses_are_not_offline(monkeypatch,payload):
    mock_http(monkeypatch,lambda _:httpx.Response(200,json=payload))
    with pytest.raises(RuntimeError): await TikTokLiveEngine().check_live_status('alice')


@pytest.mark.asyncio
@pytest.mark.parametrize('code,reason', [(403,'tiktok_access'),(429,'tiktok_rate_limit'),(404,'tiktok_not_found')])
async def test_http_errors_keep_reason(monkeypatch,code,reason):
    mock_http(monkeypatch,lambda _:httpx.Response(code))
    with pytest.raises(RecordingError) as caught: await TikTokLiveEngine().check_live_status('alice')
    assert caught.value.code==reason


@pytest.mark.asyncio
async def test_network_transport_failure(monkeypatch):
    def fail(request):
        raise httpx.ConnectError("connection refused")
    mock_http(monkeypatch, fail)
    with pytest.raises(RuntimeError) as caught:
        await TikTokLiveEngine().check_live_status('alice')
    assert '읽지 못했습니다' in str(caught.value)


@pytest.mark.asyncio
async def test_streamlink_real_dimensions_portrait_and_cookie_boundary(monkeypatch,tmp_path):
    import streamlink
    cookies(tmp_path)
    sessions=[]
    class Session:
        def __init__(self):
            self.http=requests.Session();self.http.close=Mock();self.options={};sessions.append(self)
        def set_option(self,key,value): self.options[key]=value
        def streams(self,url):
            assert url=='https://www.tiktok.com/@alice/live'
            cdn=self.http.prepare_request(requests.Request('GET','https://cdn.example/live.flv'))
            assert 'Cookie' not in cdn.headers and 'Authorization' not in cdn.headers
            stream=lambda name:SimpleNamespace(to_url=lambda:f'https://cdn.example/{name}.flv')
            return {name:stream(name)for name in ('h264_hd','h265_hd','h265_hd_60','h264_sd','h264_ao','best','worst')}
    monkeypatch.setattr(streamlink,'Streamlink',Session)
    engine=TikTokLiveEngine()
    monkeypatch.setattr(engine,'_metadata',AsyncMock(return_value=metadata()['data']))
    qualities=await engine.get_qualities('alice')
    assert [q['value']for q in qualities]==['720p60','720p','540p']
    assert qualities[0]['width']==720 and qualities[0]['height']==1280
    assert not any('url'in q for q in qualities)
    assert (await engine.resolve_stream('alice','720p60'))[0].endswith('h265_hd_60.flv')
    assert (await engine.resolve_stream('alice','worst'))[0].endswith('h264_sd.flv')
    assert all(s.http.close.called and not s.options['webbrowser'] and s.options['no-plugin-cache'] for s in sessions)


def test_public_api_cookie_and_numeric_live_quality(monkeypatch,tmp_path):
    import app.main
    from app.api import platforms,vod
    added=Mock(return_value={'status':'added'})
    monkeypatch.setattr(app.main,'get_recorder_service',lambda:SimpleNamespace(add_platform_channel=added))
    monkeypatch.setattr(platforms,'_COOKIE_SAVE_PATH',tmp_path/'data/platform.txt')
    app=FastAPI();app.include_router(platforms.router);app.include_router(vod.router)
    with TestClient(app) as client:
        response=client.post('/api/platforms/channels',json={'platform':'tiktok','channel_id':'https://tiktok.com/@Alice/live','recording_quality':'720p60'})
        assert response.status_code==200 and added.call_args.kwargs['channel_id']=='alice'
        assert any(s['id']=='tiktok'for s in client.get('/api/vod/capabilities').json()['sources'])
        response=client.post('/api/platforms/tiktok/cookie',files={'file':('tiktok.txt',b'# Netscape HTTP Cookie File\n.tiktok.com\tTRUE\t/\tTRUE\t0\tsessionid\tfixture-token\n')})
        assert response.status_code==200 and response.json()['valid'] and 'fixture-token'not in response.text
        assert client.get('/api/platforms/status').json()['tiktok']['enabled']
        assert client.delete('/api/platforms/tiktok/cookie').status_code==200


@pytest.mark.asyncio
async def test_live_share_cannot_be_downloaded_as_video(monkeypatch):
    import yt_dlp
    engine=VodEngine()
    class YDL:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def extract_info(self,*args,**kw):return {'is_live':True,'title':'Live'}
    monkeypatch.setattr('app.engine.vod.platform_ydl',lambda *a,**kw:YDL())
    monkeypatch.setattr(yt_dlp,'YoutubeDL',lambda *a,**kw:YDL())
    with pytest.raises(ValueError,match='라이브 메뉴'):
        await engine.get_video_info('https://vt.tiktok.com/ShareLive/')
    with pytest.raises(NonRetryableDownloadError,match='라이브 메뉴'):
        await engine._download_external('id',VodDownloadTask(url='https://vt.tiktok.com/ShareLive/'))


@pytest.mark.asyncio
@pytest.mark.parametrize('short', [False,True])
async def test_real_video_extractor_download_and_inspection(local_hls,monkeypatch,short):
    from yt_dlp.extractor.tiktok import TikTokIE,TikTokVMIE
    from app.engine.media_inspection import probe_media
    base,directory=local_hls
    subprocess.run([shutil.which('ffmpeg'),'-v','error','-i',str(directory/'720/index.m3u8'),'-c','copy',str(directory/'video.mp4')],check=True)
    monkeypatch.setattr(TikTokIE,'_extract_web_data_and_status',lambda *a,**kw:({'id':'7100000000000000000','desc':'Fixture',
        'author':{'uniqueId':'alice','nickname':'Alice','id':'1'},
        'video':{'width':1280,'height':720,'duration':3,'playAddr':base+'/video.mp4'}},0))
    monkeypatch.setattr(TikTokVMIE,'_request_webpage',lambda *a,**kw:SimpleNamespace(url=VIDEO))
    get_settings().tiktok_cookie_file=None
    engine=VodEngine();url='https://vt.tiktok.com/AbC123/'if short else VIDEO
    info=await engine.get_video_info(url)
    assert info['duration']==3 and info['formats']
    output=directory/'download';output.mkdir()
    task=VodDownloadTask(url=url,prepared=True,quality='720p',output_dir=str(output))
    engine._tasks[task.task_id]=task
    await engine._download_external(task.task_id,task)
    assert task.state.value=='completed' and task.inspection_state=='passed'
    assert probe_media(task.output_path)['streams']=={'video','audio'}
    assert engine.get_task_status(task.task_id)['platform']=='tiktok'
    await engine.shutdown()


@pytest.mark.asyncio
async def test_real_flv_input_is_remuxed_without_transcoding(local_hls,tmp_path):
    from app.engine.pipeline import YtdlpLivePipeline
    from app.engine.media_inspection import probe_media
    base,directory=local_hls
    subprocess.run([shutil.which('ffmpeg'),'-v','error','-i',str(directory/'720/index.m3u8'),'-c','copy','-f','flv',str(directory/'live.flv')],check=True)
    session,stream=YtdlpLivePipeline._create_streamlink_stream(base+'/live.flv',{},None,0,False,'720p',source_page_url='https://www.tiktok.com/@alice/live')
    reader=None
    try:
        reader=await asyncio.to_thread(stream.open)
        out=tmp_path/'capture.ts'
        def receive():
            with out.open('wb')as file:
                while data:=reader.read(65536):file.write(data)
        await asyncio.wait_for(asyncio.to_thread(receive),30)
        cmd=reader.muxer._cmd
        assert cmd[cmd.index('-c:v')+1]=='copy' and cmd[cmd.index('-c:a')+1]=='copy'
        assert not any('http://'in str(arg)or'https://'in str(arg)for arg in cmd)
        media=probe_media(str(out))
        assert 'mpegts'in media['format_name'] and media['duration']>2
        assert media['streams']=={'video','audio'}
    finally:
        if reader:await asyncio.to_thread(reader.close)
        session.http.close()
    assert reader.muxer.process.poll()is not None


@pytest.mark.asyncio
async def test_preview_frame_accepts_tiktok_flv(local_hls):
    from app.engine.preview_transport import decode_preview
    from app.engine.preview_frames import jpeg_dimensions
    base,directory=local_hls
    subprocess.run([shutil.which('ffmpeg'),'-v','error','-i',str(directory/'720/index.m3u8'),'-c','copy','-f','flv',str(directory/'live.flv')],check=True)
    cmd=[shutil.which('ffmpeg'),'-v','error','-i','pipe:0','-frames:v','1','-f','image2pipe','-vcodec','mjpeg','pipe:1']
    data,_,code=await asyncio.wait_for(decode_preview(cmd,base+'/live.flv',{},'tiktok',False),25)
    assert code==0 and jpeg_dimensions(data)==(1280,720)


def test_factory_and_preview_endpoint_type(monkeypatch):
    from app.api import stream
    import app.main
    conductor=Conductor()
    assert isinstance(conductor._get_engine(Platform.TIKTOK),TikTokLiveEngine)
    monkeypatch.setattr(app.main, "get_recorder_service", lambda: SimpleNamespace(
        get_live_preview_url=AsyncMock(return_value="https://pull.tiktokcdn.com/live.flv")))
    app=FastAPI();app.include_router(stream.router)
    with TestClient(app)as client:
        response = client.get('/api/stream/preview/tiktok:alice')
        assert response.status_code == 200 and response.json()["url"].endswith("/asset.flv")


def test_failed_muxer_start_closes_input_and_pipes(monkeypatch):
    from unittest.mock import Mock
    from app.engine import tiktok_transport as transport
    from streamlink.stream.http import HTTPStream
    source, pipe, session = Mock(), Mock(), Mock()
    session.http.valid_request_args.return_value = {}
    monkeypatch.setattr(HTTPStream, 'open', lambda self: source)
    muxer = Mock(pipes=[pipe])
    muxer.open.side_effect = OSError('process could not start')
    monkeypatch.setattr(transport, '_TikTokMuxer', Mock(return_value=muxer))
    with pytest.raises(OSError, match='could not start'):
        transport.TikTokFLVStream(session, 'https://cdn.example/live.flv').open()
    source.close.assert_called_once()
    pipe.close.assert_called_once()


def test_muxed_reader_reports_failure_and_reaps_once():
    from unittest.mock import Mock
    from app.engine.tiktok_transport import TikTokMuxedReader
    source, muxer = Mock(), Mock()
    muxer.read.return_value = b''
    muxer.process.wait.return_value = 1
    reader = TikTokMuxedReader(muxer, source)
    with pytest.raises(RecordingError) as caught:
        reader.read(1024)
    assert caught.value.code == 'tiktok_remux'
    reader.request_stop()
    source.close.assert_called_once()
    muxer.process.wait.reset_mock()
    reader.close()
    reader.close()
    muxer.close.assert_called_once()
    muxer.process.wait.assert_called_once_with(timeout=10)
