import pytest
from unittest.mock import AsyncMock

from app.engine.spoon import SpoonLiveEngine, normalize_spoon_channel_id, media_allowed
from app.engine.berriz import BerrizLiveEngine, normalize_berriz_channel_id
from app.engine.recording_errors import RecordingError


@pytest.mark.parametrize("url", [
    "https://evil.example/kr/channel/1", "https://www.spooncast.net:123/kr/channel/1",
    "https://user@www.spooncast.net/kr/channel/1",
])
def test_spoon_rejects_foreign_urls(url):
    with pytest.raises(ValueError):
        normalize_spoon_channel_id(url)


def test_spoon_normalizes_identity():
    assert normalize_spoon_channel_id("https://www.spooncast.net/kr/channel/508600/tab/home") == "508600"
    assert normalize_spoon_channel_id("https://www.spooncast.net/kr/live/123") == "live:123"
    assert normalize_spoon_channel_id("@zenor") == "@zenor"
    assert not media_allowed("https://localhost/cast/live.m3u8")
    assert not media_allowed("https://kr-hana-live.spooncast.net.evil.example/cast/live.m3u8")
    assert media_allowed("https://kr-hana-live.spooncast.net/cast/live.m3u8")


@pytest.mark.asyncio
async def test_spoon_offline_and_identity():
    engine = SpoonLiveEngine()
    engine._api = AsyncMock(return_value={"result": {"channel": {"id": 123, "currentLiveId": None}}})
    assert (await engine.check_live_status("123"))["is_live"] is False
    with pytest.raises(RecordingError):
        await engine.resolve_stream("123")
    engine._api = AsyncMock(return_value={"result": {"channel": {"id": 999, "currentLiveId": None}}})
    with pytest.raises(RecordingError):
        await engine.check_live_status("123")


def test_berriz_normalizes_identity():
    assert normalize_berriz_channel_id("https://berriz.in/ko/yuhz/live/") == "yuhz"
    with pytest.raises(ValueError):
        normalize_berriz_channel_id("https://link.berriz.in/web/main")
    with pytest.raises(ValueError):
        normalize_berriz_channel_id("https://user@berriz.in/ko/yuhz/")


@pytest.mark.asyncio
async def test_berriz_offline_and_drm():
    engine = BerrizLiveEngine()
    engine._api = AsyncMock(return_value={"contents": []})
    assert (await engine.check_live_status("15"))["is_live"] is False
    with pytest.raises(RecordingError):
        await engine.resolve_stream("15")
    engine._api = AsyncMock(side_effect=[
        {"contents": [{"media": {"mediaId": "01a120d4-49d8-d703-b080-fde4f4642083"}}]},
        {"live": {"isDrm": True, "hls": {"playbackUrl": "https://statics.berriz.in/live.m3u8"}}},
    ])
    with pytest.raises(RecordingError, match="DRM"):
        await engine.resolve_stream("15")


@pytest.mark.asyncio
async def test_berriz_rejects_unknown_drm_and_unsafe_media():
    engine = BerrizLiveEngine()
    engine._playback = AsyncMock(return_value={"playbackUrl": "https://127.0.0.1/live.m3u8"})
    with pytest.raises(RecordingError):
        await engine.resolve_stream("15")


def test_berriz_replay_extractor():
    from app.engine.berriz_extractor import BerrizIE
    from unittest.mock import Mock
    from yt_dlp.utils import ExtractorError
    url = "https://berriz.in/ko/yuhz/live/replay/01a120d4-49d8-d703-b080-fde4f4642083/"
    ie = BerrizIE()
    ie._download_json = Mock(return_value={"code": "0000", "data": {"replay": {
        "isDrm": False, "drmInfo": None, "duration": 2623,
        "hls": {"playbackUrl": "https://statics.berriz.in/cdn/vod/source.m3u8"},
    }}})
    ie._extract_m3u8_formats = Mock(return_value=[{"format_id": "1080", "height": 1080}])
    result = ie._real_extract(url)
    assert result["duration"] == 2623
    assert result["formats"][0]["height"] == 1080
    ie._download_json.return_value["data"]["replay"]["isDrm"] = True
    with pytest.raises(ExtractorError, match="DRM"):
        ie._real_extract(url)
    assert ie._extract_m3u8_formats.call_count == 1
