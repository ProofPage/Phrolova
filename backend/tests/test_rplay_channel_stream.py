"""Channel stream resolution and authorized fallback tests."""
from unittest.mock import AsyncMock

import pytest

from app.engine import rplay_live as rp
from app.engine import rplay_stream

CHANNEL_ID = "6575bacd579cf110bca19354"
SIGNED_IVS_URL = (
    "https://548e779de76a.ap-northeast-2.playback.live-video.net/api/video/v1/channel.m3u8?token=VALID_TOKEN"
)
UNSIGNED_IVS_URL = (
    "https://548e779de76a.ap-northeast-2.playback.live-video.net/api/video/v1/channel.m3u8"
)
BYTEPLUS_URL = f"https://livestream.rplay.live/live/{CHANNEL_ID}/abr.m3u8"


@pytest.mark.asyncio
async def test_fallback_media_prioritizes_signed_livestream_url(monkeypatch):
    """When BytePlus stream authorization fails, fallback must use the signed livestreamUrl over unsigned playUrl."""
    item = {
        "_id": CHANNEL_ID,
        "creatorOid": CHANNEL_ID,
        "creatorMetadata": {"_id": CHANNEL_ID, "nickname": "test_streamer"},
        "streamState": "live",
        "accessible": True,
        "useBytePlusStream": True,
        "bytePlusPlaybackUrl": BYTEPLUS_URL,
        "playUrl": UNSIGNED_IVS_URL,
        "livestreamUrl": SIGNED_IVS_URL,
    }
    engine = rp.RplayLiveEngine()
    monkeypatch.setattr(rp, "account_session", lambda: {"accessToken": "tok", "requestorOid": "usr"})
    monkeypatch.setattr(engine, "_metadata", AsyncMock(return_value=item))
    monkeypatch.setattr(engine, "_api", AsyncMock(return_value=False))  # /bytedance/auth fails

    parsed_urls = []

    def mock_parse(sl, media, headers=None):
        parsed_urls.append(media)
        from streamlink.stream.hls import HLSStream
        return {"720p": HLSStream(sl, "https://548e779de76a.live-video.net/v1/720p.m3u8")}

    from streamlink.stream.hls import HLSStream
    monkeypatch.setattr(HLSStream, "parse_variant_playlist", mock_parse)

    variants = await engine._streams(CHANNEL_ID)
    assert len(parsed_urls) == 1
    assert parsed_urls[0] == SIGNED_IVS_URL
    assert "token=VALID_TOKEN" in parsed_urls[0]
    assert len(variants) == 1


def test_renew_passes_force_refresh(monkeypatch):
    """RplayHLSStream.renew must invoke resolve_stream with force_refresh=True to avoid stale cached grants."""
    from streamlink import Streamlink
    stream = rplay_stream.RplayHLSStream(Streamlink(plugins_builtin=False), "https://livestream.rplay.live/old.m3u8", CHANNEL_ID, "best")
    resolver = AsyncMock(return_value=("https://livestream.rplay.live/new.m3u8", {}, None))
    monkeypatch.setattr(rplay_stream.RplayLiveEngine, "resolve_stream", resolver)

    renewed = stream.renew(0)
    assert renewed == "https://livestream.rplay.live/new.m3u8"
    resolver.assert_awaited_once_with(CHANNEL_ID, "best", force_refresh=True)
    assert stream.renewal_revision == 1
    stream.session.http.close()
