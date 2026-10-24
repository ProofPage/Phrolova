"""Native DASH selection, sequence boundaries, safe stop and post-capture remux."""

import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.config import get_settings
from app.engine.pipeline import YtdlpLivePipeline
from app.engine.pipeline.state import RecordingState
from app.engine.recording_errors import RecordingError
from app.engine.youtube_dash import DashReader, media_url, open_dash, sequence_url


def tracks():
    return [
        dict(url="https://cdn.googlevideo.com/videoplayback?sig=secret", format_id="313",
             width=3840, height=2160, fps=30, vcodec="vp9", acodec="none",
             ext="webm", target_duration=5, protocol="http_dash_segments_generator"),
        dict(url="https://cdn.googlevideo.com/videoplayback?sig=secret", format_id="140",
             vcodec="none", acodec="mp4a.40.2", ext="m4a", target_duration=5,
             protocol="http_dash_segments_generator"),
    ]


@pytest.mark.parametrize("value", [
    "http://cdn.googlevideo.com/x", "https://googlevideo.com.evil/x",
    "https://evil/x", "https://user:pass@cdn.googlevideo.com/x",
    "file:///tmp/stream", "https://cdn.googlevideo.com:8443/x",
])
def test_media_url_rejects_untrusted_destinations(value):
    with pytest.raises(RecordingError):
        media_url(value)


def test_signed_query_preserved_and_sequence_replaced():
    assert sequence_url("https://cdn.googlevideo.com/v?sig=abc%2Fdef&sq=1", 9) == (
        "https://cdn.googlevideo.com/v?sig=abc%2Fdef&sq=9")


@pytest.mark.parametrize("from_start,expected", [(False, 100), (True, 0)])
def test_start_mode_and_resume_use_media_boundary(monkeypatch, from_start, expected):
    monkeypatch.setattr(DashReader, "head", lambda self: 100 + self.index)
    session, readers = open_dash(tracks(), {}, from_start)
    try:
        assert [r.next_sequence for r in readers] == [expected, expected]
    finally:
        session.close()
    session, readers = open_dash(tracks(), {0: 44, 1: 45}, from_start)
    try:
        assert [r.next_sequence for r in readers] == [44, 45]
    finally:
        session.close()


def test_stop_drains_complete_accepted_fragment_and_commits_sequence():
    resume = {}
    reader = DashReader(tracks()[0], resume, 0)
    try:
        reader.buffer = b"abcdef"
        reader.pending_sequence = 9
        reader.request_stop()
        assert reader.read(3) == b"abc"
        assert resume == {}
        assert reader.read(3) == b"def"
        assert reader.read(3) == b""
        assert resume == {0: 10}
        assert reader.received_duration == 5
    finally:
        reader.session.close()


@pytest.mark.asyncio
async def test_dash_extraction_preserves_tracks_and_actual_resolution(monkeypatch):
    commands = []

    class Process:
        returncode = 0
        async def communicate(self):
            return json.dumps({"requested_formats": tracks()}).encode(), b""

    async def execute(*args, **kwargs):
        commands.append(args)
        return Process()

    monkeypatch.setattr("app.engine.pipeline.ytdlp.asyncio.create_subprocess_exec", execute)
    monkeypatch.setattr("app.engine.pipeline.ytdlp.require_runtime_cli_options", lambda: [])
    pipe = YtdlpLivePipeline("test")
    await pipe._extract_youtube_source("https://www.youtube.com/watch?v=test", "best")
    assert "--live-from-start" in commands[0]
    assert pipe._dash_source == tracks()
    assert pipe.get_status()["recording_resolution"] == {"width": 3840, "height": 2160, "fps": 30}
    assert pipe.preview_source_url is None


@pytest.mark.asyncio
async def test_only_unavailable_dash_falls_back_to_hls(monkeypatch):
    pipe = YtdlpLivePipeline("test")
    extract = AsyncMock(side_effect=[
        RecordingError("youtube_dash_unavailable", "unavailable"), ("hls", {}, None)])
    monkeypatch.setattr(pipe, "_extract_hls_url", extract)
    assert await pipe._extract_youtube_source("youtube", "best") == ("hls", {}, None)
    assert extract.await_count == 2
    get_settings().youtube_time_machine_enabled = True
    extract.reset_mock(side_effect=True)
    extract.side_effect = RecordingError("youtube_dash_unavailable", "unavailable")
    with pytest.raises(RecordingError):
        await pipe._extract_youtube_source("youtube", "best")
    assert extract.await_count == 1


@pytest.mark.asyncio
async def test_reconnect_failure_returns_to_error_not_permanent_reconnecting():
    pipe = YtdlpLivePipeline("test")
    pipe._state = RecordingState.ERROR
    pipe._source_resolver = AsyncMock(side_effect=RuntimeError("temporary network failure"))
    with pytest.raises(RuntimeError):
        await pipe.reconnect()
    assert pipe.state == RecordingState.ERROR
    assert pipe._closed
    assert pipe.retryable


@pytest.mark.asyncio
@pytest.mark.parametrize("fmt", ["mkv", "mp4"])
async def test_native_vp9_aac_finalization_does_not_convert_to_ts(tmp_path, fmt):
    from app.engine.base import Platform
    from app.engine.media_inspection import probe_media
    from app.engine.recording_finalizer import RecordingFinalizer
    from tests.test_recording_finalization import terminal

    ffmpeg = get_settings().resolve_ffmpeg_path()
    video, audio = tmp_path / "source.webm", tmp_path / "source.m4a"
    subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=size=3840x2160:rate=30",
                    "-t", "1", "-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "8",
                    "-an", str(video)], check=True, timeout=60)
    subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440",
                    "-t", "1", "-c:a", "aac", str(audio)], check=True, timeout=20)
    before = [p.read_bytes() for p in (video, audio)]
    pipe = YtdlpLivePipeline("test")
    pipe.capture_format = "youtube_dash"
    pipe._output_path = str(video)
    pipe._source_files = [str(video), str(audio)]
    pipe._media_duration = 1
    pipe._update_statistics()
    manager = RecordingFinalizer()
    channel = SimpleNamespace(platform=Platform.YOUTUBE, channel_id="test", channel_name="test")
    job_id = manager.register_capture("youtube:test", pipe, channel,
                                      dict(output_format=fmt, keep_source_ts=True))
    await manager.capture_finished(job_id, pipe)
    try:
        job = await terminal(manager, job_id)
        assert job["state"] == "completed", job
        result = probe_media(job["output_path"])
        assert result["streams"] == {"video", "audio"}
        v = next(t for t in result["tracks"] if t["codec_type"] == "video")
        assert (v["width"], v["height"], v["codec_name"]) == (3840, 2160, "vp9")
        assert [p.read_bytes() for p in (video, audio)] == before
        assert not list(tmp_path.glob("*.ts"))
    finally:
        await manager.close()
