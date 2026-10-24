"""숲 입력 경계, 장애 처리 및 미리보기 연결 회귀 검사."""
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from app.engine.soop import SoopLiveEngine, normalize_soop_channel_id
from app.engine.vod_preparation import canonical_prepared_url
from app.engine.preview_proxy import PreviewProxy


@pytest.mark.parametrize("value", [
    "y1026", "https://play.sooplive.com/y1026/298074801",
    "play.sooplive.com/y1026",
])
def test_channel_identity(value):
    assert normalize_soop_channel_id(value) == "y1026"


@pytest.mark.parametrize("value", [
    "", "ab cd", "https://evil.example/y1026",
    "https://play.sooplive.com.evil.example/y1026",
    "https://user:secret@play.sooplive.com/y1026",
    "https://play.sooplive.com:444/y1026",
    "ftp://play.sooplive.com/y1026",
    "https://play.sooplive.com/y1026/invalid",
    "https://vod.sooplive.com/player/210593175",
])
def test_invalid_channel(value):
    with pytest.raises(ValueError):
        normalize_soop_channel_id(value)


@pytest.mark.parametrize("video", ["210593175", "210373955"])
def test_vod_preparation(video):
    assert canonical_prepared_url(
        f"https://vod.sooplive.com/player/{video}?tracking=1", "soop"
    ) == f"https://vod.sooplive.com/player/{video}"


@pytest.mark.parametrize("value", [
    "https://play.sooplive.com/y1026/298074801",
    "https://evil.example/player/210593175",
    "https://user:secret@vod.sooplive.com/player/210593175",
])
def test_reject_non_vod(value):
    with pytest.raises(ValueError):
        canonical_prepared_url(value, "soop")


@pytest.mark.asyncio
async def test_api_failure_is_not_offline(monkeypatch):
    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url):
            raise httpx.ReadTimeout("timeout")

    monkeypatch.setattr("app.engine.soop.httpx.AsyncClient", lambda **kwargs: Client())
    engine = SoopLiveEngine()
    with pytest.raises(RuntimeError):
        await engine.check_live_status("y1026")
    assert not engine._cache


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [False, True])
async def test_stream_session_closes(monkeypatch, failure):
    import streamlink
    session = Mock()
    session.streams.return_value = {"best": Mock(to_url=lambda: "https://cdn.sooplive.com/live.m3u8")}
    if failure:
        session.streams.side_effect = RuntimeError("stream unavailable")
    monkeypatch.setattr(streamlink.session, "Streamlink", lambda: session)
    engine = SoopLiveEngine()
    if failure:
        with pytest.raises(RuntimeError):
            await engine.resolve_stream("y1026")
    else:
        assert (await engine.resolve_stream("y1026"))[0].endswith(".m3u8")
    session.http.close.assert_called_once()


@pytest.mark.asyncio
async def test_preview_is_manifest_not_webpage():
    engine = SoopLiveEngine()
    manifest = "https://cdn.sooplive.com/live.m3u8"
    engine.resolve_stream = AsyncMock(return_value=(manifest, {}, None))
    assert await engine.get_preview_url("y1026") == manifest
    assert PreviewProxy.allowed(manifest, set(), "soop")
    assert not PreviewProxy.allowed("https://sooplive.com.evil.example/live.m3u8", set(), "soop")


@pytest.mark.asyncio
async def test_preview_sends_required_origin_and_rewrites_segments(monkeypatch):
    from app.engine import preview_proxy as module
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, text="#EXTM3U\n#EXTINF:2,\nsegment.ts\n")

    client_type = httpx.AsyncClient
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kwargs: client_type(
        **kwargs, transport=httpx.MockTransport(respond)))
    proxy = PreviewProxy()
    token = proxy.register("soop:y1026", "soop", "https://cdn.sooplive.com/live.m3u8")
    body, kind, status, _ = await proxy.fetch(token)
    assert status == 200 and kind == "application/vnd.apple.mpegurl"
    assert requests[0].headers["Origin"] == "https://play.sooplive.com"
    assert requests[0].headers["Referer"] == "https://play.sooplive.com/"
    assert b"/api/stream/preview-media/" in body
    assert b"https://cdn.sooplive.com/" not in body
