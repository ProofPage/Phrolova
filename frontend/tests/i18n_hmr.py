"""번역 파일 자동 갱신 시 Context 연결이 끊기지 않는지 개발 서버에서 확인한다."""
import asyncio
import json
import os
from pathlib import Path
from playwright.async_api import async_playwright, expect
from browser_fixtures import mock

BASE = os.environ.get('PHROLOVA_TEST_URL', 'http://127.0.0.1:3001')
RESOURCE = Path(__file__).resolve().parents[1] / 'src/i18n/locales/ko-KR.json'


async def main():
    original = RESOURCE.read_bytes()
    data = json.loads(original)
    title = data['settings.title']
    errors = []
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context()
        await context.add_init_script("localStorage.setItem('phrolova-language','ko-KR'); window.EventSource=class{close(){}}")
        await context.route('**/api/**', mock)
        page = await context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        try:
            await page.goto(BASE + '/settings')
            await expect(page.get_by_role('heading', name=title, exact=True)).to_be_visible()
            for iteration in range(2):
                marker = title + f' HMR {iteration}'
                data['settings.title'] = marker
                RESOURCE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
                await expect(page.get_by_role('heading', name=marker, exact=True)).to_be_visible(timeout=15000)
                RESOURCE.write_bytes(original)
                await expect(page.get_by_role('heading', name=title, exact=True)).to_be_visible(timeout=15000)
            assert not errors, errors
        finally:
            RESOURCE.write_bytes(original)
            await context.close()
            await browser.close()
    print('PASS: translation resource hot updates and restoration without Context errors or a blank page')


if __name__ == '__main__':
    asyncio.run(main())
