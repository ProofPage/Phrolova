import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.core.config import Settings, get_settings
from app.engine.media_inspection import InspectionError, probe_media
from app.engine.vod import VodDownloadState, VodDownloadTask, VodEngine


@pytest.fixture
def media_file(tmp_path):
    path = tmp_path / '한글 영상 [1080p].ts'
    path.write_bytes(b'media fixture')
    return path


def fake_probe(monkeypatch, payload=None, *, stderr=b'', returncode=0):
    monkeypatch.setattr(Settings, 'resolve_ffprobe_path', lambda _: 'ffprobe')
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, returncode, json.dumps(payload).encode() if payload is not None else b'{', stderr)
    monkeypatch.setattr('app.engine.media_inspection.subprocess.run', run)
    return calls


def test_ffprobe_path_does_not_require_ffmpeg(tmp_path, monkeypatch):
    tool = tmp_path / ('ffprobe.exe' if os.name == 'nt' else 'ffprobe')
    tool.write_bytes(b'tool'); tool.chmod(0o755)
    monkeypatch.setattr(Settings, 'resolve_ffmpeg_path', lambda _: (_ for _ in ()).throw(FileNotFoundError('no ffmpeg')))
    monkeypatch.setattr('app.core.config.shutil.which', lambda name: str(tool) if name == 'ffprobe' else None)
    assert Settings().resolve_ffprobe_path() == str(tool.resolve())


def test_termux_prefix_and_executable_permission(tmp_path, monkeypatch):
    tool = tmp_path / 'bin' / 'ffprobe'; tool.parent.mkdir(); tool.write_bytes(b'tool'); tool.chmod(0o755)
    monkeypatch.setenv('PREFIX', str(tmp_path))
    monkeypatch.setattr('app.core.config.shutil.which', lambda _: None)
    monkeypatch.setattr(Settings, 'resolve_ffmpeg_path', lambda _: (_ for _ in ()).throw(FileNotFoundError()))
    assert Settings(ffprobe_path='missing').resolve_ffprobe_path() == str(tool.resolve())
    monkeypatch.setattr('app.core.config.sys.platform', 'linux')
    monkeypatch.setattr('app.core.config.os.access', lambda *_: False)
    with pytest.raises(FileNotFoundError): Settings(ffprobe_path='missing').resolve_ffprobe_path()


def test_unicode_path_safe_arguments_and_optional_duration(media_file, monkeypatch):
    calls = fake_probe(monkeypatch, {'format': {'format_name': 'mpegts'}, 'streams': [{'index': 0, 'codec_type': 'video', 'codec_name': 'h264', 'duration': '12.5'}]})
    info = probe_media(str(media_file))
    assert info['duration'] == 12.5 and info['streams'] == {'video'}
    args, options = calls[0]
    assert args[-1] == str(media_file) and options.get('shell', False) is False
    assert options['timeout'] == 120 and 'format=duration,size,format_name' in args[4]
    fake_probe(monkeypatch, {'format': {'format_name': 'mpegts'}, 'streams': [{'codec_type': 'video'}]})
    assert probe_media(str(media_file))['duration'] is None


@pytest.mark.parametrize('case,code', [('missing', 'missing_file'), ('empty', 'empty_file')])
def test_missing_and_empty_files_never_launch_probe(tmp_path, monkeypatch, case, code):
    path = tmp_path / case
    if case == 'empty': path.touch()
    monkeypatch.setattr(Settings, 'resolve_ffprobe_path', lambda _: pytest.fail('must check file first'))
    with pytest.raises(InspectionError) as caught: probe_media(str(path))
    assert caught.value.code == code


def test_access_denied(media_file, monkeypatch):
    monkeypatch.setattr(Path, 'open', lambda *_a, **_k: (_ for _ in ()).throw(PermissionError('ACL denied')))
    with pytest.raises(InspectionError) as caught: probe_media(str(media_file))
    assert caught.value.code == 'access_denied'


@pytest.mark.parametrize('failure,code', [(FileNotFoundError('missing'), 'tool_missing'), (PermissionError('execute denied'), 'tool_failed'), (subprocess.TimeoutExpired('ffprobe', 120, stderr=b'timed out'), 'timeout')])
def test_tool_failures_are_distinct(media_file, monkeypatch, failure, code):
    fake_probe(monkeypatch, {})
    def fail(*_a, **_k): raise failure
    monkeypatch.setattr(Settings, 'resolve_ffprobe_path', fail if code == 'tool_missing' else lambda _: 'ffprobe')
    if code != 'tool_missing': monkeypatch.setattr('app.engine.media_inspection.subprocess.run', fail)
    with pytest.raises(InspectionError) as caught: probe_media(str(media_file))
    assert caught.value.code == code
    if code == 'timeout': assert caught.value.diagnostics['stderr'] == 'timed out'


def test_exit_code_stderr_and_json_errors(media_file, monkeypatch):
    fake_probe(monkeypatch, {}, stderr=b'Invalid data found', returncode=1)
    with pytest.raises(InspectionError) as caught: probe_media(str(media_file))
    assert caught.value.code == 'probe_failed'
    assert caught.value.diagnostics == {'detail': 'FFprobe exited unsuccessfully', 'stderr': 'Invalid data found', 'returncode': 1}
    for payload in (None, [], {'format': ['invalid']}, {'streams': [1]}):
        fake_probe(monkeypatch, payload)
        with pytest.raises(InspectionError) as caught: probe_media(str(media_file))
        assert caught.value.code == 'invalid_response'


def test_large_file_uses_metadata_only(tmp_path, monkeypatch):
    # A sparse 5 GiB file exercises integer size/path handling, not real large media playback.
    path = tmp_path / 'large.ts'
    with path.open('wb') as file: file.truncate(5 * 1024**3)
    calls = fake_probe(monkeypatch, {'format': {'duration': '7370', 'format_name': 'mpegts'}, 'streams': [{'codec_type': 'video'}]})
    assert probe_media(str(path))['size'] == 5 * 1024**3
    assert '-show_frames' not in calls[0][0] and '-count_frames' not in calls[0][0]


@pytest.mark.asyncio
async def test_completed_inspection_failure_retry_recovery_and_history(media_file, monkeypatch):
    engine = VodEngine()
    task = VodDownloadTask(url='https://chzzk.naver.com/video/123', state=VodDownloadState.COMPLETED, output_path=str(media_file), metadata={'duration': 10, 'expected_streams': ['video', 'audio']})
    engine._tasks[task.task_id] = task
    def missing(_): raise InspectionError('tool_missing', 'not installed')
    monkeypatch.setattr(engine, '_probe_media_info', missing)
    await engine._inspect_chzzk_download(task, task.metadata, str(media_file))
    assert task.state == VodDownloadState.COMPLETED and task.inspection_state == 'failed'
    assert media_file.read_bytes() == b'media fixture'
    loaded = VodEngine()._tasks[task.task_id]
    assert loaded.inspection_code == 'tool_missing' and loaded.state == VodDownloadState.COMPLETED
    monkeypatch.setattr(engine, '_probe_media_info', lambda _: {'duration': 10, 'size': 13, 'streams': {'video', 'audio'}, 'format_name': 'mpegts'})
    assert engine.reinspect_download(task.task_id)['inspection_state'] == 'running'
    with pytest.raises(ValueError, match='이미'): engine.reinspect_download(task.task_id)
    with pytest.raises(ValueError, match='검사 종료'): engine.remove_vod_task(task.task_id)
    await asyncio.gather(*engine._inspection_tasks)
    assert task.inspection_state == 'passed' and task.warning_message is None
    assert task.inspection_code is None and task.inspected_at is not None
    assert VodEngine()._tasks[task.task_id].inspection_state == 'passed'


@pytest.mark.asyncio
async def test_missing_duration_is_attention_not_failed(media_file, monkeypatch):
    engine = VodEngine(); task = VodDownloadTask(state=VodDownloadState.COMPLETED)
    monkeypatch.setattr(engine, '_probe_media_info', lambda _: {'duration': None, 'streams': {'video'}, 'format_name': 'mpegts'})
    await engine._inspect_chzzk_download(task, {'duration': 600}, str(media_file))
    assert task.inspection_state == 'attention' and task.state == VodDownloadState.COMPLETED


@pytest.mark.asyncio
async def test_restart_and_legacy_history_and_remove_preserves_file(media_file):
    engine = VodEngine()
    engine._repo.upsert('old', {'url': 'https://chzzk.naver.com/video/1', 'state': 'completed', 'output_path': str(media_file), 'warning_message': 'FFprobe old warning'})
    engine._repo.upsert('running', {'url': 'https://chzzk.naver.com/video/2', 'state': 'completed', 'output_path': str(media_file), 'inspection_state': 'running'})
    restored = VodEngine()
    assert restored._tasks['old'].inspection_state == 'attention'
    assert restored._tasks['running'].inspection_state == 'pending'
    restored.remove_vod_task('old')
    assert media_file.exists() and 'old' not in VodEngine()._tasks


@pytest.mark.asyncio
async def test_retry_download_duplicate_guard_and_original_file(media_file, monkeypatch):
    engine = VodEngine(); task = VodDownloadTask(url='https://chzzk.naver.com/video/1', state=VodDownloadState.COMPLETED, output_path=str(media_file))
    engine._tasks[task.task_id] = task
    monkeypatch.setattr(engine, '_run_download', AsyncMock())
    retry = await engine.retry_download(task.task_id)
    with pytest.raises(ValueError, match='이미'): await engine.retry_download(task.task_id)
    await engine._tasks[retry].download_task
    assert media_file.read_bytes() == b'media fixture'
    assert VodEngine()._tasks[task.task_id].retry_task_id == retry


def test_inspection_api_is_background_and_conflict_safe(api_client, media_file):
    import app.main as main
    engine = main.get_recorder_service()._vod_engine
    task = VodDownloadTask(url='https://chzzk.naver.com/video/1', state=VodDownloadState.COMPLETED, output_path=str(media_file))
    engine._tasks[task.task_id] = task
    response = api_client.post(f'/api/vod/{task.task_id}/inspect')
    assert response.status_code == 202 and response.json()['inspection_state'] == 'running'
    assert api_client.get('/api/vod/status').json()['tasks'][0]['state'] == 'completed'
    assert api_client.post('/api/vod/missing/inspect').status_code == 409


@pytest.mark.parametrize('ext', ['mp4', 'ts'])
def test_real_mp4_and_ts(tmp_path, ext):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'): pytest.skip('FFmpeg/FFprobe required')
    path = tmp_path / f'한글 영상 [1080p].{ext}'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc=size=160x90:rate=10', '-f', 'lavfi', '-i', 'sine=frequency=440', '-t', '2', '-c:v', 'libx264', '-threads', '1', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(path)], check=True, timeout=30)
    result = probe_media(str(path))
    assert result['streams'] == {'video', 'audio'} and result['size'] > 0
    assert 1.8 <= result['duration'] <= 2.5


def test_real_reinspection_api_recovers(api_client, tmp_path, monkeypatch):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'): pytest.skip('FFmpeg/FFprobe required')
    import app.main as main
    path = tmp_path / '재검사 영상 [정상].mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=size=160x90:rate=10',
                    '-t', '2', '-c:v', 'libx264', str(path)], check=True, timeout=30)
    original = path.read_bytes()
    engine = main.get_recorder_service()._vod_engine
    task = VodDownloadTask(url='https://chzzk.naver.com/video/1', state=VodDownloadState.COMPLETED,
                           output_path=str(path), metadata={'duration': 2, 'expected_streams': ['video']})
    engine._tasks[task.task_id] = task
    def missing(_): raise InspectionError('tool_missing', 'temporarily unavailable')
    monkeypatch.setattr(engine, '_probe_media_info', missing)
    async def drain(): await asyncio.gather(*engine._inspection_tasks)
    assert api_client.post(f'/api/vod/{task.task_id}/inspect').status_code == 202
    api_client.portal.call(drain)
    assert task.inspection_state == 'failed' and task.state == VodDownloadState.COMPLETED
    monkeypatch.setattr(engine, '_probe_media_info', probe_media)
    assert api_client.post(f'/api/vod/{task.task_id}/inspect').status_code == 202
    api_client.portal.call(drain)
    result = api_client.get(f'/api/vod/status/{task.task_id}').json()
    assert result['inspection_state'] == 'passed' and result['state'] == 'completed'
    assert result['inspection_diagnostics']['streams'] == ['video']
    assert path.read_bytes() == original


def test_timeout_kills_and_reaps_real_child(media_file, monkeypatch):
    import sys
    actual_run, actual_popen = subprocess.run, subprocess.Popen
    children = []
    def popen(*args, **kwargs):
        child = actual_popen(*args, **kwargs); children.append(child); return child
    def run(_args, **kwargs):
        return actual_run([sys.executable, '-c', "import sys,time;sys.stderr.write('started\\n');sys.stderr.flush();time.sleep(60)"], **kwargs)
    monkeypatch.setattr(Settings, 'resolve_ffprobe_path', lambda _: 'test-child')
    monkeypatch.setattr(subprocess, 'Popen', popen)
    monkeypatch.setattr(subprocess, 'run', run)
    get_settings().file_inspection_timeout = 1
    with pytest.raises(InspectionError) as caught: probe_media(str(media_file))
    assert caught.value.code == 'timeout' and 'started' in caught.value.diagnostics['stderr']
    assert children and all(child.returncode is not None for child in children)


@pytest.mark.asyncio
async def test_inspection_does_not_block_loop_and_shutdown_preserves_completed(media_file, monkeypatch):
    import time
    engine = VodEngine(); task = VodDownloadTask(state=VodDownloadState.COMPLETED, output_path=str(media_file))
    engine._tasks[task.task_id] = task
    def slow(_):
        time.sleep(.2)
        return {'duration': 10, 'streams': {'video'}, 'format_name': 'mpegts'}
    monkeypatch.setattr(engine, '_probe_media_info', slow)
    task.download_task = asyncio.create_task(engine._inspect_chzzk_download(task, {}, str(media_file)))
    await asyncio.sleep(.05)
    assert task.inspection_state == 'running' and not task.download_task.done()
    await engine.shutdown()
    assert task.state == VodDownloadState.COMPLETED and task.inspection_state == 'passed'
    assert not task.cancel_flag


@pytest.mark.asyncio
async def test_success_exit_with_error_stderr_needs_attention(media_file, monkeypatch):
    fake_probe(monkeypatch, {'format': {'duration': 10, 'format_name': 'mpegts'}, 'streams': [{'codec_type': 'video'}]}, stderr=b'Packet corrupt')
    engine = VodEngine(); task = VodDownloadTask(state=VodDownloadState.COMPLETED)
    await engine._inspect_chzzk_download(task, {}, str(media_file))
    assert task.inspection_state == 'attention'
    assert task.inspection_diagnostics['stderr'] == 'Packet corrupt'


@pytest.mark.asyncio
@pytest.mark.parametrize('streams,state', [({'video'}, 'passed'), ({'audio'}, 'passed'), ({'subtitle'}, 'attention'), (set(), 'attention')])
async def test_requires_audio_or_video_stream(media_file, monkeypatch, streams, state):
    engine = VodEngine(); task = VodDownloadTask(state=VodDownloadState.COMPLETED)
    monkeypatch.setattr(engine, '_probe_media_info', lambda _: {'duration': 10, 'streams': streams, 'format_name': 'mpegts'})
    await engine._inspect_chzzk_download(task, {}, str(media_file))
    assert task.inspection_state == state and task.state == VodDownloadState.COMPLETED


@pytest.mark.skipif(os.environ.get('PHROLOVA_TEST_LARGE_MEDIA') != '1', reason='Opt-in: generates more than 3 GiB of actual TS video')
def test_real_large_ts(tmp_path):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'): pytest.skip('FFmpeg/FFprobe required')
    if shutil.disk_usage(tmp_path).free < 5 * 1024**3: pytest.skip('5 GiB free space required')
    path = tmp_path / '대용량 영상 [1080p 경로].ts'
    try:
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=size=160x90:rate=10',
                        '-f', 'lavfi', '-i', 'sine=frequency=440', '-t', '1400', '-c:v', 'libx264',
                        '-preset', 'ultrafast', '-threads', '1', '-b:v', '20M', '-minrate', '20M', '-maxrate', '20M',
                        '-bufsize', '20M', '-x264-params', 'nal-hrd=cbr', '-c:a', 'aac', str(path)], check=True, timeout=300)
        result = probe_media(str(path))
        assert result['size'] > 3 * 1024**3
        assert result['streams'] == {'video', 'audio'} and 1398 < result['duration'] < 1402
    finally:
        path.unlink(missing_ok=True)
