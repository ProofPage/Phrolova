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
    from streamlink import Streamlink
    from app.engine.streamlink_support import guarded_hls_stream
    session = Streamlink(plugins_builtin=False)
    stream = guarded_hls_stream(rplay_stream.RplayHLSStream)(
        session, OLD, CID, "720p60", headers={"Origin": "https://rplay.live"})
    result = object.__new__(stream.__reader__.__worker__)
    result.session = session
    monkeypatch.setattr(session.http, "get", Mock(side_effect=results))
    result.reader = SimpleNamespace(request_params={"headers": {"Origin": "https://rplay.live"}})
    result.stream = stream
    result.sequence = 123
    resolver = AsyncMock(return_value=(NEW, {}, None))
    monkeypatch.setattr(rplay_stream.RplayLiveEngine, "resolve_stream", resolver)
    return result, resolver


def test_expired_playlist_renews_without_resetting_sequence(monkeypatch):
    response = SimpleNamespace(encoding=None)
    instance, resolver = worker(monkeypatch, [StreamError("403 Forbidden"), response])
    assert instance._fetch_playlist() is response
    assert instance.stream.url == NEW and instance.sequence == 123
    assert instance.stream.to_url() == NEW
    assert instance.stream.args["headers"] == {"Origin": "https://rplay.live"}
    assert instance.session.http.get.call_args.args[0] == NEW
    resolver.assert_awaited_once_with(CID, "720p60")
    assert instance.session.http.get.call_count == 2


def test_500_server_error_playlist_renews_without_breaking_stream(monkeypatch):
    response = SimpleNamespace(encoding=None)
    instance, resolver = worker(monkeypatch, [StreamError("500 Server Error: Internal Server Error"), response])
    assert instance._fetch_playlist() is response
    assert instance.stream.url == NEW and instance.sequence == 123
    assert instance.stream.to_url() == NEW
    assert instance.session.http.get.call_args.args[0] == NEW
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


def test_repeated_renewal_updates_real_stream_without_replacing_worker(monkeypatch):
    response = SimpleNamespace(encoding=None)
    instance, resolver = worker(monkeypatch, [
        StreamError("403 Forbidden"), response, StreamError("401 Unauthorized"), response])
    latest = NEW + "?token=FIXTURE-PRIVATE"
    resolver.side_effect = [(NEW, {}, None), (latest, {}, None)]
    stream = instance.stream
    assert instance._fetch_playlist() is response
    assert instance._fetch_playlist() is response
    assert instance.stream is stream
    assert stream.to_url() == latest and instance.sequence == 123
    assert [call.args[0] for call in instance.session.http.get.call_args_list] == [OLD, NEW, NEW, latest]


def test_untrusted_renewal_does_not_change_stream_or_request_destination(monkeypatch):
    instance, resolver = worker(monkeypatch, [StreamError("403 Forbidden")])
    resolver.return_value = ("https://evil.example/playlist.m3u8", {}, None)
    with pytest.raises(RecordingError, match="허용"):
        instance._fetch_playlist()
    assert instance.stream.to_url() == OLD
    assert instance.session.http.get.call_count == 1


def test_denied_new_grant_does_not_retry_media(monkeypatch):
    instance, resolver = worker(monkeypatch, [StreamError("403 Forbidden")])
    resolver.side_effect = RecordingError("rplay_access", "시청 권한이 없습니다.")
    with pytest.raises(RecordingError) as caught:
        instance._fetch_playlist()
    assert caught.value.code == "rplay_access" and not caught.value.retryable
    assert instance.stream.to_url() == OLD
    assert instance.session.http.get.call_count == 1


@pytest.mark.parametrize("message", ["403 Forbidden token=PRIVATE", "Read timeout", "HTTP 503"])
def test_segment_fetch_failure_is_not_silently_skipped(message):
    writer = object.__new__(rplay_stream.RplayReader.__writer__)
    writer.closed = False
    writer.timeout = 30
    writer.stream_data = False
    writer.session = SimpleNamespace(http=SimpleNamespace(get=Mock(side_effect=StreamError(message))))
    writer.create_request_params = Mock(return_value={})
    with pytest.raises(RecordingError) as caught:
        writer.fetch(SimpleNamespace(uri=OLD, num=123))
    assert caught.value.code == "rplay_segment_connection" and caught.value.retryable
    assert "PRIVATE" not in str(caught.value)
    assert writer.session.http.get.call_args.kwargs["retries"] == 1


def test_segment_inherits_stream_query_parameters():
    writer = object.__new__(rplay_stream.RplayReader.__writer__)
    writer.closed = False
    writer.timeout = 30
    writer.stream_data = False
    writer.create_request_params = Mock(return_value={})
    mock_get = Mock(return_value=SimpleNamespace())
    writer.session = SimpleNamespace(http=SimpleNamespace(get=mock_get))
    stream_url = "https://livestream.rplay.live/live/123/abr.m3u8?creatorId=abc&token=xyz"
    writer.reader = SimpleNamespace(stream=SimpleNamespace(url=stream_url, channel_id="123", quality="720p"))
    writer.fetch(SimpleNamespace(uri="https://livestream.rplay.live/live/123/segment_0.ts", num=1))
    called_url = mock_get.call_args.args[0]
    from urllib.parse import parse_qs, urlsplit
    query = parse_qs(urlsplit(called_url).query)
    assert query["creatorId"] == ["abc"] and query["token"] == ["xyz"]


def test_segment_403_renews_token_and_retries_successfully(monkeypatch):
    writer = object.__new__(rplay_stream.RplayReader.__writer__)
    writer.closed = False
    writer.timeout = 30
    writer.stream_data = False
    writer.create_request_params = Mock(return_value={})
    success_response = SimpleNamespace()
    mock_get = Mock(side_effect=[StreamError("403 Forbidden"), success_response])
    writer.session = SimpleNamespace(http=SimpleNamespace(get=mock_get))
    old_stream = "https://livestream.rplay.live/live/123/abr.m3u8?token=old"
    stream_obj = SimpleNamespace(url=old_stream, args={"url": old_stream}, channel_id=CID, quality="720p")
    writer.reader = SimpleNamespace(stream=stream_obj)
    new_stream = "https://livestream.rplay.live/live/123/abr.m3u8?token=fresh_token"
    monkeypatch.setattr(rplay_stream.RplayLiveEngine, "resolve_stream", AsyncMock(return_value=(new_stream, {}, None)))
    result = writer.fetch(SimpleNamespace(uri="https://livestream.rplay.live/live/123/segment_0.ts", num=1))
    assert result is success_response
    assert mock_get.call_count == 2
    from urllib.parse import parse_qs, urlsplit
    called_url = mock_get.call_args_list[1].args[0]
    assert parse_qs(urlsplit(called_url).query)["token"] == ["fresh_token"]


def test_mid_segment_disconnect_reaches_guarded_reader():
    from requests.exceptions import ChunkedEncodingError
    writer = object.__new__(rplay_stream.RplayReader.__writer__)
    writer.iter_segment_content = Mock(side_effect=ChunkedEncodingError("connection lost"))
    writer._write_into_buffer = Mock()
    with pytest.raises(ChunkedEncodingError):
        writer._write_plain(SimpleNamespace(), SimpleNamespace())


def test_guarded_failure_preserves_recording_error_retry_policy():
    from app.engine.streamlink_support import _thread_failure
    error = RecordingError("rplay_segment_connection", "segment interrupted", retryable=True)
    reader = SimpleNamespace(
        session=SimpleNamespace(_phrolova_loss_report=None),
        worker=SimpleNamespace(close=Mock()), buffer=SimpleNamespace(close=Mock()))
    thread = SimpleNamespace(reader=reader, close=Mock())
    _thread_failure(thread, error)
    assert reader._phrolova_error is error and reader._phrolova_error.retryable
    reader.worker.close.assert_called_once()
    reader.buffer.close.assert_called_once()


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
