from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from streamlink.exceptions import StreamError

from app.engine import rplay_stream
from app.engine.preview_proxy import PreviewProxy
from app.engine.recording_errors import RecordingError

CID = "686fbe0b0d7dc463f4a6efd1"
OLD = "https://example.playlist.live-video.net/old.m3u8"
NEW = "https://example.playlist.live-video.net/new.m3u8"


def worker(monkeypatch, results):
    result = object.__new__(rplay_stream.RplayWorker)
    result.session = SimpleNamespace(http=SimpleNamespace(get=Mock(side_effect=results)))
    result.reader = SimpleNamespace(request_params={})
    result.stream = SimpleNamespace(url=OLD, channel_id=CID, quality="720p60")
    result.sequence = 123
    resolver = AsyncMock(return_value=(NEW, {}, None))
    monkeypatch.setattr(rplay_stream.RplayLiveEngine, "resolve_stream", resolver)
    return result, resolver


def test_expired_playlist_renews_without_resetting_sequence(monkeypatch):
    response = SimpleNamespace(encoding=None)
    instance, resolver = worker(monkeypatch, [StreamError("403 Forbidden"), response])
    assert instance._fetch_playlist() is response
    assert instance.stream.url == NEW and instance.sequence == 123
    resolver.assert_awaited_once_with(CID, "720p60")
    assert instance.session.http.get.call_count == 2


def test_rejected_renewal_is_not_retried_forever(monkeypatch):
    instance, resolver = worker(monkeypatch, [StreamError("403 Forbidden")] * 2)
    with pytest.raises(RecordingError) as caught:
        instance._fetch_playlist()
    assert caught.value.code == "rplay_authentication" and not caught.value.retryable
    assert instance.session.http.get.call_count == 2


def test_transport_error_does_not_request_new_permission(monkeypatch):
    instance, resolver = worker(monkeypatch, [StreamError("Read timeout")])
    with pytest.raises(StreamError):
        instance._fetch_playlist()
    resolver.assert_not_awaited()


@pytest.mark.asyncio
async def test_preview_root_renews_once_and_keeps_opaque_token(monkeypatch):
    proxy = PreviewProxy()
    token = proxy.register("rplay:" + CID, "rplay", OLD)
    import asyncio
    proxy.nodes[token].update(resolver=AsyncMock(return_value=NEW), renewal_lock=asyncio.Lock())
    calls = []
    original = httpx.AsyncClient
    def route(request):
        calls.append(str(request.url))
        return httpx.Response(403 if request.url.path == "/old.m3u8" else 200,
                              text="#EXTM3U\n#EXT-X-TARGETDURATION:2\npart.ts\n")
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(route), **kw))
    data, _, status, _ = await proxy.fetch(token)
    assert status == 200 and calls == [OLD, NEW]
    assert b"live-video.net" not in data and proxy.nodes[token]["url"] == NEW


@pytest.mark.asyncio
async def test_preview_does_not_renew_segments_or_without_resolver(monkeypatch):
    proxy = PreviewProxy()
    token = proxy.register("rplay:" + CID, "rplay", OLD)
    original = httpx.AsyncClient
    calls = []
    def route(request):
        calls.append(request)
        return httpx.Response(403)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(route), **kw))
    with pytest.raises(httpx.HTTPStatusError):
        await proxy.fetch(token)
    assert len(calls) == 1
