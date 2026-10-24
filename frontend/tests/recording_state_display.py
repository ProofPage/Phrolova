"""Recovery, blocked errors and terminal states agree in actual channel UI."""
import asyncio
import copy
import json
import os
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright, expect
from browser_fixtures import FIX, mock

BASE = os.environ.get("PHROLOVA_TEST_URL", "http://127.0.0.1:3000")
KO = json.loads((Path(__file__).parents[1] / "src/i18n/locales/ko-KR.json").read_text(encoding="utf-8-sig"))


async def main():
    channel = copy.deepcopy(FIX["channels"][1])
    channel.update(channel_id="e" * 32, channel_name="복구 표시 검사", title="예시 방송",
                   tags=[], postprocess=None, monitor_error=None, is_live=True)
    original = copy.deepcopy(channel["recording"])
    cases = [
        ("error", False, "stream_unavailable", False, "live.serverRecoveryWait"),
        ("error", False, "connection", False, "live.waitingToReconnect"),
        ("error", False, "stream_closed", False, "live.streamClosedPending"),
        ("error", False, "stream_unavailable", True, "live.recordingError"),
        ("recording", True, None, False, "live.recording"),
        ("completed", False, None, False, "live.recordingCompleted"),
        ("idle", False, None, False, "live.waitingToRecord"),
    ]

    async def route_api(route):
        if urlparse(route.request.url).path == "/api/platforms/channels":
            return await route.fulfill(json=[channel])
        return await mock(route)

    async with async_playwright() as p:
        options = {"executable_path": os.environ["PHROLOVA_CHROMIUM_EXECUTABLE"]} if "PHROLOVA_CHROMIUM_EXECUTABLE" in os.environ else {}
        browser = await p.chromium.launch(**options)
        context = await browser.new_context()
        await context.add_init_script("window.EventSource=class{close(){}};localStorage.setItem('phrolova-language','ko-KR')")
        await context.route("**/api/**", route_api)
        page = await context.new_page()
        for width in (375, 1440):
            await page.set_viewport_size({"width": width, "height": 1000})
            for state, receiving, code, blocked, key in cases:
                channel.update(retry_code=code, retry_blocked=blocked,
                               retry_at="2026-10-24T23:10:00" if code and not blocked else None,
                               last_error="503 Service Unavailable" if state == "error" and code != "stream_closed" else None)
                channel["recording"] = dict(original, state=state, is_recording=receiving,
                                            has_data=True, file_size_bytes=1048576,
                                            download_speed=1.25, bitrate=1000,
                                            connection_stage="receiving", connection_events=[])
                await page.goto(BASE)
                card = page.locator(".recording-channel")
                await expect(card).to_be_visible()
                await expect(card.locator(".recording-channel-statuses")).to_contain_text(KO[key])
                if state == "error" and code != "stream_closed":
                    await expect(card.locator(".recording-status-message.text-danger")).to_have_count(1 if blocked else 0)
                speed = card.locator(".recording-metrics > div").filter(has=page.get_by_text(KO["live.writeSpeed"], exact=True))
                await expect(speed.locator("dd")).to_have_text("1.25 MB/s" if receiving else "—")
                await card.locator(".recording-detail-action").click()
                details = page.locator(".recording-detail-panel:not([hidden])")
                await expect(details.locator(".recording-details-copy > p[role=status]").first).to_have_text(KO[key])
                assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), (width, state)
        await browser.close()
    print("PASS: seven reception/recovery/blocked/terminal states, card/detail agreement and live speed at 375/1440px.")


if __name__ == "__main__":
    asyncio.run(main())
