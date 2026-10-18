"""Four password forms: wire requests, failures, stale status and mobile layout."""
import asyncio
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright, expect
from browser_fixtures import mock

BASE = os.environ.get("PHROLOVA_TEST_URL", "http://127.0.0.1:3000")
PLATFORMS = ("cime", "pandalive", "popkontv", "hearheart")
PASSWORD = "fixture-password +&한글"


async def main():
    calls, errors = [], []
    configured = set()
    failure = None
    delay = None
    delay_started = None

    async def route_api(route):
        nonlocal failure
        request = route.request
        path = urlsplit(request.url).path
        parts = path.strip("/").split("/")
        if parts == ["api", "platforms", "rplay", "login"]:
            return await route.fulfill(status=401, json={"detail": "settings.rplaySessionInvalid"})
        if len(parts) == 4 and parts[:2] == ["api", "platforms"] and parts[2] in PLATFORMS:
            platform, operation = parts[2:]
            if operation == "login":
                calls.append((platform, request.post_data_json))
                if delay is not None:
                    delay_started.set()
                    await delay.wait()
                if failure:
                    return await route.fulfill(status=409, json={"detail": {
                        "message": failure, "code": "challenge",
                    }})
                configured.add(platform)
            elif operation == "cookie":
                if request.method == "DELETE":
                    configured.discard(platform)
                elif request.method == "POST":
                    configured.add(platform)
            else:
                return await mock(route)
            return await route.fulfill(json={"configured": platform in configured,
                "valid": platform in configured, "expired": False})
        return await mock(route)

    async with async_playwright() as playwright:
        options = {"executable_path": os.environ["PHROLOVA_CHROMIUM_EXECUTABLE"]} if os.environ.get("PHROLOVA_CHROMIUM_EXECUTABLE") else {}
        browser = await playwright.chromium.launch(**options)
        try:
            context = await browser.new_context(viewport={"width": 1440, "height": 1000})
            await context.add_init_script("window.EventSource=class{close(){}}")
            await context.route("**/api/**", route_api)
            page = await context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.goto(BASE + "/settings")
            await page.get_by_role("button", name="인증", exact=True).click()
            await expect(page.locator('[data-cookie-platform] form')).to_have_count(0)
            # Opening a left-column card must not move cards in the right column.
            right = page.locator('.auth-platform-column').nth(1).locator('.auth-platform-card')
            before_y = [await right.nth(i).evaluate("(e) => e.getBoundingClientRect().top") for i in range(await right.count())]
            chzzk = page.locator('[data-cookie-platform="chzzk"] .ui-disclosure')
            await chzzk.click()
            after_y = [await right.nth(i).evaluate("(e) => e.getBoundingClientRect().top") for i in range(await right.count())]
            assert before_y == after_y, (before_y, after_y)
            await chzzk.click()
            for platform in PLATFORMS:
                card = page.locator(f'[data-cookie-platform="{platform}"]')
                await card.locator(".ui-disclosure").click()
                form = card.locator("form")
                username = form.locator('input[name="username"]')
                password = form.locator('input[name="password"]')
                submit = form.locator('button[type="submit"]')
                await expect(form).to_have_count(1)
                await expect(submit).to_be_disabled()
                await expect(password).to_have_attribute("type", "password")
                identifier = "viewer@example.invalid" if platform in ("cime", "hearheart") else "viewer"
                await username.fill(" " + identifier + " " if platform not in ("cime", "hearheart") else identifier)
                await password.fill(PASSWORD)
                await submit.click()
                await expect(password).to_have_value("")
                await expect(card).to_contain_text("쿠키 등록됨")
                await expect(page.get_by_text("로그인 정보를 등록했습니다.", exact=True).last).to_be_visible()
                assert calls[-1] == (platform, {"username": identifier, "password": PASSWORD})
                assert await card.locator('input[type="file"]').count() == 1
                link = form.get_by_role("link")
                assert (await link.get_attribute("href")).startswith("https://")
                await expect(link).to_have_attribute("rel", "noopener noreferrer")
            assert await page.locator("[data-account-login]").count() == 4
            await page.locator('[data-auth-platform="rplay"] .ui-disclosure').click()
            assert await page.locator("[data-auth-platform=rplay] form").count() == 1
            rplay = page.locator('[data-auth-platform="rplay"]')
            await rplay.locator('#rplay-login-password').fill(PASSWORD)
            await rplay.locator('.ui-disclosure').click()
            await rplay.locator('.ui-disclosure').click()
            await expect(rplay.locator('#rplay-login-password')).to_have_value("")
            await rplay.locator('#rplay-login-email').fill("viewer@example.invalid")
            await rplay.locator('#rplay-login-password').fill(PASSWORD)
            await rplay.locator('button[type="submit"]').click()
            await expect(rplay.locator('#rplay-login-password')).to_have_value("")
            await expect(rplay.get_by_role('alert')).to_be_visible()
            await expect(rplay.get_by_role('alert')).not_to_contain_text("settings.rplaySessionInvalid")
            upload_card = page.locator('[data-cookie-platform="cime"]')
            await upload_card.locator('.auth-methods').get_by_role('button', name="쿠키 파일 등록", exact=True).click()
            await upload_card.locator('input[type="file"]').set_input_files(
                {"name": "fixture.txt", "mimeType": "text/plain", "buffer": b"# isolated cookie fixture"})
            await expect(upload_card).to_contain_text("쿠키 등록됨")
            await upload_card.locator('.auth-methods').get_by_role('button', name="계정 로그인", exact=True).click()

            card = page.locator('[data-cookie-platform="pandalive"]')
            form = card.locator("form")
            failure = "settings.platformLoginChallenge"
            await form.locator('input[name="password"]').fill(PASSWORD)
            await form.locator('button[type="submit"]').click()
            await expect(card.get_by_role("alert")).to_contain_text("공식 사이트")
            await expect(form.locator('input[name="password"]')).to_have_value("")
            await expect(card).to_contain_text("쿠키 등록됨")
            failure = None
            delay, delay_started = asyncio.Event(), asyncio.Event()
            await form.locator('input[name="password"]').fill(PASSWORD)
            before = len(calls)
            await form.locator('button[type="submit"]').click()
            await delay_started.wait()
            await expect(form.locator('input[name="username"]')).to_be_disabled()
            await expect(form.locator('button[type="submit"]')).to_be_disabled()
            await expect(card.locator('input[type="file"]')).to_be_disabled()
            for button in await card.locator('.auth-methods button').all():
                await expect(button).to_be_disabled()
            assert len(calls) == before + 1
            delay.set()
            await expect(form.locator('input[name="password"]')).to_have_value("")
            delay = None
            for width in (320, 390, 768, 1440):
                await page.set_viewport_size({"width": width, "height": 900})
                assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
                for platform in PLATFORMS:
                    form = page.locator(f'[data-account-login="{platform}"]')
                    box = await form.bounding_box()
                    assert box and box["x"] >= 0 and box["x"] + box["width"] <= width + 1
            stored = await page.evaluate("JSON.stringify({local: {...localStorage}, session: {...sessionStorage}})")
            assert PASSWORD not in stored
            await page.reload()
            await page.get_by_role("button", name="인증", exact=True).click()
            for platform in PLATFORMS:
                await page.locator(f'[data-cookie-platform="{platform}"] .ui-disclosure').click()
                await expect(page.locator(f'#{platform}-login-password')).to_have_value("")
            while await page.locator('.auth-platform-card .ui-disclosure[aria-expanded="true"]').count():
                await page.locator('.auth-platform-card .ui-disclosure[aria-expanded="true"]').first.click()
            output = Path(tempfile.mkdtemp(prefix="auth-ui-", dir=Path(__file__).resolve().parents[4] / "work"))
            await page.set_viewport_size({"width": 1440, "height": 1100})
            await page.screenshot(path=str(output / "desktop.png"), full_page=True)
            await page.set_viewport_size({"width": 375, "height": 812})
            await page.screenshot(path=str(output / "mobile.png"), full_page=True)
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            await page.locator('[data-auth-platform="rplay"] .ui-disclosure').focus()
            await page.keyboard.press("Enter")
            await expect(page.locator('#rplay-login-email')).to_be_visible()
            await page.locator('[data-auth-platform="rplay"]').get_by_role("button", name="세션 파일 등록", exact=True).click()
            await expect(page.locator('[data-auth-platform="rplay"]').get_by_role("button", name="내보내기 코드 복사")).to_be_visible()
            await page.locator('[data-auth-platform="rplay"]').screenshot(path=str(output / "session-import.png"))
            print("Screenshots:", output)
            assert not errors, errors
            await context.close()
        finally:
            await browser.close()
    print("PASS: four login forms, session persistence, secret clearing, failures, request locking and 320–1440px layouts")


if __name__ == "__main__":
    asyncio.run(main())
