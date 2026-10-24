"""Channel stream resolution and authorized fallback tests."""
from unittest.mock import AsyncMock

import httpx
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


PREVIOUS = "6575bacd579cf110bca19354"
# 이전 방송의 공유 코드는 현재 방송과 달라야 교체 동작을 검증할 수 있다.
PREVIOUS_STREAM = "6575bacd579cf110bca1d000"
CURRENT = CHANNEL_ID
RETIRED = f"https://livestream.rplay.live/live/{PREVIOUS_STREAM}_abrhd/index.m3u8?userId=usr&token=PRIVATE"
FALLBACK_IVS = f"https://live-video.net/{PREVIOUS}/index.m3u8?token=OLD_AUDIENCE"


def byteplus_item(**overrides):
    return {
        "_id": CURRENT, "creatorOid": CURRENT,
        "creatorMetadata": {"_id": CURRENT, "nickname": "fixture"},
        "streamState": "live", "accessible": True, "useBytePlusStream": True,
        "bytePlusPlaybackUrl": RETIRED,
        "livestreamUrl": FALLBACK_IVS,
        "playUrl": FALLBACK_IVS,
        **overrides,
    }


@pytest.mark.asyncio
async def test_byteplus_stream_id_of_previous_broadcast_is_replaced(monkeypatch):
    """RPLAY renders the stream id into every field, so a field from the previous broadcast
    must not stay the playlist the receiver opens."""
    from urllib.parse import parse_qs, urlsplit
    engine = rp.RplayLiveEngine()
    monkeypatch.setattr(rp, "account_session", lambda: None)
    monkeypatch.setattr(engine, "_metadata", AsyncMock(return_value=byteplus_item()))
    monkeypatch.setattr(engine, "_api", AsyncMock(return_value=True))
    from streamlink.stream.hls import HLSStream
    served = []
    def mock_parse(sl, media, headers=None):
        assert rp.media_allowed(media)
        served.append(media)
        # 서버는 실제로 방송 주소의 서명 쿼리를 그대로 물려준다. 쿼리를 떼고
        # 만들면 뒤의 token 단언이 무엇을 검사하는지 알 수 없게 된다.
        from urllib.parse import urlsplit as split_url
        signature = split_url(media).query
        return {"1080p": HLSStream(sl, f"https://livestream.rplay.live/live/{CURRENT}_abrhd/index.m3u8?{signature}&variant=1080")}
    calls = []
    def route(request):
        calls.append(str(request.url))
        path = urlsplit(str(request.url)).path
        if CURRENT in path:
            return httpx.Response(200, text="#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\nindex_1080.m3u8\n")
        return httpx.Response(404)
    original = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(route), **kw))
    monkeypatch.setattr(HLSStream, "parse_variant_playlist", mock_parse)

    target, _, _ = await engine.resolve_stream(CURRENT, "1080p", force_refresh=True)

    from urllib.parse import urlsplit as split
    assert split(target).path == f"/live/{CURRENT}_abrhd/index.m3u8"
    assert parse_qs(split(target).query)["token"] == ["PRIVATE"]
    assert served and PREVIOUS_STREAM not in served[0] and FALLBACK_IVS not in served

@pytest.mark.parametrize("path,playlist", [
    (f"/live/{PREVIOUS}_abrhd/index.m3u8", "index"),
    (f"/live/{PREVIOUS}/abr.m3u8", "abr"),
    (f"/live/{PREVIOUS}_ud/index.m3u8", "index"),
])
def test_byteplus_stream_id_is_read_from_rplay_media_paths(path, playlist):
    assert rp.byteplus_stream_id(f"https://livestream.rplay.live{path}?token=PRIVATE") == (PREVIOUS, playlist)


@pytest.mark.asyncio
async def test_reconnect_discards_cached_address_before_resolving(monkeypatch):
    """재연결은 방송 중 만료된 주소를 다시 열지 않고 새 주소를 받아야 한다.

    채널 ID 에서 _abrhd 마스터가 나오는 방송에서 첫 연결 주소가 404 로 죽으면,
    재연결에서 같은 캐시를 다시 쓰면 녹화가 끝나 버린다.
    """
    from app.engine.pipeline.ytdlp import YtdlpLivePipeline
    pipeline = YtdlpLivePipeline(CHANNEL_ID)
    pipeline._quality = "720p"
    discarded, resolved = [], []
    fresh = f"https://livestream.rplay.live/live/{CURRENT}_abrhd/index.m3u8?token=FRESH"

    async def resolver(quality):
        resolved.append(quality)
        return fresh, {}, None

    resolver.discard_cached_address = lambda: discarded.append(True)
    pipeline._source_resolver = resolver
    monkeypatch.setattr(pipeline, "_begin_receiver", AsyncMock())
    old = f"https://livestream.rplay.live/live/{CURRENT}_abrhd/index.m3u8?token=EXPIRED"
    pipeline._resume_args = (old, {}, None, 0, False, "720p")

    await pipeline._reconnect_source()

    assert discarded == [True], "재연결은 캐시를 버린 뒤 새 주소를 받아야 합니다."
    assert resolved == ["720p"]
    assert pipeline._resume_args[0] == fresh


@pytest.mark.parametrize("url", [
    "https://livestream.rplay.live/live/short/index.m3u8",
    "https://livestream.rplay.live/api/live/abcdef0123456789/index.m3u8",
    "https://evil.example/live/abcdef0123456789/index.m3u8",
    "http://livestream.rplay.live/live/abcdef0123456789/index.m3u8",
    "https://live-video.net/abcdef0123456789/index.m3u8",
])
def test_non_byteplus_addresses_carry_no_stream_id(url):
    assert rp.byteplus_stream_id(url) is None


def test_current_broadcast_and_signature_fallbacks_are_untouched():
    current = f"https://livestream.rplay.live/live/{CURRENT}_abrhd/index.m3u8?token=PRIVATE"
    assert rp.rplay_playback(byteplus_item(bytePlusPlaybackUrl=current), CURRENT, True) == {
        "media": current, "fallback": FALLBACK_IVS, "byteplus": True}
    # Without a BytePlus field or stream id, the official metadata order decides.
    unsigned = byteplus_item(bytePlusPlaybackUrl="", livestreamUrl=SIGNED_IVS_URL,
                             playUrl=UNSIGNED_IVS_URL)
    assert rp.rplay_playback(unsigned, CURRENT, True) == {
        "media": SIGNED_IVS_URL, "fallback": SIGNED_IVS_URL, "byteplus": True}
