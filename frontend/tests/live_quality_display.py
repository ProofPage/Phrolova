"""Actual quality metadata is visible in both channel details and the selector."""
import asyncio
import copy
import os
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright, expect
from browser_fixtures import FIX, mock

BASE = os.environ.get("PHROLOVA_TEST_URL", "http://127.0.0.1:3000")
OUT = Path(os.environ.get("PHROLOVA_TEST_OUTPUT", "/tmp/phrolova-live-quality"))


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    channel = copy.deepcopy(FIX["channels"][1])
    channel.update(channel_id="e" * 32, channel_name="화질 확인", title="표시 확인용 예시 방송",
                   category="예시", tags=[], recording_quality="1080p60")
    channel["recording"].update(
        recording_resolution={"width": 1920, "height": 1080, "fps": 60},
        output_path="/recordings/sample.ts")

    async def route_api(route):
        path = urlparse(route.request.url).path
        if path == "/api/platforms/channels":
            return await route.fulfill(json=[channel])
        if path.endswith("/qualities"):
            return await route.fulfill(json={"live": True, "qualities": [
                dict(value="1080p60", label="1080p60", width=1920, height=1080, fps=60),
                dict(value="720p30", label="720p30", width=1280, height=720, fps=30)]})
        return await mock(route)

    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=os.environ["PHROLOVA_CHROMIUM_EXECUTABLE"])
        context = await browser.new_context(viewport={"width": 1440, "height": 1000})
        await context.add_init_script("window.EventSource=class{close(){}}")
        await context.route("**/api/**", route_api)
        page = await context.new_page()
        for platform in ("chzzk", "cime", "kick", "twitch", "tiktok", "bilibili", "pandalive", "popkontv", "rplay"):
            channel["platform"] = platform
            await page.goto(BASE)
            await page.locator(".recording-detail-action").click()
            details = page.locator(".recording-details-fields")
            await expect(details.get_by_text("1920×1080 · 60fps", exact=True)).to_be_visible()
            if platform == "chzzk":
                await details.screenshot(path=str(OUT / "quality-details-chzzk.png"))
            await page.get_by_role("button", name="녹화 설정", exact=True).click()
            selector = page.locator("#channel-recording-quality")
            await expect(selector.locator("option:checked")).to_have_text("1080p60 · 1920×1080 · 60fps")
            await selector.select_option("720p30")
            await expect(selector.locator("option:checked")).to_have_text("720p30 · 1280×720 · 30fps")
            if platform == "chzzk":
                await selector.select_option("1080p60")
                await selector.screenshot(path=str(OUT / "quality-selector-chzzk.png"))
            await page.keyboard.press("Escape")
        await browser.close()
    print("PASS: quality details and native select labels on CHZZK and eight other supported platforms.")


if __name__ == "__main__":
    asyncio.run(main())
