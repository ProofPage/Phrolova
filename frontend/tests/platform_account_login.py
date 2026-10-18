"""Four password forms: wire requests, failures, stale status and mobile layout."""
import asyncio
import os
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
            for platform in PLATFORMS:
                card = page.locator(f'[data-cookie-platform="{platform}"]')
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
                assert calls[-1] == (platform, {"username": identifier, "password": PASSWORD})
                assert await card.locator('input[type="file"]').count() == 1
                link = form.get_by_role("link")
                assert (await link.get_attribute("href")).startswith("https://")
                await expect(link).to_have_attribute("rel", "noopener noreferrer")
            assert await page.locator("[data-account-login]").count() == 4
            assert await page.locator("[data-auth-platform=rplay] form").count() == 1

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
                await expect(page.locator(f'#{platform}-login-password')).to_have_value("")
            assert not errors, errors
            await context.close()
        finally:
            await browser.close()
    print("PASS: four login forms, session persistence, secret clearing, failures, request locking and 320–1440px layouts")


if __name__ == "__main__":
    asyncio.run(main())
