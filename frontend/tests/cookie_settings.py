"""Cookie settings interactions and responsive Chromium checks with isolated APIs."""

import asyncio
import os
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright, expect
from browser_fixtures import mock

BASE = os.environ.get("PHROLOVA_TEST_URL", "http://127.0.0.1:3001")
OUT = Path(os.environ.get("PHROLOVA_TEST_OUTPUT", "cookie-settings-results"))
NAMES = {"chzzk": "치지직", "youtube": "유튜브", "soop": "숲", "cime": "씨미"}


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    configured = {platform: False for platform in NAMES}
    calls = Counter()
    invalid_upload = False
    expired = False

    async def route_api(route):
        nonlocal invalid_upload, expired
        request = route.request
        parts = urlparse(request.url).path.split("/")
        if (
            len(parts) >= 5
            and parts[2] == "platforms"
            and parts[3] in NAMES
            and parts[4] == "cookie"
        ):
            platform = parts[3]
            calls[(platform, request.method, parts[-1])] += 1
            if request.method == "POST" and parts[-1] == "cookie":
                await asyncio.sleep(0.15)
                if invalid_upload:
                    return await route.fulfill(
                        status=400,
                        json={
                            "detail": "해당 플랫폼의 Netscape 형식 쿠키 파일을 선택하세요."
                        },
                    )
                configured[platform] = True
            elif request.method == "DELETE":
                configured[platform] = False
            return await route.fulfill(
                json={
                    "configured": configured[platform],
                    "valid": configured[platform] and not expired,
                    "expired": configured[platform] and expired,
                    "message": (
                        "쿠키가 만료되었습니다."
                        if expired and configured[platform]
                        else (
                            "쿠키 파일이 등록되었습니다."
                            if configured[platform]
                            else "쿠키가 등록되지 않았습니다."
                        )
                    ),
                }
            )
        return await mock(route)

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(viewport={"width": 1440, "height": 1100})
        await context.add_init_script("window.EventSource=class {close(){}}")
        await context.route("**/api/**", route_api)
        page = await context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        await page.goto(BASE + "/settings")
        await page.get_by_role("button", name="인증", exact=True).click()
        await expect(page.locator("[data-cookie-platform]")).to_have_count(4)
        await expect(
            page.get_by_text("유튜브 쿠키 내보내기 안내", exact=True)
        ).to_have_count(0)
        await expect(page.get_by_placeholder("NID_AUT 쿠키 값 입력...")).to_have_count(
            0
        )

        for platform, name in NAMES.items():
            card = page.locator(f'[data-cookie-platform="{platform}"]')
            file = card.locator('input[type="file"]')
            sample = {
                "name": "테스트 쿠키.txt",
                "mimeType": "text/plain",
                "buffer": b"# synthetic fixture only",
            }
            await file.set_input_files(sample)
            await expect(
                card.get_by_role("button", name=name + " 쿠키 파일 선택")
            ).to_be_disabled()
            # A second change event during the request must not produce another upload.
            await file.set_input_files(sample)
            await expect(card.get_by_text("쿠키 등록됨", exact=True)).to_be_visible()
            assert calls[(platform, "POST", "cookie")] == 1
            await expect(
                card.get_by_role("button", name=name + " 쿠키 파일 선택")
            ).to_have_text("파일 갱신")
            await card.get_by_role("button", name=name + " 쿠키 상태 확인").click()
            await expect(card.locator('[role="status"]')).to_contain_text(
                "등록되었습니다"
            )
            if platform == "chzzk":
                assert calls[(platform, "POST", "check")] == 1
            else:
                assert calls[(platform, "GET", "cookie")] >= 2

        card = page.locator('[data-cookie-platform="chzzk"]')
        invalid_upload = True
        await card.locator('input[type="file"]').set_input_files(
            {"name": "invalid.txt", "mimeType": "text/plain", "buffer": b"invalid"}
        )
        await expect(card.get_by_role("alert")).to_contain_text("Netscape")
        await expect(card.get_by_text("쿠키 등록됨", exact=True)).to_be_visible()
        invalid_upload = False
        expired = True
        await card.get_by_role("button", name="치지직 쿠키 상태 확인").click()
        await expect(card.get_by_text("쿠키 만료", exact=True)).to_be_visible()
        expired = False
        await card.get_by_role("button", name="치지직 쿠키 상태 확인").click()
        await expect(card.get_by_text("쿠키 등록됨", exact=True)).to_be_visible()
        await page.reload()
        await page.get_by_role("button", name="인증", exact=True).click()
        await expect(page.get_by_text("쿠키 등록됨", exact=True)).to_have_count(4)

        for width in (360, 390, 768, 1024, 1440):
            await page.set_viewport_size({"width": width, "height": 1100})
            await page.screenshot(
                path=str(OUT / f"cookies-{width}.png"), full_page=True
            )
            assert await page.evaluate(
                "document.documentElement.scrollWidth <= innerWidth"
            ), f"horizontal overflow at {width}"
            for platform, name in NAMES.items():
                buttons = page.locator(
                    f'[data-cookie-platform="{platform}"]'
                ).get_by_role("button")
                for button in await buttons.all():
                    rect = await button.bounding_box()
                    assert (
                        rect and rect["x"] >= 0 and rect["x"] + rect["width"] <= width
                    )

        for platform, name in NAMES.items():
            card = page.locator(f'[data-cookie-platform="{platform}"]')
            await card.get_by_role("button", name=name + " 쿠키 파일 삭제").click()
            await page.get_by_role("dialog").get_by_role(
                "button", name="취소", exact=True
            ).click()
            assert calls[(platform, "DELETE", "cookie")] == 0
            await card.get_by_role("button", name=name + " 쿠키 파일 삭제").click()
            await page.get_by_role("dialog").get_by_role(
                "button", name="삭제", exact=True
            ).click()
            await expect(
                card.get_by_text("등록된 쿠키 없음", exact=True)
            ).to_be_visible()
            assert calls[(platform, "DELETE", "cookie")] == 1
        assert not errors, errors
        await browser.close()
    print(
        "PASS: 4 shared cookie cards; upload/replace/refresh/delete/cancel; duplicate-request guard; invalid-upload preservation; expiry/recovery; reload; guide removed; 360/390/768/1024/1440 layouts; no JS errors"
    )


asyncio.run(main())
