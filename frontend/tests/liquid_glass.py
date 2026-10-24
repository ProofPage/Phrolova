"""Shared glass controls remain operable across pages, layouts and motion preferences."""
import asyncio
import os
import tempfile
from pathlib import Path

from playwright.async_api import async_playwright, expect
from browser_fixtures import mock

BASE = os.environ.get("PHROLOVA_TEST_URL", "http://127.0.0.1:3000")


async def main():
    output = Path(tempfile.mkdtemp(prefix="phrolova-glass-"))
    errors = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=os.environ["PHROLOVA_CHROMIUM_EXECUTABLE"])
        context = await browser.new_context(viewport={"width": 1440, "height": 1000})
        await context.add_init_script("window.EventSource=class{close(){}}")
        await context.route("**/api/**", mock)
        page = await context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        for width in (375, 768, 1440):
            await page.set_viewport_size({"width": width, "height": 1000})
            for path, name in (("/", "live"), ("/vod", "downloads"), ("/stats", "stats"), ("/settings", "settings"), ("/system-logs", "logs")):
                await page.goto(BASE + path)
                await expect(page.locator("#main-content")).to_be_visible()
                await expect(page.locator(".topbar-context")).to_have_count(0)
                await expect(page.get_by_role("heading").last).to_be_visible()
                surfaces = {"/": ".recording-channel", "/vod": ".download-task", "/system-logs": ".logs-file-panel, .logs-content-panel"}
                if path in surfaces:
                    cards = page.locator(surfaces[path])
                    await expect(cards.first).to_be_attached()
                    assert await cards.evaluate_all("(es)=>es.every(e=>getComputedStyle(e).backgroundColor==='rgb(23, 24, 27)')"), path
                assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (width, path)
                if path == "/settings" and width == 1440:
                    await page.locator("#main-content").evaluate("(e)=>e.scrollTo({top:600,behavior:'instant'})")
                    await page.wait_for_function("document.querySelector('.settings-tabs').getBoundingClientRect().y < 140")
                    tabs = await page.locator(".settings-tabs").bounding_box()
                    assert tabs and 60 <= tabs["y"] < 140, tabs
                    await page.get_by_role("heading", name="설정", exact=True).scroll_into_view_if_needed()
                if path == "/vod":
                    disabled = page.locator(".ui-button.btn-primary:disabled").first
                    await expect(disabled).to_be_disabled()
                    assert await disabled.evaluate("""(e)=>{
                        const reference=document.createElement('span');
                        reference.style.backgroundColor='var(--color-surface-3)';
                        e.after(reference);
                        const matches=getComputedStyle(e).backgroundColor===getComputedStyle(reference).backgroundColor;
                        reference.remove();
                        return matches;
                    }""")
                await page.screenshot(path=str(output / f"{name}-{width}.png"))
            await page.get_by_role("link", name="설정", exact=True).last.click() if width >= 1024 else await page.goto(BASE + "/settings")
            await page.get_by_role("button", name="인증", exact=True).click()
            await expect(page.get_by_role("heading", name="필요한 플랫폼만 인증하세요", exact=True)).to_have_count(0)
            await expect(page.locator(".auth-guidance")).to_have_count(0)
            assert "아래 인증 영역" not in await page.locator("#main-content").inner_text()
            grid = page.locator(".auth-platform-grid")
            layout = page.locator(".auth-platform-layout")
            assert await grid.evaluate("(e)=>Math.abs(e.getBoundingClientRect().width-e.parentElement.getBoundingClientRect().width)<2")
            if width >= 768:
                assert await grid.evaluate("(e)=>getComputedStyle(e).gridTemplateColumns.split(' ').length>1")
            assert await grid.evaluate("(e)=>e.scrollHeight<=e.clientHeight+2")
            await page.screenshot(path=str(output / f"auth-overview-{width}.png"))
            for region in (".settings-tabs", ".auth-platform-grid"):
                assert await page.locator(region).evaluate("(e)=>getComputedStyle(e).backgroundColor") == "rgb(23, 24, 27)"
            await page.locator('[data-cookie-platform="cime"] .ui-disclosure').click()
            panel = page.locator("[data-auth-detail]")
            await expect(panel).to_be_focused()
            if width > 800:
                assert await grid.evaluate("(e)=>Math.abs(e.getBoundingClientRect().width-e.nextElementSibling.getBoundingClientRect().width)<2")
                assert await grid.evaluate("""(e)=>{
                    const detail=e.nextElementSibling.querySelector('[data-auth-detail]');
                    const left=e.getBoundingClientRect(), right=detail.getBoundingClientRect();
                    const a=getComputedStyle(e), b=getComputedStyle(detail);
                    return Math.abs(left.height-right.height)<2 &&
                        a.borderRadius===b.borderRadius &&
                        a.borderTopWidth===b.borderTopWidth &&
                        a.borderTopColor===b.borderTopColor;
                }""")
            assert await panel.locator(".auth-tools .ui-button").first.evaluate("(e)=>getComputedStyle(e).wordBreak") == "keep-all"
            await expect(panel.locator('button[type="submit"]')).to_be_disabled()
            await expect(panel.get_by_role("button", name="브라우저에서 가져오기", exact=True)).to_be_enabled()
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            if width == 1440:
                control = panel.get_by_role("button", name="브라우저에서 가져오기", exact=True)
                before = await control.evaluate("(e)=>getComputedStyle(e).backgroundImage")
                await control.hover(position={"x": 10, "y": 12})
                await page.wait_for_function("document.querySelector('.auth-tools .ui-button').style.getPropertyValue('--glass-x') !== ''")
                after = await control.evaluate("(e)=>getComputedStyle(e).backgroundImage")
                assert before != after
                await page.emulate_media(reduced_motion="reduce")
                await control.hover(position={"x": 20, "y": 20})
                assert await control.evaluate("(e)=>getComputedStyle(e).transitionDuration") == "0s"
                await page.emulate_media(reduced_motion="no-preference")
                await panel.get_by_role("button", name="쿠키 파일 등록", exact=True).click()
                paste = panel.get_by_role("button", name="쿠키 직접 입력 / 붙여넣기", exact=True)
                await paste.click()
                dialog = page.get_by_role("dialog")
                await expect(dialog).to_be_visible()
                await dialog.get_by_role("textbox").fill("synthetic-session=fixture-only")
                await page.route("**/api/platforms/cime/cookie/text", lambda route: route.fulfill(status=400, json={"detail": "fixture validation failure"}))
                await dialog.get_by_role("button", name="변경사항 저장", exact=True).click()
                await expect(dialog.get_by_role("alert")).to_contain_text("fixture validation failure")
                await expect(dialog.get_by_role("textbox")).to_have_value("synthetic-session=fixture-only")
                await page.keyboard.press("Escape")
                await expect(dialog).to_have_count(0)
                await expect(paste).to_be_focused()
                await panel.get_by_role("button", name="계정 로그인", exact=True).first.click()
                await page.emulate_media(forced_colors="active")
                await expect(control).to_be_visible()
                for button in (control, panel.locator('button[type="submit"]')):
                    assert await button.evaluate("(e)=>getComputedStyle(e).color !== getComputedStyle(e).backgroundColor")
                await page.emulate_media(forced_colors="none")
                cdp = await context.new_cdp_session(page)
                await cdp.send("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-transparency", "value": "reduce"}]})
                assert await page.locator(".app-topbar").evaluate("(e)=>getComputedStyle(e).backdropFilter") == "none"
                await control.hover()
                assert await control.evaluate("(e)=>getComputedStyle(e).backdropFilter") == "none"
                await cdp.send("Emulation.setEmulatedMedia", {"features": []})
                await cdp.detach()
                checked = 0
                for platform in ("chzzk", "youtube", "kick", "twitch", "tiktok", "bilibili", "twitcasting", "berriz"):
                    await page.locator(f'[data-cookie-platform="{platform}"] .ui-disclosure').click()
                    tools = panel.locator(".auth-tools")
                    assert await tools.evaluate("(e)=>getComputedStyle(e).borderTopWidth") == "0px", platform
                    assert await panel.locator(".auth-detail-heading").evaluate("(e)=>parseFloat(getComputedStyle(e).borderBottomWidth)>0"), platform
                    checked += 1
                assert checked == 8
                await page.locator('[data-cookie-platform="cime"] .ui-disclosure').click()
            await page.screenshot(path=str(output / f"auth-{width}.png"))
            await panel.get_by_role("button", name="닫기", exact=True).click()
            await expect(panel).to_have_count(0)
            await expect(page.locator('[data-cookie-platform="cime"] .ui-disclosure')).to_be_focused()
            await expect(layout).to_have_attribute("data-selected", "false")
            assert await grid.evaluate("(e)=>Math.abs(e.getBoundingClientRect().width-e.parentElement.getBoundingClientRect().width)<2")
        assert not errors, errors
        await browser.close()
    print("PASS: five routes at 375/768/1440px; auth controls; pointer highlight; reduced motion; no overflow or JS errors")
    print(f"Screenshots: {output}")


if __name__ == "__main__":
    asyncio.run(main())
