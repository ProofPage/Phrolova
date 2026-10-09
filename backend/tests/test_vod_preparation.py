import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.core.config import get_settings
from app.engine.vod import VodEngine, VodDownloadState, VodDownloadTask
from app.engine.vod_preparation import canonical_vod_url, quality_options

URL = 'https://chzzk.naver.com/video/123'
INFO = {'id':'123','title':'방송 제목','duration':123,'uploader':'스트리머',
        'thumbnail':'https://example.test/thumbnail.jpg','profile_image':'https://example.test/profile.jpg',
        'upload_date':'20261009', 'formats':[
            {'height':1080,'vcodec':'avc1','acodec':'none'},
            {'height':720,'vcodec':'avc1','acodec':'aac'},
            {'height':720,'vcodec':'avc1','acodec':'aac'},
            {'height':None,'vcodec':'none','acodec':'aac'}]}

async def drain(engine):
    await asyncio.gather(*list(engine._metadata_tasks))

@pytest.mark.parametrize('url',['http://127.0.0.1/video/123','https://chzzk.naver.com.evil/video/123',
    'file:///video/123','https://chzzk.naver.com:8888/video/123','https://user:secret@chzzk.naver.com/video/123',
    'https://chzzk.naver.com/live/123','https://chzzk.naver.com/video/123/../123',
    'https://chzzk.naver.com/video/123%2f','https://[broken','https://youtube.com/video/123'])
def test_new_prepare_scope_rejects_unsafe_urls(url):
    with pytest.raises(ValueError): canonical_vod_url(url)


def test_canonicalization_and_real_quality_options():
    assert canonical_vod_url(URL+'/?tracking=1#fragment') == URL
    assert quality_options(INFO) == [{'value':'1080p','label':'1080p'},{'value':'720p','label':'720p'}]

@pytest.mark.asyncio
async def test_batch_deduplicates_before_lookup_and_keeps_partial_success(monkeypatch):
    engine = VodEngine(); mock = AsyncMock(return_value=INFO)
    monkeypatch.setattr(engine,'get_video_info',mock)
    result=engine.prepare_vods([URL,URL+'?tracking=x','http://127.0.0.1/video/123'])
    assert result['results'][1]['duplicate']
    assert 'error' in result['results'][2]
    await drain(engine)
    assert mock.await_count == 1
    task=next(iter(engine._tasks.values()))
    assert task.phase=='ready' and task.download_task is None
    assert task.title==INFO['title'] and task.metadata['uploader']==INFO['uploader']
    assert task.quality=='1080p'

@pytest.mark.parametrize('preference,chosen',[('480p','720p'),('720p','720p'),('1440p','1080p'),('worst','720p')])
@pytest.mark.asyncio
async def test_quality_default_fallback(monkeypatch,preference,chosen):
    get_settings().vod_default_quality=preference
    engine=VodEngine();monkeypatch.setattr(engine,'get_video_info',AsyncMock(return_value=INFO))
    task_id=engine.prepare_vods([URL])['results'][0]['task_id'];await drain(engine)
    assert engine._tasks[task_id].quality==chosen
    engine.set_prepared_quality(task_id,'720p')
    with pytest.raises(ValueError):engine.set_prepared_quality(task_id,'480p')

@pytest.mark.asyncio
async def test_individual_lookup_failure_and_retry(monkeypatch):
    engine=VodEngine();monkeypatch.setattr(engine,'get_video_info',AsyncMock(side_effect=[ValueError('restricted'),INFO,INFO]))
    result=engine.prepare_vods([URL,'https://chzzk.naver.com/video/456']);await drain(engine)
    failed=engine._tasks[result['results'][0]['task_id']];good=engine._tasks[result['results'][1]['task_id']]
    assert failed.phase=='metadata_error' and good.phase=='ready'
    engine.retry_metadata(failed.task_id);await drain(engine)
    assert failed.phase=='ready' and failed.error_message is None

@pytest.mark.asyncio
async def test_prepared_history_reload_does_not_autostart(monkeypatch):
    engine=VodEngine();monkeypatch.setattr(engine,'get_video_info',AsyncMock(return_value=INFO))
    task_id=engine.prepare_vods([URL])['results'][0]['task_id'];await drain(engine)
    engine.set_prepared_quality(task_id,'720p')
    restored=VodEngine()._tasks[task_id]
    assert restored.phase=='ready' and restored.state==VodDownloadState.IDLE
    assert restored.quality=='720p' and restored.metadata['duration']==123
    assert restored.download_task is None

@pytest.mark.asyncio
async def test_start_snapshot_and_double_click_guard(monkeypatch):
    engine=VodEngine();monkeypatch.setattr(engine,'get_video_info',AsyncMock(return_value=INFO))
    monkeypatch.setattr(engine,'_run_download',AsyncMock())
    task_id=engine.prepare_vods([URL])['results'][0]['task_id'];await drain(engine)
    get_settings().chzzk_vod_cdn='akamai'
    engine.start_prepared(task_id)
    with pytest.raises(ValueError):engine.start_prepared(task_id)
    get_settings().chzzk_vod_cdn='default'
    assert engine._tasks[task_id].cdn=='akamai'
    await engine._tasks[task_id].download_task

@pytest.mark.asyncio
async def test_batch_uses_existing_concurrency_limit_and_queued_quality(monkeypatch):
    get_settings().vod_max_concurrent=1
    engine=VodEngine();monkeypatch.setattr(engine,'get_video_info',AsyncMock(return_value=INFO))
    urls=[URL,'https://chzzk.naver.com/video/456']
    ids=[r['task_id'] for r in engine.prepare_vods(urls)['results']];await drain(engine)
    gate=asyncio.Event();running=0;peak=0
    async def download(task_id,task):
        nonlocal running,peak
        running+=1;peak=max(peak,running)
        await gate.wait();task.state=VodDownloadState.COMPLETED;running-=1
    monkeypatch.setattr(engine,'_download_external',download)
    engine.start_prepared_batch(ids);await asyncio.sleep(.01)
    engine.set_prepared_quality(ids[1],'720p')
    with pytest.raises(ValueError):engine.set_prepared_quality(ids[0],'720p')
    assert engine._tasks[ids[1]].quality=='720p'
    gate.set();await asyncio.gather(*(engine._tasks[i].download_task for i in ids))
    assert peak==1

@pytest.mark.asyncio
async def test_delete_during_metadata_cannot_resurrect_and_keeps_files(monkeypatch,tmp_path):
    engine=VodEngine();gate=asyncio.Event()
    async def lookup(url):await gate.wait();return INFO
    monkeypatch.setattr(engine,'get_video_info',lookup)
    task_id=engine.prepare_vods([URL])['results'][0]['task_id'];await asyncio.sleep(0)
    path=tmp_path/'original.mp4';path.write_bytes(b'original')
    engine._tasks[task_id].output_path=str(path)
    engine.remove_vod_task(task_id);gate.set();await drain(engine)
    assert task_id not in engine._tasks and task_id not in VodEngine()._tasks
    assert path.read_bytes()==b'original'

@pytest.mark.asyncio
async def test_completed_only_cleanup_keeps_ready_queued_errors_and_files(monkeypatch,tmp_path):
    engine=VodEngine();monkeypatch.setattr(engine,'get_video_info',AsyncMock(return_value=INFO))
    task_id=engine.prepare_vods([URL])['results'][0]['task_id'];await drain(engine)
    path=tmp_path/'keep.mp4';path.write_bytes(b'keep')
    done=VodDownloadTask(state=VodDownloadState.COMPLETED,output_path=str(path))
    failed=VodDownloadTask(state=VodDownloadState.ERROR)
    engine._tasks.update({done.task_id:done,failed.task_id:failed})
    assert engine.clear_completed_tasks(completed_only=True)['deleted_count']==1
    assert task_id in engine._tasks and failed.task_id in engine._tasks
    assert path.read_bytes()==b'keep'

@pytest.mark.asyncio
async def test_selected_resolution_preserves_audio_and_retry_metadata(monkeypatch,tmp_path):
    engine=VodEngine();monkeypatch.setattr(engine,'get_video_info',AsyncMock(return_value=INFO))
    get_settings().vod_download_dir=str(tmp_path)
    task_id=engine.prepare_vods([URL])['results'][0]['task_id'];await drain(engine)
    engine.set_prepared_quality(task_id,'720p')
    monkeypatch.setattr('app.core.config.Settings.resolve_ffmpeg_path',lambda _:'ffmpeg')
    task=engine._tasks[task_id]
    assert engine._build_ytdlp_options(task)['format']=='bestvideo*[height=720]+bestaudio/best[height=720]'
    task.state=VodDownloadState.ERROR
    monkeypatch.setattr(engine,'_run_download',AsyncMock())
    new_id=await engine.retry_download(task_id);new=engine._tasks[new_id];await new.download_task
    assert new.prepared and new.quality=='720p' and new.metadata['id']=='123'


def test_new_prepare_api_validation_and_backward_download(api_client,monkeypatch):
    import app.main as main
    engine=main.get_recorder_service()._vod_engine
    monkeypatch.setattr(engine,'get_video_info',AsyncMock(return_value=INFO))
    assert api_client.post('/api/vod/prepare',json={'urls':[]}).status_code==422
    assert api_client.post('/api/vod/prepare',json={'urls':['file:///tmp/a']}).json()['results'][0]['error']
    response=api_client.post('/api/vod/prepare',json={'urls':[URL]});assert response.status_code==200
    task_id=response.json()['results'][0]['task_id']
    api_client.portal.call(drain,engine)
    assert api_client.patch(f'/api/vod/{task_id}/quality',json={'quality':'480p'}).status_code==409
    assert api_client.patch(f'/api/vod/{task_id}/quality',json={'quality':'720p'}).status_code==200
    assert api_client.delete(f'/api/vod/{task_id}').status_code==200
    assert api_client.get(f'/api/vod/status/{task_id}').status_code==404


@pytest.mark.asyncio
async def test_restart_interrupted_metadata_and_cancelled_job_are_safe(monkeypatch):
    engine=VodEngine()
    monkeypatch.setattr(engine,'_schedule_metadata',lambda _:None)
    task_id=engine.prepare_vods([URL])['results'][0]['task_id']
    restored=VodEngine()._tasks[task_id]
    assert restored.state==VodDownloadState.IDLE and restored.phase=='metadata_error'
    restored.cancel_flag=True;restored.phase='cancelled'
    engine._tasks[task_id]=restored;engine._save_history()
    cancelled=VodEngine()._tasks[task_id]
    assert cancelled.phase=='cancelled' and cancelled.cancel_flag


def test_no_available_quality_is_not_invented():
    assert quality_options({'formats':[{'vcodec':'none','height':720}]})==[]


@pytest.mark.asyncio
@pytest.mark.parametrize('cdn',['default','akamai'])
async def test_real_prepared_dash_resolution_download(mock_media_server,tmp_path,monkeypatch,cdn):
    import yt_dlp
    from yt_dlp.extractor.common import InfoExtractor
    from tests.test_chzzk_cdn import DEFAULT_HOST
    engine=VodEngine();get_settings().vod_format='mkv'
    def extract(self,url,download=False):
        formats=InfoExtractor(self)._extract_mpd_formats('https://apis.naver.com/sample.mpd','123')
        return {'id':'123','title':'synthetic','formats':formats,'extractor':'chzzk:video',
                'extractor_key':'CHZZKVideo','webpage_url':URL,'duration':2}
    monkeypatch.setattr(yt_dlp.YoutubeDL,'extract_info',extract)
    task=VodDownloadTask(url=URL,prepared=True,quality='90p',cdn=cdn,output_dir=str(tmp_path/'downloads'))
    engine._tasks[task.task_id]=task
    await engine._download_with_ytdlp(task.task_id,task,None)
    assert task.state==VodDownloadState.COMPLETED
    media=engine._probe_media_info(task.output_path)
    assert media['streams']=={'audio','video'} and 1.8<=media['duration']<=2.5


# Reuse the existing real FFmpeg/local CDN fixture, not another download engine.
from tests.test_chzzk_cdn import mock_media_server


@pytest.mark.asyncio
async def test_metadata_extracts_real_schema_fields(monkeypatch):
    import yt_dlp
    engine=VodEngine()
    monkeypatch.setattr(yt_dlp.YoutubeDL,'extract_info',lambda *_a,**_kw:{**INFO,'channel':'actual channel','uploader':'old uploader','channel_thumbnail':'https://example.test/profile.jpg'})
    info=await engine.get_video_info(URL)
    assert info['id']=='123' and info['uploader']=='actual channel'
    assert info['profile_image']=='https://example.test/profile.jpg' and info['upload_date']=='20261009'
    assert quality_options(info)==[{'value':'1080p','label':'1080p'},{'value':'720p','label':'720p'}]


def test_manifest_resolution_without_codec_remains_available():
    assert quality_options({'formats':[{'height':144}]})==[{'value':'144p','label':'144p'}]


def test_prepare_api_enforces_batch_and_url_size_limits(api_client):
    assert api_client.post('/api/vod/prepare',json={'urls':[URL]*101}).status_code==422
    assert api_client.post('/api/vod/prepare',json={'urls':[URL+'?'+('a'*2048)]}).status_code==422


@pytest.mark.asyncio
async def test_shutdown_does_not_relabel_already_cancelled_prepared_job():
    engine=VodEngine();task=VodDownloadTask(url=URL,prepared=True,cancel_flag=True,state=VodDownloadState.IDLE)
    engine._tasks[task.task_id]=task
    await engine.shutdown()
    restored=VodEngine()._tasks[task.task_id]
    assert restored.state==VodDownloadState.IDLE and restored.phase=='cancelled'
    assert restored.error_message is None


def test_prepare_during_shutdown_is_a_conflict_not_server_error(api_client):
    import app.main as main
    main.get_recorder_service()._vod_engine._shutting_down=True
    assert api_client.post('/api/vod/prepare',json={'urls':[URL]}).status_code==409
