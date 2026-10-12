"""First-run setup in Chromium, with all settings and directory requests mocked."""

import asyncio
import os
import re
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright, expect

from browser_fixtures import mock


BASE = os.environ.get("PHROLOVA_TEST_URL", "http://127.0.0.1:3001")
OUT = Path(os.environ.get("PHROLOVA_TEST_OUTPUT", "/tmp/phrolova-setup-wizard"))
LIVE = r"C:\Users\Administrator\Downloads\Phrolova\라이브 녹화 보관\긴 폴더 이름을 확인하는 저장 위치\Live"
VIDEO = r"C:\Users\Administrator\Downloads\Phrolova\다시보기와 클립 보관\긴 폴더 이름을 확인하는 저장 위치\Video"
CHOSEN = r"D:\선택한 폴더\라이브 녹화"
DEFAULT_LIVE = r"C:\Users\Administrator\Downloads\Phrolova\Live"
DEFAULT_VIDEO = r"C:\Users\Administrator\Downloads\Phrolova\Video"
VIEWPORTS = ((320, 740), (390, 844), (640, 900), (1440, 1000), (844, 390))


async def visible_footer(page, dialog, label):
    """Navigation stays usable even when the fields need their own scroll area."""
    button = dialog.get_by_role("button", name=label, exact=True)
    bounds = await button.bounding_box()
    viewport = page.viewport_size
    assert bounds and viewport, (label, "missing navigation")
    assert 0 <= bounds["y"] and bounds["y"] + bounds["height"] <= viewport["height"] + 1, (label, bounds, viewport)
    assert await dialog.evaluate("e => e.scrollWidth <= e.clientWidth"), (label, "dialog horizontal overflow")
    assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "page horizontal overflow"


async def aligned_directory(field, button_height, field_height=None):
    sizes = await field.evaluate("""e => {
        const input=e.getBoundingClientRect(),button=e.parentElement.querySelector('button').getBoundingClientRect(),style=getComputedStyle(e);
        const top=parseFloat(style.paddingTop),bottom=parseFloat(style.paddingBottom);
        const lineCenter=parseFloat(style.borderTopWidth)+top+parseFloat(style.lineHeight)/2;
        return {height:input.height,buttonHeight:button.height,centers:Math.abs(input.top+input.height/2-button.top-button.height/2),
            paddingDelta:Math.abs(top-bottom),lineCenterDelta:Math.abs(lineCenter-input.height/2)};
    }""")
    assert abs(sizes["buttonHeight"] - button_height) < 1, ("browse height", sizes)
    if field_height is not None:
        assert abs(sizes["height"] - field_height) < 1, ("bulky default path", sizes)
        assert sizes["paddingDelta"] < 1 and sizes["lineCenterDelta"] <= 1, ("one-line path text is not vertically centered", sizes)
    assert sizes["centers"] < 1, ("path/browse alignment", sizes)


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    default_directories = {"live_download_dir": DEFAULT_LIVE, "vod_download_dir": DEFAULT_VIDEO}
    posts = []
    save_started = asyncio.Event()
    release_save = asyncio.Event()
    delay_save = True
    fail_save = True

    async def route_api(route):
        path = urlparse(route.request.url).path
        if path == "/api/setup/status":
            return await route.fulfill(json={"needs_setup": True, "default_directories": default_directories})
        if path == "/api/settings/browse-dirs":
            return await route.fulfill(json={"current": CHOSEN, "parent": "D:\\", "dirs": []})
        if path == "/api/setup/complete":
            posts.append(route.request.post_data_json)
            save_started.set()
            if delay_save:
                await release_save.wait()
            if fail_save:
                return await route.fulfill(status=400, json={"detail": "저장 경로를 생성할 수 없습니다."})
            return await route.fulfill(json={"success": True})
        return await mock(route)

    async with async_playwright() as playwright:
        launch = {}
        if executable := os.environ.get("PHROLOVA_CHROMIUM_EXECUTABLE"):
            launch["executable_path"] = executable
        browser = await playwright.chromium.launch(**launch)
        context = await browser.new_context()
        await context.add_init_script("window.EventSource=class{close(){}}")
        await context.route("**/api/**", route_api)
        page = await context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            # Default Windows paths stay compact; narrowing and widening must resize the same controls.
            await page.set_viewport_size({"width": 1440, "height": 1000})
            await page.goto(BASE, wait_until="domcontentloaded")
            dialog = page.get_by_role("dialog", name="기본 설정", exact=True)
            await expect(dialog).to_be_visible()
            fields = [dialog.get_by_role("textbox", name=label) for label in ("라이브 저장 위치", "동영상 저장 위치")]
            for field, value in zip(fields, (DEFAULT_LIVE, DEFAULT_VIDEO)):
                await expect(field).to_have_value(value)
                await expect(field).to_have_css("font-size", "13px")
                await aligned_directory(field, 34, 34)
            await visible_footer(page, dialog, "설정 확인")
            await page.screenshot(path=str(OUT / "setup-default-desktop.png"))
            await page.set_viewport_size({"width": 320, "height": 740})
            await page.wait_for_function("[...document.querySelectorAll('#setup-live-dir,#setup-vod-dir')].every(e => e.getBoundingClientRect().height > 44)")
            for field in fields:
                await expect(field).to_have_css("font-size", "13px")
                assert await field.evaluate("e => e.scrollWidth <= e.clientWidth"), "default path overflows after narrowing"
                await aligned_directory(field, 44)
            await visible_footer(page, dialog, "설정 확인")
            await page.screenshot(path=str(OUT / "setup-default-mobile.png"))
            for field, value in zip(fields, (r"C:\Live", r"C:\Video")):
                await field.fill(value)
            await page.wait_for_function("[...document.querySelectorAll('#setup-live-dir,#setup-vod-dir')].every(e => Math.abs(e.getBoundingClientRect().height - 44) < 1)")
            for field in fields:
                await aligned_directory(field, 44, 44)
            await page.screenshot(path=str(OUT / "setup-short-mobile.png"))
            for field, value in zip(fields, (DEFAULT_LIVE, DEFAULT_VIDEO)):
                await field.fill(value)
            await page.set_viewport_size({"width": 1440, "height": 1000})
            await page.wait_for_function("[...document.querySelectorAll('#setup-live-dir,#setup-vod-dir')].every(e => Math.abs(e.getBoundingClientRect().height - 34) < 1)")
            await page.screenshot(path=str(OUT / "setup-default-desktop-restored.png"))
            for field, value in zip(fields, (LIVE, VIDEO)):
                await field.fill(value)
            await page.wait_for_function("[...document.querySelectorAll('#setup-live-dir,#setup-vod-dir')].every(e => e.getBoundingClientRect().height > 34)")
            for field in fields:
                assert await field.evaluate("e => e.scrollWidth <= e.clientWidth"), "long path overflows after editing"
                await aligned_directory(field, 34)
            default_directories.update(live_download_dir=LIVE, vod_download_dir=VIDEO)
            for width, height in VIEWPORTS:
                await page.set_viewport_size({"width": width, "height": height})
                await page.goto(BASE, wait_until="domcontentloaded")
                dialog = page.get_by_role("dialog", name="기본 설정", exact=True)
                await expect(dialog).to_be_visible()
                await expect(dialog.locator('ol[aria-label="설정 단계"] li[aria-current="step"]')).to_contain_text("기본 설정")
                live = dialog.get_by_role("textbox", name="라이브 저장 위치")
                video = dialog.get_by_role("textbox", name="동영상 저장 위치")
                await expect(live).to_have_value(LIVE)
                await expect(video).to_have_value(VIDEO)
                for field in (live, video):
                    await expect(field).to_have_attribute("required", "")
                    assert await field.evaluate("e => e.tagName === 'TEXTAREA' && !!e.getAttribute('aria-describedby')"), "paths lack multiline descriptions"
                await visible_footer(page, dialog, "설정 확인")
                await page.screenshot(path=str(OUT / f"setup-basic-{width}x{height}.png"))

                # Nested directory selection must trap focus, then return it to its opener.
                browse = dialog.get_by_role("button", name="폴더 찾아보기", exact=True).first
                await browse.click()
                picker = page.get_by_role("dialog", name="폴더 선택", exact=True)
                await expect(picker.get_by_role("button", name="이 폴더 선택", exact=True)).to_be_enabled()
                for _ in range(8):
                    await page.keyboard.press("Tab")
                    assert await picker.evaluate("e => e.contains(document.activeElement)"), "nested focus escaped"
                await page.keyboard.press("Escape")
                await expect(picker).to_have_count(0)
                await expect(browse).to_be_focused()
                await expect(live).to_have_value(LIVE)
                await browse.click()
                await picker.get_by_role("button", name="이 폴더 선택", exact=True).click()
                await expect(live).to_have_value(CHOSEN)
                await expect(browse).to_be_focused()
                await live.fill(LIVE)

                # The same native selects as the live/video settings support mouse and keyboard.
                quality = dialog.get_by_role("combobox", name="라이브 녹화 화질", exact=True)
                await quality.focus()
                await page.keyboard.press("ArrowDown")
                await page.keyboard.press("Enter")
                await expect(quality).to_have_value("1080p")
                await quality.select_option("720p")
                output_format = dialog.get_by_role("combobox", name="녹화 완료 후 저장 형식", exact=True)
                await output_format.focus()
                await page.keyboard.press("ArrowDown")
                await page.keyboard.press("Enter")
                await expect(output_format).to_have_value("mp4")
                await dialog.get_by_role("button", name="설정 확인", exact=True).click()
                confirmation = page.get_by_role("dialog", name="설정 확인", exact=True)
                await expect(confirmation.get_by_role("heading", name="설정 확인", exact=True)).to_be_focused()
                await expect(confirmation.locator('ol[aria-label="설정 단계"] li[aria-current="step"]')).to_contain_text("설정 확인")
                summary = confirmation.locator("dl")
                await expect(summary).to_contain_text(LIVE)
                await expect(summary).to_contain_text(VIDEO)
                await expect(summary).to_contain_text("720p")
                await expect(summary).to_contain_text("MP4")
                assert await summary.locator("dd").evaluate_all("es => es.every(e => e.scrollWidth <= e.clientWidth && getComputedStyle(e).textOverflow !== 'ellipsis')"), "confirmation values are clipped"
                await visible_footer(page, confirmation, "설정 완료")
                await page.screenshot(path=str(OUT / f"setup-confirm-{width}x{height}.png"))
                await confirmation.get_by_role("button", name="이전", exact=True).click()
                await expect(dialog.get_by_role("heading", name="기본 설정", exact=True)).to_be_focused()
                await expect(live).to_have_value(LIVE)
                await expect(video).to_have_value(VIDEO)
                await expect(quality).to_have_value("720p")
                await expect(output_format).to_have_value("mp4")
                await live.fill("   ")
                await expect(dialog.get_by_role("button", name="설정 확인", exact=True)).to_be_disabled()
                await live.fill(LIVE)
                await video.fill("")
                await expect(dialog.get_by_role("button", name="설정 확인", exact=True)).to_be_disabled()
                await video.fill(VIDEO)

            # A delayed, failed save keeps data and prevents conflicting navigation.
            await dialog.get_by_role("button", name="설정 확인", exact=True).click()
            confirmation = page.get_by_role("dialog", name="설정 확인", exact=True)
            await confirmation.get_by_role("button", name="설정 완료", exact=True).click()
            await asyncio.wait_for(save_started.wait(), 5)
            await expect(confirmation.get_by_role("button", name="이전", exact=True)).to_be_disabled()
            await expect(confirmation.get_by_role("button", name=re.compile("^저장 중"))).to_be_disabled()
            assert len(posts) == 1, posts
            expected = {"download_dir": LIVE, "live_download_dir": LIVE, "vod_download_dir": VIDEO,
                        "live_format": "mp4", "recording_quality": "720p"}
            assert posts[0] == expected, posts[0]
            release_save.set()
            await expect(confirmation.get_by_role("alert")).to_contain_text("설정을 저장하지 못했습니다.")
            await expect(confirmation.get_by_role("button", name="이전", exact=True)).to_be_enabled()
            await expect(confirmation.get_by_role("button", name="설정 완료", exact=True)).to_be_enabled()
            await expect(confirmation.locator("dl")).to_contain_text(LIVE)
            await page.screenshot(path=str(OUT / "setup-save-retry.png"))
            delay_save = False
            fail_save = False
            await confirmation.get_by_role("button", name="설정 완료", exact=True).click()
            await expect(page.get_by_role("dialog")).to_have_count(0)
            assert posts == [expected, expected], posts
            assert not errors, errors
        finally:
            release_save.set()
            await context.close()
            await browser.close()
    print("PASS: compact 34/44px paths, textarea resize/edit growth, shared settings selects, nested folder focus, next/back, blank validation, save busy/failure/retry, 320/390/640/1440px and 844x390 landscape")


if __name__ == "__main__":
    asyncio.run(main())
