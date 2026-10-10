"""Transient capture failure appends the same TS; postprocess kills/reaps children."""

import asyncio
import io
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from app.engine.pipeline import YtdlpLivePipeline, RecordingState
from app.engine.recording_finalizer import RecordingFinalizer
from tests.test_recording_finalization import local_hls, stopped_job, terminal


@pytest.mark.asyncio
async def test_manual_stop_closes_blocked_reader_and_writer(tmp_path, monkeypatch):
    import threading

    packet = b"\x47" + bytes(187)
    entered = threading.Event()
    release = threading.Event()

    class Reader:
        count = 0

        def read(self, n):
            self.count += 1
            if self.count == 1:
                return packet * 2
            entered.set()
            release.wait(5)
            return b""

        def close(self):
            release.set()

    reader = Reader()
    pipe = YtdlpLivePipeline("manual")
    session = Mock()

    async def opening(*args):
        return session, [reader]

    monkeypatch.setattr(pipe, "_open_raw_readers", opening)

    async def resolve(quality):
        return "https://example.com/live.m3u8", {}, None

    output = await pipe.start_recording(
        stream_obj="https://example.com/live",
        output_dir=str(tmp_path),
        source_resolver=resolve,
    )
    assert await asyncio.to_thread(entered.wait, 2)
    assert not pipe._closed and not pipe._feeder_task.done()
    await pipe.stop_recording()
    assert (
        pipe._closed
        and pipe._feeder_task.done()
        and pipe.state == RecordingState.COMPLETED
    )
    assert Path(output).read_bytes() == packet * 2 and pipe.end_reason == "manual"


@pytest.mark.asyncio
async def test_network_eof_reconnects_same_file_and_manual_stop_waits_writer(
    tmp_path, monkeypatch
):
    packet = b"\x47" + bytes(187)
    first = io.BytesIO(packet * 2)
    first.worker = SimpleNamespace(playlist_end=None, sequence=0)
    second = io.BytesIO(packet * 3)
    second.worker = SimpleNamespace(playlist_end=2, sequence=3)
    sessions = []
    opened = iter([first, second])
    calls = 0

    async def open_sources(*args):
        session = Mock()
        sessions.append(session)
        return session, [next(opened)]

    pipe = YtdlpLivePipeline("recover")
    monkeypatch.setattr(pipe, "_open_raw_readers", open_sources)

    async def resolve(quality):
        nonlocal calls
        calls += 1
        return f"https://example.com/{calls}.m3u8", {}, None

    output = await pipe.start_recording(
        stream_obj="https://example.com/live",
        output_dir=str(tmp_path),
        source_resolver=resolve,
    )
    await pipe._feeder_task
    assert pipe.state == RecordingState.ERROR and pipe._closed
    assert (
        not Path(output).exists() and Path(output + ".part").read_bytes() == packet * 2
    )
    await pipe.reconnect()
    await pipe._feeder_task
    assert (
        pipe.state == RecordingState.COMPLETED
        and Path(output).read_bytes() == packet * 5
    )
    assert calls == 2 and all(s.http.close.call_count == 1 for s in sessions)


@pytest.mark.asyncio
async def test_ffmpeg_stderr_drain_and_nonzero_preserve_source(local_hls, monkeypatch):
    import shutil

    _, directory = local_hls
    source = directory / "stderr.ts"
    shutil.copy(directory / "720/index0.ts", source)
    actual = asyncio.create_subprocess_exec

    async def noisy(*args, **kwargs):
        return await actual(
            sys.executable,
            "-c",
            'import sys;sys.stderr.write("x"*300000);sys.stderr.flush();sys.exit(1)',
            **kwargs,
        )

    monkeypatch.setattr(asyncio, "create_subprocess_exec", noisy)
    manager = RecordingFinalizer()
    try:
        job = await terminal(manager, await stopped_job(manager, source, keep=False))
        assert job["state"] == "failed" and source.exists()
        assert (
            job["diagnostics"]["returncode"] == 1
            and len(job["diagnostics"]["stderr"]) == 65536
        )
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_shutdown_kills_conversion_and_preserves_source(local_hls, monkeypatch):
    import shutil

    _, directory = local_hls
    source = directory / "shutdown.ts"
    shutil.copy(directory / "720/index0.ts", source)
    actual = asyncio.create_subprocess_exec
    processes = []
    ready = asyncio.Event()

    async def slow(*args, **kwargs):
        proc = await actual(
            sys.executable, "-c", "import time;time.sleep(30)", **kwargs
        )
        processes.append(proc)
        ready.set()
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", slow)
    manager = RecordingFinalizer()
    job_id = await stopped_job(manager, source, keep=False)
    await asyncio.wait_for(ready.wait(), 5)
    await manager.close()
    assert processes[0].returncode is not None and source.is_file()
    assert manager.get(job_id)["state"] == "attention"


@pytest.mark.asyncio
async def test_youtube_recording_resolver_uses_auth_fallback_copy(
    tmp_path, monkeypatch
):
    from unittest.mock import AsyncMock
    from app.core.config import get_settings
    from app.engine.conductor import Conductor
    from app.engine.base import Platform
    import app.engine.conductor as module

    cookie = tmp_path / "youtube.txt"
    content = "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t2147483647\tsession\ttest\n"
    cookie.write_text(content)
    get_settings().youtube_cookie_file = str(cookie)
    observed = []

    class FakePipeline:
        state = RecordingState.IDLE

        def __init__(self, channel_id):
            pass

        def get_status(self):
            return {"state": "idle", "is_recording": False}

        async def _extract_hls_url(self, page, quality, cookies, *, cookie_file=None):
            observed.append(cookie_file)
            if cookie_file is None:
                raise RuntimeError("login required")
            assert (
                Path(cookie_file).read_text() == content and Path(cookie_file) != cookie
            )
            return "https://cdn.example.com/live.m3u8", {}, None

        async def start_recording(self, **kwargs):
            assert kwargs["cookie_str"] is None
            await kwargs["source_resolver"](kwargs["quality"])

    conductor = Conductor()
    conductor.add_channel("@fixture", platform=Platform.YOUTUBE)
    monkeypatch.setattr(module, "YtdlpLivePipeline", FakePipeline)
    try:
        await conductor._start_recording("youtube:@fixture", is_retry=True)
        assert (
            len(observed) == 2
            and observed[0] is None
            and not Path(observed[1]).exists()
        )
        assert cookie.read_text() == content
    finally:
        await conductor.finalizer.close()


def test_channel_output_override_and_legacy_payload_persistence(api_client):
    from app.engine.conductor import Conductor

    cid = "a" * 32
    path = f"/api/stream/channels/{cid}/download-options"
    assert (
        api_client.post(
            "/api/stream/channels",
            json={"channel_id": cid, "auto_record": False, "output_format": "mkv"},
        ).status_code
        == 200
    )
    assert Conductor()._channels[f"chzzk:{cid}"].output_format == "mkv"
    assert api_client.put(path, json={"auto_record": False}).status_code == 200
    assert Conductor()._channels[f"chzzk:{cid}"].output_format == "mkv"
    assert (
        api_client.put(
            path, json={"auto_record": False, "output_format": None}
        ).status_code
        == 200
    )
    assert Conductor()._channels[f"chzzk:{cid}"].output_format is None


@pytest.mark.asyncio
async def test_hls_endlist_automatically_enqueues_and_does_not_restart_old_broadcast(
    local_hls, monkeypatch
):
    from app.engine.conductor import Conductor
    from app.engine.base import Platform
    import app.engine.conductor as module

    base, directory = local_hls
    from app.core.config import get_settings

    get_settings().live_download_dir = str(directory / "autonomous")
    conductor = Conductor()
    conductor.add_channel("alice", platform=Platform.CIME)
    pipe = YtdlpLivePipeline("alice")

    async def resolve(channel, quality):
        return base + "/720/index.m3u8", {}, None

    engine = SimpleNamespace(
        get_stream_url=lambda channel: "https://ci.me/@alice/live",
        resolve_stream=resolve,
    )
    monkeypatch.setattr(conductor, "_get_engine", lambda platform: engine)
    monkeypatch.setattr(module, "YtdlpLivePipeline", lambda channel_id: pipe)
    try:
        await conductor._start_recording("cime:alice", is_retry=True)
        task = conductor._channels["cime:alice"]
        job = await terminal(conductor.finalizer, task.recording_job_id)
        assert job["state"] == "completed", job
        assert task.pipeline is None and task.broadcast_ended
        assert not conductor._can_auto_record(task)
        conductor._apply_status(
            task, {"is_live": True, "live_started_at": "new-broadcast"}
        )
        assert conductor._can_auto_record(task)
    finally:
        await conductor.finalizer.close()
