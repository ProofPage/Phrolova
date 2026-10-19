"""Isolated Twitch proxy consent, persistence and responsive settings checks."""
import asyncio
import copy
import os
from urllib.parse import urlparse

from playwright.async_api import async_playwright, expect
from browser_fixtures import FIX, mock

BASE = os.environ.get("PHROLOVA_TEST_URL", "http://127.0.0.1:3017")


async def main():
    settings = copy.deepcopy(FIX["settings"])
    settings["twitch_proxy_enabled"] = False
    requests = []

    async def api(route):
        path = urlparse(route.request.url).path
        if path == "/api/settings":
            return await route.fulfill(json=settings)
        if path == "/api/settings/live":
            data = route.request.post_data_json
            requests.append(data)
            settings.update(data)
            return await route.fulfill(json={"settings": settings})
        return await mock(route)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        context = await browser.new_context(viewport={"width": 1440, "height": 1000})
        await context.add_init_script("window.EventSource=class{close(){}}")
        await context.route("**/api/**", api)
        page = await context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            await page.goto(BASE + "/settings")
            card = page.locator('[data-settings-section="twitch"]')
            toggle = card.get_by_role("switch")
            save = page.locator(".download-settings-save").get_by_role("button")
            await expect(toggle).not_to_be_checked()
            assert "auth=" in await card.inner_text()
            await toggle.click()
            await expect(save).to_be_enabled()
            await save.click()
            await expect(save).to_be_disabled()
            assert requests[-1]["twitch_proxy_enabled"] is True
            await page.reload()
            await expect(toggle).to_be_checked()
            for width in (1440, 768, 375, 320):
                await page.set_viewport_size({"width": width, "height": 1000})
                await toggle.scroll_into_view_if_needed()
                assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
                box = await toggle.bounding_box()
                if width <= 375:
                    assert box["width"] >= 44 and box["height"] >= 44, box
                assert await card.evaluate("(e)=>e.scrollWidth<=e.clientWidth"), width
            await toggle.click()
            await save.click()
            await expect(save).to_be_disabled()
            assert requests[-1]["twitch_proxy_enabled"] is False
            assert not errors, errors
            print("PASS: Twitch proxy off by default; consent warning; enable/save/reload/disable; 320–1440px layout; no page errors")
        finally:
            await browser.close()


asyncio.run(main())
