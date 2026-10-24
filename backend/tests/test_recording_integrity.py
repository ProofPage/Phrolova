import hashlib
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.engine import recording_integrity as integrity
from app.engine.recording_errors import classify_recording_error


@pytest.mark.parametrize("status,code", [(404, "stream_unavailable"), (503, "stream_unavailable"), (401, "authentication"), (403, "authentication")])
def test_http_classification(status, code):
    error = RuntimeError("upstream request")
    error.response = SimpleNamespace(status_code=status)
    classified = classify_recording_error(error)
    assert classified.code == code
    assert classified.retryable == (status in (404, 503))


@pytest.mark.parametrize("returncode,stderr,state", [(0, b"", "passed"), (1, b"corrupt frame", "failed"), (0, b"decoder error", "failed")])
def test_saved_file_verification(tmp_path, monkeypatch, returncode, stderr, state):
    path = tmp_path / "video.mp4"
    payload = b"independent hash fixture"
    path.write_bytes(payload)
    monkeypatch.setattr(integrity, "probe_media", lambda _: {"streams": {"video"}})
    monkeypatch.setattr(integrity, "get_settings", lambda: SimpleNamespace(resolve_ffmpeg_path=lambda: "ffmpeg"))
    run = Mock(return_value=subprocess.CompletedProcess([], returncode, stderr=stderr))
    monkeypatch.setattr(integrity.subprocess, "run", run)
    result = integrity.verify_recording(path)
    assert result["sha256"] == hashlib.sha256(payload).hexdigest()
    assert result["full_decode"] == state
    assert result["broadcast_completeness"] == "unverified"
    args = run.call_args.args[0]
    assert "-xerror" in args and "-read_intervals" not in args
    assert path.read_bytes() == payload


def test_rejects_file_changed_during_inspection(tmp_path, monkeypatch):
    path = tmp_path / "video.mp4"
    path.write_bytes(b"initial")
    monkeypatch.setattr(integrity, "probe_media", lambda _: {"streams": {"audio"}})
    monkeypatch.setattr(integrity, "get_settings", lambda: SimpleNamespace(resolve_ffmpeg_path=lambda: "ffmpeg"))
    def run(*args, **kwargs):
        path.write_bytes(b"modified contents")
        return subprocess.CompletedProcess([], 0, stderr=b"")
    monkeypatch.setattr(integrity.subprocess, "run", run)
    with pytest.raises(ValueError, match="변경"):
        integrity.verify_recording(path)


def test_real_file_full_decode_and_corrupt_input(tmp_path):
    from app.core.config import get_settings
    path = tmp_path / "sample.mkv"
    subprocess.run([get_settings().resolve_ffmpeg_path(), "-nostdin", "-v", "error",
                    "-f", "lavfi", "-i", "testsrc2=size=64x64:rate=10",
                    "-t", "1", "-c:v", "ffv1", str(path)], check=True, capture_output=True)
    result = integrity.verify_recording(path)
    assert result["full_decode"] == "passed"
    assert result["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    broken = tmp_path / "broken.mkv"
    broken.write_bytes(path.read_bytes()[:16])
    from app.engine.media_inspection import InspectionError
    with pytest.raises(InspectionError):
        integrity.verify_recording(broken)


def test_server_wait_preserves_live_and_retry(tmp_path, monkeypatch):
    from app.engine.conductor import Conductor
    from app.engine.channel import ChannelTask
    from app.engine.base import Platform
    from app.engine.recording_errors import RecordingError
    conductor = object.__new__(Conductor)
    monkeypatch.setattr(conductor, "_persist_retry", lambda _: None)
    monkeypatch.setattr(conductor, "_broadcast_status", lambda: None)
    task = ChannelTask("a" * 24, Platform.RPLAY, auto_record=True)
    task.is_live = True
    task.retry_count = 10
    conductor._record_failure(task, RecordingError("stream_unavailable", "server unavailable", retryable=True))
    assert task.is_live and not task.broadcast_ended
    assert not task.retry_blocked and task.retry_at and task.retry_count == 0


@pytest.mark.asyncio
async def test_integrity_api_rejects_active_and_unknown_jobs(monkeypatch):
    from app.api import recordings
    from fastapi import HTTPException
    manager = SimpleNamespace(get=lambda _: {"state": "recording", "output_available": True})
    monkeypatch.setattr(recordings, "manager", lambda: manager)
    with pytest.raises(HTTPException) as caught:
        await recordings.verify_integrity("active")
    assert caught.value.status_code == 409
    def missing(_):
        raise ValueError()
    manager.get = missing
    with pytest.raises(HTTPException) as caught:
        await recordings.verify_integrity("../../outside")
    assert caught.value.status_code == 404


@pytest.mark.asyncio
async def test_integrity_api_keeps_capture_scope_unknown(monkeypatch):
    from app.api import recordings
    monkeypatch.setattr(recordings, "manager", lambda: SimpleNamespace(get=lambda _: {
        "state": "completed", "output_available": True, "output_path": "registered-file",
    }))
    monkeypatch.setattr(integrity, "verify_recording", lambda path: {"scope": "saved_file_only"})
    result = await recordings.verify_integrity("registered")
    assert result["capture_observations"] is None
    assert result["scope"] == "saved_file_only"
    assert not recordings._integrity_busy


@pytest.mark.asyncio
async def test_repeated_server_wait_does_not_exhaust_monitor_counter(monkeypatch):
    from datetime import datetime, timedelta
    from unittest.mock import AsyncMock
    from app.engine.conductor import Conductor
    from app.engine.channel import ChannelTask
    from app.engine.base import Platform
    from app.engine.pipeline import RecordingState
    from app.engine.recording_errors import RecordingError
    conductor = object.__new__(Conductor)
    conductor._running = True
    monkeypatch.setattr(conductor, "_persist_retry", lambda _: None)
    monkeypatch.setattr(conductor, "_broadcast_status", lambda: None)
    monkeypatch.setattr(conductor, "_can_auto_record", lambda _: True)
    task = ChannelTask("a" * 24, Platform.RPLAY, auto_record=True)
    task.is_live = True
    task.pipeline = SimpleNamespace(
        state=RecordingState.ERROR, retryable=True,
        reconnect=AsyncMock(side_effect=RecordingError("stream_unavailable", "server", retryable=True)),
    )
    task.retry_code = "stream_unavailable"
    # A stale local monitor counter must not block recovery after its limit.
    for _ in range(5):
        task.retry_at = (datetime.now() - timedelta(seconds=1)).isoformat()
        count = await conductor._retry_stalled_recording(task.composite_key, task, 3, 3)
        assert count == 1 and not task.retry_blocked and task.is_live
    assert task.pipeline.reconnect.await_count == 5


@pytest.mark.asyncio
@pytest.mark.parametrize("recovers", [True, False])
async def test_youtube_503_recovery_resets_count_only_after_success(monkeypatch, recovers):
    from datetime import datetime, timedelta
    from unittest.mock import AsyncMock
    from app.engine.conductor import Conductor
    from app.engine.channel import ChannelTask
    from app.engine.base import Platform
    from app.engine.pipeline import RecordingState
    conductor = object.__new__(Conductor)
    conductor._running = True
    monkeypatch.setattr(conductor, "_persist_retry", lambda _: None)
    monkeypatch.setattr(conductor, "_broadcast_status", lambda: None)
    monkeypatch.setattr(conductor, "_can_auto_record", lambda task: task.auto_record and not task.retry_blocked)
    task = ChannelTask("youtube-recovery", Platform.YOUTUBE, auto_record=True)
    task.is_live = True
    async def reconnect():
        if not recovers:
            raise error
        task.pipeline.state = RecordingState.RECORDING
    task.pipeline = SimpleNamespace(
        state=RecordingState.ERROR, retryable=True,
        reconnect=AsyncMock(side_effect=reconnect),
    )
    count = 0
    attempts = 5 if recovers else 1
    for _ in range(attempts):
        task.pipeline.state = RecordingState.ERROR
        error = RuntimeError("503 Service Unavailable")
        error.response = SimpleNamespace(status_code=503)
        conductor._record_failure(task, error)
        task.retry_at = (datetime.now() - timedelta(seconds=1)).isoformat()
        count = await conductor._retry_stalled_recording(task.composite_key, task, count, 3)
        assert count == task.retry_count == (0 if recovers else 1)
        if recovers:
            assert not task.retry_blocked and task.retry_code is None and task.last_error is None
        else:
            assert task.retry_code == "stream_unavailable" and task.last_error is not None
    assert task.pipeline.reconnect.await_count == attempts


@pytest.mark.parametrize("report,expected", [
    (None, "unknown"),
    ({"tracks": {}, "segment_errors": 0, "omitted_ranges": 0}, "unknown"),
    ({"tracks": {"0": {"completed_segment_writes": 10}}}, "no_observed_discontinuities"),
    ({"tracks": {"0": {"completed_segment_writes": 10, "sequence_gaps": [{"first": 2, "last": 4}]}}}, "observed_discontinuities"),
    ({"tracks": {"0": {"completed_segment_writes": 10}}, "omitted_ranges": 1}, "observed_discontinuities"),
])
def test_capture_assessment_does_not_claim_unobserved_completeness(report, expected):
    assert integrity.capture_assessment(report) == expected


def test_timestamp_repair_preserves_packets_and_fixes_null_muxer_decode(tmp_path):
    from app.engine.timestamp_repair import repair_ts_clock
    from app.engine.media_inspection import probe_media
    import subprocess
    from app.core.config import get_settings

    ffmpeg = get_settings().resolve_ffmpeg_path()
    source = tmp_path / "source.ts"
    # Create an artificial TS file with two video/audio segments that have a timestamp discontinuity
    p1 = tmp_path / "part1.ts"
    p2 = tmp_path / "part2.ts"
    subprocess.run([
        ffmpeg, "-nostdin", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=64x64:rate=25",
        "-f", "lavfi", "-i", "sine=frequency=1000:sample_rate=48000",
        "-t", "1", "-c:v", "libx264", "-c:a", "aac", "-f", "mpegts", str(p1)
    ], check=True)
    subprocess.run([
        ffmpeg, "-nostdin", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=64x64:rate=25",
        "-f", "lavfi", "-i", "sine=frequency=1000:sample_rate=48000",
        "-t", "1", "-c:v", "libx264", "-c:a", "aac", "-f", "mpegts", str(p2)
    ], check=True)
    
    # Concat them with an intentional backward timestamp step
    concat_file = tmp_path / "list.txt"
    concat_file.write_text(f"file '{p1.name}'\nfile '{p2.name}'\n", encoding="utf-8")
    subprocess.run([
        ffmpeg, "-nostdin", "-v", "error", "-f", "concat", "-safe", "0",
        "-i", str(concat_file), "-c", "copy", "-f", "mpegts", str(source)
    ], check=True)

    media = probe_media(str(source))
    candidate = tmp_path / "output.mkv"
    subprocess.run([
        ffmpeg, "-nostdin", "-v", "warning", "-i", str(source),
        "-map", "0:v", "-map", "0:a", "-c", "copy", str(candidate)
    ], check=True)

    result = repair_ts_clock(source, candidate, media)
    assert result["applied"] is True
    assert result["full_decode"] == "passed"
    assert candidate.exists() and candidate.stat().st_size > 0


@pytest.mark.parametrize("state,stage", [
    ("idle", "idle"), ("reconnecting", "reconnecting"), ("stopping", "stopping"),
    ("error", "waiting"), ("completed", "completed"),
])
def test_connection_stage_does_not_keep_stale_receiving_state(state, stage):
    from app.engine.pipeline import RecordingState, YtdlpLivePipeline
    pipe = YtdlpLivePipeline("state-fixture")
    pipe.connection_stage = "receiving"
    pipe._state = RecordingState(state)
    assert pipe.get_status()["connection_stage"] == stage


@pytest.mark.asyncio
async def test_youtube_eof_pending_status_is_not_recording_failure(tmp_path, monkeypatch, caplog):
    import io
    import logging
    from app.engine.pipeline import YtdlpLivePipeline
    from app.engine.conductor import Conductor
    from app.engine.channel import ChannelTask
    from app.engine.base import Platform
    reader = io.BytesIO((b"\x47" + bytes(187)) * 2)
    reader.worker = SimpleNamespace(playlist_end=None, sequence=0)
    pipe = YtdlpLivePipeline("fixture")
    async def opening(*args):
        return Mock(), [reader]
    async def resolve(_):
        return "https://cdn.example/stream.m3u8", {}, None
    monkeypatch.setattr(pipe, "_open_raw_readers", opening)
    with caplog.at_level(logging.INFO):
        await pipe.start_recording(stream_obj="https://www.youtube.com/watch?v=fixture",
                                   output_dir=str(tmp_path), source_resolver=resolve)
        await pipe._feeder_task
    assert pipe.error_code == "stream_closed" and pipe.retryable
    records = [r for r in caplog.records if "stream_closed" in r.getMessage()]
    assert records and all(r.levelno == logging.INFO for r in records)
    conductor = object.__new__(Conductor)
    monkeypatch.setattr(conductor, "_persist_retry", lambda _: None)
    monkeypatch.setattr(conductor, "_broadcast_status", lambda: None)
    task = ChannelTask("fixture", Platform.YOUTUBE)
    task.is_live = True
    conductor._record_failure(task, pipe.last_exception)
    assert task.retry_code == "stream_closed"
    assert task.last_error is None and not task.recent_errors and task.is_live
    conductor._reset_retry(task)  # The next scan confirms the real broadcast end.
    assert task.retry_code is None
    await pipe.stop_recording()
