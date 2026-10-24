"""Keep real rendition metadata from quality discovery through recording setup."""
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.engine.live_quality import hls_quality_options
from app.engine.chzzk_time_machine import _select_variant
from app.engine.pipeline.ytdlp import YtdlpLivePipeline
from app.engine.kick import KickLiveEngine
from app.engine.twitch import TwitchLiveEngine
from app.engine.tiktok import TikTokLiveEngine
from app.engine.bilibili import BilibiliLiveEngine
from app.engine.pandalive import PandaliveLiveEngine
from app.engine.popkontv import PopkonTVLiveEngine
from app.engine.rplay_live import RplayLiveEngine
from tests.test_new_platforms import local_hls

MASTER = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=6000000,RESOLUTION=1920x1080,FRAME-RATE=60
60/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=7000000,RESOLUTION=1920x1080,FRAME-RATE=30
30/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=2000000,RESOLUTION=1280x720
720/index.m3u8
"""
URL = "https://live.pstatic.net/master.m3u8"


def test_manifest_dimensions_and_frame_rates_are_not_inferred():
    options = hls_quality_options(MASTER, URL)
    assert [(q["value"], q["width"], q["height"], q["fps"]) for q in options] == [
        ("1080p60", 1920, 1080, 60), ("1080p30", 1920, 1080, 30),
        ("720p", 1280, 720, None),
    ]
    assert hls_quality_options("#EXTM3U\n#EXTINF:2,\nsegment.ts", URL) == []


def test_chzzk_selection_respects_requested_frame_rate():
    assert _select_variant(MASTER, URL, "1080p60")[0].endswith("/60/index.m3u8")
    assert _select_variant(MASTER, URL, "1080p30")[0].endswith("/30/index.m3u8")
    assert _select_variant(MASTER, URL, "720p")[0].endswith("/720/index.m3u8")


@pytest.mark.asyncio
async def test_chzzk_quality_discovery_uses_manifest(monkeypatch):
    from app.engine import downloader
    engine = downloader.ChzzkLiveEngine()
    monkeypatch.setattr(engine, "get_preview_url", AsyncMock(return_value=URL))
    response = SimpleNamespace(text=MASTER, url=URL, raise_for_status=Mock())
    client = SimpleNamespace(get=AsyncMock(return_value=response))
    monkeypatch.setattr(downloader, "get_http_client", lambda: client)
    assert (await engine.get_qualities("fixture"))[0]["width"] == 1920


@pytest.mark.asyncio
@pytest.mark.parametrize("engine_type", [
    KickLiveEngine, TwitchLiveEngine, TikTokLiveEngine, BilibiliLiveEngine,
    PandaliveLiveEngine, PopkonTVLiveEngine, RplayLiveEngine,
])
async def test_selected_rendition_reaches_pipeline(monkeypatch, engine_type):
    variant = dict(value="1080p60", label="1080p60", width=1920, height=1080,
                   fps=60, bitrate=6000000, weight=1, quality_id=10000,
                   container="ts", _verified_at=time.monotonic(), url=URL)
    engine = engine_type()
    channel_id = "12345" if engine_type is BilibiliLiveEngine else "a" * 24
    streams = ([variant], {"Referer": "https://kick.com/"}) if engine_type is KickLiveEngine else [variant]
    monkeypatch.setattr(engine, "_streams", AsyncMock(return_value=streams))
    pipeline = YtdlpLivePipeline("fixture")
    url, headers, cookies = await pipeline._resolve_stream_spec(engine, channel_id, "1080p60")
    assert url == URL and isinstance(headers, dict) and cookies is None
    assert pipeline.recording_resolution == {"width": 1920, "height": 1080, "fps": 60}
    assert (await engine.resolve_stream(channel_id, "1080p60"))[0] == URL


@pytest.mark.asyncio
async def test_open_reader_keeps_actual_master_selection(monkeypatch):
    resolution = {"width": 1280, "height": 720, "fps": 29.97}
    reader = SimpleNamespace(close=Mock())
    stream = SimpleNamespace(recording_resolution=resolution, open=lambda: reader)
    session = SimpleNamespace(http=SimpleNamespace(close=Mock()))
    pipeline = YtdlpLivePipeline("fixture")
    monkeypatch.setattr(pipeline, "_create_streamlink_stream", lambda *a, **k: (session, stream))
    assert await pipeline._open_raw_readers() == (session, [reader])
    assert pipeline.recording_resolution == resolution


def test_real_master_selection_exposes_rendition_dimensions(local_hls):
    base, _ = local_hls
    session, stream = YtdlpLivePipeline._create_streamlink_stream(
        base + "/master.m3u8", {}, None, 0, False, "720p")
    try:
        assert stream.recording_resolution == {"width": 1280, "height": 720, "fps": 5}
    finally:
        session.http.close()


def test_chzzk_quality_endpoint_returns_real_metadata(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import app.main
    from app.api import platforms

    engine = SimpleNamespace(
        check_live_status=AsyncMock(return_value={"is_live": True}),
        get_qualities=AsyncMock(return_value=hls_quality_options(MASTER, URL)))
    service = SimpleNamespace(_conductor=SimpleNamespace(_get_engine=lambda platform: engine))
    monkeypatch.setattr(app.main, "get_recorder_service", lambda: service)
    app = FastAPI()
    app.include_router(platforms.router)
    with TestClient(app) as client:
        response = client.get("/api/platforms/chzzk/" + "a" * 32 + "/qualities")
    assert response.status_code == 200
    assert response.json()["qualities"][0]["fps"] == 60
    assert response.json()["qualities"][0]["width"] == 1920
