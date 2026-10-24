"""Channel-add scheduling stays aligned and preserves submitted settings."""
import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright, expect
from browser_fixtures import mock

BASE = os.environ.get("PHROLOVA_TEST_URL", "http://127.0.0.1:3000")
OUT = Path(os.environ.get("PHROLOVA_TEST_OUTPUT", "/tmp/phrolova-schedule-layout"))
LOCALES = Path(__file__).resolve().parents[1] / "src/i18n/locales"


async def aligned(left, right):
    a, b = await left.bounding_box(), await right.bounding_box()
    assert a and b
    for key in ("y", "width", "height"):
        assert abs(a[key] - b[key]) < 2, (key, a, b)


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    submitted = []

    async def route_api(route):
        path = urlparse(route.request.url).path
        if path == "/api/platforms/channels":
            return await route.fulfill(json=[])
        if path == "/api/stream/channels" and route.request.method == "POST":
            submitted.append(route.request.post_data_json)
            return await route.fulfill(json={"message": "live.channelAdded"})
        return await mock(route)

    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=os.environ["PHROLOVA_CHROMIUM_EXECUTABLE"])
        for locale in ("ko-KR", "en-US", "ja-JP", "de-DE", "es-ES", "ru-RU", "zh-CN", "zh-TW"):
            messages = json.loads((LOCALES / f"{locale}.json").read_text(encoding="utf-8"))
            context = await browser.new_context(locale=locale)
            await context.add_init_script(
                f'localStorage.setItem("phrolova-language",{json.dumps(locale)});'
                "window.EventSource=class{close(){}}")
            await context.route("**/api/**", route_api)
            page = await context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            for width in (320, 375, 507, 1440):
                await page.set_viewport_size({"width": width, "height": 1600})
                await page.goto(BASE)
                form = page.locator(".dashboard-add-channel")
                await form.get_by_role("textbox").fill("e" * 32)
                await form.get_by_role("button", name=messages["live.openChannelSetup"]).click()
                dialog = page.get_by_role("dialog")
                await expect(dialog).to_be_visible()
                await dialog.locator("#channel-monitor-mode").select_option("scheduled")
                await aligned(dialog.locator("#schedule-start-0"), dialog.locator("#schedule-end-0"))
                await aligned(dialog.locator("#schedule-lead"), dialog.locator("#schedule-delay"))
                heading = await dialog.get_by_role("heading").bounding_box()
                label = await dialog.locator('label[for="channel-monitor-mode"]').bounding_box()
                assert heading and label and abs(heading["x"] - label["x"]) < 2
                days = dialog.locator(".channel-schedule-days button")
                boxes = [await days.nth(i).bounding_box() for i in range(7)]
                assert all(box and abs(box["y"] - boxes[0]["y"]) < 2
                           and abs(box["width"] - boxes[0]["width"]) < 2 for box in boxes)
                assert await dialog.evaluate("e=>e.scrollWidth<=e.clientWidth")
                assert await page.evaluate("document.documentElement.scrollWidth<=innerWidth")
                if locale == "ko-KR" and width in (507, 1440):
                    await page.screenshot(path=str(OUT / f"schedule-aligned-{width}.png"))
                await dialog.get_by_role("button", name=messages["live.scheduleAddWindow"]).click()
                await expect(dialog.locator(".channel-schedule-window")).to_have_count(2)
                await dialog.locator(".channel-schedule-window").last.get_by_role(
                    "button", name=messages["live.scheduleRemoveWindow"]).click()
                await expect(dialog.locator(".channel-schedule-window")).to_have_count(1)
                await dialog.locator("#schedule-lead").fill("15")
                await dialog.locator("#schedule-delay").fill("45")
                await dialog.get_by_role("button", name=messages["live.addChannel"], exact=True).click()
                await expect(dialog).to_have_count(0)
                schedule = submitted[-1]["monitor_schedule"]
                assert schedule["mode"] == "scheduled"
                assert schedule["lead_minutes"] == 15 and schedule["delay_minutes"] == 45
                assert schedule["windows"] == [{"days": list(range(7)), "start": "20:00", "end": "23:00"}]
            assert not errors, errors
            await context.close()
        await browser.close()
    print("PASS: schedule alignment at four widths in eight locales; window add/remove and submitted settings preserved.")
    print(f"Screenshots: {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
