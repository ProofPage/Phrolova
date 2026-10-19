"""Authentication selection, isolated login requests and responsive detail panel."""
import asyncio
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright, expect
from browser_fixtures import mock

BASE = os.environ.get("PHROLOVA_TEST_URL", "http://127.0.0.1:3011")


async def main():
    calls, errors = [], []
    failure = False

    async def route_api(route):
        path = urlsplit(route.request.url).path
        if path.startswith("/api/platforms/") and path.endswith("/login"):
            calls.append(route.request.post_data_json)
            return await route.fulfill(status=401 if failure else 200,
                json={"detail": "settings.rplaySessionInvalid"} if failure else
                     {"configured": True, "valid": True, "expired": False})
        return await mock(route)

    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=os.environ["PHROLOVA_CHROMIUM_EXECUTABLE"])
        try:
            context = await browser.new_context(viewport={"width": 1440, "height": 1100})
            await context.add_init_script("window.EventSource=class{close(){}}")
            await context.route("**/api/**", route_api)
            page = await context.new_page()
            page.on("pageerror", lambda e: errors.append(str(e)))
            await page.goto(BASE + "/settings")
            await page.get_by_role("button", name="인증", exact=True).click()
            selectors = page.locator(".auth-platform-card .ui-disclosure")
            await expect(selectors).to_have_count(11)
            positions = "(es)=>es.map(e=>{const r=e.getBoundingClientRect();return [r.x,r.y-es[0].getBoundingClientRect().y,r.height]})"
            baseline = await selectors.evaluate_all(positions)
            assert len({box[2] for box in baseline}) == 1
            for i in range(11):
                await selectors.nth(i).click()
                await expect(page.locator("[data-auth-detail]")).to_have_count(1)
                await expect(page.locator(".ui-disclosure[aria-expanded=true]")).to_have_count(1)
                assert baseline == await selectors.evaluate_all(positions)
                await expect(page.locator("[data-auth-detail]")).to_be_focused()
            panel = page.locator("[data-auth-detail]")
            for platform in ("cime", "pandalive", "popkontv", "hearheart", "rplay"):
                selector = page.locator(f'[data-{"auth" if platform == "rplay" else "cookie"}-platform="{platform}"] .ui-disclosure')
                if await selector.get_attribute("aria-expanded") != "true":
                    await selector.click()
                form = panel.locator("form")
                await expect(form.locator("label")).to_have_count(2)
                username = form.locator("input").first
                password = form.locator('input[type=password]')
                await expect(form.locator('button[type=submit]')).to_be_disabled()
                await username.fill("viewer@example.invalid" if platform in ("cime", "hearheart", "rplay") else "viewer")
                await password.fill("fixture-password")
                await form.locator('button[type=submit]').click()
                await expect(password).to_have_value("")
                assert calls[-1]["password"] == "fixture-password"
                await password.fill("must-clear")
                await panel.locator(".auth-methods button").nth(1).click()
                await expect(panel.locator("form")).to_have_count(0)
                await panel.locator(".auth-methods button").first.click()
                await expect(panel.locator('input[type=password]')).to_have_value("")
                await password.fill("must-clear")
                await page.locator('[data-cookie-platform="chzzk"] .ui-disclosure').click()
                await selector.click()
                await expect(panel.locator('input[type=password]')).to_have_value("")
            failure = True
            await panel.locator("form input").first.fill("viewer@example.invalid")
            await panel.locator('input[type=password]').fill("fixture-password")
            await panel.locator('button[type=submit]').click()
            await expect(panel.get_by_role("alert")).to_be_visible()
            await expect(panel.get_by_role("alert")).not_to_contain_text("settings.")
            await expect(panel.locator('input[type=password]')).to_have_value("")
            await page.reload()
            await page.get_by_role("button", name="인증", exact=True).click()
            await page.locator('[data-auth-platform="rplay"] .ui-disclosure').click()
            output = Path(tempfile.mkdtemp(prefix="auth-selection-", dir=Path(__file__).resolve().parents[4] / "work"))
            for width in (320, 375, 768, 1440):
                await page.set_viewport_size({"width": width, "height": 1000})
                assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
                for button in await panel.locator("button").all():
                    box = await button.bounding_box()
                    assert not box or box["height"] >= 44
                if width in (375, 1440):
                    await page.screenshot(path=str(output / f"{width}.png"), full_page=True)
            await selectors.first.focus()
            await page.keyboard.press("Enter")
            await expect(page.locator('[data-auth-detail="chzzk"]')).to_be_visible()
            assert "fixture-password" not in await page.evaluate("JSON.stringify({...localStorage,...sessionStorage})")
            assert not errors, errors
            print("PASS: stable selection grid, one detail panel, five login forms, labels, password clearing, failures, keyboard and 320–1440px layouts")
            print("Screenshots:", output)
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
