import asyncio
from unittest.mock import AsyncMock, Mock
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.config import get_settings
from app.engine.vod import VodEngine, VodDownloadState, VodDownloadTask
from app.engine.vod_preparation import canonical_prepared_url
from tests.test_chzzk_cdn import mock_media_server, DEFAULT_HOST

VIDEO = 'dQw4w9WgXcQ'
URL = f'https://www.youtube.com/watch?v={VIDEO}'

@pytest.mark.parametrize('url', [VIDEO, f'https://youtu.be/{VIDEO}', URL+'&list=example', f'https://youtube.com/shorts/{VIDEO}'])
def test_youtube_video_queue_canonicalization(url):
    assert canonical_prepared_url(url, 'youtube') == URL

@pytest.mark.parametrize('url', ['file:///etc/passwd', 'https://user:pass@example.com/video', 'https://twitcasting.tv/channel'])
def test_external_queue_rejects_unsupported_urls(url):
    with pytest.raises(ValueError): canonical_prepared_url(url, 'external')

def test_youtube_collection_uses_existing_immediate_import():
    with pytest.raises(ValueError, match='채널'):
        canonical_prepared_url('https://youtube.com/@channel', 'youtube')

@pytest.mark.asyncio
async def test_external_queue_metadata_deduplication_and_storage(monkeypatch, tmp_path):
    settings = get_settings()
    settings.vod_download_dir = ''
    settings.split_download_dirs = True
    settings.vod_external_dir = str(tmp_path / 'external')
    settings.vod_chzzk_dir = str(tmp_path / 'chzzk')
    engine = VodEngine()
    monkeypatch.setattr(engine, 'get_video_info', AsyncMock(return_value={
        'title': 'External video', 'duration': 120, 'id': VIDEO, 'formats': [{'height': 1080, 'vcodec': 'avc1'}],
    }))
    result = engine.prepare_vods([URL, f'https://youtu.be/{VIDEO}'], source='youtube')
    assert result['results'][1]['duplicate']
    await asyncio.gather(*list(engine._metadata_tasks))
    task = engine._tasks[result['results'][0]['task_id']]
    assert task.phase == 'ready' and task.quality == '1080p'
    assert task.output_dir == str(tmp_path / 'external')
    assert task.metadata['duration'] == 120
    result = engine.prepare_vods(['file:///unsupported', 'https://example.com/video.mp4'], source='external')
    assert 'error' in result['results'][0]
    await asyncio.gather(*list(engine._metadata_tasks))
    assert engine._tasks[result['results'][1]['task_id']].phase == 'ready'

@pytest.mark.parametrize('phase', ['merging', 'verifying', 'processing'])
def test_postprocessing_cannot_be_paused(phase):
    engine = VodEngine()
    task = VodDownloadTask(url=URL, state=VodDownloadState.DOWNLOADING, phase=phase)
    engine._tasks[task.task_id] = task
    assert 'error' in engine.pause_download(task.task_id)
    assert task.state == VodDownloadState.DOWNLOADING and task.pause_event.is_set()

def test_capabilities_and_completed_file_open(monkeypatch, tmp_path):
    path = tmp_path / '한글 영상 [1080p].mp4'
    path.write_bytes(b'actual-test-file')
    service = Mock()
    service.get_vod_task_status.return_value = {'state': 'completed', 'output_path': str(path)}
    monkeypatch.setattr('app.main.get_recorder_service', lambda: service)
    client = TestClient(app)
    assert [source['id'] for source in client.get('/api/vod/capabilities').json()['sources']] == ['chzzk', 'youtube', 'soop', 'cime', 'external']
    response = client.get('/api/vod/completed/file')
    assert response.status_code == 200 and response.content == path.read_bytes()
    assert response.headers['content-disposition'].startswith('inline')
    service.get_vod_task_status.return_value = {'state': 'downloading', 'output_path': str(path)}
    assert client.get('/api/vod/completed/file').status_code == 409
    service.get_vod_task_status.return_value = {'state': 'completed', 'output_path': str(tmp_path / 'missing.mp4')}
    assert client.get('/api/vod/completed/file').status_code == 404
    service.get_vod_task_status.return_value = {'error': 'unknown task'}
    assert client.get('/api/vod/unknown/file').status_code == 404


@pytest.mark.asyncio
async def test_actual_external_mp4_queue_start_and_file_inspection(mock_media_server, tmp_path):
    settings = get_settings()
    settings.vod_download_dir = str(tmp_path / '다운로드 폴더 [검증]')
    settings.vod_default_quality = '1080p'
    engine = VodEngine()
    result = engine.prepare_vods([f'https://{DEFAULT_HOST}/sample.mp4'], source='external')
    await asyncio.gather(*list(engine._metadata_tasks))
    task = engine._tasks[result['results'][0]['task_id']]
    assert task.phase == 'ready' and task.quality == 'best'
    engine.start_prepared(task.task_id)
    await asyncio.wait_for(task.download_task, timeout=60)
    assert task.state == VodDownloadState.COMPLETED
    from pathlib import Path
    assert Path(task.output_path).stat().st_size > 0
    assert task.inspection_state == 'passed'
    assert engine._probe_media_info(task.output_path)['streams'] == {'audio', 'video'}


def test_all_advertised_video_qualities_are_available():
    from app.engine.vod_preparation import quality_options
    heights = [144, 360, 480, 720, 1080, 1440, 2160]
    info = {'formats': [{'height': height, 'vcodec': 'avc1'} for height in heights] + [{'height': 720, 'vcodec': 'none'}]}
    assert [option['value'] for option in quality_options(info)] == [f'{height}p' for height in reversed(heights)]
