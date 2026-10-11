"""Real Hls.js decoding through the backend opaque manifest/segment routes."""

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
from fastapi import FastAPI
from playwright.async_api import async_playwright
from pytest import MonkeyPatch
from browser_fixtures import mock
from live_details_layout import create_channels, FFMPEG

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from app.api.stream import router
from app.engine.preview_proxy import PreviewProxy
import app.main

BASE = os.environ.get("PHROLOVA_TEST_URL", "http://127.0.0.1:3001")
OUT = Path(os.environ["PHROLOVA_TEST_OUTPUT"])


async def main():
    media = OUT / "media"
    media.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            str(FFMPEG),
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "smptebars=size=640x360:rate=10",
            "-t",
            "20",
            "-c:v",
            "libx264",
            "-g",
            "10",
            "-f",
            "hls",
            "-hls_time",
            "1",
            "-hls_list_size",
            "0",
            str(media / "video.m3u8"),
        ],
        check=True,
    )
    channel = create_channels()[0]
    proxy = PreviewProxy()
    service = SimpleNamespace(
        get_live_preview_url=AsyncMock(
            return_value="https://live.navercdn.com/master.m3u8?token=SECRET"
        ),
        _conductor=SimpleNamespace(
            _channels={channel["composite_key"]: SimpleNamespace(is_live=True)}
        ),
    )
    server = FastAPI()
    server.include_router(router)
    upstream_requests = []

    async def upstream(request):
        upstream_requests.append(str(request.url))
        if request.url.path == "/master.m3u8":
            body = b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=500000,RESOLUTION=640x360\nvideo.m3u8?token=SECRET\n"
        elif request.url.path == "/video.m3u8":
            body = (media / "video.m3u8").read_text()
            body = "\n".join(
                line + "?token=SECRET" if line.endswith(".ts") else line
                for line in body.splitlines()
            ).encode()
        else:
            path = media / Path(request.url.path).name
            assert path.suffix == ".ts" and path.is_file(), request.url
            body = path.read_bytes()
        return httpx.Response(200, content=body)

    original_client = httpx.AsyncClient

    def client_factory(**kwargs):
        if "verify" in kwargs:
            kwargs["transport"] = httpx.MockTransport(upstream)
        return original_client(**kwargs)

    with MonkeyPatch.context() as patches:
        patches.setattr(app.main, "get_recorder_service", lambda: service)
        patches.setattr("app.engine.preview_proxy.preview_proxy", proxy)
        patches.setattr("app.engine.preview_proxy.preview_ca_bundle", lambda: True)
        patches.setattr("app.engine.preview_proxy.httpx.AsyncClient", client_factory)
        async with original_client(
            transport=httpx.ASGITransport(app=server), base_url=BASE
        ) as backend:
            async with async_playwright() as p:
                browser = await p.chromium.launch()
                for width in (320, 1440):
                    context = await browser.new_context(
                        viewport={"width": width, "height": 1000}
                    )
                    await context.add_init_script(
                        "localStorage.setItem('dashboardViewMode','list');window.EventSource=class{close(){}}"
                    )
                    responses = []

                    async def route_api(route):
                        path = httpx.URL(route.request.url).raw_path.decode()
                        if path.startswith("/api/stream/preview"):
                            result = await backend.get(path)
                            if "mpegurl" in result.headers.get(
                                "content-type", ""
                            ) or path.startswith("/api/stream/preview/"):
                                assert (
                                    b"SECRET" not in result.content
                                    and b"navercdn" not in result.content
                                )
                            responses.append(path)
                            return await route.fulfill(
                                status=result.status_code,
                                body=result.content,
                                headers=dict(result.headers),
                            )
                        if path == "/api/platforms/channels":
                            return await route.fulfill(json=[channel])
                        return await mock(route)

                    await context.route("**/api/**", route_api)
                    page = await context.new_page()
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    await page.goto(BASE)
                    card = page.locator(
                        f'[data-channel-key="{channel["composite_key"]}"]'
                    )
                    await card.locator(".recording-detail-action").click()
                    await page.wait_for_function(
                        "document.querySelector('video')?.videoWidth===640"
                    )
                    for mode, label in (
                        ("grid", "카드로 보기"),
                        ("list", "목록으로 보기"),
                    ):
                        await page.get_by_role("button", name=label, exact=True).click()
                        before = await card.locator("video").evaluate(
                            "v=>v.currentTime"
                        )
                        await page.wait_for_timeout(1000)
                        assert (
                            await card.locator("video").evaluate("v=>v.currentTime")
                            > before
                        )
                        assert await page.evaluate(
                            "document.documentElement.scrollWidth<=innerWidth"
                        )
                        await page.screenshot(
                            path=str(OUT / f"{width}-{mode}.png"), full_page=True
                        )
                    assert not errors, errors
                    assert any(path.endswith(".ts") for path in responses), responses
                    assert all("SECRET" not in path for path in responses)
                    await context.close()
                await browser.close()
    (OUT / "result.json").write_text(
        json.dumps(
            {
                "passed": True,
                "widths": [320, 1440],
                "modes": ["grid", "list"],
                "upstream_requests": len(upstream_requests),
            }
        )
    )
    print(
        "Opaque proxy: master, variant and TS routes decoded real 640x360 HLS in four browser combinations."
    )


if __name__ == "__main__":
    asyncio.run(main())
