"""SOOP/CIME integration with isolated API fixtures and real local media."""
import asyncio
import functools
import http.server
import json
import shutil
import sqlite3
import subprocess
import threading
import time
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.core.config import get_settings
from app.engine.base import Platform
from app.engine.cime import (CimeLiveEngine, normalize_cime_channel_id, parse_cime_video_url,
                             parse_cime_variants, select_cime_variant, cime_quality_options)
from app.engine.soop import SoopLiveEngine, normalize_soop_channel_id, normalize_soop_vod_url
from app.engine.platform_auth import (get_platform_cookies, platform_cookie_file,
                                      platform_cookie_status, with_platform_cookie_fallback, PlatformAuthenticationError)

MASTER = '''#EXTM3U
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",URI="audio.m3u8",DEFAULT=YES
#EXT-X-STREAM-INF:RESOLUTION=3840x2160,BANDWIDTH=14000000,FRAME-RATE=60,AUDIO="audio"
uhd.m3u8
#EXT-X-STREAM-INF:RESOLUTION=1920x1080,BANDWIDTH=6000000,FRAME-RATE=60,AUDIO="audio"
full.m3u8
#EXT-X-STREAM-INF:RESOLUTION=1920x1080,BANDWIDTH=4000000,FRAME-RATE=30
regular.m3u8
#EXT-X-STREAM-INF:RESOLUTION=1280x720,BANDWIDTH=2000000,FRAME-RATE=30
hd.m3u8
'''

@pytest.mark.parametrize('text', ['alice','@alice','https://ci.me/@alice','https://ci.me/@alice/live','https://ci.me/@alice.name/live'])
def test_cime_channel_inputs(text):
    assert normalize_cime_channel_id(text) in ('alice', 'alice.name')

@pytest.mark.parametrize('text', ['@@alice','https://ci.me.evil/@alice','https://ci.me/settings','https://user:pass@ci.me/@alice','https://ci.me/@alice/vods/1'])
def test_invalid_cime_inputs(text):
    with pytest.raises(ValueError): normalize_cime_channel_id(text)

@pytest.mark.parametrize('url', ['https://ci.me/@alice/vods/1','https://ci.me/clips/2'])
def test_cime_vod_clip_routes(url):
    assert parse_cime_video_url(url)['url'] == url
    assert parse_cime_video_url(url.replace('ci.me','ci.me.evil')) is None

@pytest.mark.parametrize('url', ['alice','https://play.sooplive.com/alice/123','https://play.sooplive.co.kr/alice','https://play.afreecatv.com/alice','https://www.sooplive.com/station/alice','https://bj.afreecatv.com/alice'])
def test_soop_channel_inputs(url):
    assert normalize_soop_channel_id(url) == 'alice'

@pytest.mark.parametrize('url', ['https://vod.sooplive.com/player/123','https://vod.sooplive.co.kr/player/123','https://vod.afreecatv.com/player/123'])
def test_soop_vod_aliases(url):
    assert normalize_soop_vod_url(url) == 'https://vod.sooplive.com/player/123'

@pytest.mark.parametrize('url', ['https://play.sooplive.com.evil/alice','https://ci.me/@alice','https://www.sooplive.com/video/123','file:///alice'])
def test_soop_invalid_channels(url):
    with pytest.raises(ValueError): normalize_soop_channel_id(url)

def test_actual_manifest_dimensions_fps_and_audio():
    variants = parse_cime_variants('https://cdn.example/master.m3u8', MASTER)
    assert select_cime_variant(variants,'best')['height'] == 2160
    assert select_cime_variant(variants,'1080p60')['fps'] == 60
    assert select_cime_variant(variants,'1080p30')['fps'] == 30
    assert select_cime_variant(variants,'1440p')['height'] == 1080
    assert select_cime_variant(variants,'worst')['height'] == 720
    assert variants[1]['external_audio']
    assert cime_quality_options(variants)[0]['value'] == '2160p60'
    assert not any(q['height'] == 2160 for q in cime_quality_options(variants[1:]))

def mock_http(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *a, **kw: original(*a, **kw, transport=httpx.MockTransport(handler)))

@pytest.mark.asyncio
@pytest.mark.parametrize('legacy', [False, True])
async def test_cime_online_metadata_current_and_legacy(monkeypatch, legacy):
    requests=[]
    live={'state':'ACTIVE','title':'테스트 방송','openedAt':'2026-10-11T00:00:00Z','curViewerCnt':17,
          'channel':{'name':'씨미 채널','imageUrl':'https://ci.me/profile.jpg'},'category':{'name':'게임'},
          'playback':{'url':'https://cdn.example/live.m3u8'}}
    def respond(request):
        requests.append(request)
        return httpx.Response(200,json={'bodyData': {'homeData':{'live':live}} if legacy else {'live':live}})
    mock_http(monkeypatch, respond)
    engine=CimeLiveEngine()
    result=await engine.check_live_status('alice')
    assert result['is_live'] and result['viewer_count']==17 and result['channel_name']=='씨미 채널'
    await engine.check_live_status('alice')
    assert len(requests)==1 and 'cookie' not in requests[0].headers

@pytest.mark.asyncio
async def test_cime_offline_no_recommendation_capture(monkeypatch):
    mock_http(monkeypatch, lambda request:httpx.Response(200,json={'bodyData':{'live':None,'recommendations':[{'state':'ACTIVE','playback':{'url':'https://evil.example/live.m3u8'}}]}}))
    assert not (await CimeLiveEngine().check_live_status('alice'))['is_live']

@pytest.mark.asyncio
async def test_cime_manifest_auth_is_response_based(monkeypatch,tmp_path):
    cookie=tmp_path/'cime.txt';cookie.write_text('# Netscape HTTP Cookie File\n.ci.me\tTRUE\t/\tTRUE\t0\tsession-id\tfixture\n')
    get_settings().cime_cookie_file=str(cookie)
    calls=[]
    def respond(request):
        calls.append(request)
        if '/json/' in request.url.path:
            return httpx.Response(200,json={'bodyData':{'live':{'state':'ACTIVE','playback':{'url':'https://ci.me/stream/master.m3u8'}}}})
        if 'cookie' not in request.headers:return httpx.Response(403)
        return httpx.Response(200,text=MASTER)
    mock_http(monkeypatch,respond)
    engine=CimeLiveEngine()
    q=await engine.get_qualities('alice')
    assert q[0]['height']==2160
    assert 'cookie' not in calls[0].headers and 'cookie' not in calls[1].headers and 'fixture' in calls[2].headers['cookie']
    url,headers,cookies=await engine.resolve_stream('alice','1080p60')
    assert url=='https://ci.me/stream/master.m3u8' and cookies and 'cookie' not in {k.lower() for k in headers}

@pytest.mark.asyncio
async def test_soop_metadata_and_dynamic_actual_qualities(monkeypatch):
    calls=[]
    def respond(request):
        calls.append(request)
        return httpx.Response(200,json={'CHANNEL':{'RESULT':1,'BNO':'123','BJNICK':'숲 채널','TITLE':'방송','VIEWPRESET':[{'name':'hd','label':'720p','label_resolution':'1280x720','bps':2000},{'name':'original','label':'1080p','label_resolution':'1920x1080','bps':6000}]}} if request.method=='POST' else {'DATA':{'station_name':'숲 채널','broad_start':'2026-10-11 09:00:00'}})
    mock_http(monkeypatch,respond)
    engine=SoopLiveEngine()
    status=await engine.check_live_status('alice')
    assert status['is_live'] and status['channel_name']=='숲 채널'
    qualities=await engine.get_qualities('alice')
    assert [q['height'] for q in qualities]==[1080,720]
    assert len(calls)==2 and all('cookie' not in r.headers for r in calls)

def test_cookie_domain_expiry_and_borrowed_copy(tmp_path):
    cookie=tmp_path/'cime.txt';cookie.write_text('# Netscape HTTP Cookie File\n.ci.me\tTRUE\t/\tTRUE\t0\tsession-id\tfixture\n.evil.example\tTRUE\t/\tTRUE\t0\tauth\twrong\n')
    get_settings().cime_cookie_file=str(cookie)
    assert platform_cookie_status('cime')['valid']
    assert get_platform_cookies('cime','https://ci.me/api')=={'session-id':'fixture'}
    assert not get_platform_cookies('cime','https://cdn.example/video')
    with platform_cookie_file('cime') as borrowed:
        path=Path(borrowed);assert path.exists() and path!=cookie
        assert 'evil.example' not in path.read_text()
    assert not path.exists() and cookie.exists()
    cookie.write_text('# Netscape HTTP Cookie File\n.ci.me\tTRUE\t/\tTRUE\t1\tsession-id\tfixture\n')
    assert platform_cookie_status('cime')['expired']

@pytest.mark.asyncio
async def test_public_first_fallback_and_not_for_network_error(tmp_path):
    cookie=tmp_path/'soop.txt';cookie.write_text('# Netscape HTTP Cookie File\n.sooplive.com\tTRUE\t/\tTRUE\t0\tPdboxUser\tfixture\n');get_settings().soop_cookie_file=str(cookie)
    calls=[]
    async def operation(path):
        calls.append(path)
        if path is None:raise RuntimeError('HTTP Error 403')
        return 'authorized'
    assert await with_platform_cookie_fallback('soop',operation)=='authorized' and calls[0] is None and len(calls)==2
    calls.clear()
    async def unavailable(path):calls.append(path);raise RuntimeError('network unavailable')
    with pytest.raises(RuntimeError,match='network'):await with_platform_cookie_fallback('soop',unavailable)
    assert calls==[None]

def test_api_registration_quality_persistence_and_cookie_routes(monkeypatch,tmp_path):
    from app.api.platforms import router
    from app.engine.conductor import Conductor
    from app.services.recorder import RecorderService
    import app.api.platforms as routes
    import app.main
    conductor=Conductor();service=RecorderService(conductor)
    monkeypatch.setattr(app.main,'get_recorder_service',lambda:service)
    monkeypatch.setattr(routes,'_COOKIE_SAVE_PATH',tmp_path/'x_cookies.txt')
    app=FastAPI();app.include_router(router);client=TestClient(app)
    for platform,url,cid in [('cime','https://ci.me/@alice/live','alice'),('soop','https://play.sooplive.co.kr/alice','alice'),('youtube','UCabcdefghijklmnopqrstuv','UCabcdefghijklmnopqrstuv')]:
        response=client.post('/api/platforms/channels',json={'platform':platform,'channel_id':url,'auto_record':False,'recording_quality':'1080p60' if platform=='cime' else 'best'})
        assert response.status_code==200,response.text
        assert response.json()['platform']==platform
    restored=Conductor()
    assert restored._channels['cime:alice'].recording_quality=='1080p60'
    assert restored._channels['youtube:UCabcdefghijklmnopqrstuv'].platform==Platform.YOUTUBE
    assert client.get('/api/platforms/youtube/cookie').status_code==200
    assert client.post('/api/platforms/cime/cookie',files={'file':('c.txt',b'# Netscape HTTP Cookie File\n.ci.me\tTRUE\t/\tTRUE\t0\tsession-id\tfixture\n')}).status_code==200
    status=client.get('/api/platforms/cime/cookie').json()
    assert status['configured'] and 'fixture' not in json.dumps(status)
    assert client.delete('/api/platforms/cime/cookie').json()['configured'] is False

@pytest.fixture
def local_hls(tmp_path):
    ffmpeg=shutil.which('ffmpeg')
    if not ffmpeg:pytest.skip('FFmpeg unavailable')
    for name,size in [('1080','1920x1080'),('720','1280x720'),('480','854x480')]:
        folder=tmp_path/name;folder.mkdir()
        subprocess.run([ffmpeg,'-y','-v','error','-f','lavfi','-i',f'testsrc2=size={size}:rate=5','-f','lavfi','-i','sine=frequency=1000:sample_rate=44100','-t','3','-c:v','libx264','-preset','ultrafast','-c:a','aac','-g','5','-f','hls','-hls_time','1','-hls_list_size','0',str(folder/'index.m3u8')],check=True)
    (tmp_path/'master.m3u8').write_text('#EXTM3U\n' + '\n'.join(f'#EXT-X-STREAM-INF:RESOLUTION={size},BANDWIDTH={int(name)*4000},FRAME-RATE=5\n{name}/index.m3u8' for name,size in [('1080','1920x1080'),('720','1280x720'),('480','854x480')])+'\n')
    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self,*a):pass
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Handler,directory=str(tmp_path)))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    yield f'http://127.0.0.1:{server.server_port}',tmp_path
    server.shutdown();server.server_close()

@pytest.mark.asyncio
@pytest.mark.parametrize('height,width',[('1080',1920),('720',1280),('480',854)])
async def test_real_ffmpeg_frame_no_upscale_and_cache(local_hls,monkeypatch,height,width):
    from app.engine.preview_frames import FramePreviewService
    base,_=local_hls
    engine=type('Engine',(),{})()
    engine.get_qualities=AsyncMock(return_value=[{'value':height+'p','height':int(height)}])
    engine.resolve_stream=AsyncMock(return_value=(base+'/'+height+'/index.m3u8',{},None))
    get_settings().soop_cookie_file=None
    preview=FramePreviewService()
    one,two=await asyncio.gather(*(preview.get_frame('soop:fixture','soop','fixture',engine) for _ in range(2)))
    assert one==two and one[1:]==(width,int(height))
    engine.resolve_stream.assert_awaited_once()

@pytest.mark.asyncio
async def test_actual_cime_vod_engine_download_merge_and_probe(local_hls,monkeypatch,tmp_path):
    from app.engine.cime_extractor import CimeIE
    from app.engine.vod import VodEngine,VodDownloadTask,VodDownloadState
    base,_=local_hls
    monkeypatch.setattr(CimeIE,'_router',lambda self,route:{'id':'1','title':'실제 다운로드','duration':3000,'channel':{'slug':'alice','name':'Alice'},'playback':{'url':base+'/master.m3u8'}})
    get_settings().cime_cookie_file=None
    get_settings().vod_format='mp4'
    engine=VodEngine()
    info=await engine.get_video_info('https://ci.me/@alice/vods/1')
    assert info['duration']==3 and any(f['height']==720 for f in info['formats'])
    task=VodDownloadTask(url='https://ci.me/@alice/vods/1',output_dir=str(tmp_path/'영상 폴더'),quality=next(f['format_id'] for f in info['formats'] if f['height']==720))
    engine._tasks[task.task_id]=task;Path(task.output_dir).mkdir()
    await engine._download_external(task.task_id,task)
    assert task.state==VodDownloadState.COMPLETED and task.inspection_state=='passed'
    assert Path(task.output_path).stat().st_size>0
    engine._save_history()
    restored=VodEngine()
    assert restored.get_task_status(task.task_id)['platform']=='cime'
    assert restored.get_task_status(task.task_id)['state']=='completed'
    await engine.shutdown();await restored.shutdown()

@pytest.mark.asyncio
@pytest.mark.parametrize('platform',['cime','soop'])
@pytest.mark.parametrize('container',['ts','mkv','mp4'])
async def test_actual_new_platform_recording_pipeline_containers(local_hls,platform,container):
    from app.engine.pipeline import YtdlpLivePipeline
    from app.engine.media_inspection import probe_media
    base,directory=local_hls
    get_settings().live_format=container
    pipeline=YtdlpLivePipeline('fixture')
    async def resolve(quality):
        assert quality=='720p'
        return base+'/720/index.m3u8',{},None
    output=await pipeline.start_recording(stream_obj='https://ci.me/@fixture/live' if platform=='cime' else 'https://play.sooplive.com/fixture',output_dir=str(directory/'녹화 폴더'),quality='720p',source_resolver=resolve)
    for _ in range(100):
        if pipeline._feeder_task.done():break
        await asyncio.sleep(.1)
    await pipeline.stop_recording()
    assert pipeline.state.value=='completed'
    assert Path(output).suffix=='.ts' and Path(output).stat().st_size>0
    media=await asyncio.to_thread(probe_media,output)
    assert media['streams']=={'video','audio'} and media['duration']>1
    assert next(track for track in media['tracks'] if track['codec_type']=='video')['height']==720

@pytest.mark.asyncio
async def test_soop_multi_part_actual_download_concat(local_hls,monkeypatch,tmp_path):
    from yt_dlp.extractor.afreecatv import AfreecaTVIE
    from app.engine.vod import VodEngine,VodDownloadTask,VodDownloadState
    base,_=local_hls
    def extract(self,url):
        return {'_type':'multi_video','id':'123','title':'여러 부분 영상','uploader':'Alice','entries':[
            {'id':str(i),'title':f'부분 {i}','duration':3,'formats':[{'format_id':'hls','url':base+'/720/index.m3u8','protocol':'m3u8_native','ext':'mp4','height':720,'vcodec':'h264','acodec':'aac'}]}
            for i in range(2)]}
    monkeypatch.setattr(AfreecaTVIE,'_real_extract',extract)
    get_settings().soop_cookie_file=None
    get_settings().vod_format='mp4'
    engine=VodEngine()
    info=await engine.get_video_info('https://vod.sooplive.co.kr/player/123')
    assert info['duration']==6 and info['formats'][0]['height']==720
    task=VodDownloadTask(url='https://vod.sooplive.com/player/123',output_dir=str(tmp_path/'숲 다운로드'),quality='best')
    Path(task.output_dir).mkdir();engine._tasks[task.task_id]=task
    await engine._download_external(task.task_id,task)
    assert task.state==VodDownloadState.COMPLETED and task.inspection_state=='passed'
    assert engine._probe_media_info(task.output_path)['duration']>5
    await engine.shutdown()

@pytest.mark.asyncio
@pytest.mark.parametrize('platform',[Platform.SOOP,Platform.CIME])
async def test_conductor_shared_automatic_pipeline_and_no_duplicates(monkeypatch,platform):
    from app.engine.conductor import Conductor
    from app.engine.pipeline import YtdlpLivePipeline,RecordingState
    conductor=Conductor();conductor.add_channel('alice',platform=platform,recording_quality='1080p')
    conductor._running=True
    async def start(pipeline,**kwargs):
        assert kwargs['quality']=='1080p' and kwargs['cookie_str'] is None
        assert 'source_resolver' in kwargs
        pipeline._state=RecordingState.RECORDING
        return 'fixture.ts'
    monkeypatch.setattr(YtdlpLivePipeline,'start_recording',start)
    key=platform.value+':alice'
    await asyncio.gather(conductor._start_recording(key,is_retry=True,automatic=True),conductor._start_recording(key,is_retry=True,automatic=True))
    assert conductor._channels[key].pipeline.state==RecordingState.RECORDING
    assert conductor.get_all_status()[0]['platform']==platform.value

def test_frame_api_unknown_offline_and_redacted_failure(monkeypatch):
    import app.main
    from app.api.stream import router
    from app.engine.conductor import Conductor
    from app.services.recorder import RecorderService
    from app.engine.preview_frames import frame_previews
    conductor=Conductor();conductor.add_channel('alice',platform=Platform.CIME,auto_record=False)
    service=RecorderService(conductor)
    monkeypatch.setattr(app.main,'get_recorder_service',lambda:service)
    app=FastAPI();app.include_router(router);client=TestClient(app)
    assert client.get('/api/stream/preview-frame/cime:missing').status_code==404
    assert client.get('/api/stream/preview-frame/cime:alice').status_code==409
    conductor._channels['cime:alice'].is_live=True
    monkeypatch.setattr(frame_previews,'get_frame',AsyncMock(side_effect=RuntimeError('https://example.com?token=PRIVATE cookie:secret')))
    response=client.get('/api/stream/preview-frame/cime:alice')
    assert response.status_code==502 and 'PRIVATE' not in response.text and 'secret' not in response.text

@pytest.mark.asyncio
@pytest.mark.parametrize('finish',['resume','cancel'])
async def test_actual_cime_hls_pause_resume_or_cancel(local_hls,monkeypatch,tmp_path,finish):
    from app.engine.cime_extractor import CimeIE
    from app.engine.vod import VodEngine,VodDownloadTask,VodDownloadState,DownloadCancelledError
    base,_=local_hls
    monkeypatch.setattr(CimeIE,'_router',lambda self,route:{'id':'1','title':'일시정지 영상','duration':3000,'playback':{'url':base+'/720/index.m3u8'}})
    get_settings().cime_cookie_file=None;get_settings().vod_format='mp4'
    engine=VodEngine(); loop=asyncio.get_running_loop();paused=asyncio.Event()
    task=VodDownloadTask(url='https://ci.me/@alice/vods/1',output_dir=str(tmp_path/'일시정지'),state=VodDownloadState.DOWNLOADING)
    Path(task.output_dir).mkdir();engine._tasks[task.task_id]=task
    original=engine._make_progress_callback
    def wrap(t):
        callback=original(t);first=True
        def progress(data):
            nonlocal first
            if first and data.get('status')=='downloading':
                first=False
                engine.pause_download(t.task_id)
                loop.call_soon_threadsafe(paused.set)
            callback(data)
        return progress
    monkeypatch.setattr(engine,'_make_progress_callback',wrap)
    worker=asyncio.create_task(engine._download_external(task.task_id,task))
    try:
        await asyncio.wait_for(paused.wait(),15)
        assert task.state==VodDownloadState.PAUSED
        await asyncio.sleep(.2); assert not worker.done()
        assert list(Path(task.output_dir).glob('*.part')), 'Native downloader preserves partial data'
        if finish=='resume':
            assert engine.resume_download(task.task_id)['state']=='downloading'
            await asyncio.wait_for(worker,30)
            assert task.state==VodDownloadState.COMPLETED and task.inspection_state=='passed'
        else:
            engine.cancel_download(task.task_id)
            with pytest.raises(DownloadCancelledError): await asyncio.wait_for(worker,15)
            assert list(Path(task.output_dir).glob('*.part'))
    finally:
        task.pause_event.set();await engine.shutdown()

@pytest.mark.asyncio
async def test_completed_recording_probe_failure_preserves_file(local_hls,monkeypatch):
    from app.engine.conductor import Conductor
    from app.engine.pipeline import YtdlpLivePipeline,RecordingState
    import app.engine.media_inspection as inspection
    _,directory=local_hls;file=directory/'저장된 파일.ts';file.write_bytes(b'preserved')
    conductor=Conductor();conductor.add_channel('alice',platform=Platform.CIME,auto_record=False)
    task=conductor._channels['cime:alice'];pipe=YtdlpLivePipeline('alice')
    pipe._state=RecordingState.COMPLETED;pipe._output_path=str(file);pipe._source_files=[str(file)];task.pipeline=pipe
    monkeypatch.setattr(inspection,'probe_media',lambda path:(_ for _ in ()).throw(RuntimeError('검사 실패')))
    await conductor._stop_recording('cime:alice')
    assert pipe.state==RecordingState.COMPLETED
    assert file.read_bytes()==b'preserved'

def test_cime_actual_uhd_master_for_1440p_without_fixed_cookie_gate():
    from app.engine.cime import playback_url
    item={'playback':{'url':'https://cdn.example/hd.m3u8','urlUhd':'https://cdn.example/uhd.m3u8','canWatchUhd':True}}
    assert playback_url(item,quality='1440p60').endswith('/uhd.m3u8')
    assert playback_url(item,quality='720p').endswith('/hd.m3u8')

def test_streamlink_master_selects_requested_fps(local_hls):
    from app.engine.pipeline import YtdlpLivePipeline
    base,directory=local_hls
    (directory/'fps.m3u8').write_text('#EXTM3U\n#EXT-X-STREAM-INF:RESOLUTION=1920x1080,BANDWIDTH=6000000,FRAME-RATE=60\n1080/index.m3u8\n#EXT-X-STREAM-INF:RESOLUTION=1920x1080,BANDWIDTH=4000000,FRAME-RATE=30\n720/index.m3u8\n')
    session,stream=YtdlpLivePipeline._create_streamlink_stream(base+'/fps.m3u8',{},None,0,False,'1080p30',source_page_url='https://ci.me/@alice/live')
    try: assert stream.url.endswith('/720/index.m3u8'), 'Manifest selection follows requested 30fps, not highest bitrate'
    finally: session.http.close()

@pytest.mark.asyncio
async def test_preview_timeout_kills_and_reaps_process(monkeypatch):
    from app.engine.preview_frames import FramePreviewService
    preview=FramePreviewService();engine=type('Engine',(),{})()
    engine.get_qualities=AsyncMock(return_value=[])
    engine.resolve_stream=AsyncMock(return_value=('https://cdn.example/live.m3u8',{},None))
    class Process:
        returncode=None; killed=False; reaped=False
        async def communicate(self):
            if self.killed: self.reaped=True; return b'',b''
            await asyncio.sleep(30)
        def kill(self): self.killed=True;self.returncode=-9
    proc=Process();monkeypatch.setattr(asyncio,'create_subprocess_exec',AsyncMock(return_value=proc))
    original=asyncio.wait_for
    async def fast_wait(awaitable,timeout): return await original(awaitable,.01 if timeout==25 else timeout)
    monkeypatch.setattr(asyncio,'wait_for',fast_wait)
    with pytest.raises(asyncio.TimeoutError): await preview.get_frame('soop:timeout','soop','timeout',engine)
    assert proc.killed and proc.reaped

@pytest.mark.asyncio
async def test_actual_mixed_platform_download_queue_concurrency_and_restore(local_hls,monkeypatch,tmp_path):
    from app.engine.cime_extractor import CimeIE
    from yt_dlp.extractor.afreecatv import AfreecaTVIE
    from app.engine.vod import VodEngine,VodDownloadState
    base,_=local_hls
    monkeypatch.setattr(CimeIE,'_router',lambda self,route:{'id':'1','title':'씨미 큐','duration':3000,'playback':{'url':base+'/720/index.m3u8'}})
    monkeypatch.setattr(AfreecaTVIE,'_real_extract',lambda self,url:{'id':'123','title':'숲 큐','duration':3,'formats':[{'url':base+'/720/index.m3u8','format_id':'hls','ext':'mp4','protocol':'m3u8_native','vcodec':'h264','acodec':'aac'}]})
    get_settings().vod_max_concurrent=1;get_settings().cime_cookie_file=None;get_settings().soop_cookie_file=None
    engine=VodEngine();loop=asyncio.get_running_loop();paused=asyncio.Event();original=engine._make_progress_callback
    def wrap(task):
        callback=original(task);first=True
        def progress(data):
            nonlocal first
            if first and 'ci.me' in task.url and data.get('status')=='downloading':
                first=False;engine.pause_download(task.task_id);loop.call_soon_threadsafe(paused.set)
            callback(data)
        return progress
    monkeypatch.setattr(engine,'_make_progress_callback',wrap)
    first=await engine.download('https://ci.me/@alice/vods/1',output_dir=str(tmp_path/'mixed'))
    second=await engine.download('https://vod.sooplive.co.kr/player/123',output_dir=str(tmp_path/'mixed'))
    try:
        await asyncio.wait_for(paused.wait(),15)
        assert engine._tasks[second].state==VodDownloadState.IDLE
        assert engine._tasks[second].url=='https://vod.sooplive.com/player/123'
        engine.resume_download(first)
        await asyncio.wait_for(asyncio.gather(engine._tasks[first].download_task,engine._tasks[second].download_task),30)
        assert all(engine._tasks[key].state==VodDownloadState.COMPLETED for key in (first,second))
        restored=VodEngine()
        assert restored.get_task_status(first)['platform']=='cime' and restored.get_task_status(second)['platform']=='soop'
        await restored.shutdown()
    finally:
        engine._tasks[first].pause_event.set();await engine.shutdown()

@pytest.mark.asyncio
async def test_actual_cime_progressive_clip_download(local_hls,monkeypatch,tmp_path):
    from app.engine.cime_extractor import CimeIE
    from app.engine.vod import VodEngine,VodDownloadTask,VodDownloadState
    base,directory=local_hls;video=directory/'clip.mp4'
    subprocess.run([shutil.which('ffmpeg'),'-y','-v','error','-i',str(directory/'720/index.m3u8'),'-c','copy',str(video)],check=True)
    monkeypatch.setattr(CimeIE,'_router',lambda self,route:{'id':'1','title':'씨미 클립','duration':3000,'playback':{'url':base+'/clip.mp4'}})
    get_settings().cime_cookie_file=None;get_settings().vod_format='mp4'
    engine=VodEngine();info=await engine.get_video_info('https://ci.me/clips/1')
    assert info['formats'][0]['format_id']=='source' and info['formats'][0].get('height') is None
    task=VodDownloadTask(url='https://ci.me/clips/1',output_dir=str(tmp_path/'클립'),quality='source')
    Path(task.output_dir).mkdir();engine._tasks[task.task_id]=task
    await engine._download_external(task.task_id,task)
    assert task.state==VodDownloadState.COMPLETED and task.inspection_state=='passed'
    await engine.shutdown()

@pytest.mark.asyncio
async def test_actual_recording_refreshes_expired_stream_url(local_hls):
    from app.engine.pipeline import YtdlpLivePipeline,RecordingState
    base,directory=local_hls;calls=0
    get_settings().live_format='ts';pipeline=YtdlpLivePipeline('expired')
    async def resolve(quality):
        nonlocal calls
        calls+=1
        return base+('/expired.m3u8' if calls==1 else '/720/index.m3u8'),{},None
    path=await pipeline.start_recording(stream_obj='https://ci.me/@expired/live',output_dir=str(directory/'재연결'),quality='720p',source_resolver=resolve)
    for _ in range(120):
        if pipeline._feeder_task.done():break
        await asyncio.sleep(.1)
    await pipeline.stop_recording()
    assert calls>=2 and pipeline.state==RecordingState.COMPLETED and Path(path).stat().st_size>0

@pytest.mark.asyncio
async def test_actual_cime_external_audio_master_recording(local_hls):
    from app.engine.pipeline import YtdlpLivePipeline,RecordingState
    from app.engine.media_inspection import probe_media
    base,directory=local_hls;ffmpeg=shutil.which('ffmpeg')
    for name,flag in [('video','-an'),('audio','-vn')]:
        folder=directory/name;folder.mkdir()
        subprocess.run([ffmpeg,'-y','-v','error','-i',str(directory/'720/index.m3u8'),flag,'-c','copy','-f','hls','-hls_time','1','-hls_list_size','0',str(folder/'index.m3u8')],check=True)
    (directory/'separate.m3u8').write_text('#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="audio",DEFAULT=YES,URI="audio/index.m3u8"\n#EXT-X-STREAM-INF:RESOLUTION=1280x720,BANDWIDTH=2000000,FRAME-RATE=5,AUDIO="audio"\nvideo/index.m3u8\n')
    get_settings().live_format='mp4';pipeline=YtdlpLivePipeline('separate')
    async def resolve(quality):return base+'/separate.m3u8',{},None
    path=await pipeline.start_recording(stream_obj='https://ci.me/@separate/live',output_dir=str(directory/'별도 음성'),quality='720p5',source_resolver=resolve)
    for _ in range(150):
        if pipeline._feeder_task.done():break
        await asyncio.sleep(.1)
    await pipeline.stop_recording()
    assert pipeline.state==RecordingState.COMPLETED
    media=await asyncio.to_thread(probe_media,path)
    assert media['streams']=={'video'} and media['duration']>1
    assert len(pipeline._source_files)==2
    audio=await asyncio.to_thread(probe_media,pipeline._source_files[1])
    assert audio['streams']=={'audio'}
    from app.engine.recording_finalizer import RecordingFinalizer
    from types import SimpleNamespace
    from tests.test_recording_finalization import terminal
    manager=RecordingFinalizer()
    try:
        job_id=manager.register_capture('cime:separate',pipeline,SimpleNamespace(platform=Platform.CIME,channel_id='separate',channel_name='Separate audio'),{'output_format':'mp4','keep_source_ts':True})
        await manager.capture_finished(job_id,pipeline)
        job=await terminal(manager,job_id)
        assert job['state']=='completed',job
        assert probe_media(job['output_path'])['streams']=={'video','audio'}
    finally:await manager.close()

