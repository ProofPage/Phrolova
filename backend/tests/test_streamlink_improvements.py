"""Transport options, bounded loss reports, capture state and measured FPS contracts."""
import asyncio
import base64
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
from pydantic import ValidationError
import pytest
import requests
from streamlink import Streamlink
from streamlink.exceptions import StreamError
from streamlink.stream.hls import HLSStream, HLSStreamReader, HLSStreamWriter

from app.core.config import Settings, get_settings
from app.core.streamlink_settings import StreamlinkPlatformOptions
from app.engine.base import Platform
from app.engine.channel import ChannelTask
from app.engine.conductor import Conductor
from app.engine.pipeline import RecordingState, YtdlpLivePipeline
from app.engine.recording_loss import RecordingLossReport
from app.engine.streamlink_support import StreamQueryAuth, configure_streamlink_session, guarded_hls_stream
from tests.test_new_platforms import local_hls


@pytest.mark.parametrize("method,args,code", [
    ("_write_plain", (object(), object()), "segment_write"),
    ("_write_decrypt", (object(), object(), object()), "segment_decrypt"),
])
def test_failed_segment_write_cannot_be_counted_as_success(monkeypatch, method, args, code):
    from app.engine.recording_errors import RecordingError
    monkeypatch.setattr(HLSStreamWriter, method, lambda *args: False)
    writer_type = guarded_hls_stream(HLSStream).__reader__.__writer__
    writer = object.__new__(writer_type)
    with pytest.raises(RecordingError) as caught:
        getattr(writer, method)(*args)
    assert caught.value.code == code and caught.value.retryable


def test_initialization_map_is_not_counted_as_a_completed_media_segment(monkeypatch):
    monkeypatch.setattr(HLSStreamWriter, "write", lambda *args: None)
    writer_type = guarded_hls_stream(HLSStream).__reader__.__writer__
    writer = object.__new__(writer_type)
    report = RecordingLossReport()
    writer.session = SimpleNamespace(_phrolova_loss_report=report)
    writer.stream = SimpleNamespace(_phrolova_track_id="video")
    writer.should_filter_segment = lambda segment: False
    segment = SimpleNamespace(num=10)
    writer.write(segment, object(), True)
    assert report.snapshot()["tracks"] == {}
    writer.write(segment, object(), False)
    assert report.snapshot()["tracks"]["video"]["completed_segment_writes"] == 1


@pytest.mark.parametrize("order", [
    "import streamlink; import yt_dlp.networking._requests",
    "import yt_dlp.networking._requests; import streamlink",
])
def test_downloader_import_orders_preserve_request_url_parsing(order):
    code = order + """\nimport app.core.http\nimport requests\nurl = requests.Request('GET', 'https://ExAmPlE.com/path%2fsegment?value=a%20b').prepare().url\nassert url == 'https://example.com/path%2fsegment?value=a%20b', url\n"""
    subprocess.run([sys.executable, "-c", code], check=True, timeout=20)


@pytest.mark.parametrize("value", [-1, 0.1, 1, 61, float("nan"), float("inf")])
def test_reload_interval_is_supported_by_streamlink(value):
    with pytest.raises(ValidationError):
        StreamlinkPlatformOptions(playlist_reload_seconds=value)


@pytest.mark.parametrize("parameters", [{"": "x"}, {"ok": "x\nsecret"}, {"bad\rkey": "x"}, {"key": 3},
                                      {str(index): "x" for index in range(33)}])
def test_query_schema_rejects_invalid_values(parameters):
    with pytest.raises(ValidationError):
        StreamlinkPlatformOptions(query_parameters=parameters)


def test_options_roundtrip_and_vod_formats(monkeypatch, tmp_path):
    from app.api.settings.media import router
    import app.core.utils as utils
    monkeypatch.setattr(utils, "_get_env_path", lambda: tmp_path / ".env")
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    options = {"cime": {"playlist_reload_seconds": 3, "query_parameters": {"cache": "a & b"}}}
    response = client.put("/api/settings/live", json={"max_record_retries": 3, "streamlink_platform_options": options})
    assert response.status_code == 200, response.text
    assert response.json()["settings"]["streamlink_platform_options"] == options
    restored = Settings(_env_file=tmp_path / ".env")
    assert restored.streamlink_platform_options[Platform.CIME].query_parameters == {"cache": "a & b"}
    assert client.put("/api/settings/live", json={"max_record_retries": 3, "streamlink_platform_options": {"unknown": {}}}).status_code == 422
    assert client.put("/api/settings/vod", json={"vod_format": "ts"}).status_code == 400
    assert client.put("/api/settings/vod", json={"vod_format": "mkv"}).status_code == 200
    assert Settings(vod_format="ts").vod_format == "mp4"
    assert Settings().live_format == "mkv"


def test_forced_queries_replace_keys_preserve_auth_and_stay_scoped(monkeypatch):
    from urllib.parse import parse_qs, urlsplit
    settings = get_settings()
    monkeypatch.setattr(settings, "streamlink_platform_options", {
        "cime": StreamlinkPlatformOptions(playlist_reload_seconds=3, query_parameters={"cache": "new & value"})
    })
    session = Streamlink(plugins_builtin=False)
    seen = []
    def authorize(request):
        seen.append(parse_qs(urlsplit(request.url).query))
        request.headers["Authorization"] = "test-only"
        return request
    session.http.auth = authorize
    try:
        configure_streamlink_session(session, "cime", "https://view.ci.me/uhd/1/playlist.m3u8")
        prepared = session.http.prepare_request(requests.Request("GET", "https://view.ci.me/uhd/1/segment.m4s?cache=old&keep=yes"))
        assert parse_qs(urlsplit(prepared.url).query) == {"cache": ["new & value"], "keep": ["yes"]}
        assert seen[-1]["cache"] == ["new & value"] and prepared.headers["Authorization"] == "test-only"
        assert session.get_option("hls-playlist-reload-time") == 3
        foreign = session.http.prepare_request(requests.Request("GET", "https://evil.example/segment.m4s"))
        assert not urlsplit(foreign.url).query
        other_platform = session.http.prepare_request(requests.Request("GET", "https://video.googlevideo.com/segment.m4s"))
        assert not urlsplit(other_platform.url).query
        configure_streamlink_session(session, "youtube", "https://www.youtube.com/@sample/live")
    finally:
        session.http.close()


def test_loss_report_summarizes_large_gaps_without_enumerating(tmp_path):
    report = RecordingLossReport()
    report.segment("video", 1)
    report.segment("video", 2**63)
    for index in range(70):
        report.segment("audio", index * 2)
    report.segment("video", 3)
    path = report.write(tmp_path / "recording.ts", {"file_size_bytes": 188, "duration_seconds": 1})
    body = json.loads(Path(path).read_text(encoding="utf-8"))
    assert body["tracks"]["video"]["sequence_gaps"] == [{"first": 2, "last": 2**63 - 1}]
    assert body["tracks"]["video"]["sequence_resets"] == 1
    assert len(body["tracks"]["audio"]["sequence_gaps"]) == 64 and body["omitted_ranges"] == 5
    assert Path(path).stat().st_size < 10000
    with pytest.raises(ValueError):
        report.segment("video", 2**64)
    report.transport = "http-flv"
    assert report.snapshot()["segment_tracking"] == "not_applicable"


def test_unexpected_segment_future_errors_are_propagated_and_closed(local_hls):
    base, _ = local_hls
    class FailingWriter(HLSStreamWriter):
        def fetch(self, segment):
            raise RuntimeError("failed https://cdn.example/segment?token=PRIVATE")
    class Reader(HLSStreamReader):
        __writer__ = FailingWriter
    class Stream(HLSStream):
        __reader__ = Reader
    session = Streamlink(plugins_builtin=False)
    session.set_option("stream-timeout", 2)
    configure_streamlink_session(session, "cime", base, RecordingLossReport())
    reader = guarded_hls_stream(Stream)(session, base + "/720/index.m3u8").open()
    try:
        with pytest.raises(StreamError) as caught:
            reader.read(1024)
        assert "PRIVATE" not in str(caught.value)
    finally:
        reader.close()
        session.http.close()
    assert not reader.worker.is_alive() and not reader.writer.is_alive()


@pytest.mark.asyncio
async def test_real_capture_writes_losscheck_after_file_is_closed(local_hls):
    base, folder = local_hls
    pipeline = YtdlpLivePipeline("fixture")
    try:
        await pipeline.start_recording(stream_obj="https://ci.me/@fixture/live", output_dir=str(folder / "capture"),
                                       quality="720p", source_resolver=AsyncMock(return_value=(base + "/720/index.m3u8", {}, None)))
        await asyncio.wait_for(asyncio.shield(pipeline._feeder_task), 15)
        await pipeline.stop_recording()
        report = json.loads(Path(pipeline.losscheck_path).read_text(encoding="utf-8"))
        assert pipeline._closed and report["file_size_bytes"] == Path(pipeline.output_path).stat().st_size
        assert report["tracks"]["0"]["first_sequence"] == 0
        assert report["tracks"]["0"]["completed_segment_writes"] == 3
        assert report["tracks"]["0"]["sequence_gaps"] == []
        assert report["duration_seconds"] > 1
    finally:
        await pipeline.stop_recording()


@pytest.mark.parametrize("incoming", [None, "", "   "])
def test_missing_streamer_name_keeps_target_name(incoming):
    task = ChannelTask("fixture", channel_name="Saved target name")
    Conductor._apply_status(task, {"is_live": True, "channel_name": incoming})
    assert task.channel_name == "Saved target name"
    task.channel_name = None
    Conductor._apply_status(task, {"is_live": True, "channel_name": incoming})
    assert task.channel_name == "fixture"


@pytest.mark.asyncio
async def test_manual_retry_resets_cooldown_without_startup_wait(monkeypatch):
    conductor = Conductor()
    task = ChannelTask("fixture", channel_name="Saved name", retry_blocked=True, retry_count=10,
                       last_error="Old failure", retry_at="2099-01-01T00:00:00")
    conductor._channels["cime:fixture"] = task
    task.platform = Platform.CIME
    monkeypatch.setattr(conductor, "_get_engine", lambda _: SimpleNamespace(
        get_stream_url=lambda _: "https://ci.me/@fixture/live",
        check_live_status=AsyncMock(return_value={"is_live": True, "channel_name": ""}),
        resolve_stream=AsyncMock(),
    ))
    monkeypatch.setattr(conductor.finalizer, "start", AsyncMock())
    async def start(pipeline, **kwargs):
        pipeline._state = RecordingState.RECORDING
        return "fixture.ts"
    monkeypatch.setattr(YtdlpLivePipeline, "start_recording", start)
    sleep = AsyncMock()
    monkeypatch.setattr("app.engine.conductor.asyncio.sleep", sleep)
    await conductor.start_manual_recording("cime:fixture")
    assert task.channel_name == "Saved name" and not task.retry_blocked and task.retry_count == 0
    assert task.retry_at is None and task.last_error is None
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_skip_status_waits_for_closed_writer(monkeypatch):
    conductor = Conductor()
    conductor._running = True
    task = ChannelTask("fixture", is_live=True, capture_automatic=True, download_condition="watchalong")
    conductor._channels["chzzk:fixture"] = task
    class Pipe:
        state = RecordingState.RECORDING
        _closed = False
        async def stop_recording(self):
            assert task.skip_pending and conductor._download_hold_reason(task) is None
            self.state = RecordingState.COMPLETED
            self._closed = True
        def get_status(self):
            return {"state": "completed", "is_recording": False}
    task.pipeline = Pipe()
    monkeypatch.setattr(conductor, "_get_engine", lambda _: SimpleNamespace(
        check_live_status=AsyncMock(return_value={"is_live": True, "channel_name": "Fixture", "is_watchalong": False,
                                                  "broadcast_tags": []})
    ))
    monkeypatch.setattr(conductor, "_save_live_history", lambda *args: None)
    async def finish(*args):
        conductor._running = False
    monkeypatch.setattr(conductor, "_wait_for_next_scan", finish)
    await conductor._monitor_channel("chzzk:fixture")
    assert task.pipeline is None and not task.skip_pending
    assert conductor._download_hold_reason(task) is not None


@pytest.mark.asyncio
async def test_stop_error_after_writer_closed_does_not_keep_a_stale_capture():
    conductor = Conductor()
    task = ChannelTask("fixture")
    task.pipeline = SimpleNamespace(_closed=True, state=RecordingState.ERROR,
                                    stop_recording=AsyncMock(side_effect=RuntimeError("closed with error")),
                                    get_status=lambda: {"state": "error", "is_recording": False})
    conductor._channels["chzzk:fixture"] = task
    with pytest.raises(RuntimeError, match="closed with error"):
        await conductor._stop_recording("chzzk:fixture")
    assert task.pipeline is None


def test_near_expiry_cookies_and_tokens_are_not_reused(monkeypatch, tmp_path):
    from app.engine import platform_auth, rplay
    monkeypatch.setattr(platform_auth.time, "time", lambda: 1000.0)
    path = tmp_path / "cookies.txt"
    path.write_text("# Netscape HTTP Cookie File\n.ci.me\tTRUE\t/\tTRUE\t1010\tsession\tsoon\n")
    monkeypatch.setattr(get_settings(), "cime_cookie_file", str(path))
    assert not len(platform_auth.platform_cookie_jar("cime"))
    assert platform_auth.platform_cookie_status("cime")["expired"]
    payload = base64.urlsafe_b64encode(b'{"exp":1020}').decode().rstrip("=")
    assert rplay.session_expired({"accessToken": f"header.{payload}.signature"})


def test_fps_comes_from_frame_timestamps_without_altering_original_metadata(monkeypatch, tmp_path):
    from app.engine.media_inspection import probe_media
    import subprocess
    file = tmp_path / "sample.mp4"
    file.write_bytes(b"fixture")
    monkeypatch.setattr(Settings, "resolve_ffprobe_path", lambda self: "ffprobe")
    body = {"format": {"duration": "1", "format_name": "mp4"}, "streams": [
        {"index": 0, "codec_type": "video", "width": 1920, "height": 1080, "avg_frame_rate": "1000/1"}
    ], "frames": [{"stream_index": 0, "media_type": "video", "best_effort_timestamp_time": value}
                   for value in ("0", "0.04", "0.08")]}
    monkeypatch.setattr(subprocess, "run", lambda args, **kwargs: subprocess.CompletedProcess(
        args, 0, json.dumps(body).encode(), b""))
    video = probe_media(str(file))["tracks"][0]
    assert video["fps"] == 25 and video["fps_source"] == "sampled_frame_timestamps"
    assert video["avg_frame_rate"] == "1000/1"


@pytest.mark.asyncio
async def test_multi_import_metadata_runs_asynchronous_tasks(monkeypatch):
    from app.engine.vod import VodEngine
    engine = VodEngine()
    gate = asyncio.Event()
    started = []
    async def metadata(url):
        started.append(url)
        await gate.wait()
        return {"id": url.rsplit("/", 1)[-1], "formats": [{"height": 720, "vcodec": "avc1", "format_id": "720"}]}
    monkeypatch.setattr(engine, "get_video_info", metadata)
    try:
        engine.prepare_vods(["https://chzzk.naver.com/video/1", "https://chzzk.naver.com/video/2"])
        await asyncio.sleep(0)
        assert len(started) == 2
        gate.set()
        await asyncio.gather(*list(engine._metadata_tasks))
        assert all(task.phase == "ready" for task in engine._tasks.values())
    finally:
        gate.set()
        await engine.shutdown()
