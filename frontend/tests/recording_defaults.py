"""Settings defaults, legacy values, source-format alignment and persistence in Chromium."""

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
    for key in (
        "chzzk_stream_mode",
        "chzzk_time_machine_enabled",
        "vod_max_concurrent",
    ):
        settings.pop(key, None)
    calls = []

    async def route_api(route):
        request = route.request
        path = urlparse(request.url).path
        if path == "/api/settings":
            return await route.fulfill(json=settings)
        if path in ("/api/settings/live", "/api/settings/vod"):
            calls.append((path, request.post_data_json))
            settings.update(request.post_data_json)
            return await route.fulfill(json={"settings": settings})
        if path == "/api/recordings/settings":
            return await route.fulfill(
                json={
                    "output_format": "mkv",
                    "keep_source_ts": True,
                    "max_concurrent": 1,
                }
            )
        return await mock(route)

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(viewport={"width": 1440, "height": 1100})
        await context.add_init_script("window.EventSource=class{close(){}}")
        await context.route("**/api/**", route_api)
        page = await context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        async def open_settings():
            await page.goto(BASE + "/settings")
            await page.get_by_role("button", name="다운로드", exact=True).click()

        await open_settings()
        mode = page.get_by_role("combobox", name="치지직 녹화 방식", exact=True)
        concurrent = page.get_by_role(
            "spinbutton", name="동시 다운로드 개수", exact=True
        )
        source = page.get_by_role("textbox", name="라이브 녹화 원본 형식", exact=True)
        final = page.get_by_role("combobox", name="녹화 완료 후 저장 형식", exact=True)
        await expect(mode).to_have_value("force-timemachine")
        await expect(concurrent).to_have_value("5")
        await expect(source).to_have_value("자동 감지 · TS / fMP4")
        await expect(source).to_have_attribute("readonly", "")
        await expect(final).to_have_value("mkv")

        # Existing explicit and legacy settings remain selectable.
        settings.update(chzzk_stream_mode="standard", vod_max_concurrent=2)
        await page.reload()
        await page.get_by_role("button", name="다운로드", exact=True).click()
        await expect(mode).to_have_value("standard")
        await expect(concurrent).to_have_value("2")
        settings.pop("chzzk_stream_mode")
        settings["chzzk_time_machine_enabled"] = False
        await page.reload()
        await page.get_by_role("button", name="다운로드", exact=True).click()
        await expect(mode).to_have_value("standard")

        await mode.select_option("force-timemachine")
        await concurrent.fill("5")
        await page.get_by_role(
            "button", name="변경사항 저장", exact=True
        ).click()
        await expect(page.get_by_role("button", name="변경사항 저장", exact=True)).to_be_disabled()
        assert any(
            path.endswith("/live") and body["chzzk_stream_mode"] == "force-timemachine"
            for path, body in calls
        )
        assert any(
            path.endswith("/vod") and body["vod_max_concurrent"] == 5
            for path, body in calls
        )
        await page.reload()
        await page.get_by_role("button", name="다운로드", exact=True).click()
        await expect(mode).to_have_value("force-timemachine")
        await expect(concurrent).to_have_value("5")
        for width in (360, 390, 768, 1024, 1440, 1920):
            await page.set_viewport_size({"width": width, "height": 1100})
            assert await page.evaluate(
                "document.documentElement.scrollWidth <= innerWidth"
            ), width
            source_box, final_box = (
                await source.bounding_box(),
                await final.bounding_box(),
            )
            assert abs(source_box["x"] - final_box["x"]) < 1
            assert abs(source_box["width"] - final_box["width"]) < 1
            await page.screenshot(
                path=str(OUT / f"settings-{width}.png"), full_page=True
            )

        await page.goto(BASE)
        await page.locator("[data-channel-key]").first.get_by_role(
            "button", name="녹화 설정", exact=True
        ).click()
        dialog = page.get_by_role("dialog")
        await expect(
            dialog.get_by_role("textbox", name="녹화 원본 형식", exact=True)
        ).to_have_value("자동 감지 · TS / fMP4")
        await expect(
            dialog.get_by_role("textbox", name="녹화 원본 형식", exact=True)
        ).to_have_attribute("readonly", "")
        await page.screenshot(path=str(OUT / "channel-source-format.png"))
        assert not errors, errors
        await browser.close()
    print(
        "PASS: force-timemachine / 5 defaults, missing-field fallback, explicit and legacy values preserved, save/reload, read-only source format shared with channel dialog, aligned fields and no overflow at 360/390/768/1024/1440/1920, no JavaScript errors"
    )


asyncio.run(main())
