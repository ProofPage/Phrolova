"""Regression checks for platform selection, interruption and process cleanup."""
import asyncio
import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from app.core.config import Settings
from app.engine.vod import VodEngine, VodDownloadTask, VodDownloadState
from app.engine.youtube import YoutubeLiveEngine


def test_posix_never_selects_windows_binary(tmp_path, monkeypatch):
    import app.core.config as config
    monkeypatch.setattr(config.shutil, "which", lambda name: None)
    exe = tmp_path / "ffmpeg.exe"
    exe.touch()
    exe.chmod(0o755)
    with pytest.raises(FileNotFoundError):
        Settings(_env_file=None, ffmpeg_path=str(exe)).resolve_ffmpeg_path()


def test_windows_configured_binary_is_preserved(tmp_path, monkeypatch):
    import app.core.config as config
    monkeypatch.setattr(config.sys, "platform", "win32")
    exe = tmp_path / "ffmpeg.exe"
    exe.touch()
    assert Settings(_env_file=None, ffmpeg_path=str(exe)).resolve_ffmpeg_path() == str(exe)


def test_run_does_not_download_exe_on_posix(tmp_path, monkeypatch):
    import urllib.request
    spec = importlib.util.spec_from_file_location("phrolova_run", Path(__file__).parents[1] / "run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    download = Mock()
    monkeypatch.setattr(urllib.request, "urlretrieve", download)
    assert module._download_ytdlp(tmp_path) is None
    download.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_spaces_terminates_process():
    engine = VodEngine()
    process = Mock(returncode=None)
    task = VodDownloadTask(state=VodDownloadState.DOWNLOADING, process=process)
    engine._tasks[task.task_id] = task
    engine.cancel_download(task.task_id)
    process.terminate.assert_called_once()
    assert task.pause_event.is_set()


def test_interrupted_work_is_restored_as_retryable_error():
    repo = Mock()
    repo.list_all.return_value = [{"task_id": "interrupted", "url": "https://example.com/v.mp4", "state": "downloading"}]
    task = VodEngine(repo=repo)._tasks["interrupted"]
    assert task.state == VodDownloadState.ERROR
    assert "중단" in task.error_message
    repo.replace_all.assert_not_called()


@pytest.mark.asyncio
async def test_shutdown_drains_download_before_saving():
    engine = VodEngine()
    task = VodDownloadTask(state=VodDownloadState.PAUSED)
    task.pause_event.clear()
    async def worker():
        while not task.cancel_flag:
            await asyncio.sleep(0)
        assert task.pause_event.is_set()
        task.state = VodDownloadState.IDLE
    task.download_task = asyncio.create_task(worker())
    engine._tasks[task.task_id] = task
    await engine.shutdown()
    assert task.download_task.done()
    assert task.state == VodDownloadState.ERROR


@pytest.mark.asyncio
async def test_youtube_cancel_reaps_child(monkeypatch):
    process = Mock(returncode=None)
    process.communicate = AsyncMock(side_effect=[asyncio.CancelledError(), (b"", b"")])
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    monkeypatch.setattr(Settings, "resolve_ytdlp_path", lambda self: "yt-dlp")
    with pytest.raises(asyncio.CancelledError):
        await YoutubeLiveEngine()._check_via_ytdlp("https://example.com")
    process.kill.assert_called_once()


def test_korean_filename_fits_posix_component_limit(tmp_path):
    from app.core.utils import clean_filename
    name = clean_filename('한글제목' * 100) + '.mp4.part'
    assert len(name.encode('utf-8')) <= 255
    target = tmp_path / name
    target.write_bytes(b'test')
    assert target.read_bytes() == b'test'


def test_filename_truncation_preserves_media_extension():
    from app.core.utils import clean_filename
    assert clean_filename("한" * 150 + ".ts").endswith(".ts")


def test_cli_uses_same_detected_js_runtime_as_python_api(monkeypatch):
    import app.engine.youtube_support as support
    monkeypatch.setattr(support, "runtime_options", lambda: {"js_runtimes": {"node": {"path": "/test/node"}}})
    assert support.runtime_cli_options() == ["--js-runtimes", "node:/test/node"]


def test_sse_closes_when_server_shutdown_is_requested(monkeypatch):
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.events import router
    import app.main as main
    conductor = Mock()
    conductor.get_all_status.return_value = []
    monkeypatch.setattr(main, 'get_recorder_service', lambda: SimpleNamespace(_conductor=conductor))
    app = FastAPI()
    app.state.uvicorn_server = SimpleNamespace(should_exit=True)
    app.include_router(router)
    response = TestClient(app).get('/api/events')
    assert response.status_code == 200
    assert 'status_update' in response.text
    conductor.remove_event_queue.assert_called_once()
