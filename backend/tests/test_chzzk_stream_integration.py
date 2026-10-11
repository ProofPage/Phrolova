"""Phrolova-specific source policy, native capture and file-boundary contracts."""

import asyncio
import base64
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from streamlink import Streamlink

from app.core.config import get_settings
from app.engine.chzzk_continuity import SourcePath
from app.engine.chzzk_continuity_events import EVENT_PREFIX, parse_event
from app.engine.chzzk_stream import ChzzkHLSStream, source_paths
from app.engine.chzzk_time_machine import _media_path
from app.engine.pipeline import RecordingState, YtdlpLivePipeline
from tests.test_chzzk_continuity import CDN, INITIALIZATION, MEDIA, START


def media(url, mode='HLS', **kwargs):
    return dict(mediaId=mode, protocol='HLS', path=url, **kwargs)


def test_domestic_llhls_and_explicit_akamai_selection():
    korean='https://nvelop-livecloud.pstatic.net/ll/master.m3u8'
    akamai='https://livecloud.akamaized.net/master.m3u8'
    items=[media(akamai), media(korean, 'LLHLS'), media(korean.replace('/ll/', '/hls/'))]
    assert _media_path(items)==korean
    assert _media_path(items, 'akamai')==akamai
    paths=source_paths(items)
    assert [(p.cdn,p.mode) for p in paths[:2]]==[('korean','llhls'),('korean','hls')]


def test_standby_mapping_preserves_signature_and_rejects_untrusted_history():
    url='https://nvelop-livecloud.pstatic.net/live/master.m3u8?sig=a%2Fb%20c&token=x'
    encoded=base64.b64encode(b'https://evil.example/history.m3u8').decode()
    paths=source_paths([media(url,'LLHLS',encodingTrack=[{'p2pPath':'https://p2p.example/?cdn_url='+encoded}])])
    assert len(paths)==2 and paths[1].probe
    assert paths[1].url==url.replace('nvelop-livecloud.pstatic.net','livecloud.akamaized.net')
    for origin in ('https://nvelop-livecloud.pstatic.net.evil.example/live', 'https://u:p@livecloud.pstatic.net/live','http://livecloud.pstatic.net/live','https://[bad'):
        assert source_paths([media(origin)])==[]


def test_safe_event_allowlist_and_runtime_state():
    event=dict(version=1,kind='source',live_id=1,rendition='1080p',cdn='akamai',mode='llhls',state='ready',url='https://secret.example/?token=x',cookie='secret')
    safe=parse_event(EVENT_PREFIX+json.dumps(event))
    assert 'url' not in safe and 'cookie' not in safe
    pipe=YtdlpLivePipeline('test')
    pipe._accept_continuity_event(event)
    assert pipe.get_status()['continuity_source']['standby']==dict(cdn='akamai',mode='llhls',state='ready')
    for i in range(100):
        pipe._accept_continuity_event(event)
    assert len(pipe.continuity_events)==64
    assert 'secret' not in json.dumps(pipe.get_status())


def test_api_cookie_only_on_api_and_selected_time_machine_stays_primary(monkeypatch):
    session=Streamlink(plugins_builtin=False)
    calls=[]
    current='https://nvelop-livecloud.pstatic.net/live/1080p/list.m3u8'
    historical='https://nvelop-livecloud.pstatic.net/history/1080p/list.m3u8'
    def get(url, **kwargs):
        calls.append((url,kwargs))
        if 'time-machine' in url:
            payload={'code':200,'content':{'playback':{'media':[media(historical)]}}}
        else:
            payload={'code':200,'content':{'status':'OPEN','liveId':1,'livePlaybackJson':json.dumps({'media':[media(current,'LLHLS')]})}}
        return SimpleNamespace(raise_for_status=lambda:None,json=lambda:payload)
    monkeypatch.setattr(session.http,'get',get)
    stream=ChzzkHLSStream(session,historical,'channel',api_cookie='NID_AUT=test; NID_SES=test',recording_time_machine=True)
    stream.initialize_sources()
    snapshot=stream._source_snapshot()
    assert snapshot[1][0].url==historical
    assert stream.continuity.primary.url==historical
    assert all('api.chzzk.naver.com' in url and args['headers']['Cookie']=='NID_AUT=test; NID_SES=test' for url,args in calls)
    assert 'Cookie' not in session.http.headers
    session.http.close()


@pytest.mark.asyncio
async def test_actual_streamlink_native_boundary_closes_and_resumes_new_file(tmp_path, monkeypatch):
    get_settings().chzzk_stream_mode='standard'
    with CDN() as cdn:
        cdn.playlist('primary',changed_map=2)
        paths=[SourcePath(cdn.url('primary'),cdn='korean')]
        monkeypatch.setattr(ChzzkHLSStream,'_source_snapshot',lambda self:(1,paths,True))
        async def resolve(quality):
            return cdn.url('primary'),{},None
        ended=[]
        first=YtdlpLivePipeline('fixture')
        first._on_capture_ended=AsyncMock(side_effect=lambda pipe:ended.append(pipe))
        await first.start_recording(stream_obj='https://chzzk.naver.com/live/fixture',output_dir=str(tmp_path),source_resolver=resolve)
        await first._feeder_task
        await asyncio.sleep(0)
        assert first.state==RecordingState.COMPLETED and first._closed
        assert first.end_reason=='continuity_boundary'
        assert first.capture_format=='fmp4' and ended==[first]
        assert Path(first.output_path).read_bytes()==INITIALIZATION+b''.join(MEDIA[:2])
        assert first.continuity_resume['from']==(START.replace(second=8)).isoformat()
        second=YtdlpLivePipeline('fixture')
        second.continuity_resume=first.continuity_resume
        await second.start_recording(stream_obj='https://chzzk.naver.com/live/fixture',output_dir=str(tmp_path),source_resolver=resolve)
        await second._feeder_task
        assert second.state==RecordingState.COMPLETED and second.output_path!=first.output_path
        assert Path(second.output_path).read_bytes().endswith(b''.join(MEDIA[2:]))
        assert Path(first.output_path).read_bytes()==INITIALIZATION+b''.join(MEDIA[:2])


@pytest.mark.asyncio
async def test_container_boundary_continues_auto_off_with_same_policy(monkeypatch):
    from app.engine.conductor import Conductor
    import app.engine.conductor as module
    conductor=Conductor()
    conductor._running=True
    conductor.add_channel('boundary',auto_record=False)
    task=conductor._channels['chzzk:boundary']
    task.is_live=True
    task.output_format='mp4'
    task.recording_quality='1080p'
    created=[]
    class FakePipeline:
        _intentional_stop=False
        _closed=True
        end_reason='continuity_boundary'
        state=RecordingState.IDLE
        def __init__(self,channel_id):
            self.continuity_resume=None
            created.append(self)
        async def start_recording(self,**kwargs):
            self.applied_quality=kwargs["quality"]
            self.state=RecordingState.RECORDING
        def get_status(self):
            return {'state':self.state.value,'is_recording':self.state==RecordingState.RECORDING}
    monkeypatch.setattr(module,'YtdlpLivePipeline',FakePipeline)
    sleep=asyncio.sleep
    async def wait(seconds):
        await sleep(0 if seconds==5 else seconds)
    monkeypatch.setattr(module.asyncio,'sleep',wait)
    try:
        await conductor._start_recording('chzzk:boundary')
        first=created[0]
        first.state=RecordingState.COMPLETED
        first.continuity_resume=dict(live_id=1,rendition='1080p',**{'from':START.isoformat()})
        task.output_format='mkv'  # Changed while capturing: next full session only.
        task.recording_quality='720p'
        await first._on_capture_ended(first)
        assert len(created)==2 and task.pipeline is created[1]
        assert created[1].continuity_resume==first.continuity_resume
        assert created[1].applied_quality=='1080p'
        assert not task.auto_record and not task.broadcast_ended
        # Inspect the registered callback closure: the capture policy is frozen.
        policy=next(cell.cell_contents for cell in created[1]._on_capture_started.__closure__ if isinstance(cell.cell_contents,dict) and 'output_format' in cell.cell_contents)
        assert policy['output_format']=='mp4'
    finally:
        await conductor.finalizer.close()



def test_membership_without_cookie_is_actionable_and_never_auto_retried(monkeypatch):
    from app.engine.chzzk_continuity import Unavailable
    from app.engine.recording_errors import classify_recording_error
    session=Streamlink(plugins_builtin=False)
    response=SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'code':200,'content':{'status':'OPEN','liveId':1,'membershipBenefitType':'MEMBER_ONLY'}})
    monkeypatch.setattr(session.http,'get',lambda *args,**kwargs:response)
    stream=ChzzkHLSStream(session,'https://livecloud.pstatic.net/live/1080p/list.m3u8','test')
    with pytest.raises(Unavailable) as error:
        stream.initialize_sources()
    failure=classify_recording_error(error.value)
    assert failure.code=='authentication' and not failure.retryable
    session.http.close()
