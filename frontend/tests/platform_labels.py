"""Display localization must never change platform keys, URLs or API paths."""
import asyncio
import os
import re
from playwright.async_api import async_playwright, expect
from browser_fixtures import mock

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(viewport={'width': 1440, 'height': 1000})
        await context.add_init_script('window.EventSource=class{close(){}}')
        await context.route('**/api/**', mock)
        page = await context.new_page()
        base = os.environ.get('PHROLOVA_TEST_URL', 'http://localhost:3000')
        await page.goto(base)
        await expect(page.get_by_role('textbox', name='치지직 채널 ID 또는 채널 링크')).to_be_visible()
        labels = await page.evaluate("async()=> (await import('/src/api/client.ts')).PLATFORM_LABELS")
        assert labels == {'chzzk': '치지직', 'x_spaces': '스페이스', 'youtube': '유튜브'}
        result = await page.evaluate('''async()=> {
            const {localizePlatformNames: name} = await import('/src/utils/platformNames.ts');
            return [name('CHZZK 연결 오류 · YouTube 다운로드 · X Spaces 인증'),
                name('https://youtube.com/watch?v=abc /platforms/youtube/cookie chzzk x_spaces youtube'),
                name('https://example.com/YouTube /CHZZK/file.ts CHZZK_CHANNEL_INPUT_ERROR'),
                name('Chzzk의 방송과 YouTubeの動画')];
        }''')
        assert result == ['치지직 연결 오류 · 유튜브 다운로드 · 스페이스 인증',
                          'https://youtube.com/watch?v=abc /platforms/youtube/cookie chzzk x_spaces youtube',
                          'https://example.com/YouTube /CHZZK/file.ts CHZZK_CHANNEL_INPUT_ERROR',
                          '치지직의 방송과 유튜브の動画'], result
        await page.get_by_role('button', name='플랫폼 선택: 치지직').click()
        for name in ('치지직', '유튜브', '스페이스'):
            await expect(page.get_by_role('option', name=re.compile('^'+name))).to_be_visible()
        await page.keyboard.press('Escape')
        for path in ('/vod', '/archive', '/settings', '/stats'):
            await page.goto(base+path)
            await page.locator('#main-content').wait_for()
            body = await page.locator('#main-content').inner_text()
            assert not re.search(r'CHZZK|Chzzk|YouTube|X Spaces', body), (path, body)
        await page.goto(base+'/settings')
        await page.get_by_role('button', name='인증', exact=True).click()
        for name in ('치지직', '유튜브', '스페이스'):
            await expect(page.get_by_role('heading', name=name, exact=True)).to_be_visible()
        print('Platform labels PASS: live menu, downloads, archive, settings/auth, stats, original keys and URLs, diagnostic text')
        await browser.close()

asyncio.run(main())
