"""Settings persistence, invalid input, mobile tags and recording retry/skip UI."""
import asyncio
import copy
import json
import os
from urllib.parse import unquote, urlparse

from playwright.async_api import async_playwright, expect
from browser_fixtures import FIX, mock

BASE = os.environ.get("PHROLOVA_TEST_URL", "http://127.0.0.1:3000")


async def main():
    settings = copy.deepcopy(FIX["settings"])
    settings["streamlink_platform_options"] = {}
    channels = [copy.deepcopy(FIX["channels"][0]), copy.deepcopy(FIX["channels"][0])]
    channels[0].update(channel_id="retry-fixture", composite_key="chzzk:retry-fixture", channel_name="Retry fixture",
                       is_live=False, last_error="Recording failed", tags=["MobileTag"],
                       recording={"state": "error", "is_recording": False, "has_data": False,
                                  "duration_seconds": 0, "file_size_bytes": 0, "download_speed": 0, "bitrate": 0,
                                  "output_path": None, "start_time": None})
    channels[1].update(channel_id="skip-fixture", composite_key="chzzk:skip-fixture", channel_name="Skip fixture",
                       is_live=True, last_error=None, skip_pending=True, download_hold_reason=None, tags=[],
                       recording={"state": "stopping", "is_recording": True, "has_data": True,
                                  "duration_seconds": 10, "file_size_bytes": 18800, "download_speed": 0, "bitrate": 0,
                                  "output_path": "/recordings/skip.ts", "start_time": "2026-10-18T00:00:00"})
    calls = []
    async def route_api(route):
        path = unquote(urlparse(route.request.url).path)
        if path == "/api/settings":
            return await route.fulfill(json=settings)
        if path == "/api/settings/live":
            calls.append((path, route.request.post_data_json))
            settings.update(route.request.post_data_json)
            return await route.fulfill(json={"settings": settings})
        if path == "/api/stream/channels":
            return await route.fulfill(json={"channels": channels})
        if path == "/api/platforms/channels":
            return await route.fulfill(json=channels)
        if path == "/api/stream/record/chzzk:retry-fixture/start":
            calls.append((path, route.request.post_data_json))
            return await route.fulfill(json={"state": "connecting", "is_recording": True})
        return await mock(route)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        context = await browser.new_context(viewport={"width": 1440, "height": 1100}, locale="ko-KR")
        await context.add_init_script("window.EventSource=class{close(){}}")
        await context.route("**/api/**", route_api)
        page = await context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            await page.goto(BASE + "/settings")
            root = page.locator(".download-settings")
            card = root.locator('[data-settings-section="transport"]')
            save = root.locator(".download-settings-save").get_by_role("button")
            await expect(save).to_be_disabled()
            await card.get_by_role("combobox").select_option("cime")
            delay = card.get_by_role("spinbutton")
            parameters = card.get_by_role("textbox")
            await delay.fill("1")
            await expect(save).to_be_disabled()
            await delay.fill("3")
            await parameters.fill('{"cache":"value"}')
            await expect(save).to_be_enabled()
            await save.click()
            await expect(save).to_be_disabled()
            assert calls[-1][1]["streamlink_platform_options"]["cime"] == {
                "playlist_reload_seconds": 3, "query_parameters": {"cache": "value"}
            }
            await page.reload()
            await card.get_by_role("combobox").select_option("cime")
            await expect(delay).to_have_value("3")
            assert json.loads(await parameters.input_value()) == {"cache": "value"}
            await parameters.fill("{")
            await expect(card.get_by_role("alert")).to_be_visible()
            await expect(save).to_be_disabled()
            await parameters.fill('{"cache":"value"}')
            await expect(save).to_be_disabled()
            format_select = root.locator('[data-settings-section="video"] select').filter(
                has=page.locator('option[value="mkv"]'))
            await expect(format_select.locator('option[value="ts"]')).to_have_count(0)
            for width in (390, 768, 1440):
                await page.set_viewport_size({"width": width, "height": 1000})
                assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            await page.set_viewport_size({"width": 390, "height": 900})
            await page.goto(BASE + "/")
            retry = page.locator(".recording-channel").filter(has=page.get_by_role("heading", name="Retry fixture", exact=True))
            await expect(retry.get_by_role("button", name="다시 시도", exact=True)).to_be_enabled()
            await expect(retry.locator(".recording-tag")).to_be_hidden()
            await retry.get_by_role("button", name="다시 시도", exact=True).click()
            assert any(path.endswith("retry-fixture/start") for path, _ in calls)
            skip = page.locator(".recording-channel").filter(has=page.get_by_role("heading", name="Skip fixture", exact=True))
            await expect(skip.get_by_text("건너뛰기 위해 녹화 중지 중", exact=True)).to_be_visible()
            channels[1]["skip_pending"] = False
            channels[1]["recording"].update(state="completed", is_recording=False)
            channels[1]["download_hold_reason"] = "같이보기 태그 조건과 일치하지 않는 방송입니다."
            await page.reload()
            await expect(skip.get_by_text("건너뜀", exact=True)).to_be_visible()
            assert not errors, errors
            print("PASS: stream request settings, JSON validation, VOD formats, retry/skip states and mobile tags")
        finally:
            await context.close()
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
