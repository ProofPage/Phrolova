"""RPLAY live selection, validated registration, quality selection and previews."""
import asyncio
import copy
import os
from pathlib import Path
from urllib.parse import unquote, urlsplit

from playwright.async_api import async_playwright, expect
from browser_fixtures import FIX, mock
from popkontv_integration import PLATFORMS, LIVE_LABELS

BASE = os.environ.get('PHROLOVA_TEST_URL', 'http://127.0.0.1:3019')
OUT = Path(__file__).resolve().parents[4] / 'work/rplay-live-ui'
CID = '6a56030961df0d415aa5b5d5'
PAGE = f'https://rplay.live/live/{CID}'


async def main():
    OUT.mkdir(exist_ok=True)
    calls, errors = [], []
    channel = copy.deepcopy(FIX['channels'][0])
    channel.update(platform='rplay', composite_key='rplay:' + CID, channel_id=CID, channel_name='알플레이 테스트',
        title='라이브 방송 테스트', is_live=True, broadcast_status='live', viewer_count=0, recording=None,
        recording_quality='best', postprocess=None, auto_record=False, channel_url=PAGE, last_error='', monitor_error=None, tags=[])

    async def route_api(route):
        request = route.request; path = unquote(urlsplit(request.url).path)
        if path == '/api/platforms/channels':
            if request.method == 'POST':
                calls.append(('add', request.post_data_json))
            return await route.fulfill(json=[channel] if request.method == 'GET' else {'status': 'added'})
        if path == '/api/platforms/status':
            return await route.fulfill(json={p: {'enabled': True, 'authenticated': False} for p in PLATFORMS})
        if path == f'/api/platforms/rplay/{CID}/qualities':
            calls.append(('qualities', path))
            return await route.fulfill(json={'live': True, 'qualities': [{'value': str(h)+'p', 'label': str(h)+'p', 'height': h} for h in (720, 480)]})
        if path == '/api/stream/preview/rplay:' + CID:
            calls.append(('preview', path))
            return await route.fulfill(status=403, json={'detail': '알플레이 로그인 또는 시청 권한이 필요합니다.'})
        return await mock(route)

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel='chrome')
        try:
            context = await browser.new_context(viewport={'width': 1440, 'height': 900})
            await context.add_init_script('window.EventSource=class{close(){}}')
            await context.route('**/api/**', route_api)
            page = await context.new_page(); page.on('pageerror', lambda e: errors.append(str(e)))
            await page.goto(BASE + '/')
            await expect(page.locator('[data-channel-key="rplay:' + CID + '"] .platform-badge')).to_have_text('알플레이')
            await expect(page.locator('[data-channel-key="rplay:' + CID + '"] .recording-viewers')).to_have_count(0)
            await page.get_by_role('button', name='플랫폼 선택: 치지직', exact=True).click()
            assert await page.get_by_role('listbox').get_by_role('option').all_text_contents() == LIVE_LABELS
            await page.get_by_role('option', name='알플레이', exact=True).click()
            await page.get_by_placeholder('알플레이 채널 ID 또는 https://rplay.live/live/...').fill(PAGE + '?share=1')
            await page.locator('.dashboard-add-channel button[type=submit]').click()
            dialog = page.get_by_role('dialog')
            await dialog.locator('#channel-recording-quality').select_option('720p')
            for width in (320, 390, 768, 1440):
                await page.set_viewport_size({'width': width, 'height': 900})
                assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'), width
            await dialog.get_by_role('button', name='채널 추가', exact=True).click()
            assert any(k == 'add' and d['platform'] == 'rplay' and d['channel_id'] == CID and d['recording_quality'] == '720p' for k,d in calls)
            cases = [CID, CID.upper(), PAGE, PAGE + '/?from=share', PAGE.replace('https:', 'http:'), PAGE.replace('.live/', '.live.evil/'), PAGE.replace('rplay.live', 'u:p@rplay.live'), PAGE.replace('.live/', '.live:444/'), PAGE.replace('/live/', '/play/'), 'bad-id']
            actual = await page.evaluate('''async values=>{
                const {parsePlatformChannelInput:parse}=await import('/src/utils/platformChannels.ts');
                return values.map(v=>parse('rplay',v));
            }''', cases)
            assert actual == [CID] * 5 + [None] * 5, actual
            await page.locator('[data-channel-key="rplay:' + CID + '"] .recording-detail-action').click()
            await expect(page.locator('.channel-preview-message')).to_be_visible()
            assert any(k == 'preview' for k,_ in calls)
            for width in (320, 390, 768, 1440):
                await page.set_viewport_size({'width': width, 'height': 900})
                assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'), width
                if width in (390, 1440):
                    await page.screenshot(path=str(OUT / f'live-{width}.png'), full_page=True)
            assert not errors, errors
        finally:
            await browser.close()
    print('PASS: 11 live platforms, RPLAY registration, quality permission options, 10 URL cases, preview authentication errors, 320/390/768/1440px')


if __name__ == '__main__':
    asyncio.run(main())
