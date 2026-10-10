"""치지직 ID/link parsing and real form submission through Chromium."""
import asyncio
import os
from urllib.parse import urlparse
from playwright.async_api import async_playwright, expect
from browser_fixtures import mock

ID = '19e3b97ca1bca954d1ac84cf6862e0dc'
MESSAGE = '올바른 치지직 채널 ID 또는 채널 링크를 입력하세요.'

async def main():
    payloads = []
    async def route_api(route):
        if urlparse(route.request.url).path == '/api/stream/channels' and route.request.method == 'POST':
            payloads.append(route.request.post_data_json)
            return await route.fulfill(json={'channel_id': ID, 'message': '채널이 추가되었습니다.'})
        return await mock(route)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        for width in (390, 1440):
            context = await browser.new_context(viewport={'width': width, 'height': 1000})
            await context.add_init_script('window.EventSource=class{close(){}}')
            await context.route('**/api/**', route_api)
            page = await context.new_page()
            await page.goto(os.environ.get('PHROLOVA_TEST_URL', 'http://localhost:3000'))
            form = page.get_by_role('form', name='감시 채널 추가')
            field = form.get_by_role('textbox', name='치지직 채널 ID 또는 채널 링크', exact=True)
            button = form.get_by_role('button', name='채널 추가 설정 열기')
            await expect(field).to_have_attribute('placeholder', '치지직 채널 ID 또는 https://chzzk.naver.com/...')
            await expect(button).to_be_disabled()
            for value in ('invalid-id', ID[:-1], ID+'0', f'https://example.com/{ID}',
                          f'https://chzzk.naver.com.evil.test/{ID}', f'https://chzzk.naver.com/video/{ID}',
                          f'https://chzzk.naver.com/clips/{ID}', f'https://chzzk.naver.com/{ID}/extra'):
                before = len(payloads)
                await field.fill(value)
                await button.click()
                await expect(form.get_by_role('alert')).to_have_text(MESSAGE)
                await expect(field).to_have_attribute('aria-invalid', 'true')
                assert await page.get_by_role('dialog').count() == 0
                assert len(payloads) == before
            for value in (ID, f'https://chzzk.naver.com/{ID}',
                          f' https://chzzk.naver.com/live/{ID}/?source=share#channel ', ID.upper()):
                await field.fill(value)
                await expect(form.get_by_role('alert')).to_have_count(0)
                await button.click()
                dialog = page.get_by_role('dialog')
                await expect(dialog).to_contain_text(ID)
                await dialog.get_by_role('button', name='채널 추가', exact=True).click()
                await expect(dialog).not_to_be_visible()
                assert payloads[-1]['channel_id'] == ID, payloads[-1]
                assert payloads[-1]['auto_record'] is True
                await expect(field).to_have_value('')
            # Other platforms retain their existing input and registration flow.
            await form.get_by_role('button', name='플랫폼 선택: 치지직').click()
            await page.get_by_role('option', name='유튜브', exact=True).click()
            await expect(form.get_by_role('textbox')).to_have_attribute('placeholder', '핸들(@username) 또는 채널 ID')
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            print(f'치지직 channel input PASS {width}: ID/link normalization, invalid URL/ID blocking, settings and POST payload, 유튜브 preserved')
            await context.close()
        await browser.close()

asyncio.run(main())
