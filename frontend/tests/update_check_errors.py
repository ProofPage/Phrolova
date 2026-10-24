"""확인 실패 시 이전 캐시가 최신 버전 확인으로 오인되지 않는지 검사한다."""
import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright, expect
from browser_fixtures import mock

BASE = os.environ.get('PHROLOVA_TEST_URL', 'http://127.0.0.1:3002')
OUT = Path(os.environ.get('PHROLOVA_TEST_OUTPUT', '/tmp/phrolova-update-errors'))

async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    state = {'failed': True}
    async def route_api(route):
        if urlparse(route.request.url).path.startswith('/api/system/update'):
            data = dict(current_version='2.0.65', latest_version='2.0.65', has_update=False,
                        release_notes='', published_at='', download_url='https://github.com/ProofPage/Phrolova/releases',
                        checked_at='2026-10-14T10:00:00', environment='windows-exe')
            if state['failed']:
                data['check_error'] = {'code':'release_unavailable','status':404}
            return await route.fulfill(json=data)
        return await mock(route)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        for locale in ('ko-KR','en-US'):
            d = json.loads((Path(__file__).parents[1]/'src/i18n/locales'/f'{locale}.json').read_text(encoding='utf-8'))
            context = await browser.new_context(viewport={'width':390,'height':844})
            await context.add_init_script(f"localStorage.setItem('phrolova-language',{json.dumps(locale)});")
            page = await context.new_page()
            await page.route('**/api/**',route_api)
            state['failed'] = True
            await page.goto(BASE+'/settings?tab=info')
            # 정보 탭은 페이지의 설정 탐색에서 선택한다.
            if await page.locator('.info-update-section').count() == 0:
                await page.locator('.settings-tabs').get_by_role('button').last.click()
            await expect(page.locator('.info-update-section')).to_contain_text('HTTP 404')
            await page.get_by_role('button',name=d['settings.checkForUpdates'],exact=True).click()
            await expect(page.locator('.toast-stack')).to_contain_text(d['settings.couldNotCheckForUpdates'])
            assert d['settings.youAreUsingTheLatestVersion'] not in await page.locator('.toast-stack').inner_text()
            for width in (320,390,1280):
                await page.set_viewport_size({'width':width,'height':844})
                assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (locale,width)
            await page.screenshot(path=str(OUT/f'update-error-{locale}.png'),full_page=True)
            state['failed'] = False
            await page.get_by_role('button',name=d['settings.checkForUpdates'],exact=True).click()
            await expect(page.locator('.info-update-section')).not_to_contain_text('HTTP 404')
            await expect(page.locator('.toast-stack')).to_contain_text(d['settings.youAreUsingTheLatestVersion'])
            await context.close()
        await browser.close()
    print('PASS: failed checks with stale cache never show success; HTTP detail, recovery, Korean/English and 320/390/1280px layout')

asyncio.run(main())
