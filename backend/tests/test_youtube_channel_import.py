import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from app.engine import youtube_channel as channels


def test_nested_tabs_are_flattened_without_video_extraction(monkeypatch):
    calls = []
    def extract(self, url, download, process):
        assert download is False and process is False
        calls.append(url)
        if len(calls) == 1:
            return {"entries": iter([
                {"id": "channel-id", "entries": iter([
                    {"id": "abcdefghijk", "title": "Video"}, None,
                    {"id": "abcdefghijk"},
                    {"id": "live1234567", "live_status": "is_live"},
                ])},
                {"ie_key": "YoutubeTab", "url": "https://www.youtube.com/@test/shorts"},
            ])}
        return {"entries": [{"id": "12345678901", "title": "Short"}]}
    monkeypatch.setattr(channels.yt_dlp.YoutubeDL, "extract_info", extract)
    entries = list(channels.channel_entries("https://www.youtube.com/@test", threading.Event()))
    assert [entry["id"] for entry in entries] == ["abcdefghijk", "12345678901"]
    assert len(calls) == 2
    assert entries[0]["url"] == "https://www.youtube.com/watch?v=abcdefghijk"


@pytest.mark.asyncio
async def test_add_responds_before_collection_and_status_is_visible(monkeypatch):
    from app.api.vod import router
    from app.services.recorder import RecorderService
    from app.engine.vod import VodEngine
    gate = threading.Event()
    def collect(url, stopped):
        while not gate.wait(0.01):
            if stopped.is_set():
                return
        yield {"id": "abcdefghijk", "url": "https://www.youtube.com/watch?v=abcdefghijk"}
    monkeypatch.setattr(channels, "channel_entries", collect)
    manager = channels.ChannelImports(AsyncMock(return_value=True))
    service = RecorderService.__new__(RecorderService)
    service._vod_engine = SimpleNamespace(
        channel_imports=manager, is_youtube_channel_url=VodEngine.is_youtube_channel_url,
        list_all_tasks=lambda: [],
    )
    monkeypatch.setattr("app.main.get_recorder_service", lambda: service)
    app = FastAPI()
    app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        try:
            response = await asyncio.wait_for(client.post("/api/vod/download", json={"url": "@itsub"}), 1)
            assert response.status_code == 200
            job_id = response.json()["import_id"]
            assert response.json()["added_count"] == 0
            status = (await client.get("/api/vod/status")).json()
            assert status["imports"][0]["id"] == job_id
            gate.set()
            await asyncio.wait_for(manager.tasks[job_id], 2)
            assert manager.list()[0]["added_count"] == 1
            assert manager.list()[0]["state"] == "completed"
        finally:
            gate.set()


@pytest.mark.asyncio
async def test_failure_after_partial_collection_preserves_count(monkeypatch):
    def collect(url, stopped):
        yield {"id": "abcdefghijk"}
        raise RuntimeError("YouTube network unavailable")
    monkeypatch.setattr(channels, "channel_entries", collect)
    manager = channels.ChannelImports(AsyncMock(return_value=True))
    job = manager.start("https://www.youtube.com/@test", None, "best")
    await asyncio.wait_for(manager.tasks[job["id"]], 2)
    result = manager.list()[0]
    assert result["state"] == "error" and result["added_count"] == 1
    assert "network unavailable" in result["error"]


@pytest.mark.asyncio
async def test_cancel_stops_collection_and_repeated_submit_reuses_job(monkeypatch):
    def collect(url, stopped):
        while not stopped.wait(0.01):
            yield {"id": "abcdefghijk"}
    monkeypatch.setattr(channels, "channel_entries", collect)
    enqueue = AsyncMock(return_value=True)
    manager = channels.ChannelImports(enqueue)
    job = manager.start("https://www.youtube.com/@test", None, "best")
    assert manager.start(job["url"], None, "best")["id"] == job["id"]
    task = manager.tasks[job["id"]]
    while not enqueue.await_count:
        await asyncio.sleep(0.01)
    manager.cancel(job["id"])
    with pytest.raises(asyncio.CancelledError):
        await task
    count = enqueue.await_count
    await asyncio.sleep(0.05)
    assert enqueue.await_count == count
    assert manager.list()[0]["state"] == "cancelled"


def test_cookie_upload_validates_format_and_filters_other_domains(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.api import platforms
    settings = SimpleNamespace(youtube_cookie_file=None)
    getter = lambda: settings
    getter.cache_clear = lambda: None
    monkeypatch.setattr(platforms, "get_settings", getter)
    monkeypatch.setattr(platforms, "_COOKIE_SAVE_PATH", tmp_path / "x_cookies.txt")
    monkeypatch.setattr(platforms, "_update_env_file", lambda values: setattr(settings, "youtube_cookie_file", values["YOUTUBE_COOKIE_FILE"]))
    app = FastAPI()
    app.include_router(platforms.router)
    client = TestClient(app)
    assert client.post("/api/platforms/youtube/cookie", files={"file": ("cookies.txt", b"invalid")}).status_code == 400
    cookies = "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tsynthetic\n.example.com\tTRUE\t/\tTRUE\t0\tsession\tunrelated\n"
    response = client.post("/api/platforms/youtube/cookie", files={"file": ("cookies.txt", cookies)})
    assert response.status_code == 200
    stored = (tmp_path / "youtube_cookies.txt").read_text()
    assert "synthetic" in stored and "unrelated" not in stored
    assert client.get("/api/platforms/youtube/cookie").json() == {"configured": True}
    assert client.delete("/api/platforms/youtube/cookie").status_code == 200
    assert not (tmp_path / "youtube_cookies.txt").exists()


@pytest.mark.asyncio
async def test_youtube_signin_error_does_not_retry(tmp_path, monkeypatch):
    from app.engine.vod import VodEngine, VodDownloadTask, VodDownloadState
    monkeypatch.setattr("app.core.config.Settings.resolve_ffmpeg_path", lambda _: "ffmpeg")
    def denied(*args, **kwargs):
        raise channels.yt_dlp.utils.DownloadError("Sign in to confirm you're not a bot")
    monkeypatch.setattr(channels.yt_dlp.YoutubeDL, "extract_info", denied)
    engine = VodEngine()
    task = VodDownloadTask(url="https://www.youtube.com/watch?v=abcdefghijk", output_dir=str(tmp_path))
    engine._tasks[task.task_id] = task
    await asyncio.wait_for(engine._run_download(task.task_id), 3)
    assert task.state == VodDownloadState.ERROR
    assert "설정 → 인증 → 유튜브" in task.error_message
    assert task.retry_count == 0


@pytest.mark.asyncio
async def test_stalled_collector_times_out_and_signals_worker(monkeypatch):
    def collect(url, stopped):
        stopped.wait(2)
        return
        yield
    monkeypatch.setattr(channels, "channel_entries", collect)
    manager = channels.ChannelImports(AsyncMock())
    manager.idle_timeout = 0.02
    job = manager.start("https://www.youtube.com/@test", None, "best")
    await asyncio.wait_for(manager.tasks[job["id"]], 1)
    assert manager.list()[0]["state"] == "error"
    assert "응답이 지연" in manager.list()[0]["error"]


@pytest.mark.asyncio
async def test_real_engine_enqueues_titles_and_skips_existing_videos(tmp_path, monkeypatch):
    from app.engine.vod import VodEngine
    def collect(url, stopped):
        yield {"id": "abcdefghijk", "url": "https://www.youtube.com/watch?v=abcdefghijk", "title": "Channel video"}
    monkeypatch.setattr(channels, "channel_entries", collect)
    engine = VodEngine()
    monkeypatch.setattr(engine, "_run_download", AsyncMock())
    for _ in range(2):
        job = engine.channel_imports.start("https://www.youtube.com/@test", str(tmp_path), "best")
        await asyncio.wait_for(engine.channel_imports.tasks[job["id"]], 2)
    assert len(engine.list_all_tasks()) == 1
    assert engine.list_all_tasks()[0]["title"] == "Channel video"
    assert engine.channel_imports.list()[-1]["skipped_count"] == 1


def test_frozen_runtime_is_used(tmp_path, monkeypatch):
    from app.engine import youtube_support
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "node.exe").touch()
    monkeypatch.setattr(youtube_support.sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(youtube_support.sys, "platform", "win32")
    monkeypatch.setattr(youtube_support.shutil, "which", lambda _: None)
    assert youtube_support.runtime_options()["js_runtimes"]["node"]["path"] == str(tmp_path / "bin" / "node.exe")
