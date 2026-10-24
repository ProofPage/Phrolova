"""Proxy consent, token scoping, fallback and log protection."""
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest
import requests
from requests.adapters import HTTPAdapter

from app.core.config import get_settings
from app.core.logger import _redact_log_secrets
from app.engine.platform_auth import redact_media_error
from app.engine.twitch_proxy import PROXY_SERVERS, TwitchProxyAdapter, _valid_manifest, configure_twitch_proxy

MASTER = '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=6000000,RESOLUTION=1920x1080,FRAME-RATE=60\nhttps://video.ttvnw.net/1080.m3u8\n'
USHER = "https://usher.ttvnw.net/api/v2/channel/hls/humzh.m3u8?sig=public&token=playback"


def response(code=200, text=MASTER):
    result = requests.Response()
    result.status_code = code
    result._content = text.encode()
    result.encoding = "utf-8"
    result.url = "https://proxy4.rte.net.ru/private?auth=fixture-token"
    result.headers["Set-Cookie"] = "injected=wrong"
    return result


def request(url=USHER, method="GET"):
    return requests.Request(method, url, headers={
        "Authorization": "OAuth fixture-token", "Cookie": "auth-token=fixture-token",
    }).prepare()


@pytest.fixture
def transport(monkeypatch):
    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    client.get.return_value = response()
    monkeypatch.setattr(requests, "Session", lambda: client)
    return client


def test_explicit_enable_and_disable():
    session = Mock()
    get_settings().twitch_proxy_enabled = False
    configure_twitch_proxy(session, "fixture-token")
    session.http.mount.assert_not_called()
    get_settings().twitch_proxy_enabled = True
    configure_twitch_proxy(session, "fixture-token")
    prefix, adapter = session.http.mount.call_args.args
    assert prefix == "https://usher.ttvnw.net/"
    assert adapter.auth_token == "fixture-token"


@pytest.mark.parametrize("token", ["", "fixture-token"])
def test_proxy_protocol_and_credential_isolation(transport, token):
    prepared = request()
    result = TwitchProxyAdapter(token).send(prepared)
    url = transport.get.call_args.args[0]
    assert url.startswith(PROXY_SERVERS[0] + USHER)
    query = parse_qs(urlsplit(url).query)
    assert query.get("auth") == ([token] if token else None)
    assert transport.get.call_args.kwargs["allow_redirects"] is False
    assert transport.get.call_args.kwargs["headers"] == {"Accept": "application/vnd.apple.mpegurl"}
    assert result.text == MASTER
    assert result.request is prepared and result.url == USHER
    assert "auth=" not in result.url and "Set-Cookie" not in result.headers
    transport.cookies.clear.assert_called()


def test_server_failover_and_redirect_not_followed(transport):
    transport.get.side_effect = [response(302), response(503), requests.Timeout("auth=fixture-token"), response()]
    assert TwitchProxyAdapter("fixture-token").send(request()).status_code == 200
    assert [c.args[0].split("https://usher")[0] for c in transport.get.call_args_list] == list(PROXY_SERVERS)


def test_all_proxies_fail_then_original_direct_request(transport, monkeypatch):
    transport.get.return_value = response(403)
    fallback = Mock(return_value=response())
    monkeypatch.setattr(HTTPAdapter, "send", fallback)
    original = request()
    TwitchProxyAdapter("fixture-token").send(original, timeout=7)
    assert transport.get.call_count == 4
    assert fallback.call_args.args[0] is original
    assert fallback.call_args.kwargs == {"timeout": 7}


@pytest.mark.parametrize("url,method", [
    ("https://usher.ttvnw.net.evil.example/api/v2/channel/hls/humzh.m3u8", "GET"),
    ("http://usher.ttvnw.net/api/v2/channel/hls/humzh.m3u8", "GET"),
    ("https://usher.ttvnw.net/vod/v2/123.m3u8", "GET"),
    ("https://usher.ttvnw.net/api/v2/channel/hls/humzh.m3u8", "POST"),
    ("https://gql.twitch.tv/gql", "GET"),
    ("https://video.ttvnw.net/1080.m3u8", "GET"),
])
def test_other_requests_are_never_proxied(transport, monkeypatch, url, method):
    fallback = Mock(return_value=response())
    monkeypatch.setattr(HTTPAdapter, "send", fallback)
    TwitchProxyAdapter("fixture-token").send(request(url, method))
    transport.get.assert_not_called()
    fallback.assert_called_once()


@pytest.mark.parametrize("text", [
    "<html>not a playlist</html>",
    MASTER.replace("video.ttvnw.net", "video.ttvnw.net.evil.example"),
    MASTER.replace("video.ttvnw.net", "127.0.0.1"),
    MASTER.replace("https://video", "http://video"),
    MASTER.replace("1080.m3u8", "1080.m3u8?auth=fixture-token"),
    MASTER + '#EXT-X-MEDIA:TYPE=AUDIO,URI="https://evil.example/audio.m3u8"\n',
])
def test_untrusted_or_token_echoing_playlists_rejected(text):
    assert not _valid_manifest(text, "fixture-token")


@pytest.mark.parametrize("text", [
    "auth=fixture-token",
    "/https://usher.ttvnw.net/a?x=1&auth=fixture-token",
    "https://proxy4.rte.net.ru/https://usher.ttvnw.net/a?auth=fixture-token",
])
def test_proxy_tokens_redacted(text):
    assert "fixture-token" not in _redact_log_secrets(text)
    assert "fixture-token" not in redact_media_error(text)


@pytest.mark.asyncio
async def test_proxy_settings_roundtrip(monkeypatch):
    from app.api.settings import general, media
    from app.api.settings.media import DownloadSettingsUpdateRequest
    saved = Mock()
    monkeypatch.setattr(media, "_update_env_file", saved)
    monkeypatch.setattr(general, "_get_ffmpeg_version", Mock())
    # The persistence path and response must not need or reveal credentials.
    for enabled in (True, False):
        result = await media.update_download_settings(DownloadSettingsUpdateRequest(
            max_record_retries=3, twitch_proxy_enabled=enabled))
        assert result["settings"]["twitch_proxy_enabled"] is enabled
        assert saved.call_args.args[0]["TWITCH_PROXY_ENABLED"] == str(enabled).lower()
