"""RPLAY video-only selection, queue preparation, session files and mobile UI."""
import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright, expect
from animaru_integration import IDS, LABELS
from browser_fixtures import mock
from download_redesign import make_task

BASE = os.environ.get('PHROLOVA_TEST_URL', 'http://127.0.0.1:3019')
OUT = Path(__file__).resolve().parents[4] / 'work/rplay-ui'
URL = 'https://rplay.live/play/6a8edff1f1781bc93acb28cf'


async def main():
    OUT.mkdir(exist_ok=True)
    tasks, calls, errors = [], [], []
    registered = False
    capabilities_failure = False

    async def route_api(route):
        nonlocal registered
        req = route.request; path = urlsplit(req.url).path
        if path == '/api/platforms/rplay/session':
            if req.method in ('POST', 'DELETE'):
                registered = req.method == 'POST'; calls.append(('session', req.method))
            return await route.fulfill(json={'configured': registered, 'valid': registered, 'expired': False})
        if path == '/api/vod/capabilities':
            if capabilities_failure:
                return await route.fulfill(status=503, json={'detail': 'fixture unavailable'})
            return await route.fulfill(json={'sources': [{'id': i, 'label': l} for i, l in zip(IDS, LABELS)], 'prepare': True, 'pause': True, 'file_open': True})
        if path == '/api/vod/status':
            return await route.fulfill(json={'tasks': tasks, 'imports': [], 'active_count': 0})
        if path == '/api/vod/prepare':
            data = req.post_data_json; calls.append(('prepare', data))
            task = make_task('rplay-test', data['urls'][0]); task.update(platform='rplay', title='알플레이 테스트 영상', quality='best')
            task['metadata']['qualities'] = [{'value': str(h) + 'p', 'label': str(h) + 'p'} for h in (1080, 720, 480)]
            tasks[:] = [task]
            return await route.fulfill(json={'results': [{'url': task['url'], 'task_id': task['task_id']}]})
        return await mock(route)

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel='chrome')
        try:
            context = await browser.new_context(viewport={'width': 1440, 'height': 900})
            await context.add_init_script('window.EventSource=class{close(){}}')
            await context.route('**/api/**', route_api)
            page = await context.new_page(); page.on('pageerror', lambda e: errors.append(str(e)))
            await page.goto(BASE + '/vod')
            panel = page.get_by_test_id('vod-preparation')
            await panel.get_by_role('combobox').click()
            assert await page.get_by_role('listbox').get_by_role('option').all_text_contents() == LABELS
            await page.get_by_role('option', name='알플레이', exact=True).click()
            cases = [URL, URL + '/?share=1#top', URL.upper().replace('/PLAY/', '/play/'), URL + '/extra',
                     URL.replace('rplay.live', 'u:p@rplay.live'), URL.replace('.live/', '.live.evil/'), URL.replace('.live/', '.live:444/'), URL.replace('/play/', '/live/')]
            result = await page.evaluate('''async values => {
                const {normalizeDownloadInput,detectDownloadPlatform} = await import('/src/utils/downloads.ts');
                return values.map(v=>({value:normalizeDownloadInput(v,'rplay'),platform:detectDownloadPlatform(v)}));
            }''', cases)
            assert all(r['value']['url'] == URL and r['platform'] == 'rplay' for r in result[:3])
            assert all(r['value'] is None for r in result[3:])
            await panel.get_by_role('textbox').fill(URL + '?share=1#top')
            await panel.get_by_role('button', name='목록에 추가', exact=True).click()
            assert ('prepare', {'urls': [URL], 'source': 'rplay'}) in calls
            await expect(page.get_by_role('heading', name='알플레이 테스트 영상', exact=True)).to_be_visible()
            await expect(page.locator('.platform-badge.platform-rplay')).to_have_text('알플레이')
            for width in (320, 390, 768, 1440):
                await page.set_viewport_size({'width': width, 'height': 900})
                assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'), width
                if width in (390, 1440):
                    await page.screenshot(path=str(OUT / f'videos-{width}.png'), full_page=True)
            capabilities_failure = True
            await page.reload(); await page.get_by_test_id('vod-preparation').get_by_role('combobox').click()
            assert await page.get_by_role('listbox').get_by_role('option').all_text_contents() == LABELS
            await page.goto(BASE + '/settings'); await page.get_by_role('button', name='인증', exact=True).click()
            card = page.locator('[data-auth-platform=rplay]')
            await expect(card).to_contain_text('등록된 세션 없음')
            await card.locator('input[type=file]').set_input_files({'name': 'session.json', 'mimeType': 'application/json', 'buffer': json.dumps({'accessToken': 'PRIVATE-FIXTURE-TOKEN', 'requestorOid': 'a' * 24}).encode()})
            await expect(card).to_contain_text('세션 파일 등록됨')
            await expect(card).not_to_contain_text('PRIVATE-FIXTURE-TOKEN')
            await card.get_by_role('button', name='상태 확인', exact=True).click()
            for width in (320, 390, 768, 1440):
                await page.set_viewport_size({'width': width, 'height': 900})
                assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'), width
            await card.scroll_into_view_if_needed(); await page.screenshot(path=str(OUT / 'auth-1440.png'))
            await card.get_by_role('button', name='삭제', exact=True).click()
            await page.get_by_role('dialog').get_by_role('button', name='삭제', exact=True).click()
            await expect(card).to_contain_text('등록된 세션 없음')
            assert ('session', 'POST') in calls and ('session', 'DELETE') in calls
            assert not errors, errors
        finally:
            await browser.close()
    print('PASS: RPLAY selection and fallback, URL validation, preparation and badge, session upload/status/delete, 320/390/768/1440px; no browser errors')


if __name__ == '__main__':
    asyncio.run(main())
