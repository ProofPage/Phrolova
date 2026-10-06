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
    monkeypatch.setattr(YtdlpLivePipeline, "_extract_hls_url", resolver)
    monkeypatch.setattr("app.engine.youtube_support.youtube_cookies", lambda: nullcontext("temporary-cookie-copy"))
    assert asyncio.run(conductor.get_live_preview_url("youtube:channel")) == "https://example.com/live.m3u8"
    resolver.assert_awaited_once_with("https://www.youtube.com/@channel/live", "720p", None, cookie_file="temporary-cookie-copy")
    assert channel.pipeline is None
