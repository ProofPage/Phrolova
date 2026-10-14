"""오류 필터가 예외 상세를 보존하고 메시지 속 ERROR를 잘못 분류하지 않는지 검사한다."""
import asyncio
import os
from urllib.parse import urlparse
from playwright.async_api import async_playwright, expect
from browser_fixtures import mock

BASE = os.environ.get('PHROLOVA_TEST_URL','http://127.0.0.1:3002')
LINES = [
    '2026-10-14 12:00:00 | INFO | SERVER | Message contains | ERROR | but is normal',
    '2026-10-14 12:00:01 | error | SOOP/RECORDING | channel=sample code=storage',
    'Traceback (most recent call last):',
    '  File "record.py", line 5, in receive',
    'PermissionError: write denied',
    '2026-10-14 12:00:02 | WARNING | UPDATE | HTTP 404',
]

async def main():
    async def route_api(route):
        path=urlparse(route.request.url).path
        if path=='/api/system/logs':
            return await route.fulfill(json=[dict(filename='service.log',size_bytes=1024,modified_at='2026-10-14T12:00:00')])
        if path.startswith('/api/system/logs/'):
            return await route.fulfill(json=dict(content='\n'.join(LINES),total_lines=len(LINES)))
        return await mock(route)
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        page=await browser.new_page(viewport={'width':1280,'height':900})
        await page.route('**/api/**',route_api)
        await page.goto(BASE+'/system-logs')
        await expect(page.locator('.logs-entry')).to_have_count(6)
        await expect(page.locator('[data-log-level="error"] strong')).to_have_text('1')
        await expect(page.locator('[data-log-level="info"] strong')).to_have_text('1')
        await page.locator('[data-log-level="error"]').click()
        await expect(page.locator('.logs-entry')).to_have_count(4)
        await expect(page.locator('.log-viewer')).to_contain_text('PermissionError: write denied')
        await expect(page.locator('.log-viewer')).to_contain_text('SOOP/RECORDING')
        assert 'Message contains' not in await page.locator('.log-viewer').inner_text()
        await page.locator('[data-log-level="warning"]').click()
        await expect(page.locator('.logs-entry')).to_have_count(1)
        await browser.close()
    print('PASS: lowercase legacy levels, platform details, full traceback, correct severity counts and no message misclassification')

asyncio.run(main())
