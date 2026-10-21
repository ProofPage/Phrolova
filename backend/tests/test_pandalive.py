"""PandaTV API, scoped authentication, HLS selection and recording integration."""
import asyncio
import copy
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
from app.engine.pandalive import PandaliveLiveEngine, normalize_pandalive_channel_id, _media_url
from app.engine.platform_auth import platform_cookie_jar
from app.engine.preview_proxy import PreviewProxy
from app.engine.recording_errors import RecordingError
from tests.test_new_platforms import local_hls

PAGE='https://www.pandalive.co.kr/play/fixture'
MEDIA='https://fixture.playback.live-video.net/master.m3u8?token=fixture-secret'
MEMBER={'result':True,'bjInfo':{'id':'fixture','idx':42,'nick':'팬더 테스트','thumbUrl':'https://cdn.pandalive.co.kr/avatar.png'}}
PLAY={'result':True,'media':{'userId':'fixture','userIdx':42,'title':'테스트 방송','isLive':True,'isPw':False,'user':123,
    'startTime':'2026-10-16 12:00:00','category':'ind'},'PlayList':{'hls':[{'url':MEDIA}],'hls2':[{'url':MEDIA}]}}


def mock_api(monkeypatch, member=None, play=None, status=200):
    calls=[];original=httpx.AsyncClient
    def route(request):
        calls.append(request)
        if request.url.path.endswith('/member/bj'):
            return httpx.Response(200,json=MEMBER if member is None else member)
        return httpx.Response(status,json=PLAY if play is None else play)
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(route),**kw))
    return calls


@pytest.mark.parametrize('value',['fixture',' FIXTURE ','https://www.pandalive.co.kr/play/FIXTURE?from=home#top',
    'http://pandalive.co.kr:80/play/fixture/','https://www.pandalive.co.kr:443/play/%66ixture'])
def test_channel_urls_normalize(value):
    assert normalize_pandalive_channel_id(value)=='fixture'


@pytest.mark.parametrize('value',['','https://www.pandalive.co.kr/','https://www.pandalive.co.kr/play/fixture/other',
    'https://www.pandalive.co.kr.evil/play/fixture','https://@www.pandalive.co.kr/play/fixture',
    'https://u:p@www.pandalive.co.kr/play/fixture','https://www.pandalive.co.kr:444/play/fixture',
    'https://www.pandalive.co.kr\\@evil/play/fixture','https://127.0.0.1/play/fixture',
    'file://www.pandalive.co.kr/play/fixture','fixture\nother','한글'])
def test_invalid_channel_urls_never_reach_api(value):
    with pytest.raises(ValueError):normalize_pandalive_channel_id(value)


@pytest.mark.asyncio
async def test_status_identity_cache_and_private_fields(monkeypatch):
    calls=mock_api(monkeypatch);engine=PandaliveLiveEngine()
    first=await engine.check_live_status('fixture');second=await engine.check_live_status('fixture')
    assert first==second and first['is_live'] and first['viewer_count']==123
    assert first['live_started_at']=='2026-10-16T12:00:00+09:00'
    assert 'PlayList' not in first and 'token' not in str(first)
    assert len(calls)==2 and calls[0].content==b'userId=fixture'
    assert calls[1].content==b'action=watch&userId=42'
    assert all(r.headers['origin']=='https://www.pandalive.co.kr' and r.headers['referer']==PAGE for r in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize('message',['본인인증이 필요합니다.','성인 인증이 필요합니다.','로그인해 주세요.'])
async def test_actual_400_identity_verification_is_not_offline_or_retryable(monkeypatch,message):
    mock_api(monkeypatch,play={'result':False,'message':message},status=400)
    with pytest.raises(RecordingError) as caught:await PandaliveLiveEngine().check_live_status('fixture')
    assert caught.value.code=='pandalive_authentication' and not caught.value.retryable
    assert '설정 → 인증' in str(caught.value)


@pytest.mark.asyncio
async def test_explicit_ended_broadcast_is_offline(monkeypatch):
    mock_api(monkeypatch,play={'result':False,'message':'방송이 종료되었습니다.'},status=400)
    engine=PandaliveLiveEngine();status=await engine.check_live_status('fixture')
    assert status['is_live'] is False and status['viewer_count']==0
    assert await engine.get_qualities('fixture')==[]


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['wrong_member','bad_idx','wrong_media','bad_live','password','adult','banned','unknown_denial'])
async def test_mismatched_or_restricted_responses_do_not_start_capture(monkeypatch,change):
    member,play=copy.deepcopy(MEMBER),copy.deepcopy(PLAY)
    if change=='wrong_member':member['bjInfo']['id']='other'
    elif change=='bad_idx':member['bjInfo']['idx']=True
    elif change=='wrong_media':play['media']['userId']='other'
    elif change=='bad_live':play['media']['isLive']='false'
    elif change=='password':play['media']['isPw']=True
    elif change=='adult':play['adultOut']=True
    elif change=='banned':play['roomBanInfo']={'enable':True}
    elif change=='unknown_denial':play={'result':False,'message':'unknown failure'}
    mock_api(monkeypatch,member,play)
    with pytest.raises(RecordingError):await PandaliveLiveEngine().check_live_status('fixture')


@pytest.mark.asyncio
@pytest.mark.parametrize('status,code,retryable',[(401,'pandalive_authentication',False),(403,'pandalive_authentication',False),
    (404,'pandalive_not_found',False),(429,'pandalive_rate_limit',True),(500,'pandalive_connection',True)])
async def test_http_failures_have_stable_retry_policy(monkeypatch,status,code,retryable):
    mock_api(monkeypatch,play={'result':False},status=status)
    with pytest.raises(RecordingError) as caught:await PandaliveLiveEngine().check_live_status('fixture')
    assert caught.value.code==code and caught.value.retryable is retryable


@pytest.mark.parametrize('url',['https://127.0.0.1/a','https://live-video.net.evil/a','http://a.live-video.net/a',
    'https://u:p@a.live-video.net/a','https://a.live-video.net:444/a','https://a.live-video.net/a#frag',None])
def test_media_host_boundaries(url):
    assert not _media_url(url)


@pytest.mark.asyncio
async def test_streamlink_qualities_scope_selection_and_cache(monkeypatch):
    from streamlink.stream.hls import HLSStream
    calls=mock_api(monkeypatch);seen=[]
    def parse(session,url,**kw):
        seen.append((url,kw));assert session.get_option('http-timeout')==12
        return {f'{h}p':SimpleNamespace(to_url=lambda h=h:MEDIA.replace('master',str(h))) for h in (1080,720)}
    monkeypatch.setattr(HLSStream,'parse_variant_playlist',parse)
    engine=PandaliveLiveEngine()
    qualities=await engine.get_qualities('fixture')
    assert [q['value'] for q in qualities]==['1080p','720p']
    assert 'fixture-secret' not in str(qualities)
    assert '1080' in (await engine.resolve_stream('fixture','best'))[0]
    assert '720' in (await engine.resolve_stream('fixture','720p'))[0]
    assert '720' in (await engine.resolve_stream('fixture','worst'))[0]
    assert await engine.get_preview_url('fixture')==(await engine.resolve_stream('fixture','best'))[0]
    with pytest.raises(RecordingError,match='화질'):await engine.resolve_stream('fixture','2160p')
    assert len(calls)==2 and len(seen)==1 and seen[0][1]['headers']['Referer']==PAGE


def test_registration_persistence_cookie_isolation_and_live_only_capabilities(monkeypatch,tmp_path):
    import app.main
    from app.api import platforms,stream,vod
    from app.core.logger import get_media_logger
    from app.engine.pandalive import PandaliveLiveEngine
    conductor=Conductor()
    service=SimpleNamespace(_conductor=conductor,add_platform_channel=Mock(return_value={'status':'added'}))
    monkeypatch.setattr(app.main,'get_recorder_service',lambda:service)
    monkeypatch.setattr(platforms,'_COOKIE_SAVE_PATH',tmp_path/'platform.txt')
    app=FastAPI();app.include_router(platforms.router);app.include_router(vod.router)
    with TestClient(app) as client:
        response=client.post('/api/platforms/channels',json={'platform':'pandalive','channel_id':PAGE,'recording_quality':'720p'})
        assert response.status_code==200 and service.add_platform_channel.call_args.kwargs['channel_id']=='fixture'
        assert service.add_platform_channel.call_args.kwargs['recording_quality']=='720p'
        assert client.get('/api/platforms/status').json()['pandalive']['enabled']
        assert 'pandalive' not in {s['id'] for s in client.get('/api/vod/capabilities').json()['sources']}
        cookies=b'# Netscape HTTP Cookie File\n.pandalive.co.kr\tTRUE\t/\tTRUE\t0\tsession\tfixture-secret\n.evil.example\tTRUE\t/\tTRUE\t0\tsession\tother-secret\n'
        response=client.post('/api/platforms/pandalive/cookie',files={'file':('cookies.txt',cookies)})
        assert response.status_code==200 and response.json()['configured'] and not response.json()['valid'] and 'fixture-secret' not in response.text
        session=requests.Session();session.cookies.update(platform_cookie_jar('pandalive'))
        assert 'fixture-secret' in session.prepare_request(requests.Request('GET','https://api.pandalive.co.kr/')).headers['Cookie']
        for host in ('https://a.playback.live-video.net/','https://pandalive.co.kr.evil/','https://evil.example/'):
            assert 'Cookie' not in session.prepare_request(requests.Request('GET',host)).headers
        session.close()
        assert client.delete('/api/platforms/pandalive/cookie').status_code==200
    assert isinstance(conductor._get_engine(Platform.PANDALIVE),PandaliveLiveEngine)
    assert isinstance(PandaliveLiveEngine(),PlatformEngine)
    assert stream._to_composite_key('pandalive:fixture')=='pandalive:fixture'
    assert get_media_logger(PAGE).name=='phrolova.pandalive'


def test_preview_opaque_urls_and_platform_cdn_boundary():
    proxy=PreviewProxy();token=proxy.register('pandalive:fixture','pandalive',MEDIA)
    body=proxy.rewrite(proxy.nodes[token],'#EXTM3U\nhttps://other.playback.live-video.net/part.ts?token=secret\n')
    assert 'token=secret' not in body and '/api/stream/preview-media/' in body
    assert not proxy.allowed('https://a.googlevideo.com/a',{''},'pandalive')
    assert not proxy.allowed('http://a.live-video.net/a',{''},'pandalive')


@pytest.mark.parametrize('target',['https://other.playback.live-video.net/part.ts?token=secret','next.ts?token=secret'])
def test_low_latency_prefetch_urls_are_opaque_and_scoped(target):
    proxy=PreviewProxy();token=proxy.register('pandalive:fixture','pandalive',MEDIA)
    result=proxy.rewrite(proxy.nodes[token],'#EXTM3U\n#EXT-X-PREFETCH:'+target+'\n')
    assert '#EXT-X-PREFETCH:/api/stream/preview-media/' in result
    assert 'token=secret' not in result and 'https://' not in result
    assert any(node['url'].endswith('token=secret') for node in proxy.nodes.values())


@pytest.mark.parametrize('target',['https://127.0.0.1/private','https://evil.example/part.ts',
    'http://other.playback.live-video.net/part.ts'])
def test_low_latency_prefetch_cannot_contact_unrelated_origins(target):
    proxy=PreviewProxy();token=proxy.register('pandalive:fixture','pandalive',MEDIA)
    with pytest.raises(ValueError):proxy.rewrite(proxy.nodes[token],'#EXTM3U\n#EXT-X-PREFETCH:'+target+'\n')


@pytest.mark.asyncio
async def test_actual_streamlink_capture_and_finalizer(local_hls,monkeypatch):
    from app.engine.pipeline import YtdlpLivePipeline
    from app.engine.media_inspection import probe_media
    from app.engine.recording_finalizer import RecordingFinalizer
    from tests.test_recording_finalization import terminal
    base,directory=local_hls
    engine=PandaliveLiveEngine()
    monkeypatch.setattr(engine,'_streams',AsyncMock(return_value=[{'value':'720p','label':'720p','url':base+'/720/index.m3u8','height':720,'fps':5,'bitrate':1}]))
    pipeline=YtdlpLivePipeline('fixture');manager=RecordingFinalizer()
    try:
        await pipeline.start_recording(stream_obj=PAGE,output_dir=str(directory/'panda'),quality='720p',source_resolver=lambda q:engine.resolve_stream('fixture',q))
        await asyncio.wait_for(asyncio.shield(pipeline._feeder_task),15)
        await pipeline.stop_recording()
        job_id=manager.register_capture('pandalive:fixture',pipeline,
            SimpleNamespace(platform=Platform.PANDALIVE,channel_id='fixture',channel_name='PandaTV'),{'output_format':'mkv','keep_source_ts':True})
        await manager.capture_finished(job_id,pipeline);job=await terminal(manager,job_id)
        assert job['state']=='completed' and job['inspection_state']=='passed'
        media=probe_media(job['output_path'])
        assert media['streams']=={'video','audio'} and media['duration']>1
        assert next(t for t in media['tracks'] if t['codec_type']=='video')['height']==720
    finally:
        await pipeline.stop_recording();await manager.close()
