"""Reproduce the supplied log failures without recording a user's live channel."""

import asyncio
import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from app.engine.base import Platform
from app.engine.pipeline import YtdlpLivePipeline, RecordingState
from app.engine.recording_finalizer import RecordingFinalizer, recording_policy
from app.store.db import get_database
from tests.test_new_platforms import local_hls


def shift_fragment_clocks(raw, seconds):
    """Reproduce CHZZK's absolute fragment timestamps in generated local media."""
    import struct
    from app.engine.native_clock import boxes

    data = bytearray(raw)
    scales = {}

    def offsets(start, end):
        while start + 8 <= end:
            size, kind = struct.unpack_from(">I4s", data, start)
            header = 8
            if size == 1:
                size = struct.unpack_from(">Q", data, start + 8)[0]
                header = 16
            if size < header or start + size > end:
                return
            yield kind, start + header, start + size
            start += size

    for kind, start, end in offsets(0, len(data)):
        if kind != b"moov":
            continue
        for tag, track in boxes(data[start:end]):
            if tag != b"trak":
                continue
            parts = dict(boxes(track))
            tkhd = parts[b"tkhd"]
            offset = 20 if tkhd[0] else 12
            track_id = int.from_bytes(tkhd[offset : offset + 4], "big")
            mdhd = dict(boxes(parts[b"mdia"]))[b"mdhd"]
            offset = 20 if mdhd[0] else 12
            scales[track_id] = int.from_bytes(mdhd[offset : offset + 4], "big")
    for kind, start, end in offsets(0, len(data)):
        if kind != b"moof":
            continue
        for tag, left, right in offsets(start, end):
            if tag != b"traf":
                continue
            children = list(offsets(left, right))
            tfhd = next((a for k, a, b in children if k == b"tfhd"), None)
            tfdt = next((a for k, a, b in children if k == b"tfdt"), None)
            if tfhd is None or tfdt is None:
                continue
            track_id = int.from_bytes(data[tfhd + 4 : tfhd + 8], "big")
            width = 8 if data[tfdt] else 4
            clock = tfdt + 4
            value = (
                int.from_bytes(data[clock : clock + width], "big")
                + seconds * scales[track_id]
            )
            data[clock : clock + width] = value.to_bytes(width, "big")
    return bytes(data)


async def configure(pipe, reader, monkeypatch):
    reader.worker = SimpleNamespace(playlist_end=1, sequence=2)

    async def opening(*args):
        return Mock(), [reader]

    monkeypatch.setattr(pipe, "_open_raw_readers", opening)

    async def resolve(quality):
        return "https://example.com/live.m3u8", {}, None

    return resolve


@pytest.mark.asyncio
async def test_short_ts_reads_are_buffered_before_container_validation(
    tmp_path, monkeypatch
):
    packet = b"\x47" + bytes(187)

    class Reader(io.BytesIO):
        def read(self, n=-1):
            return super().read(min(n, 73))

    pipe = YtdlpLivePipeline("short")
    resolve = await configure(pipe, Reader(packet * 10), monkeypatch)
    await pipe.start_recording(output_dir=str(tmp_path), source_resolver=resolve)
    await pipe._feeder_task
    assert pipe.state == RecordingState.COMPLETED
    assert Path(pipe.output_path).read_bytes() == packet * 10


@pytest.mark.asyncio
async def test_native_headers_without_media_do_not_register_or_tick(
    tmp_path, monkeypatch
):
    pipe = YtdlpLivePipeline("cmaf")
    registered = []
    pipe._on_capture_started = lambda p: registered.append(p)
    reader = io.BytesIO(bytes.fromhex("000000146674797069736f360000000069736f36"))
    resolve = await configure(pipe, reader, monkeypatch)
    with pytest.raises(RuntimeError):
        await pipe.start_recording(output_dir=str(tmp_path), source_resolver=resolve)
    assert not registered and pipe.duration_seconds == 0 and pipe._closed
    assert pipe.error_code == "empty_stream"


def test_same_session_registration_is_idempotent(tmp_path):
    path = tmp_path / "session.ts"
    path.write_bytes(b"\x47" + bytes(187))
    pipe = YtdlpLivePipeline("same")
    pipe._output_path = str(path)
    pipe._source_files = [str(path)]
    manager = RecordingFinalizer()
    channel = SimpleNamespace(
        platform=Platform.CHZZK, channel_id="same", channel_name="채널"
    )
    policy = dict(output_format="mkv", keep_source_ts=True)
    first = manager.register_capture("chzzk:same", pipe, channel, policy)
    second = manager.register_capture("chzzk:same", pipe, channel, policy)
    assert first == second and len(manager.list_jobs()) == 1


@pytest.mark.asyncio
async def test_zero_byte_capture_is_not_conversion_or_live_history(tmp_path):
    path = tmp_path / "empty.ts"
    path.touch()
    pipe = YtdlpLivePipeline("empty")
    pipe._output_path = str(path)
    pipe._source_files = [str(path)]
    pipe._closed = True
    manager = RecordingFinalizer()
    channel = SimpleNamespace(
        platform=Platform.CHZZK, channel_id="empty", channel_name="채널"
    )
    job = manager.register_capture(
        "chzzk:empty", pipe, channel, dict(output_format="mkv", keep_source_ts=True)
    )
    try:
        await manager.capture_finished(job, pipe)
        assert manager.get(job)["state"] == "capture_failed"
        assert not get_database().query("SELECT * FROM live_history")
    finally:
        await manager.close()


def test_missing_output_preference_defaults_to_mkv(monkeypatch):
    import app.engine.recording_finalizer as module
    from app.core.config import Settings

    settings = Settings(_env_file=None)
    settings.model_fields_set.discard("live_format")
    monkeypatch.setattr(module, "get_settings", lambda: settings)
    assert recording_policy()["output_format"] == "mkv"


@pytest.mark.asyncio
@pytest.mark.parametrize("fmt", ["mkv", "mp4"])
async def test_real_fragmented_capture_normalizes_after_close(
    tmp_path, monkeypatch, fmt
):
    import shutil, subprocess
    from app.engine.media_inspection import probe_media
    from tests.test_recording_finalization import terminal

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg unavailable")
    native = tmp_path / "fixture.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=10",
            "-f",
            "lavfi",
            "-i",
            "sine=sample_rate=48000",
            "-t",
            "3",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-g",
            "10",
            "-c:a",
            "aac",
            "-output_ts_offset",
            "1000",
            "-movflags",
            "+frag_keyframe+empty_moov",
            str(native),
        ],
        check=True,
    )
    raw = shift_fragment_clocks(native.read_bytes(), 1000)
    pipe = YtdlpLivePipeline("native")
    manager = RecordingFinalizer()
    ids = []
    pipe._on_capture_started = lambda capture: ids.append(
        manager.register_capture(
            "chzzk:native",
            capture,
            SimpleNamespace(
                platform=Platform.CHZZK, channel_id="native", channel_name="한글 [채널]"
            ),
            dict(output_format=fmt, keep_source_ts=True),
        )
    )
    real = asyncio.create_subprocess_exec
    commands = []

    async def guard(*args, **kwargs):
        if Path(args[0]).stem == "ffmpeg":
            assert pipe._closed and pipe._feeder_task.done()
            assert "-c" in args and args[args.index("-c") + 1] == "copy"
            commands.append(args)
        return await real(*args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", guard)
    resolve = await configure(pipe, io.BytesIO(raw), monkeypatch)
    try:
        await pipe.start_recording(
            output_dir=str(tmp_path / "한글 폴더"), source_resolver=resolve
        )
        await pipe._feeder_task
        assert pipe.capture_format == "fmp4" and len(ids) == 1
        assert (
            Path(pipe.output_path).suffix == ".mp4"
            and Path(pipe.output_path).read_bytes() == raw
        )
        assert 1 <= pipe.duration_seconds <= 4
        await manager.capture_finished(ids[0], pipe)
        await manager.capture_finished(ids[0], pipe)
        result = await terminal(manager, ids[0])
        assert result["state"] == "completed", result
        assert len(commands) == 2
        assert Path(pipe.output_path).read_bytes() == raw
        ts = probe_media(result["source_paths"][0])
        final = probe_media(result["output_path"])
        assert "mpegts" in ts["format_name"] and final["duration"] < 5
        assert [(x.get("codec_type"), x.get("codec_name")) for x in ts["tracks"]] == [
            (x.get("codec_type"), x.get("codec_name")) for x in final["tracks"]
        ]
        assert len(get_database().query("SELECT * FROM live_history")) == 1
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_best_prefers_real_ts_rendition_over_higher_native(local_hls):
    base, folder = local_hls
    (folder / "native.m3u8").write_text(
        '#EXTM3U\n#EXT-X-MAP:URI="init.mp4"\n#EXTINF:1,\nfragment.m4v\n'
    )
    (folder / "mixed.m3u8").write_text(
        "#EXTM3U\n#EXT-X-STREAM-INF:RESOLUTION=1920x1080,BANDWIDTH=9000000\nnative.m3u8\n#EXT-X-STREAM-INF:RESOLUTION=1280x720,BANDWIDTH=4000000\n720/index.m3u8\n"
    )
    session, stream = await asyncio.to_thread(
        YtdlpLivePipeline._create_streamlink_stream,
        base + "/mixed.m3u8",
        {},
        None,
        0,
        False,
        "best",
    )
    try:
        assert stream.url.endswith("/720/index.m3u8")
    finally:
        session.http.close()


@pytest.mark.asyncio
async def test_unknown_container_is_not_retried(tmp_path, monkeypatch):
    pipe = YtdlpLivePipeline("unknown")
    resolve = await configure(pipe, io.BytesIO(b"x" * 65536), monkeypatch)
    with pytest.raises(RuntimeError):
        await pipe.start_recording(output_dir=str(tmp_path), source_resolver=resolve)
    assert not pipe.retryable and pipe.duration_seconds == 0


def test_error_classes_and_public_runtime_fallback(monkeypatch):
    from app.core.config import get_settings
    from app.engine.recording_errors import classify_recording_error
    import app.engine.youtube_support as youtube

    for failure in (
        PermissionError("denied"),
        FileNotFoundError("ffmpeg"),
        ValueError("bad channel"),
        RuntimeError("Sign in to confirm you are not a bot"),
        RuntimeError("DASH 전용"),
    ):
        assert not classify_recording_error(failure).retryable
    assert classify_recording_error(TimeoutError()).retryable
    monkeypatch.setattr(youtube, "runtime_options", lambda: {})
    monkeypatch.setattr(get_settings(), "youtube_po_token_provider_url", None)
    # Public HLS may be available without JS; do not block a usable fallback.
    assert youtube.require_runtime_cli_options() == []


@pytest.mark.asyncio
async def test_retry_budget_survives_refresh_restart_and_auto_off():
    from app.engine.conductor import Conductor
    from unittest.mock import AsyncMock

    conductor = Conductor()
    conductor.add_channel("retry", auto_record=True)
    task = conductor._channels["chzzk:retry"]
    task.is_live = True
    conductor._running = True
    task.pipeline = SimpleNamespace(
        state=RecordingState.ERROR,
        retryable=True,
        reconnect=AsyncMock(side_effect=TimeoutError("network")),
        get_status=lambda: {},
    )
    for _ in range(10):
        task.retry_at = None
        await conductor._retry_stalled_recording(
            "chzzk:retry", task, task.retry_count, 3
        )
    assert task.pipeline.reconnect.await_count == 3 and task.retry_blocked
    restarted = Conductor()
    restored = restarted._channels["chzzk:retry"]
    assert restored.retry_blocked and restored.retry_count == 3
    assert not restarted._can_auto_record(restored)
    await conductor.toggle_auto_record("chzzk:retry")
    pipe = task.pipeline
    await conductor._retry_stalled_recording("chzzk:retry", task, 3, 3)
    assert (
        task.pipeline is pipe
        and pipe.reconnect.await_count == 3
        and not task.auto_record
    )


def test_history_clear_preserves_database_files_and_active_jobs(tmp_path):
    path = tmp_path / "source.ts"
    path.write_bytes(b"preserve")
    manager = RecordingFinalizer()
    pipe = YtdlpLivePipeline("keep")
    pipe._output_path = str(path)
    pipe._source_files = [str(path)]
    ch = SimpleNamespace(
        platform=Platform.CHZZK, channel_id="keep", channel_name="채널"
    )
    job_id = manager.register_capture(
        "chzzk:keep", pipe, ch, dict(output_format="mkv", keep_source_ts=True)
    )
    manager.clear_history([job_id])
    assert len(manager.list_jobs()) == 1
    job = manager.get(job_id)
    job["state"] = "failed"
    manager._save(job)
    manager.clear_history([job_id])
    assert not manager.list_jobs()
    assert manager.get(job_id)["hidden"] and path.read_bytes() == b"preserve"
    assert get_database().query_one(
        "SELECT id FROM recording_jobs WHERE id=?", (job_id,)
    )


def test_live_cdn_selects_only_api_urls_and_reports_unavailable():
    from app.engine.chzzk_time_machine import _media_path, _cdn_warning

    media = [
        dict(
            mediaId="HLS",
            protocol="HLS",
            path="https://live.navercdn.com/video.m3u8?token=a",
        ),
        dict(
            mediaId="HLS",
            protocol="HLS",
            path="https://live.akamaized.net/video.m3u8?token=b",
        ),
    ]
    assert _media_path(media, "default") == media[0]["path"]
    assert _media_path(media, "akamai") == media[1]["path"]
    actual = _media_path(media[:1], "akamai")
    assert actual == media[0]["path"] and _cdn_warning(actual, "akamai")


@pytest.mark.asyncio
async def test_youtube_watch_redirect_is_not_a_live_broadcast(monkeypatch):
    from app.engine.youtube import YoutubeLiveEngine
    from unittest.mock import AsyncMock
    import app.engine.youtube as module

    response = SimpleNamespace(
        status_code=200,
        text="<title>Past video - YouTube</title>",
        url="https://youtube.com/watch?v=aaaaaaaaaaa",
    )
    monkeypatch.setattr(
        module,
        "get_http_client",
        lambda: SimpleNamespace(get=AsyncMock(return_value=response)),
    )
    engine = YoutubeLiveEngine()
    monkeypatch.setattr(
        engine, "_check_via_ytdlp", AsyncMock(return_value=(False, None))
    )
    assert not (await engine.check_live_status("@sample"))["is_live"]


def test_duration_freezes_without_data_and_uses_media_clock():
    from datetime import datetime, timedelta

    pipe = YtdlpLivePipeline("clock")
    assert pipe.duration_seconds == 0
    pipe._start_time = datetime.now() - timedelta(hours=1)
    pipe._last_data_at = pipe._start_time + timedelta(seconds=3)
    assert pipe.duration_seconds == 3
    pipe._media_duration = 2.5
    assert pipe.duration_seconds == 2.5


@pytest.mark.asyncio
async def test_concurrent_manual_auto_start_uses_one_capture(tmp_path, monkeypatch):
    from app.engine.conductor import Conductor
    import app.engine.conductor as module
    from unittest.mock import AsyncMock

    conductor = Conductor()
    conductor.add_channel("concurrent", auto_record=True)
    conductor._running = True
    task = conductor._channels["chzzk:concurrent"]
    task.is_live = True
    pipe = YtdlpLivePipeline("concurrent")
    path = tmp_path / "unique.ts"
    path.write_bytes(b"\x47" + bytes(187))
    pipe._output_path = str(path)
    pipe._source_files = [str(path)]

    async def start(**options):
        pipe._state = RecordingState.RECORDING
        pipe._on_capture_started(pipe)
        return str(path)

    pipe.start_recording = AsyncMock(side_effect=start)
    monkeypatch.setattr(module, "YtdlpLivePipeline", lambda **kwargs: pipe)
    sleep = asyncio.sleep

    async def wait(seconds):
        await sleep(0 if seconds == 5 else seconds)

    monkeypatch.setattr(module.asyncio, "sleep", wait)
    try:
        await asyncio.gather(
            conductor._start_recording("chzzk:concurrent", automatic=True),
            conductor._start_recording("chzzk:concurrent"),
        )
        assert (
            pipe.start_recording.await_count == 1
            and len(conductor.finalizer.list_jobs()) == 1
        )
    finally:
        await conductor.finalizer.close()


def test_live_cdn_settings_saved_independently(api_client):
    from app.core.config import get_settings
    previous_vod_cdn = get_settings().chzzk_vod_cdn

    result = api_client.put(
        "/api/settings/live", json={"max_record_retries": 3, "chzzk_live_cdn": "akamai"}
    )
    assert (
        result.status_code == 200
        and result.json()["settings"]["chzzk_live_cdn"] == "akamai"
    )
    assert api_client.get("/api/settings").json()["chzzk_live_cdn"] == "akamai"
    assert get_settings().chzzk_vod_cdn == previous_vod_cdn
    assert (
        api_client.put(
            "/api/settings/live",
            json={"max_record_retries": 3, "chzzk_live_cdn": "invalid"},
        ).status_code
        == 422
    )


def test_part_file_counts_in_live_statistics_and_preserves_empty_time(tmp_path):
    part = tmp_path / "capture.ts.part"
    part.write_bytes(bytes(1024 * 128))
    pipe = YtdlpLivePipeline("stats")
    pipe._output_path = str(tmp_path / "capture.ts")
    pipe._source_files = [str(part)]
    pipe._update_statistics()
    assert pipe.file_size_bytes == part.stat().st_size and pipe.duration_seconds == 0


def test_missing_policy_fields_receive_defaults():
    get_database().execute(
        "INSERT INTO app_settings(key,value) VALUES('recording_output','{}')"
    )
    assert recording_policy() == dict(
        output_format="mkv", keep_source_ts=True, max_concurrent=1
    )


@pytest.mark.asyncio
async def test_youtube_metadata_auth_failure_remains_actionable(monkeypatch):
    import app.engine.youtube as module
    from app.engine.youtube import YoutubeLiveEngine
    from unittest.mock import AsyncMock

    response = SimpleNamespace(
        status_code=403, text="", url="https://youtube.com/@sample/live"
    )
    monkeypatch.setattr(
        module,
        "get_http_client",
        lambda: SimpleNamespace(get=AsyncMock(return_value=response)),
    )
    proc = SimpleNamespace(
        returncode=1,
        communicate=AsyncMock(
            return_value=(b"", b"Sign in to confirm you are not a bot")
        ),
    )
    monkeypatch.setattr(
        module.asyncio, "create_subprocess_exec", AsyncMock(return_value=proc)
    )
    status = await YoutubeLiveEngine().check_live_status("@sample")
    assert (
        not status["is_live"]
        and status["status_error"]
        and not status["status_error_retryable"]
    )


@pytest.mark.asyncio
async def test_youtube_recommended_live_is_not_current_channel(monkeypatch):
    import app.engine.youtube as module
    from unittest.mock import AsyncMock

    response = SimpleNamespace(
        status_code=200,
        text='recommended: {"isLive":true,"videoId":"aaaaaaaaaaa"}',
        url="https://youtube.com/@sample/live",
    )
    monkeypatch.setattr(
        module,
        "get_http_client",
        lambda: SimpleNamespace(get=AsyncMock(return_value=response)),
    )
    engine = module.YoutubeLiveEngine()
    monkeypatch.setattr(
        engine, "_check_via_ytdlp", AsyncMock(return_value=(False, None))
    )
    assert not (await engine.check_live_status("@sample"))["is_live"]


@pytest.mark.asyncio
async def test_youtube_current_player_uses_real_video_url(monkeypatch):
    import app.engine.youtube as module
    from unittest.mock import AsyncMock
    import json

    player = {
        "videoDetails": {"isLive": True, "videoId": "abcdefghijk"},
        "playabilityStatus": {"status": "OK"},
    }
    response = SimpleNamespace(
        status_code=200,
        text="var ytInitialPlayerResponse = " + json.dumps(player) + ";",
        url="https://youtube.com/watch?v=abcdefghijk",
    )
    monkeypatch.setattr(
        module,
        "get_http_client",
        lambda: SimpleNamespace(get=AsyncMock(return_value=response)),
    )
    engine = module.YoutubeLiveEngine()
    monkeypatch.setattr(engine, "_check_via_ytdlp", AsyncMock())
    assert (await engine.check_live_status("@sample"))["is_live"]
    assert (
        engine.get_stream_url("@sample")
        == "https://www.youtube.com/watch?v=abcdefghijk"
    )
    engine._check_via_ytdlp.assert_not_awaited()


@pytest.mark.asyncio
async def test_native_reconnect_keeps_session_and_valid_boxes(tmp_path, monkeypatch):
    import shutil, subprocess
    from app.engine.media_inspection import probe_media
    from tests.test_recording_finalization import terminal

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg unavailable")
    parts = []
    for index in range(2):
        file = tmp_path / f"fragment-{index}.mp4"
        subprocess.run(
            [
                ffmpeg,
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=320x180:rate=10",
                "-t",
                "3",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-g",
                "10",
                "-output_ts_offset",
                str(1000 + index * 3),
                "-movflags",
                "+frag_keyframe+empty_moov",
                str(file),
            ],
            check=True,
        )
        reader = io.BytesIO(shift_fragment_clocks(file.read_bytes(), 1000 + index * 3))
        reader.worker = (
            SimpleNamespace(playlist_end=None)
            if index == 0
            else SimpleNamespace(playlist_end=1, sequence=2)
        )
        parts.append(reader)
    pipe = YtdlpLivePipeline("reconnect")
    manager = RecordingFinalizer()
    ids = []
    pipe._on_capture_started = lambda p: ids.append(
        manager.register_capture(
            "chzzk:reconnect",
            p,
            SimpleNamespace(
                platform=Platform.CHZZK, channel_id="reconnect", channel_name="채널"
            ),
            dict(output_format="mkv", keep_source_ts=True),
        )
    )

    async def opening(*args):
        return Mock(), [parts.pop(0)]

    monkeypatch.setattr(pipe, "_open_raw_readers", opening)

    async def resolve(quality):
        return "https://example.com/live.m3u8", {}, None

    try:
        await pipe.start_recording(output_dir=str(tmp_path), source_resolver=resolve)
        await pipe._feeder_task
        assert pipe.state == RecordingState.ERROR
        await pipe.reconnect()
        await pipe._feeder_task
        assert len(ids) == 1 and pipe.state == RecordingState.COMPLETED
        assert 5 <= pipe.duration_seconds <= 7
        await manager.capture_finished(ids[0], pipe)
        job = await terminal(manager, ids[0])
        assert job["state"] == "completed", job
        assert 5 <= probe_media(job["output_path"])["duration"] <= 7
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_closed_conversion_recovery_reuses_final_file(local_hls, monkeypatch):
    import shutil, subprocess
    from tests.test_recording_finalization import terminal

    base, folder = local_hls
    source = folder / "720" / "index0.ts"
    target = source.with_suffix(".mkv")
    subprocess.run(
        [
            shutil.which("ffmpeg"),
            "-v",
            "error",
            "-i",
            str(source),
            "-c",
            "copy",
            str(target),
        ],
        check=True,
    )
    original = target.read_bytes()
    manager = RecordingFinalizer()
    pipe = YtdlpLivePipeline("recovery")
    pipe._output_path = str(source)
    pipe._source_files = [str(source)]
    ch = SimpleNamespace(
        platform=Platform.CHZZK, channel_id="recovery", channel_name="채널"
    )
    job_id = manager.register_capture(
        "chzzk:recovery", pipe, ch, dict(output_format="mkv", keep_source_ts=True)
    )
    job = manager.get(job_id)
    job.update(state="verifying", writer_closed=True, output_path=None)
    manager._save(job)
    recovered = RecordingFinalizer()
    exec_process = Mock(
        side_effect=AssertionError("Existing final file must only be inspected")
    )
    monkeypatch.setattr(asyncio, "create_subprocess_exec", exec_process)
    try:
        await recovered.start(recover=True)
        result = await terminal(recovered, job_id)
        assert result["state"] == "completed", result
        assert target.read_bytes() == original and Path(result["output_path"]) == target
        exec_process.assert_not_called()
        assert len(recovered.list_jobs()) == 1
    finally:
        await recovered.close()


@pytest.mark.asyncio
async def test_auto_off_during_resolution_does_not_open_stream(tmp_path, monkeypatch):
    from app.engine.recording_errors import RecordingError

    enabled = True
    pipe = YtdlpLivePipeline("cancel-start")
    pipe._start_guard = lambda: enabled
    opened = Mock(side_effect=AssertionError("Auto OFF must not open a new reader"))
    monkeypatch.setattr(pipe, "_open_raw_readers", opened)

    async def resolve(quality):
        nonlocal enabled
        enabled = False
        return "https://example.com/live.m3u8", {}, None

    with pytest.raises(RecordingError) as failure:
        await pipe.start_recording(output_dir=str(tmp_path), source_resolver=resolve)
    assert failure.value.code == "auto_record_disabled" and pipe.duration_seconds == 0
    opened.assert_not_called()


@pytest.mark.parametrize("port", [57403, 5401, 403, 401])
def test_url_numbers_do_not_become_authentication_status(port):
    from app.engine.recording_errors import classify_recording_error
    error = RuntimeError(f"Unable to open URL http://127.0.0.1:{port}/expired.m3u8: 404 Client Error: Not Found")
    failure = classify_recording_error(error)
    assert failure.code == "connection" and failure.retryable

@pytest.mark.parametrize("status", [401, 403])
def test_http_cause_keeps_authentication_nonretryable(status):
    from app.engine.recording_errors import classify_recording_error
    from requests import HTTPError, Response
    response = Response(); response.status_code = status
    error = RuntimeError("Unable to open protected stream")
    error.__cause__ = HTTPError("request failed", response=response)
    failure = classify_recording_error(error)
    assert failure.code == "authentication" and not failure.retryable
