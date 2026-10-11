import asyncio, json
import httpx
import pytest
from app.engine.preview_proxy import PreviewProxy


def test_all_manifest_uri_types_hide_signatures_and_preserve_extensions():
    proxy = PreviewProxy()
    token = proxy.register(
        "chzzk:a", "chzzk", "https://live.navercdn.com/live/master.m3u8?token=SECRET"
    )
    body = '#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,URI="audio.m3u8?token=SECRET"\n#EXT-X-MAP:URI="init.mp4?token=SECRET"\n#EXT-X-KEY:METHOD=AES-128,URI="key.key?token=SECRET"\n#EXT-X-PART:DURATION=1,URI="part.m4s?token=SECRET"\nvideo.ts?token=SECRET\n'
    result = proxy.rewrite(proxy.nodes[token], body)
    assert "SECRET" not in result and "navercdn" not in result
    assert (
        "asset.mp4" in result
        and "asset.key" in result
        and "asset.m4s" in result
        and "asset.ts" in result
    )
    assert len(proxy.nodes) == 6


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "https://localhost/live",
        "https://127.0.0.1/live",
        "https://10.0.0.1/live",
        "https://user:secret@example.com/live",
    ],
)
def test_unsafe_media_addresses_rejected(url):
    with pytest.raises(ValueError):
        PreviewProxy().register("chzzk:a", "chzzk", url)


@pytest.mark.asyncio
async def test_proxy_keeps_signed_query_and_limits_redirect_hosts(monkeypatch):
    proxy = PreviewProxy()
    token = proxy.register(
        "chzzk:a", "chzzk", "https://live.navercdn.com/master.m3u8?token=SECRET"
    )
    requests = []

    async def handler(request):
        requests.append(str(request.url))
        return httpx.Response(
            200,
            content=b"#EXTM3U\nsegment.ts?token=SECRET\n",
            headers={"Content-Type": "application/vnd.apple.mpegurl"},
        )

    client = httpx.AsyncClient
    monkeypatch.setattr(
        "app.engine.preview_proxy.httpx.AsyncClient",
        lambda **kwargs: client(transport=httpx.MockTransport(handler), **kwargs),
    )
    monkeypatch.setattr("app.engine.preview_proxy.preview_ca_bundle", lambda: True)
    data, kind, status, _ = await proxy.fetch(
        token, {"_HLS_msn": "123", "evil": "SECRET"}
    )
    assert (
        "token=SECRET" in requests[0]
        and "_HLS_msn=123" in requests[0]
        and "evil=" not in requests[0]
    )
    assert b"SECRET" not in data and status == 200
    with pytest.raises(ValueError):
        proxy.rewrite(
            proxy.nodes[token], "#EXTM3U\nhttps://attacker.example/secret.ts\n"
        )


def test_browser_resolver_never_returns_original_url(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    import app.main
    from app.api.stream import live_preview

    monkeypatch.setattr(
        app.main,
        "get_recorder_service",
        lambda: SimpleNamespace(
            get_live_preview_url=AsyncMock(
                return_value="https://live.navercdn.com/master.m3u8?token=SECRET"
            )
        ),
    )
    response = asyncio.run(live_preview("chzzk:a"))
    assert json.loads(response.body)["url"].startswith("/api/stream/preview-media/")
    assert b"SECRET" not in response.body


@pytest.mark.asyncio
async def test_proxy_byte_ranges_redirect_restrictions_and_expiry(monkeypatch):
    proxy = PreviewProxy()
    token = proxy.register(
        "chzzk:a", "chzzk", "https://live.navercdn.com/segment.mp4?token=SECRET"
    )
    requests = []
    redirect = False

    async def handler(request):
        requests.append(request)
        if redirect:
            return httpx.Response(
                302, headers={"location": "https://127.0.0.1/private"}
            )
        return httpx.Response(
            206,
            content=b"part",
            headers={"content-range": "bytes 0-3/10", "accept-ranges": "bytes"},
        )

    client = httpx.AsyncClient
    monkeypatch.setattr(
        "app.engine.preview_proxy.httpx.AsyncClient",
        lambda **kwargs: client(transport=httpx.MockTransport(handler), **kwargs),
    )
    monkeypatch.setattr("app.engine.preview_proxy.preview_ca_bundle", lambda: True)
    data, _, status, headers = await proxy.fetch(token, range_header="bytes=0-3")
    assert (
        data == b"part" and status == 206 and headers["content-range"] == "bytes 0-3/10"
    )
    assert requests[-1].headers["range"] == "bytes=0-3"
    redirect = True
    with pytest.raises(ValueError):
        await proxy.fetch(token)
    assert len(requests) == 2  # No request reaches the private redirect target.
    proxy.nodes[token]["time"] -= 121
    with pytest.raises(KeyError):
        await proxy.fetch(token)


@pytest.mark.asyncio
async def test_media_endpoint_stops_when_channel_removed_or_offline(monkeypatch):
    from types import SimpleNamespace
    from fastapi import FastAPI
    from app.api.stream import router
    import app.main

    proxy = PreviewProxy()
    token = proxy.register("chzzk:a", "chzzk", "https://live.navercdn.com/master.m3u8")
    channels = {}
    monkeypatch.setattr("app.engine.preview_proxy.preview_proxy", proxy)
    monkeypatch.setattr(
        app.main,
        "get_recorder_service",
        lambda: SimpleNamespace(_conductor=SimpleNamespace(_channels=channels)),
    )
    server = FastAPI()
    server.include_router(router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=server), base_url="http://test"
    ) as client:
        response = await client.get(f"/api/stream/preview-media/{token}/asset.m3u8")
        assert response.status_code == 409
        channels["chzzk:a"] = SimpleNamespace(is_live=False)
        response = await client.get(f"/api/stream/preview-media/{token}/asset.m3u8")
        assert response.status_code == 409
        response = await client.get("/api/stream/preview-media/unknown/asset.m3u8")
        assert response.status_code == 404
