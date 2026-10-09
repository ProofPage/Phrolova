"""실제 결함 입력과 종료 경쟁을 재현하는 회귀 검사."""
import asyncio
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from dotenv import dotenv_values
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.engine.vod import VodEngine, VodDownloadTask, VodDownloadState
from app.engine.conductor import Conductor
from app.engine.pipeline import RecordingState


def test_reorder_duplicates_cannot_drop_downloads():
    engine = VodEngine()
    a, b = VodDownloadTask(), VodDownloadTask()
    engine._tasks = {a.task_id: a, b.task_id: b}
    result = engine.reorder_tasks([a.task_id, a.task_id])
    assert 'error' in result
    assert list(engine._tasks) == [a.task_id, b.task_id]


@pytest.mark.asyncio
async def test_remove_channel_stops_pipeline_before_forgetting_it():
    conductor = Conductor()
    conductor.add_channel('abc')
    task = conductor._channels['chzzk:abc']
    pipe = Mock(state=RecordingState.RECORDING)
    async def stop():
        assert conductor._channels['chzzk:abc'] is task
        pipe.state = RecordingState.COMPLETED
    pipe.stop_recording = AsyncMock(side_effect=stop)
    pipe.get_status.return_value = {}
    task.pipeline = pipe
    await conductor.remove_channel('chzzk:abc')
    pipe.stop_recording.assert_awaited_once()
    assert 'chzzk:abc' not in conductor._channels


@pytest.mark.asyncio
async def test_shutdown_cleans_failed_pipeline_and_chat():
    conductor = Conductor()
    conductor.add_channel('abc')
    task = conductor._channels['chzzk:abc']
    task.pipeline = Mock(state=RecordingState.ERROR, stop_recording=AsyncMock())
    task.chat_archiver = Mock(stop=AsyncMock())
    task.pipeline.get_status.return_value = {}
    pipe, chat = task.pipeline, task.chat_archiver
    await conductor.stop()
    pipe.stop_recording.assert_awaited_once()
    chat.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_capture_clear_is_persisted(monkeypatch):
    import app.main as main
    from app.api.archive import router
    conductor = Conductor()
    from app.engine.base import Platform
    conductor.add_channel('tester', platform=Platform.X_SPACES)
    task = conductor._channels['x_spaces:tester']
    task.captured_m3u8_url = 'https://example.test/list.m3u8'
    conductor._save_capture_state('x_spaces:tester')
    monkeypatch.setattr(main, 'get_recorder_service', lambda: SimpleNamespace(_conductor=conductor))
    app = FastAPI(); app.include_router(router)
    response = TestClient(app).delete('/api/archive/spaces/captured/x_spaces:tester')
    assert response.status_code == 200
    assert Conductor()._channels['x_spaces:tester'].captured_m3u8_url is None


def test_youtube_composite_key_is_preserved():
    from app.api.stream import _to_composite_key
    assert _to_composite_key('youtube:@tester') == 'youtube:@tester'


def test_env_value_cannot_inject_another_setting(tmp_path, monkeypatch):
    import app.core.utils as utils
    path = tmp_path / '.env'
    monkeypatch.setattr(utils, '_get_env_path', lambda: path)
    value = 'token\nHOST=0.0.0.0'
    utils.update_env_file({'NID_AUT': value}, raise_on_error=True)
    result = dotenv_values(path)
    assert result['NID_AUT'] == value
    assert 'HOST' not in result


def test_env_duplicate_key_update_survives_reload(tmp_path, monkeypatch):
    import app.core.utils as utils
    path = tmp_path / '.env'
    path.write_bytes(b'DOWNLOAD_DIR=old\r\nDOWNLOAD_DIR=older\r\n')
    monkeypatch.setattr(utils, '_get_env_path', lambda: path)
    utils.update_env_file({'DOWNLOAD_DIR': 'new'}, raise_on_error=True)
    assert dotenv_values(path)['DOWNLOAD_DIR'] == 'new'
    assert b'\r\n' in path.read_bytes()


@pytest.mark.parametrize('filtered', [False, True])
def test_chat_skips_non_object_json_and_partial_tail(tmp_path, filtered):
    from app.api.chat import _read_messages
    path = tmp_path / 'chat.jsonl'
    path.write_bytes(b'null\n[]\n42\n{"nickname":null,"message":123}\n'
                     b'{"nickname":"user","message":"hello"}\n'
                     b'{"nickname":"user","message":"hello unfinished"}')
    messages, total = _read_messages(path, 1, 100, 'hello' if filtered else None)
    assert total == 1
    assert [m['message'] for m in messages] == ['hello']


def test_chat_file_download_rejects_non_chat_file(tmp_path):
    from app.api.chat import _resolve_and_validate, _encode_file_id
    from fastapi import HTTPException
    get_settings().download_dir = str(tmp_path)
    (tmp_path / 'private.txt').write_text('secret')
    with pytest.raises(HTTPException):
        _resolve_and_validate(_encode_file_id('private.txt'))


def test_external_browser_cannot_access_local_api():
    from app.main import app
    response = TestClient(app).get('/health', headers={'Origin': 'https://evil.example'})
    assert response.status_code == 403
    assert 'access-control-allow-origin' not in response.headers


@pytest.mark.asyncio
async def test_cancel_during_retry_backoff_finishes(monkeypatch):
    engine = VodEngine()
    task = VodDownloadTask(url='https://example.test/video', state=VodDownloadState.DOWNLOADING)
    engine._tasks[task.task_id] = task
    entered, released = asyncio.Event(), asyncio.Event()
    async def attempt(task_id):
        if task.cancel_flag:
            return False
        task.retry_count += 1
        return True
    async def delay(seconds):
        entered.set()
        await released.wait()
    monkeypatch.setattr(engine, '_attempt_download', attempt)
    monkeypatch.setattr('app.engine.vod.asyncio.sleep', delay)
    task.download_task = asyncio.create_task(engine._run_download(task.task_id))
    await entered.wait()
    engine.cancel_download(task.task_id)
    released.set()
    await task.download_task
    assert task.state != VodDownloadState.CANCELLING
    assert not task.downloaded_bytes


def test_mpd_patch_reimport_does_not_recurse():
    script = '''import importlib, xml.etree.ElementTree as ET
import app.engine.vod as vod
from yt_dlp.extractor.common import InfoExtractor
importlib.reload(vod)
from yt_dlp import YoutubeDL
list(InfoExtractor(YoutubeDL({'quiet': True}))._parse_mpd_periods(ET.fromstring('<MPD/>')))
'''
    result = subprocess.run([sys.executable, '-c', script], cwd=Path(__file__).parents[1], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr


def test_env_failed_replace_preserves_original(tmp_path, monkeypatch):
    import app.core.utils as utils
    path = tmp_path / '.env'; original = b'DOWNLOAD_DIR=keep\n'
    path.write_bytes(original)
    monkeypatch.setattr(utils, '_get_env_path', lambda: path)
    monkeypatch.setattr(utils.os, 'replace', Mock(side_effect=OSError('disk full')))
    with pytest.raises(OSError):
        utils.update_env_file({'DOWNLOAD_DIR': 'new'}, raise_on_error=True)
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]


def test_history_replace_rolls_back_all_changes():
    from app.store.repositories import VodRepository
    repo = VodRepository()
    repo.upsert('keep', {'title': 'original'})
    with pytest.raises(ValueError):
        repo.replace_all({'keep': {'title': 'changed'}, 'bad': {'progress': 'invalid'}})
    assert repo.list_all()[0]['title'] == 'original'
    assert len(repo.list_all()) == 1


@pytest.mark.asyncio
async def test_duplicate_live_start_keeps_one_pipeline(monkeypatch):
    import app.engine.conductor as module
    conductor = Conductor(); conductor.add_channel('abc'); conductor._running = True
    pipeline = Mock(state=RecordingState.IDLE)
    async def start(**kwargs):
        await asyncio.sleep(0.01)
        pipeline.state = RecordingState.RECORDING
    pipeline.start_recording = AsyncMock(side_effect=start)
    monkeypatch.setattr(module, 'YtdlpLivePipeline', Mock(return_value=pipeline))
    monkeypatch.setattr(conductor, '_start_chat_archiver', AsyncMock())
    await asyncio.gather(conductor._start_recording('chzzk:abc', is_retry=True), conductor._start_recording('chzzk:abc', is_retry=True))
    pipeline.start_recording.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancel_during_metadata_does_not_start_media_download(tmp_path, monkeypatch):
    import yt_dlp
    engine = VodEngine()
    task = VodDownloadTask(url='https://example.test/video', output_dir=str(tmp_path))
    engine._tasks[task.task_id] = task
    fake = Mock()
    fake.__enter__ = Mock(return_value=fake); fake.__exit__ = Mock()
    def extract(*args, **kwargs):
        task.cancel_flag = True
        return {'title': 'test', 'ext': 'mp4'}
    fake.extract_info.side_effect = extract
    monkeypatch.setattr(yt_dlp, 'YoutubeDL', Mock(return_value=fake))
    monkeypatch.setattr(engine, '_build_ytdlp_options', lambda *a, **kw: {})
    from app.engine.vod import DownloadCancelledError
    with pytest.raises(DownloadCancelledError):
        await engine._download_with_ytdlp(task.task_id, task, None)
    fake.process_ie_result.assert_not_called()


@pytest.mark.parametrize('url', ['file:///etc/passwd', '/etc/passwd', 'ftp://example.test/a', 'https://user:secret@example.test/a'])
def test_media_rejects_local_protocols_and_url_credentials(url):
    from app.engine.vod import NonRetryableDownloadError
    with pytest.raises(NonRetryableDownloadError):
        VodEngine._validate_media_url(url)


def test_generated_filename_has_no_control_characters(tmp_path):
    from app.core.utils import clean_filename
    path = tmp_path / clean_filename('a\x00b\r\nc.ts')
    path.write_bytes(b'content')
    assert '\n' not in path.name and '\r' not in path.name


def test_same_origin_and_cli_requests_remain_allowed():
    from app.main import app
    client = TestClient(app)
    assert client.get('/health').status_code == 200
    assert client.get('/health', headers={'Origin': 'http://testserver'}).status_code == 200
    assert client.get('/health', headers={'Origin': 'http://localhost:3000'}).status_code == 200
    assert client.post('/api/tags', json={'name': 'blocked'}, headers={'Origin': 'https://evil.example'}).status_code == 403
    assert client.get('/api/tags').json()['tags'] == []


@pytest.mark.asyncio
async def test_ffmpeg_stderr_is_drained_while_child_runs(tmp_path, monkeypatch):
    from app.engine.pipeline import FFmpegPipeline
    # 실제 subprocess가 파이프 버퍼보다 큰 출력을 써도 막히지 않아야 한다.
    actual_exec = asyncio.create_subprocess_exec
    processes = []
    async def fake_ffmpeg(*args, **kwargs):
        proc = await actual_exec(sys.executable, '-c', 'import sys; sys.stderr.write("x"*300000); sys.stderr.flush()', **kwargs)
        processes.append(proc)
        return proc
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', fake_ffmpeg)
    monkeypatch.setattr('app.core.config.Settings.resolve_ffmpeg_path', lambda self: 'ffmpeg')
    pipeline = FFmpegPipeline('stderr-test')
    try:
        await pipeline.start_recording('https://example.test/stream', output_dir=str(tmp_path), filename='test.ts')
        await asyncio.wait_for(processes[0].wait(), timeout=3)
        for _ in range(100):
            if pipeline.state == RecordingState.COMPLETED:
                break
            await asyncio.sleep(0.01)
        assert pipeline.state == RecordingState.COMPLETED
    finally:
        if processes and processes[0].returncode is None:
            processes[0].kill()
            await processes[0].communicate()


def test_public_font_is_served_as_font_not_spa_html():
    from app.main import app, STATIC_DIR
    if not (STATIC_DIR / 'fonts/PretendardVariable.woff2').is_file():
        pytest.skip('프론트엔드 빌드가 필요합니다.')
    response = TestClient(app).get('/fonts/PretendardVariable.woff2')
    assert response.status_code == 200
    assert response.content[:4] == b'wOF2'
    assert 'text/html' not in response.headers['content-type']


def test_log_output_redacts_signed_urls_cookies_and_exceptions():
    import logging
    from app.core.logger import _make_formatter
    record = logging.LogRecord('test', logging.ERROR, '', 1,
        'failed https://user:password@example.test/a?token=signature NID_AUT=secret; Cookie: session=private', (), None)
    text = _make_formatter().format(record)
    assert all(value not in text for value in ('password', 'signature', 'secret', 'private'))
    assert 'example.test/a' in text


def test_env_multiline_value_updates_without_orphan_lines(tmp_path, monkeypatch):
    import app.core.utils as utils
    path = tmp_path / '.env'
    path.write_text('NID_AUT="first\nsecond"\nHOST=127.0.0.1\n')
    monkeypatch.setattr(utils, '_get_env_path', lambda: path)
    utils.update_env_file({'NID_AUT': 'new\nHOST=evil'})
    utils.update_env_file({'DOWNLOAD_DIR': 'recordings'})
    values = dotenv_values(path)
    assert values['HOST'] == '127.0.0.1'
    assert values['NID_AUT'] == 'new\nHOST=evil'
    assert 'second' not in path.read_text()


@pytest.mark.asyncio
async def test_spaces_resolves_nested_segments_keys_and_unique_output(tmp_path, monkeypatch):
    import httpx
    engine = VodEngine()
    task = VodDownloadTask(url='https://cdn.pscp.tv/root/master_playlist.m3u8', output_dir=str(tmp_path))
    engine._tasks[task.task_id] = task
    master = '#EXTM3U\nsub/audio.m3u8\n'
    playlist = '#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="key.bin"\n#EXTINF:1,\n../chunk.aac\n'
    requests = []
    async def get(url):
        requests.append(url)
        return httpx.Response(200, text=master if len(requests) == 1 else playlist, request=httpx.Request('GET', url))
    client = Mock(get=AsyncMock(side_effect=get))
    client.__aenter__ = AsyncMock(return_value=client); client.__aexit__ = AsyncMock()
    monkeypatch.setattr(httpx, 'AsyncClient', Mock(return_value=client))
    async def spawn(*cmd, **kwargs):
        text = Path(cmd[cmd.index('-i') + 1]).read_text()
        assert 'URI="https://cdn.pscp.tv/root/sub/key.bin"' in text
        assert 'https://cdn.pscp.tv/root/chunk.aac' in text
        assert task.task_id in cmd[-1]
        Path(cmd[-1]).write_bytes(b'fake-audio')
        return Mock(returncode=0, communicate=AsyncMock(return_value=(b'', b'')))
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', spawn)
    monkeypatch.setattr('app.core.config.Settings.resolve_ffmpeg_path', lambda self: 'ffmpeg')
    await engine._download_x_spaces_replay(task.task_id, task)
    assert requests[1] == 'https://cdn.pscp.tv/root/sub/audio.m3u8'
    assert task.state == VodDownloadState.COMPLETED
    assert not list(tmp_path.glob('_tmp_*'))


@pytest.mark.asyncio
async def test_cancel_during_stream_open_closes_late_reader(monkeypatch):
    import threading
    from app.engine.pipeline import YtdlpLivePipeline
    pipeline = YtdlpLivePipeline('open-cancel')
    entered, release = threading.Event(), threading.Event()
    fd = Mock()
    def open_reader():
        entered.set()
        release.wait(timeout=3)
        return fd
    session = Mock()
    stream = Mock(open=Mock(side_effect=open_reader))
    monkeypatch.setattr(pipeline, '_create_streamlink_stream', lambda *args: (session, stream))
    opening = asyncio.create_task(pipeline._open_streamlink_reader('url', {}, None, 0, False, 'best'))
    assert await asyncio.to_thread(entered.wait, 2)
    opening.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await opening
    fd.close.assert_called_once()
    session.http.close.assert_called_once()
