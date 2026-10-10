"""Exercise the expanded recording layout and actual HLS playback in Chromium.

Synthetic media and isolated API fixtures avoid touching recordings or services.
"""
import asyncio
import copy
import json
import os
from pathlib import Path
import subprocess
import shutil
import tempfile
from urllib.parse import unquote, urlparse

from playwright.async_api import async_playwright, expect
from browser_fixtures import FIX, mock

BASE = os.environ.get("PHROLOVA_TEST_URL", "http://127.0.0.1:3001")
OUT = Path(os.environ.get("PHROLOVA_TEST_OUTPUT", tempfile.gettempdir() + "/phrolova-live-details"))
WORK = Path(__file__).resolve().parents[4] / "work"
BUNDLED_FFMPEG = WORK / "media-tools/ffmpeg-9.0.2-essentials_build/bin/ffmpeg.exe"
FFMPEG = os.environ.get("PHROLOVA_FFMPEG") or shutil.which("ffmpeg") or (str(BUNDLED_FFMPEG) if BUNDLED_FFMPEG.is_file() else "ffmpeg")
WIDTHS = (360, 390, 768, 1024, 1440, 1920)


GEOMETRY = """card => {
 const rect = e => { const r=e.getBoundingClientRect(); return {x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom}; };
 const details=card.querySelector('.recording-channel-details'), copy=details.querySelector('.recording-details-copy');
 const preview=details.querySelector('.channel-live-preview'), stage=preview.querySelector('.channel-preview-stage');
 const player=preview.querySelector('.channel-preview-player'), video=preview.querySelector('video');
 const fields=copy.querySelector('.recording-details-fields');
 return {card:rect(card),containerWidth:card.clientWidth,summary:rect(card.querySelector('.recording-channel-summary')),
 details:rect(details),copy:rect(copy),preview:rect(preview),stage:rect(stage),player:player?rect(player):null,
 columns:getComputedStyle(details).gridTemplateColumns.split(' ').length,
 overflow:document.documentElement.scrollWidth-innerWidth,
 mainOverflow:document.querySelector('#main-content').scrollWidth-document.querySelector('#main-content').clientWidth,
 fields:[...fields.querySelectorAll('dd')].map(e=>({...rect(e),scroll:e.scrollWidth,client:e.clientWidth})),
 labels:[...fields.querySelectorAll('dt')].map(rect),
 video:video?{...rect(video),objectFit:getComputedStyle(video).objectFit,intrinsicWidth:video.videoWidth,intrinsicHeight:video.videoHeight,time:video.currentTime}:null};
}"""


def close(a, b, tolerance=1.5):
    return abs(a - b) <= tolerance


def validate_geometry(g, ready=False):
    assert g["overflow"] == g["mainOverflow"] == 0, g
    assert close(g["stage"]["width"], g["preview"]["width"]), g
    assert close(g["stage"]["height"], g["stage"]["width"] * 9 / 16), g
    assert g["stage"]["right"] <= g["details"]["right"] + 1, g
    if g["containerWidth"] >= 820:
        assert g["columns"] == 2, g
        assert close(g["copy"]["y"], g["preview"]["y"]), g
        assert g["preview"]["x"] >= g["copy"]["right"] + 16, g
        assert g["preview"]["width"] >= g["copy"]["width"] * 1.75, g
    else:
        assert g["columns"] == 1, g
        assert close(g["preview"]["width"], g["copy"]["width"]), g
        assert g["preview"]["y"] >= g["copy"]["bottom"] + 14, g
    assert all(f["scroll"] <= f["client"] + 1 and f["right"] <= g["copy"]["right"] + 1 for f in g["fields"]), g
    assert all(close(label["x"], g["labels"][0]["x"]) for label in g["labels"]), g
    assert all(close(field["x"], g["fields"][0]["x"]) for field in g["fields"]), g
    if ready:
        assert g["video"]["intrinsicWidth"] > 0 and g["video"]["intrinsicHeight"] > 0, g
        assert g["video"]["objectFit"] == "contain", g
        assert close(g["player"]["width"], g["stage"]["width"]), g
        assert close(g["player"]["height"], g["stage"]["height"]), g
        assert close(g["video"]["width"], g["stage"]["width"]), g
        assert close(g["video"]["height"], g["stage"]["height"]), g


def assert_stage_unchanged(before, after):
    for key in ("width", "height"):
        assert close(before["stage"][key], after["stage"][key]), (key, before, after)


def create_media():
    for name, size in (("wide", "320x180"), ("standard", "320x240")):
        folder = OUT / "media" / name
        folder.mkdir(parents=True, exist_ok=True)
        subprocess.run([
            str(FFMPEG), "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
            f"smptebars=size={size}:rate=10", "-t", "60", "-c:v", "libx264", "-g", "10",
            "-f", "hls", "-hls_time", "1", "-hls_list_size", "0", str(folder / "preview.m3u8"),
        ], check=True)


def create_channels():
    result = []
    for i in range(3):
        channel = copy.deepcopy(FIX["channels"][1])
        channel.update(
            channel_id=f"details-{i}", composite_key=f"chzzk:details-{i}", platform="chzzk",
            channel_name=("라이브 상세 확인 " if i < 2 else "오프라인 채널 ") + str(i),
            title="긴 방송 제목 / 화면이 잘리지 않고 전체 내용을 유지합니다 " * 8 + "W" * 180,
            category="게임 및 라이브 스튜디오", tags=["즐겨찾기", "회귀 검사"], is_live=i < 2,
            auto_record=True, last_error="", thumbnail_url="", profile_image_url="",
            recording=dict(
                state="recording" if i < 2 else "completed", is_recording=i < 2, duration_seconds=3601,
                start_time="2026-10-10T00:00:00Z", file_size_bytes=8 * 1024**3,
                download_speed=1.62, bitrate=13570,
                output_path=("C:\\녹화 폴더\\한글 [1080p]\\" if i == 0 else "/home/termux/영상/한글 공백 [1080p]/")
                + "매우긴파일이름" * 24 + ".ts",
            ),
        )
        result.append(channel)
    return result


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    create_media()
    channels = create_channels()
    results = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=os.environ.get("PHROLOVA_CHROMIUM_EXECUTABLE"))
        for width in WIDTHS:
            context = await browser.new_context(viewport={"width": width, "height": 1000},
                                                is_mobile=width < 500, has_touch=width < 500)
            await context.add_init_script("localStorage.setItem('dashboardViewMode','list');window.EventSource=class{close(){}}")
            gate = asyncio.Event()
            responses = {0: "loading", 1: "error"}
            resolver_calls = []
            errors = []

            async def route_api(route):
                path = unquote(urlparse(route.request.url).path)
                if path == "/api/platforms/channels":
                    return await route.fulfill(json=channels)
                if path.startswith("/api/stream/preview/"):
                    index = int(path.rsplit("-", 1)[-1])
                    resolver_calls.append(index)
                    if responses[index] == "loading":
                        await gate.wait()
                    if responses[index] == "error":
                        return await route.fulfill(status=503, json={"detail": "isolated preview test failure"})
                    folder = "wide" if index == 0 else "standard"
                    return await route.fulfill(json={"url": BASE + f"/live-details-media/{folder}/preview.m3u8"})
                return await mock(route)

            async def route_media(route):
                suffix = urlparse(route.request.url).path.split("/live-details-media/", 1)[1]
                path = OUT / "media" / suffix
                assert path.resolve().is_relative_to((OUT / "media").resolve())
                await route.fulfill(path=path, content_type="application/vnd.apple.mpegurl" if path.suffix == ".m3u8" else "video/mp2t")

            await context.route("**/api/**", route_api)
            await context.route("**/live-details-media/**", route_media)
            await context.route("https://fonts.googleapis.com/**", lambda route: route.abort())
            await context.route("https://fonts.gstatic.com/**", lambda route: route.abort())
            page = await context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.goto(BASE)
            cards = [page.locator(f'[data-channel-key="chzzk:details-{i}"]') for i in range(3)]
            await cards[0].wait_for()
            compact = [await card.locator(".recording-channel-summary").evaluate("e=>({width:e.offsetWidth,height:e.offsetHeight})") for card in cards]
            for card in cards:
                await card.locator(".recording-detail-action").click()
            await expect(cards[0].get_by_text("미리보기를 불러오는 중", exact=True)).to_be_visible()
            await expect(cards[1].get_by_role("button", name="다시 시도", exact=True)).to_be_visible()
            await expect(cards[2].locator(".channel-preview-message")).to_have_text("현재 방송 중이 아닙니다.")
            initial = [await card.evaluate(GEOMETRY) for card in cards]
            for i, g in enumerate(initial):
                validate_geometry(g)
                assert close(g["summary"]["width"], compact[i]["width"]) and close(g["summary"]["height"], compact[i]["height"]), (compact[i], g)
            responses[0] = responses[1] = "ready"
            gate.set()
            await cards[1].get_by_role("button", name="다시 시도", exact=True).click()
            await page.wait_for_function("[...document.querySelectorAll('video')].every(v=>v.readyState>=2&&v.videoWidth>0)")
            await expect(cards[0].locator(".channel-preview-player")).to_be_visible()
            await expect(cards[1].locator(".channel-preview-player")).to_be_visible()
            for i in range(2):
                current = await cards[i].evaluate(GEOMETRY)
                validate_geometry(current, ready=True)
                assert_stage_unchanged(initial[i], current)
            assert await cards[0].locator("video").evaluate("v=>v.videoWidth/v.videoHeight") == 16 / 9
            assert await cards[1].locator("video").evaluate("v=>v.videoWidth/v.videoHeight") == 4 / 3
            assert 2 not in resolver_calls, resolver_calls
            await page.evaluate("window.preservedPlayers=[...document.querySelectorAll('video')]")
            expected_calls = list(resolver_calls)
            for mode, label in (("grid", "카드로 보기"), ("list", "목록으로 보기")):
                await page.get_by_role("button", name=label, exact=True).click()
                await page.wait_for_timeout(150)
                assert await page.evaluate("window.preservedPlayers.every(v=>v.isConnected&&[...document.querySelectorAll('video')].includes(v))")
                assert resolver_calls == expected_calls, (mode, resolver_calls, expected_calls)
                measures = [await card.evaluate(GEOMETRY) for card in cards]
                for i, g in enumerate(measures):
                    validate_geometry(g, ready=i < 2)
                results.append({"viewport": width, "mode": mode, "channels": measures})
                await cards[0].evaluate("e=>e.scrollIntoView({block:'start'})")
                await page.screenshot(path=str(OUT / f"{mode}-{width}.png"), animations="disabled")
                print(f"{width}px {mode}: layout/ratio/full-width/long-path PASS", flush=True)
            # Decode/play real media; the displayed video continues advancing.
            previous = await cards[0].locator("video").evaluate("v=>v.currentTime")
            frames = await cards[0].locator("video").evaluate("v=>v.getVideoPlaybackQuality().totalVideoFrames")
            await page.wait_for_function("document.querySelector('video').currentTime > " + str(previous + .15))
            await page.wait_for_function("document.querySelector('video').getVideoPlaybackQuality().totalVideoFrames > " + str(frames))
            if width == 1920:
                for resized in (360, 768, 1024, 1440, 1920):
                    await page.set_viewport_size({"width": resized, "height": 1000})
                    await page.wait_for_timeout(100)
                    assert await page.evaluate("window.preservedPlayers.every(v=>v.isConnected&&[...document.querySelectorAll('video')].includes(v))")
                    assert resolver_calls == expected_calls
                    for i, card in enumerate(cards):
                        validate_geometry(await card.evaluate(GEOMETRY), ready=i < 2)
            # A collapsed disclosure releases the media; reopening resolves fresh playback.
            await cards[0].locator("video").evaluate("v=>window.closedPlayer=v")
            await cards[0].locator(".recording-detail-action").click()
            assert await cards[0].locator("video").count() == 0
            assert await page.evaluate("!window.closedPlayer.isConnected&&!window.closedPlayer.hasAttribute('src')&&window.closedPlayer.paused")
            before_reopen = len(resolver_calls)
            await cards[0].locator(".recording-detail-action").click()
            await expect(cards[0].locator(".channel-preview-player")).to_be_visible()
            assert len(resolver_calls) == before_reopen + 1
            assert not errors, errors
            await context.close()
        await browser.close()
    (OUT / "geometry.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Live details PASS: 6 widths x 2 views; simultaneous 16:9/4:3 HLS; stable state geometry; retry/offline; resize/view identity; cleanup/reopen; frames advance.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
