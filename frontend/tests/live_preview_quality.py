"""Decode real HLS variants to verify preview quality without upstream services.

Synthetic media and isolated API routes never touch live channels or recordings.
Run with PHROLOVA_TEST_URL and optional PHROLOVA_TEST_OUTPUT / PHROLOVA_FFMPEG.
"""
import asyncio
import base64
import copy
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import struct
import tempfile
import time
from urllib.parse import unquote, urlparse

from playwright.async_api import async_playwright, expect
from browser_fixtures import FIX, mock

BASE = os.environ.get("PHROLOVA_TEST_URL", "http://127.0.0.1:3001")
OUT = Path(os.environ.get("PHROLOVA_TEST_OUTPUT", tempfile.gettempdir() + "/phrolova-preview-quality"))
WORK = Path(__file__).resolve().parents[4] / "work"
BUNDLED = WORK / "media-tools/ffmpeg-9.0.2-essentials_build/bin/ffmpeg.exe"
FFMPEG = os.environ.get("PHROLOVA_FFMPEG") or shutil.which("ffmpeg") or (str(BUNDLED) if BUNDLED.is_file() else "ffmpeg")
PROFILES = {"full-hd": (1920, 1080), "hd": (1280, 720), "sd": (854, 480), "standard": (1440, 1080)}
CASES = {
    "multi": {"dimensions": (1920, 1080), "profile": "full-hd"},
    "only-720": {"dimensions": (1280, 720), "profile": "hd"},
    "only-480": {"dimensions": (854, 480), "profile": "sd"},
    "standard": {"dimensions": (1440, 1080), "profile": "standard"},
}
NATIVE_MASTERS = {
    "external-audio": '#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="audio",URI="audio.m3u8"\n'
    '#EXT-X-STREAM-INF:RESOLUTION=1920x1080,BANDWIDTH=4000000,AUDIO="audio"\n../preview-quality-media/full-hd/preview.m3u8\n',
    "external-subtitles": '#EXTM3U\n#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="captions",URI="captions.m3u8"\n'
    '#EXT-X-STREAM-INF:RESOLUTION=1920x1080,BANDWIDTH=4000000,SUBTITLES="subs"\n../preview-quality-media/full-hd/preview.m3u8\n',
    "resolution-first": '#EXTM3U\n#EXT-X-STREAM-INF:RESOLUTION=1920x1080,BANDWIDTH=4000000\n../preview-quality-media/full-hd/preview.m3u8\n'
    '#EXT-X-STREAM-INF:RESOLUTION=1280x720,BANDWIDTH=1500000\n../preview-quality-media/hd/preview.m3u8\n',
    "quoted-name": '#EXTM3U\n#EXT-X-STREAM-INF:NAME="wrong,RESOLUTION=1920x1080,quality",RESOLUTION=854x480,BANDWIDTH=300000\n'
    '../preview-quality-media/sd/preview.m3u8\n#EXT-X-STREAM-INF:RESOLUTION=1280x720,BANDWIDTH=1500000\n../preview-quality-media/hd/preview.m3u8\n',
    "missing-uri": '#EXTM3U\n#EXT-X-STREAM-INF:RESOLUTION=1920x1080,BANDWIDTH=4000000\n'
    '#EXT-X-STREAM-INF:RESOLUTION=854x480,BANDWIDTH=300000\n../preview-quality-media/sd/preview.m3u8\n'
    '#EXT-X-STREAM-INF:RESOLUTION=1280x720,BANDWIDTH=1500000\n../preview-quality-media/hd/preview.m3u8\n',
}


def create_media():
    root = OUT / "media"
    root.mkdir(parents=True, exist_ok=True)
    encoding = {}
    for name, (width, height) in PROFILES.items():
        folder = root / name
        folder.mkdir(exist_ok=True)
        started = time.perf_counter()
        subprocess.run([
            str(FFMPEG), "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
            f"testsrc2=size={width}x{height}:rate=5", "-t", "24", "-an", "-c:v", "libx264",
            "-preset", "ultrafast", "-crf", "30", "-pix_fmt", "yuv420p", "-profile:v", "baseline",
            "-level:v", "4.1", "-g", "10", "-keyint_min", "10", "-sc_threshold", "0",
            "-f", "hls", "-hls_time", "2", "-hls_list_size", "0", str(folder / "preview.m3u8"),
        ], check=True)
        encoding[name] = {"width": width, "height": height, "sourceSeconds": 24, "sourceFps": 5,
                          "syntheticEncodingSeconds": round(time.perf_counter() - started, 3)}
    # Deliberately misleading names and higher bandwidth on a non-Full-HD
    # 1080-line variant ensure selection uses dimensions, not text/bitrate.
    variants = [
        ("sd", 300_000, "Full HD best"),
        ("full-hd", 4_000_000, "lowest quality"),
        ("hd", 1_500_000, "1080p"),
        ("standard", 6_000_000, "Full HD 1080p"),
    ]
    for case in CASES:
        folder = root / case
        folder.mkdir(exist_ok=True)
        selected = variants if case == "multi" else [v for v in variants if v[0] == CASES[case]["profile"]]
        lines = ["#EXTM3U", "#EXT-X-VERSION:3"]
        for profile, bandwidth, misleading_name in selected:
            width, height = PROFILES[profile]
            lines.extend([
                f'#EXT-X-STREAM-INF:BANDWIDTH={bandwidth},RESOLUTION={width}x{height},CODECS="avc1.42E029",NAME="{misleading_name}"',
                f"../{profile}/preview.m3u8",
            ])
        (folder / "master.m3u8").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root, encoding


def create_channels():
    channels = []
    for case in [*CASES, "offline"]:
        channel = copy.deepcopy(FIX["channels"][1])
        channel.update(
            channel_id=f"quality-{case}", composite_key=f"chzzk:quality-{case}", platform="chzzk",
            channel_name=f"미리보기 화질 확인 {case}", title="원본 스트림 해상도와 실제 디코딩 화질 확인",
            is_live=case != "offline", auto_record=False, last_error="", thumbnail_url="", profile_image_url="",
            recording={"state": "idle", "is_recording": False},
        )
        channels.append(channel)
    return channels


async def video_measure(card):
    return await card.locator("video").evaluate("""v => {
      const quality=v.getVideoPlaybackQuality();
      return {width:v.videoWidth,height:v.videoHeight,time:v.currentTime,
        totalFrames:quality.totalVideoFrames,droppedFrames:quality.droppedVideoFrames,
        renderedWidth:v.getBoundingClientRect().width,renderedHeight:v.getBoundingClientRect().height,
        objectFit:getComputedStyle(v).objectFit};
    }""")


async def assert_no_resolution_caption(card):
    assert await card.locator(".channel-preview-resolution").count() == 0
    assert await card.get_by_text(re.compile(r"미리보기\s*·\s*\d+p\s*·")).count() == 0


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    media_root, encoding = create_media()
    results = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=os.environ.get("PHROLOVA_CHROMIUM_EXECUTABLE"))
        for width in (1440, 390):
            channels = create_channels()
            context = await browser.new_context(viewport={"width": width, "height": 1050},
                                                is_mobile=width < 500, has_touch=width < 500)
            await context.add_init_script("""
              localStorage.setItem('dashboardViewMode','list');
              window.EventSource=class { constructor(){ window.qualitySSE=this; } close(){} };
            """)
            gate = asyncio.Event()
            responses = {case: "loading" for case in CASES}
            resolver_calls = []
            media_requests = []
            errors = []

            async def route_api(route):
                path = unquote(urlparse(route.request.url).path)
                if path == "/api/platforms/channels":
                    return await route.fulfill(json=channels)
                if path.startswith("/api/stream/preview/"):
                    case = path.rsplit("quality-", 1)[-1]
                    resolver_calls.append(case)
                    assert case != "offline", "Offline preview must not resolve a stream"
                    if responses[case] == "loading":
                        await gate.wait()
                    if responses[case] == "error":
                        return await route.fulfill(status=503, json={"detail": "isolated test resolver error"})
                    return await route.fulfill(json={"url": BASE + f"/preview-quality-media/{case}/master.m3u8"})
                return await mock(route)

            async def route_media(route):
                suffix = urlparse(route.request.url).path.split("/preview-quality-media/", 1)[1]
                path = media_root / suffix
                assert path.resolve().is_relative_to(media_root.resolve())
                media_requests.append({"path": suffix, "bytes": path.stat().st_size})
                await route.fulfill(path=path,
                                    content_type="application/vnd.apple.mpegurl" if path.suffix == ".m3u8" else "video/mp2t")

            await context.route("**/api/**", route_api)
            await context.route("**/preview-quality-media/**", route_media)
            async def route_native_master(route):
                name = urlparse(route.request.url).path.rsplit("/", 1)[-1].removesuffix(".m3u8")
                return await route.fulfill(body=NATIVE_MASTERS[name], content_type="application/vnd.apple.mpegurl")

            await context.route("**/native-quality/*.m3u8", route_native_master)
            await context.route("https://fonts.googleapis.com/**", lambda route: route.abort())
            await context.route("https://fonts.gstatic.com/**", lambda route: route.abort())
            page = await context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.goto(BASE)
            policy = await page.evaluate("""async () => {
              const {preferredPreviewLevel,preferredNativePreviewUrl}=await import('/src/utils/livePreviewQuality.ts');
              const sets=[
                [{width:3840,height:2160},{width:1920,height:1080},{width:1280,height:720}],
                [{width:1440,height:1080,bitrate:6000000},{width:1920,height:1080,bitrate:4000000}],
                [{width:854,height:480},{width:1280,height:720}],
                [{width:1280,height:720},{width:3840,height:2160}],
                [{width:0,height:0},{width:NaN,height:1080}],
              ];
              const signal=new AbortController().signal;
              const nativeEdgeCases={};
              for (const name of ['external-audio','external-subtitles','resolution-first','quoted-name','missing-uri']) {
                nativeEdgeCases[name]=await preferredNativePreviewUrl(location.origin+'/native-quality/'+name+'.m3u8',signal);
              }
              return {indexes:sets.map(preferredPreviewLevel),nativeEdgeCases,
                nativeMaster:await preferredNativePreviewUrl(location.origin+'/preview-quality-media/multi/master.m3u8',signal),
                nativeMedia:await preferredNativePreviewUrl(location.origin+'/preview-quality-media/hd/preview.m3u8',signal)};
            }""")
            assert policy["indexes"] == [1, 1, 1, 1, -1], policy
            assert policy["nativeMaster"] == BASE + "/preview-quality-media/full-hd/preview.m3u8", policy
            assert policy["nativeMedia"] == BASE + "/preview-quality-media/hd/preview.m3u8", policy
            for name in ("external-audio", "external-subtitles"):
                assert policy["nativeEdgeCases"][name] == BASE + f"/native-quality/{name}.m3u8", policy
            assert policy["nativeEdgeCases"]["resolution-first"] == BASE + "/preview-quality-media/full-hd/preview.m3u8", policy
            for name in ("quoted-name", "missing-uri"):
                assert policy["nativeEdgeCases"][name] == BASE + "/preview-quality-media/hd/preview.m3u8", policy
            cards = {case: page.locator(f'[data-channel-key="chzzk:quality-{case}"]') for case in [*CASES, "offline"]}
            await cards["multi"].wait_for()
            for card in cards.values():
                await card.locator(".recording-detail-action").click()
            for case in CASES:
                await expect(cards[case].get_by_text("미리보기를 불러오는 중", exact=True)).to_be_visible()
                await assert_no_resolution_caption(cards[case])
            await expect(cards["offline"].locator(".channel-preview-message")).to_have_text("현재 방송 중이 아닙니다.")
            await assert_no_resolution_caption(cards["offline"])
            responses.update({case: "ready" for case in CASES})
            gate.set()
            await page.wait_for_function("[...document.querySelectorAll('video')].every(v=>v.readyState>=2&&v.videoWidth>0)")
            for case, expected in CASES.items():
                await assert_no_resolution_caption(cards[case])
                measure = await video_measure(cards[case])
                assert (measure["width"], measure["height"]) == expected["dimensions"], (case, measure)
                assert measure["objectFit"] == "contain", (case, measure)
                if width == 1440:
                    # Export exactly the browser's decoded pixels. No CSS size,
                    # image resize, or upscaling can create the asserted IHDR.
                    frame = await cards[case].locator("video").evaluate("""v => {
                      const canvas=document.createElement('canvas');
                      canvas.width=v.videoWidth;canvas.height=v.videoHeight;
                      canvas.getContext('2d').drawImage(v,0,0);
                      return canvas.toDataURL('image/png').split(',')[1];
                    }""")
                    png = base64.b64decode(frame)
                    assert png[:8] == b"\x89PNG\r\n\x1a\n"
                    assert struct.unpack(">II", png[16:24]) == expected["dimensions"], case
                    (OUT / f"frame-{expected['profile']}.png").write_bytes(png)
            # Capture actual decoding for concurrent players, not only CSS sizes.
            before = {case: await video_measure(cards[case]) for case in CASES}
            await page.wait_for_function("[...document.querySelectorAll('video')].every(v=>v.getVideoPlaybackQuality().totalVideoFrames>=8)")
            await page.wait_for_timeout(1200)
            after = {case: await video_measure(cards[case]) for case in CASES}
            for case in CASES:
                assert after[case]["totalFrames"] > before[case]["totalFrames"], (case, before[case], after[case])
                assert after[case]["time"] > before[case]["time"], (case, before[case], after[case])
            for case in CASES:
                assert any(r["path"].startswith(CASES[case]["profile"] + "/") and r["path"].endswith(".ts") for r in media_requests), media_requests
            # Isolate the multivariant player's requests to prove that it never
            # starts decoding a lower variant or the higher bitrate 4:3 source.
            for case in ("only-720", "only-480", "standard"):
                await cards[case].locator(".recording-detail-action").click()
            await cards["multi"].locator(".recording-detail-action").click()
            multi_start = len(media_requests)
            await cards["multi"].locator(".recording-detail-action").click()
            await page.wait_for_function("document.querySelector('video').videoWidth===1920&&document.querySelector('video').readyState>=2")
            multi_requests = media_requests[multi_start:]
            assert any(r["path"].startswith("full-hd/") and r["path"].endswith(".ts") for r in multi_requests), multi_requests
            assert all(r["path"].startswith("full-hd/") for r in multi_requests if r["path"].endswith(".ts")), multi_requests
            # Reopen 720p to record two concurrently decoded players and verify
            # that switching layouts does not restart either media source.
            await cards["only-720"].locator(".recording-detail-action").click()
            await expect(cards["only-720"].locator(".channel-preview-player")).to_be_visible()
            await assert_no_resolution_caption(cards["only-720"])
            reopened_720 = await video_measure(cards["only-720"])
            assert (reopened_720["width"], reopened_720["height"]) == (1280, 720), reopened_720
            await page.evaluate("window.qualityPlayers=[...document.querySelectorAll('video')]")
            calls_before = len(resolver_calls)
            for mode, label in (("grid", "카드로 보기"), ("list", "목록으로 보기")):
                await page.get_by_role("button", name=label, exact=True).click()
                await page.wait_for_timeout(120)
                assert await page.evaluate("window.qualityPlayers.every(v=>v.isConnected)")
                assert len(resolver_calls) == calls_before, resolver_calls
                assert await page.evaluate("document.documentElement.scrollWidth===innerWidth")
                await cards["multi"].evaluate("e=>e.scrollIntoView({block:'start'})")
                await page.screenshot(path=str(OUT / f"{mode}-{width}.png"), animations="disabled")
            # Collapse destroys media, and the removed resolution caption stays
            # absent during loading, resolver failure, retry, and offline changes.
            await cards["multi"].locator("video").evaluate("v=>window.closedQualityPlayer=v")
            await cards["multi"].locator(".recording-detail-action").click()
            assert await page.evaluate("!window.closedQualityPlayer.isConnected&&!window.closedQualityPlayer.hasAttribute('src')&&window.closedQualityPlayer.paused")
            gate.clear()
            responses["multi"] = "loading"
            await cards["multi"].locator(".recording-detail-action").click()
            await expect(cards["multi"].get_by_text("미리보기를 불러오는 중", exact=True)).to_be_visible()
            await assert_no_resolution_caption(cards["multi"])
            responses["multi"] = "error"
            gate.set()
            await expect(cards["multi"].get_by_role("button", name="다시 시도", exact=True)).to_be_visible()
            await assert_no_resolution_caption(cards["multi"])
            responses["multi"] = "ready"
            await cards["multi"].get_by_role("button", name="다시 시도", exact=True).click()
            await expect(cards["multi"].locator(".channel-preview-player")).to_be_visible()
            await assert_no_resolution_caption(cards["multi"])
            retried_hd = await video_measure(cards["multi"])
            assert (retried_hd["width"], retried_hd["height"]) == (1920, 1080), retried_hd
            channels[0]["is_live"] = False
            await page.evaluate("channels=>window.qualitySSE.onmessage({data:JSON.stringify({type:'status_update',data:channels})})", channels)
            await expect(cards["multi"].locator(".channel-preview-message")).to_have_text("현재 방송 중이 아닙니다.")
            await assert_no_resolution_caption(cards["multi"])
            assert await cards["multi"].locator("video").count() == 0
            assert not errors, errors
            results.append({"viewport": width, "decodedBefore": before, "decodedAfter": after,
                            "policy": policy,
                            "resolutionCaptionDisplayed": False,
                            "syntheticMediaEncoding": encoding,
                            "routedSegmentsByProfile": {
                                profile: {"requestCount": sum(r["path"].startswith(profile + "/") and r["path"].endswith(".ts") for r in media_requests),
                                          "bytes": sum(r["bytes"] for r in media_requests if r["path"].startswith(profile + "/") and r["path"].endswith(".ts"))}
                                for profile in PROFILES},
                            "multivariantRequests": multi_requests, "allRequests": media_requests,
                            "routedMediaBytes": sum(r["bytes"] for r in media_requests if r["path"].endswith(".ts")),
                            "resolverCalls": resolver_calls})
            print(f"{width}px: Full HD / 720p / 480p / 4:3 actual decode, segment selection, concurrent playback, removed caption across states PASS", flush=True)
            await context.close()
        await browser.close()
    (OUT / "quality.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Preview quality PASS: exact 1920x1080 chosen despite misleading names / higher bitrate 4:3; no 720p/480p upscale; real frames advance; cleanup/retry/offline; desktop/mobile.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
