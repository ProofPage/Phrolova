"""Quick navigation dialog semantics and keyboard behavior with isolated data."""
import asyncio
import os
from playwright.async_api import async_playwright, expect
from browser_fixtures import mock

BASE = os.environ.get("PHROLOVA_TEST_URL", "http://127.0.0.1:3011")


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            context = await browser.new_context()
            await context.add_init_script("window.EventSource=class{close(){}}")
            await context.route("**/api/**", mock)
            page = await context.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: (errors.append(m.text), print(m.text, flush=True)) if m.type == "error" else None)
            for width in (320, 375, 768, 1440):
                await page.set_viewport_size({"width": width, "height": 812})
                for route in ("/", "/vod", "/stats", "/system-logs", "/settings"):
                    await page.goto(BASE + route)
                    trigger = page.get_by_role("button", name="빠른 이동", exact=True)
                    await trigger.click()
                    dialog = page.get_by_role("dialog", name="빠른 이동", exact=True)
                    await expect(dialog).to_be_visible()
                    await expect(dialog.get_by_role("heading", name="빠른 이동")).to_have_count(1)
                    search = page.get_by_role("combobox", name="빠른 이동", exact=True)
                    await search.fill("없는페이지")
                    await expect(page.get_by_text("검색 결과가 없습니다.", exact=True)).to_be_visible()
                    await page.keyboard.press("Escape")
                    await expect(dialog).to_have_count(0)
                    await expect(trigger).to_be_focused()
                    await trigger.click()
                    await expect(dialog).to_be_visible()
                    await page.mouse.click(1, 1)
                    await expect(dialog).to_have_count(0)
                    await expect(trigger).to_be_focused()
                    assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                await page.keyboard.press("Control+k")
                await page.get_by_role("combobox", name="빠른 이동", exact=True).fill("통계")
                await page.keyboard.press("Enter")
                await expect(page).to_have_url(BASE + "/stats")
            assert not errors, errors
        finally:
            await browser.close()
    print("PASS: quick-navigation names, headings, search, Escape/focus, keyboard routing and 20 responsive page states")


if __name__ == "__main__":
    asyncio.run(main())
