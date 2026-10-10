"""Real Streamlink TS capture and post-close FFmpeg remux, with data protection."""

import asyncio
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.config import get_settings
from app.engine.base import Platform
from app.engine.pipeline import YtdlpLivePipeline
from app.engine.media_inspection import probe_media, InspectionError
from app.engine.recording_finalizer import (
    RecordingFinalizer,
    recording_policy,
    save_recording_policy,
    publish_file,
)
from app.store.db import get_database
from tests.test_new_platforms import local_hls


async def terminal(manager, job_id):
    for _ in range(150):
        job = manager.get(job_id)
        task = manager._active.get(job_id)
        if job["state"] in ("completed", "failed", "attention") and (
            task is None or task.done()
        ):
            return job
        await asyncio.sleep(0.1)
    raise AssertionError(manager.get(job_id))


def channel(platform="chzzk"):
    return SimpleNamespace(
        platform=Platform(platform), channel_id="fixture", channel_name="한글 채널"
    )


async def stopped_job(manager, path, fmt="mp4", keep=True):
    pipe = YtdlpLivePipeline("fixture")
    pipe._output_path = str(path)
    pipe._source_files = [str(path)]
    pipe._closed = True
    pipe._file_size_bytes = path.stat().st_size
    pipe.end_reason = "manual"
    job_id = manager.register_capture(
        "chzzk:fixture", pipe, channel(), dict(output_format=fmt, keep_source_ts=keep)
    )
    await manager.capture_finished(job_id, pipe)
    return job_id


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["chzzk", "youtube", "soop", "cime"])
@pytest.mark.parametrize("fmt", ["mp4", "mkv"])
async def test_four_platforms_streamlink_ts_then_real_remux(
    local_hls, monkeypatch, platform, fmt
):
    base, directory = local_hls
    manager = RecordingFinalizer()
    pipe = YtdlpLivePipeline("fixture")
    ids = []
    pipe._on_capture_started = lambda capture: ids.append(
        manager.register_capture(
            f"{platform}:fixture",
            capture,
            channel(platform),
            dict(output_format=fmt, keep_source_ts=True),
        )
    )
    real_exec = asyncio.create_subprocess_exec
    commands = []

    async def guarded(*args, **kwargs):
        commands.append(args)
        if Path(args[0]).stem == "ffmpeg":
            assert pipe._closed and pipe._feeder_task.done()
        return await real_exec(*args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", guarded)

    async def resolve(quality):
        return base + "/720/index.m3u8", {}, None

    try:
        source = await pipe.start_recording(
            stream_obj="https://example.com/live",
            output_dir=str(directory / "한글 [녹화 폴더]"),
            source_resolver=resolve,
            quality="720p",
        )
        await asyncio.wait_for(pipe._feeder_task, 15)
        assert pipe.state.value == "completed" and pipe._closed
        assert Path(source).suffix == ".ts" and not commands
        await manager.capture_finished(ids[0], pipe)
        job = await terminal(manager, ids[0])
        assert job["state"] == "completed", job
        assert Path(job["output_path"]).suffix == "." + fmt and Path(source).is_file()
        before = probe_media(source)
        after = probe_media(job["output_path"])
        assert before["streams"] == after["streams"] == {"video", "audio"}
        assert [
            (t["codec_name"], t.get("height"), t["avg_frame_rate"])
            for t in before["tracks"]
        ] == [
            (t["codec_name"], t.get("height"), t["avg_frame_rate"])
            for t in after["tracks"]
        ]
        assert abs(before["duration"] - after["duration"]) < 2
        cmd = next(cmd for cmd in commands if Path(cmd[0]).stem == "ffmpeg")
        assert cmd[cmd.index("-c") + 1] == "copy" and not any(
            str(a).startswith("http") for a in cmd
        )
        assert (
            get_database().query("SELECT output_path FROM live_history")[0][
                "output_path"
            ]
            == job["output_path"]
        )
    finally:
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("keep", [True, False])
async def test_delete_source_only_after_success_and_reinspect_without_source(
    local_hls, keep
):
    _, directory = local_hls
    source = directory / "원본 TS.ts"
    shutil.copy(directory / "720/index0.ts", source)
    manager = RecordingFinalizer()
    try:
        job_id = await stopped_job(manager, source, keep=keep)
        job = await terminal(manager, job_id)
        assert job["state"] == "completed", job
        assert source.exists() == keep
        assert (await manager.retry(job_id, inspect_only=True))[
            "inspection_state"
        ] == "passed"
    finally:
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["tool", "probe", "publish"])
async def test_failure_protects_ts_and_retry_recovers(local_hls, monkeypatch, failure):
    import app.engine.recording_finalizer as module

    _, directory = local_hls
    source = directory / "실패 원본.ts"
    shutil.copy(directory / "720/index0.ts", source)
    original = source.read_bytes()
    manager = RecordingFinalizer()
    real_probe = module.probe_media
    real_publish = module.publish_file
    original_resolver = get_settings().resolve_ffmpeg_path
    if failure == "tool":
        monkeypatch.setattr(
            type(get_settings()),
            "resolve_ffmpeg_path",
            lambda self: "missing-ffmpeg-test",
        )
    elif failure == "probe":

        def bad_probe(path):
            if ".converting." in str(path):
                raise InspectionError("timeout", stderr="probe timed out")
            return real_probe(path)

        monkeypatch.setattr(module, "probe_media", bad_probe)
    else:
        monkeypatch.setattr(
            module,
            "publish_file",
            lambda *args: (_ for _ in ()).throw(OSError("disk full")),
        )
    try:
        job_id = await stopped_job(manager, source, keep=False)
        job = await terminal(manager, job_id)
        assert (
            job["state"] == "failed"
            and source.read_bytes() == original
            and job["diagnostics"]
        )
        monkeypatch.setattr(
            type(get_settings()),
            "resolve_ffmpeg_path",
            lambda self: original_resolver(),
        )
        monkeypatch.setattr(module, "probe_media", real_probe)
        monkeypatch.setattr(module, "publish_file", real_publish)
        await manager.retry(job_id)
        with pytest.raises(ValueError):
            await manager.retry(job_id)
        job = await terminal(manager, job_id)
        assert job["state"] == "completed", job
        assert not source.exists() and job["retry_count"] == 1
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_writer_barrier_restart_and_snapshot(tmp_path):
    save_recording_policy(
        dict(output_format="mp4", keep_source_ts=True, max_concurrent=1)
    )
    pipe = YtdlpLivePipeline("fixture")
    source = tmp_path / "live.ts.part"
    source.write_bytes(b"raw")
    pipe._output_path = str(source)
    pipe._source_files = [str(source)]
    pipe._closed = False
    manager = RecordingFinalizer()
    job_id = manager.register_capture(
        "chzzk:fixture", pipe, channel(), recording_policy()
    )
    save_recording_policy(
        dict(output_format="mkv", keep_source_ts=False, max_concurrent=2)
    )
    assert (
        manager.get(job_id)["target_format"] == "mp4"
        and manager.get(job_id)["keep_source_ts"]
    )
    with pytest.raises(RuntimeError):
        await manager.capture_finished(job_id, pipe)
    assert manager.get(job_id)["state"] == "recording"
    await manager.close()
    manager = RecordingFinalizer()
    await manager.start(recover=True)
    try:
        assert (
            manager.get(job_id)["state"] == "attention"
            and source.read_bytes() == b"raw"
        )
        assert RecordingFinalizer().get(job_id)["target_format"] == "mp4"
    finally:
        await manager.close()


def test_publish_never_overwrites_and_rolls_back_partial_copy(tmp_path, monkeypatch):
    import errno

    source = tmp_path / "source.ts"
    source.write_bytes(b"original")
    target = tmp_path / "final.ts"
    target.write_bytes(b"existing")
    with pytest.raises(FileExistsError):
        publish_file(source, target)
    assert target.read_bytes() == b"existing" and source.read_bytes() == b"original"
    target.unlink()
    monkeypatch.setattr(
        os, "link", lambda *args: (_ for _ in ()).throw(OSError(errno.EPERM, "FUSE"))
    )

    def partial(incoming, outgoing, *args):
        outgoing.write(b"partial")
        raise OSError("disk full")

    monkeypatch.setattr(shutil, "copyfileobj", partial)
    with pytest.raises(OSError):
        publish_file(source, target)
    assert not target.exists() and source.read_bytes() == b"original"


@pytest.mark.asyncio
async def test_queue_concurrency_and_duplicate_claim(tmp_path, monkeypatch):
    manager = RecordingFinalizer()
    save_recording_policy(
        dict(output_format="mp4", keep_source_ts=True, max_concurrent=1)
    )
    running = 0
    peak = 0
    gate = asyncio.Event()
    ids = []

    async def convert(job_id):
        nonlocal running, peak
        assert manager._claim(job_id)
        running += 1
        peak = max(peak, running)
        job = manager.get(job_id)
        job["state"] = "converting"
        manager._save(job)
        await gate.wait()
        running -= 1
        job["state"] = "completed"
        manager._save(job)

    monkeypatch.setattr(manager, "_convert", convert)
    for i in range(3):
        path = tmp_path / f"{i}.ts"
        path.write_bytes(b"raw")
        ids.append(await stopped_job(manager, path))
    try:
        await asyncio.sleep(0.3)
        assert peak == 1
        assert not RecordingFinalizer()._claim(next(iter(manager._active)))
        gate.set()
        await asyncio.sleep(0.8)
        assert peak == 1 and all(manager.get(i)["state"] == "completed" for i in ids)
    finally:
        await manager.close()


def test_retired_features_not_mounted_and_old_rows_retained():
    from app.main import app
    from app.engine.conductor import Conductor
    from app.store.repositories import ChannelRepository

    routes = app.openapi()["paths"]
    assert not any(
        "/chat" in route or "/archive" in route or "/platforms/x/" in route
        for route in routes
    )
    repo = ChannelRepository()
    repo.upsert("x_spaces:old", "x_spaces", "old", True)
    before = repo.list_all()
    assert "x_spaces:old" not in Conductor(channel_repo=repo)._channels
    assert repo.list_all() == before


def test_recording_settings_and_file_api(api_client):
    from app.api.recordings import router

    api_client.app.include_router(router)
    payload = dict(output_format="mkv", keep_source_ts=False, max_concurrent=2)
    assert api_client.put("/api/recordings/settings", json=payload).json() == payload
    assert api_client.get("/api/recordings/settings").json() == payload
    assert (
        api_client.put(
            "/api/recordings/settings", json={**payload, "max_concurrent": 0}
        ).status_code
        == 422
    )
    assert api_client.get("/api/recordings/missing/file").status_code == 404
    assert api_client.get("/api/recordings/jobs").json() == {"jobs": []}


@pytest.mark.asyncio
async def test_hevc_aac_stream_copy_into_mp4(tmp_path):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg unavailable")
    source = tmp_path / "HEVC 한글 원본.ts"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=128x72:rate=5",
            "-f",
            "lavfi",
            "-i",
            "sine=sample_rate=44100",
            "-t",
            "1",
            "-c:v",
            "libx265",
            "-x265-params",
            "log-level=error:pools=1",
            "-c:a",
            "aac",
            "-f",
            "mpegts",
            str(source),
        ],
        check=True,
    )
    manager = RecordingFinalizer()
    try:
        job = await terminal(manager, await stopped_job(manager, source))
        assert job["state"] == "completed", job
        assert [
            track["codec_name"] for track in probe_media(job["output_path"])["tracks"]
        ] == ["hevc", "aac"]
        assert source.is_file()
    finally:
        await manager.close()


def test_fresh_mp4_and_explicit_legacy_preferences(monkeypatch):
    import app.engine.recording_finalizer as module
    from app.core.config import Settings

    fresh = Settings(_env_file=None)
    fresh.model_fields_set.discard("live_format")
    monkeypatch.setattr(module, "get_settings", lambda: fresh)
    assert module.recording_policy()["output_format"] == "mp4"
    for fmt in ("ts", "mkv", "mp4"):
        previous = Settings(_env_file=None, live_format=fmt)
        monkeypatch.setattr(module, "get_settings", lambda: previous)
        assert module.recording_policy()["output_format"] == fmt


def test_implicit_old_ts_preference_is_preserved(tmp_path, monkeypatch):
    import app.core.utils as utils
    import app.engine.recording_finalizer as module
    from app.core.config import Settings

    path = tmp_path / "old.env"
    path.write_text("DOWNLOAD_DIR=recordings\n")
    monkeypatch.setattr(utils, "_get_env_path", lambda: path)
    settings = Settings(_env_file=None)
    settings.model_fields_set.discard("live_format")
    monkeypatch.setattr(module, "get_settings", lambda: settings)
    assert module.recording_policy()["output_format"] == "ts"
