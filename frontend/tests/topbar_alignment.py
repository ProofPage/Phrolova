"""The collapsed navigation trigger shares the topbar controls' center line."""
import asyncio
import os
from pathlib import Path

from playwright.async_api import async_playwright, expect
from browser_fixtures import mock

BASE = os.environ.get("PHROLOVA_TEST_URL", "http://127.0.0.1:3000")
OUT = Path(os.environ.get("PHROLOVA_TEST_OUTPUT", "/tmp/phrolova-topbar-alignment"))


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=os.environ["PHROLOVA_CHROMIUM_EXECUTABLE"])
        for touch in (False, True):
            context = await browser.new_context(has_touch=touch)
            await context.add_init_script("window.EventSource=class{close(){}}")
            await context.route("**/api/**", mock)
            page = await context.new_page()
            await page.goto(BASE)
            for height in (354, 1000):
                for width in (320, 375, 640, 768, 944, 1023, 1440):
                    await page.set_viewport_size({"width": width, "height": height})
                    menu = page.get_by_role("button", name="메뉴 열기", exact=True)
                    if width >= 1024:
                        await expect(menu).to_be_hidden()
                        continue
                    await expect(menu).to_be_visible()
                    buttons = [menu, page.get_by_role("button", name="빠른 이동", exact=True)]
                    boxes = [await button.bounding_box() for button in buttons]
                    centers = [box["y"] + box["height"] / 2 for box in boxes]
                    assert max(centers) - min(centers) < 2, (touch, width, height, boxes)
                    assert await page.evaluate("document.documentElement.scrollWidth<=innerWidth")
                    await menu.click()
                    await expect(page.locator("#mobile-sidebar")).to_be_visible()
                    await page.keyboard.press("Escape")
                    await expect(page.locator("#mobile-sidebar")).to_have_count(0)
                    await expect(menu).to_be_focused()
                    if not touch and height == 354 and width == 944:
                        await page.locator(".app-topbar").screenshot(path=str(OUT / "topbar-aligned-944.png"))
            await context.close()
        await browser.close()
    print("PASS: topbar center lines, narrow/short windows, mouse/touch, menu open/Escape/focus restoration.")


if __name__ == "__main__":
    asyncio.run(main())
