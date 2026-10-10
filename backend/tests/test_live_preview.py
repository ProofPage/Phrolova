"""Playback resolution does not alter monitoring or recording state."""
import asyncio
import json
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api.stream import live_preview
from app.engine.auth import AuthManager
from app.engine.base import Platform
from app.engine.channel import ChannelTask
from app.engine.conductor import Conductor
from app.engine.downloader import ChzzkLiveEngine


def test_chzzk_preview_uses_standard_live_playback(monkeypatch):
    engine = ChzzkLiveEngine(AuthManager())
    detail = AsyncMock(return_value={"status": "OPEN", "livePlaybackJson": json.dumps({
        "media": [{"mediaId": "HLS", "protocol": "HLS", "path": "https://live.navercdn.com/master.m3u8"}],
    })})
    monkeypatch.setattr(engine, "get_live_detail", detail)
    assert asyncio.run(engine.get_preview_url("channel")) == "https://live.navercdn.com/master.m3u8"
    detail.assert_awaited_once_with("channel")


def test_chzzk_preview_stops_when_offline(monkeypatch):
    engine = ChzzkLiveEngine()
    monkeypatch.setattr(engine, "get_live_detail", AsyncMock(return_value={"status": "CLOSE"}))
    with pytest.raises(ValueError, match="오프라인"):
        asyncio.run(engine.get_preview_url("channel"))


def test_preview_leaves_recording_and_monitoring_untouched():
    conductor = Conductor.__new__(Conductor)
    pipeline = object()
    monitor = object()
    channel = ChannelTask("channel", is_live=True, pipeline=pipeline, monitor_task=monitor)
    conductor._channels = {"chzzk:channel": channel}
    engine = SimpleNamespace(get_preview_url=AsyncMock(return_value="https://live.navercdn.com/master.m3u8"))
    conductor._get_engine = lambda _: engine
    assert asyncio.run(conductor.get_live_preview_url("chzzk:channel")).endswith("master.m3u8")
    assert channel.pipeline is pipeline
    assert channel.monitor_task is monitor
    assert channel.auto_record is True
    with pytest.raises(KeyError):
        asyncio.run(conductor.get_live_preview_url("chzzk:removed"))
    channel.is_live = False
    with pytest.raises(ValueError):
        asyncio.run(conductor.get_live_preview_url("chzzk:channel"))


@pytest.mark.parametrize("error,status", [(KeyError("channel"), 404), (ValueError("오프라인"), 409), (ValueError("signed-token-secret"), 409), (RuntimeError("signed-token-secret"), 502)])
def test_preview_api_errors_are_isolated_and_redacted(monkeypatch, error, status):
    import app.main
    monkeypatch.setattr(app.main, "get_recorder_service", lambda: SimpleNamespace(get_live_preview_url=AsyncMock(side_effect=error)))
    with pytest.raises(HTTPException) as captured:
        asyncio.run(live_preview("chzzk:channel"))
    assert captured.value.status_code == status
    assert "signed-token-secret" not in captured.value.detail


def test_preview_response_is_not_cached(monkeypatch):
    import app.main
    resolver = AsyncMock(return_value="https://live.navercdn.com/master.m3u8")
    monkeypatch.setattr(app.main, "get_recorder_service", lambda: SimpleNamespace(get_live_preview_url=resolver))
    response = asyncio.run(live_preview("youtube:channel"))
    assert response.headers["cache-control"] == "no-store"
    resolver.assert_awaited_once_with("youtube:channel")


def test_other_video_platform_reuses_resolver_without_starting_recording(monkeypatch):
    from app.engine.pipeline import YtdlpLivePipeline
    conductor = Conductor.__new__(Conductor)
    channel = ChannelTask("channel", platform=Platform.YOUTUBE, is_live=True)
    conductor._channels = {"youtube:channel": channel}
    conductor._get_engine = lambda _: SimpleNamespace(get_stream_url=lambda _: "https://www.youtube.com/@channel/live")
    resolver = AsyncMock(return_value=("https://example.com/live.m3u8", {}, None))
    monkeypatch.setattr(YtdlpLivePipeline, "_extract_preview_hls_url", resolver)
    monkeypatch.setattr("app.engine.youtube_support.youtube_cookies", lambda: nullcontext("temporary-cookie-copy"))
    assert asyncio.run(conductor.get_live_preview_url("youtube:channel")) == "https://example.com/live.m3u8"
    resolver.assert_awaited_once_with("https://www.youtube.com/@channel/live", cookie_file="temporary-cookie-copy")
    assert channel.pipeline is None


def hls_format(width, height, name="video", **extra):
    return {
        "url": f"https://example.com/{name}.m3u8?signature=signed-token-secret",
        "width": width, "height": height,
        "protocol": "m3u8_native", "vcodec": "avc1.64002a",
        **extra,
    }


@pytest.mark.parametrize("formats,selected_dimensions", [
    ([hls_format(3840, 2160, "4k"), hls_format(1920, 1080, "1080")], (1920, 1080)),
    ([hls_format(2560, 1080, "wide"), hls_format(1920, 1080, "fullhd")], (1920, 1080)),
    ([hls_format(1280, 720, "720"), hls_format(854, 480, "480")], (1280, 720)),
    ([hls_format(854, 480)], (854, 480)),
    ([hls_format(3840, 2160, "4k"), hls_format(1280, 720, "720")], (3840, 2160)),
    ([hls_format(1440, 1080, "4by3"), hls_format(3840, 2160, "4k")], (1440, 1080)),
    ([hls_format(854, 480, "fake-1080p", format_id="1080p"), hls_format(1280, 720, "real720", format_id="480p")], (1280, 720)),
    ([hls_format(3840, 2160, "unsupported", vcodec="vp9"), hls_format(1280, 720, "compatible")], (1280, 720)),
])
def test_preview_prefers_numeric_full_hd_then_highest_available(formats, selected_dimensions):
    from app.engine.pipeline import YtdlpLivePipeline
    selected = YtdlpLivePipeline._select_preview_hls_format({"formats": formats})
    assert (selected["width"], selected["height"]) == selected_dimensions


@pytest.mark.parametrize("extra", [
    {"vcodec": "none"},
    {"protocol": "http_dash_segments", "url": "https://example.com/video.mpd"},
    {"protocol": "https", "url": "https://example.com/video.mp4"},
    {"vcodec": "av01.0.12M.08"},
])
def test_preview_does_not_select_audio_or_nonbrowser_hls(extra):
    from app.engine.pipeline import YtdlpLivePipeline
    unusable = hls_format(1920, 1080, **extra)
    playable = hls_format(1280, 720, "video720")
    assert YtdlpLivePipeline._select_preview_hls_format({
        "url": unusable["url"], "vcodec": "none", "protocol": "m3u8",
        "requested_formats": [unusable, playable],
    }) is playable
    with pytest.raises(RuntimeError, match="영상 HLS"):
        YtdlpLivePipeline._select_preview_hls_format({"formats": [unusable]})


def test_preview_does_not_fabricate_resolution_from_format_names():
    from app.engine.pipeline import YtdlpLivePipeline
    with pytest.raises(RuntimeError, match="영상 HLS"):
        YtdlpLivePipeline._select_preview_hls_format({
            "url": "https://example.com/1080p.m3u8", "format_id": "1080p",
            "acodec": "aac", "protocol": "m3u8_native",
        })


def test_preview_accepts_hls_video_when_only_height_is_available():
    from app.engine.pipeline import YtdlpLivePipeline
    candidate = hls_format(None, 1080)
    assert YtdlpLivePipeline._select_preview_hls_format({"formats": [candidate]}) is candidate


def mock_extract_process(monkeypatch, payload, returncode=0, stderr=b""):
    commands = []

    class FakeProcess:
        def __init__(self):
            self.returncode = returncode

        async def communicate(self):
            data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            return data, stderr

    async def fake_exec(*args, **kwargs):
        commands.append((args, kwargs))
        return FakeProcess()

    monkeypatch.setattr("app.core.config.Settings.resolve_ytdlp_path", lambda self, auto_download=False: "yt-dlp")
    monkeypatch.setattr("app.engine.pipeline.ytdlp.asyncio.create_subprocess_exec", fake_exec)
    return commands


def test_preview_extracts_all_formats_preserves_cookie_copy_and_redacts_logs(monkeypatch, tmp_path, caplog):
    from app.engine.pipeline import YtdlpLivePipeline
    from app.core.logger import logger
    cookie = tmp_path / "쿠키 사본.txt"
    cookie.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    formats = [hls_format(1280, 720, "720"), hls_format(1920, 1080, "1080", http_headers={"Origin": "https://example.com"})]
    commands = mock_extract_process(monkeypatch, {"formats": formats, "cookies": "private-session=secret"})
    pipeline = YtdlpLivePipeline("channel")
    monkeypatch.setattr(logger, "propagate", True)
    with caplog.at_level("INFO", logger="phrolova"):
        url, headers, cookies = asyncio.run(pipeline._extract_preview_hls_url(
            "https://www.youtube.com/@channel/live", cookie_file=str(cookie),
        ))
    assert url == formats[1]["url"]
    assert headers == {"Origin": "https://example.com"}
    assert cookies == "private-session=secret"
    assert cookie.exists()
    command, options = commands[0]
    assert command[command.index("--cookies") + 1] == str(cookie)
    assert "--skip-download" in command
    assert "720" not in command[command.index("--format") + 1]
    assert not options.get("shell")
    assert "signed-token-secret" not in caplog.text
    assert "1920×1080" in caplog.text
    assert "private-session" not in caplog.text
    assert str(cookie) not in caplog.text
    assert pipeline.state.value == "idle"
    assert pipeline._process is None


@pytest.mark.parametrize("payload,returncode,message", [
    (b"invalid-json", 0, "정보를 읽지 못했습니다"),
    (b"null", 0, "정보를 읽지 못했습니다"),
    ({}, 1, "조회 실패"),
])
def test_preview_invalid_response_and_exit_are_redacted(monkeypatch, payload, returncode, message):
    from app.engine.pipeline import YtdlpLivePipeline
    mock_extract_process(monkeypatch, payload, returncode, b"https://example.com?token=signed-token-secret")
    with pytest.raises(RuntimeError, match=message) as captured:
        asyncio.run(YtdlpLivePipeline("channel")._extract_preview_hls_url("https://example.com/live"))
    assert "signed-token-secret" not in str(captured.value)


@pytest.mark.parametrize("interruption", [asyncio.TimeoutError, asyncio.CancelledError])
def test_preview_timeout_and_cancellation_kill_and_reap_process(monkeypatch, interruption):
    from app.engine.pipeline import YtdlpLivePipeline
    calls = []

    class FakeProcess:
        returncode = None

        async def communicate(self):
            calls.append("communicate")
            return b"", b""

        def kill(self):
            calls.append("kill")
            self.returncode = -9

    async def fake_exec(*args, **kwargs):
        return FakeProcess()

    async def interrupted_wait(awaitable, timeout):
        awaitable.close()
        raise interruption()

    monkeypatch.setattr("app.core.config.Settings.resolve_ytdlp_path", lambda self, auto_download=False: "yt-dlp")
    monkeypatch.setattr("app.engine.pipeline.ytdlp.asyncio.create_subprocess_exec", fake_exec)
    monkeypatch.setattr("app.engine.pipeline.ytdlp.asyncio.wait_for", interrupted_wait)
    with pytest.raises(interruption):
        asyncio.run(YtdlpLivePipeline("channel")._extract_preview_hls_url("https://example.com/live"))
    assert calls == ["kill", "communicate"]


def test_recording_keeps_requested_quality_while_preview_selects_independently(monkeypatch):
    from app.engine.pipeline import YtdlpLivePipeline
    payload = {"url": "https://example.com/recording720.m3u8", "formats": [hls_format(1920, 1080)]}
    commands = mock_extract_process(monkeypatch, payload)
    pipeline = YtdlpLivePipeline("channel")
    assert asyncio.run(pipeline._extract_hls_url("https://example.com/live", "720p", None))[0] == payload["url"]
    command = commands[0][0]
    assert command[command.index("--format") + 1] == "best[protocol^=m3u8][height<=720]/best[protocol^=m3u8]"


def test_video_only_full_hd_preserves_master_audio_rendition_connections(monkeypatch, caplog):
    from app.engine.pipeline import YtdlpLivePipeline
    from app.core.logger import logger

    master = "https://example.com/master.m3u8?signature=signed-token-secret"
    full_hd = hls_format(1920, 1080, "video1080", acodec="none", manifest_url=master)
    muxed_hd = hls_format(1280, 720, "muxed720", acodec="mp4a.40.2")
    mock_extract_process(monkeypatch, {"formats": [full_hd, muxed_hd]})
    monkeypatch.setattr(logger, "propagate", True)
    with caplog.at_level("INFO", logger="phrolova"):
        url, _, _ = asyncio.run(YtdlpLivePipeline("channel")._extract_preview_hls_url("https://example.com/live"))
    assert url == master
    assert "1920×1080" in caplog.text
    assert "signed-token-secret" not in caplog.text
    assert master not in caplog.text


@pytest.mark.parametrize("manifest", [
    None, "", "javascript:alert(1)", "file:///master.m3u8", "ftp://example.com/master.m3u8",
    "https:///master.m3u8", "https://[broken/master.m3u8", "https://example.com/manifest.mpd",
    "https://example.com:invalid/master.m3u8", "https://invalid host/master.m3u8",
    "https://example.com/video.mp4", "https://secret:password@example.com/master.m3u8",
])
def test_video_only_without_valid_master_does_not_displace_muxed_video(manifest):
    from app.engine.pipeline import YtdlpLivePipeline

    full_hd = hls_format(1920, 1080, "silent1080", acodec="none", manifest_url=manifest)
    muxed_hd = hls_format(1280, 720, "muxed720", acodec="mp4a.40.2")
    selected = YtdlpLivePipeline._select_preview_hls_format({"formats": [full_hd, muxed_hd]})
    assert selected is muxed_hd


def test_silent_only_broadcast_remains_available_without_upscaling():
    from app.engine.pipeline import YtdlpLivePipeline

    silent_hd = hls_format(1280, 720, "silent720", acodec="none")
    silent_sd = hls_format(854, 480, "silent480", acodec="none")
    assert YtdlpLivePipeline._select_preview_hls_format({"formats": [silent_hd, silent_sd]}) is silent_hd


def test_preview_master_can_use_extensionless_hls_endpoint_and_keeps_format_headers():
    from app.engine.pipeline import YtdlpLivePipeline

    video = hls_format(1920, 1080, acodec="none", manifest_url="https://example.com/hls/master?token=private",
                       http_headers={"Origin": "https://example.com"}, cookies="private-cookie")
    selected = YtdlpLivePipeline._select_preview_hls_format({"formats": [video]})
    assert selected["url"] == video["manifest_url"]
    assert selected["http_headers"] == video["http_headers"]
    assert selected["cookies"] == video["cookies"]
    assert (selected["width"], selected["height"]) == (1920, 1080)
    assert video["url"] != video["manifest_url"]
