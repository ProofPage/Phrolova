"""Settings save scopes, failure recovery and left-aligned responsive controls."""

import asyncio
import copy
import os
from pathlib import Path
from urllib.parse import urlparse
from playwright.async_api import async_playwright, expect
from browser_fixtures import FIX, mock

BASE = os.environ.get("PHROLOVA_TEST_URL", "http://127.0.0.1:3001")
OUT = Path(os.environ["PHROLOVA_TEST_OUTPUT"])


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    settings = copy.deepcopy(FIX["settings"])
    settings.update(
        live_download_dir="/recordings/live",
        vod_download_dir="/recordings/vod",
        chzzk_live_cdn="default",
        chzzk_vod_cdn="default",
    )
    policy = {"output_format": "mkv", "keep_source_ts": True, "max_concurrent": 1}
    calls = []
    fail_processing = False

    async def route_api(route):
        nonlocal policy
        path = urlparse(route.request.url).path
        if path == "/api/settings/browse-dirs":
            return await route.fulfill(
                json={
                    "current": "/recordings/선택한 폴더",
                    "parent": "/recordings",
                    "dirs": [],
                }
            )
        if path == "/api/settings":
            return await route.fulfill(json=settings)
        if path == "/api/recordings/settings":
            if route.request.method == "PUT":
                calls.append((path, route.request.post_data_json))
                await asyncio.sleep(0.15)
                if fail_processing:
                    return await route.fulfill(
                        status=500, json={"detail": "파일 처리 설정 저장 실패"}
                    )
                policy = route.request.post_data_json
            return await route.fulfill(json=policy)
        if path in ("/api/settings/general", "/api/settings/vod", "/api/settings/live"):
            calls.append((path, route.request.post_data_json))
            await asyncio.sleep(0.15)
            settings.update(route.request.post_data_json)
            return await route.fulfill(json={"settings": settings})
        return await mock(route)

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(viewport={"width": 1440, "height": 1100})
        await context.add_init_script("window.EventSource=class{close(){}}")
        await context.route("**/api/**", route_api)
        page = await context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        await page.goto(BASE + "/settings")
        await expect(page.get_by_role("button", name="일반", exact=True)).to_have_count(
            0
        )
        await expect(
            page.get_by_role("button", name="일반 설정 저장", exact=True)
        ).to_have_count(0)
        await expect(
            page.get_by_role("combobox", name="라이브 녹화 파일 형식")
        ).to_have_count(0)
        await expect(page.locator("[data-settings-section]")).to_have_count(3)
        video = page.locator('[data-settings-section="video"]')
        processing = page.locator('[data-settings-section="processing"]')
        live = page.locator('[data-settings-section="live"]')
        await expect(video).to_contain_text("저장 즉시 적용됩니다")
        for card in (video, processing, live):
            await expect(card.locator(".settings-save-row button")).to_have_count(1)
            await expect(card.locator(".settings-save-row button")).to_be_disabled()

        await expect(
            video.get_by_role("textbox", name="영상 저장 위치", exact=True)
        ).to_have_value("/recordings/vod")
        await expect(
            live.get_by_role("textbox", name="라이브 저장 위치", exact=True)
        ).to_have_value("/recordings/live")
        await video.get_by_role("button", name="폴더 찾아보기", exact=True).click()
        await page.get_by_role("dialog", name="폴더 선택").get_by_role(
            "button", name="이 폴더 선택", exact=True
        ).click()
        await expect(
            video.get_by_role("textbox", name="영상 저장 위치", exact=True)
        ).to_have_value("/recordings/선택한 폴더")
        await live.get_by_role("textbox", name="라이브 저장 위치", exact=True).fill(
            "/recordings/라이브 폴더"
        )
        await live.get_by_role("spinbutton", name="라이브 확인 주기 (초)").fill("4")
        await expect(
            live.get_by_role("button", name="라이브 설정 저장", exact=True)
        ).to_be_disabled()
        await live.get_by_role("spinbutton", name="라이브 확인 주기 (초)").fill("45")
        # Saving video settings must preserve the unsaved live change.
        await live.get_by_role("combobox", name="치지직 라이브 CDN").select_option(
            "akamai"
        )
        await video.get_by_role("spinbutton", name="동시 다운로드 개수").fill("2")
        await video.get_by_role(
            "button", name="영상 다운로드 설정 저장", exact=True
        ).click()
        await expect(video).to_have_attribute("aria-busy", "false")
        await expect(
            video.get_by_role("button", name="영상 다운로드 설정 저장", exact=True)
        ).to_be_disabled()
        await expect(
            live.get_by_role("combobox", name="치지직 라이브 CDN")
        ).to_have_value("akamai")
        await expect(
            live.get_by_role("button", name="라이브 설정 저장", exact=True)
        ).to_be_enabled()
        assert not any(path.endswith("/live") for path, _ in calls)
        assert any(
            body.get("vod_download_dir") == "/recordings/선택한 폴더"
            for _, body in calls
        )
        await expect(
            live.get_by_role("spinbutton", name="라이브 확인 주기 (초)")
        ).to_have_value("45")
        await live.get_by_role("button", name="라이브 설정 저장", exact=True).click()
        await expect(live).to_have_attribute("aria-busy", "false")
        assert any(
            body.get("live_download_dir") == "/recordings/라이브 폴더"
            and body.get("monitor_interval") == 45
            for _, body in calls
        )
        await expect(
            live.get_by_role("button", name="라이브 설정 저장", exact=True)
        ).to_be_disabled()

        await processing.get_by_role(
            "combobox", name="녹화 완료 후 저장 형식", exact=True
        ).select_option("mp4")
        fail_processing = True
        await processing.get_by_role(
            "button", name="파일 처리 설정 저장", exact=True
        ).click()
        await expect(processing.get_by_role("alert")).to_contain_text("저장 실패")
        assert policy["output_format"] == "mkv"
        await expect(
            processing.get_by_role(
                "combobox", name="녹화 완료 후 저장 형식", exact=True
            )
        ).to_have_value("mp4")
        fail_processing = False
        await processing.get_by_role(
            "button", name="파일 처리 설정 저장", exact=True
        ).click()
        await expect(processing).to_have_attribute("aria-busy", "false")
        await expect(
            processing.get_by_role("button", name="파일 처리 설정 저장", exact=True)
        ).to_be_disabled()
        assert policy["output_format"] == "mp4"
        await page.reload()
        await page.get_by_role("button", name="다운로드", exact=True).click()
        await expect(
            page.get_by_role("combobox", name="녹화 완료 후 저장 형식", exact=True)
        ).to_have_value("mp4")
        await expect(
            page.get_by_role("textbox", name="영상 저장 위치", exact=True)
        ).to_have_value("/recordings/선택한 폴더")
        await expect(
            page.get_by_role("textbox", name="라이브 저장 위치", exact=True)
        ).to_have_value("/recordings/라이브 폴더")
        await expect(
            page.get_by_role("spinbutton", name="라이브 확인 주기 (초)")
        ).to_have_value("45")
        for width in (360, 390, 768, 1024, 1440, 1920):
            await page.set_viewport_size({"width": width, "height": 1100})
            assert await page.evaluate(
                "document.documentElement.scrollWidth <= innerWidth"
            ), width
            for name in ("video", "processing", "live"):
                card = page.locator(f'[data-settings-section="{name}"]')
                row = card.locator(".settings-save-row")
                button = row.get_by_role("button")
                a, b = await row.bounding_box(), await button.bounding_box()
                assert abs(a["x"] - b["x"]) < 1, (width, name, a, b)
            await page.screenshot(
                path=str(OUT / f"download-{width}.png"), full_page=True
            )
        await expect(
            page.get_by_text("원본 TS 보관", exact=False).first
        ).to_be_visible()
        assert not errors, errors
        await browser.close()
    print(
        "PASS: duplicate format removed, 3 separate save scopes, left alignment at 360/390/768/1024/1440/1920, no overflow, dirty/pending/error/retry, other unsaved changes retained, save/reload, legacy payload preserved, no JS errors"
    )


asyncio.run(main())
