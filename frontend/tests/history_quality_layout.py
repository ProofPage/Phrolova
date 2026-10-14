"""처리 이력과 화질 선택을 긴 번역에서도 읽고 조작할 수 있는지 검사한다."""
import asyncio
import copy
import json
import os
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright, expect
from browser_fixtures import FIX, mock

BASE = os.environ.get('PHROLOVA_TEST_URL', 'http://127.0.0.1:3002')
OUT = Path(os.environ['PHROLOVA_TEST_OUTPUT'])
LOCALES = Path(__file__).parents[1] / 'src/i18n/locales'


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = [dict(id=f'history-{i}', composite_key=f'chzzk:history-{i}',
                 channel_name='긴 채널 이름 · Long channel name · 日本語', platform='chzzk',
                 state=state, capture_format='ts', target_format='mkv',
                 started_at='2026-10-14T09:00:00', file_size_bytes=320_000_000,
                 source_available=i == 1, output_available=False, can_open=i == 1,
                 can_retry=i == 1, can_inspect=i == 1,
                 error_message='errors.processing', diagnostics={})
            for i, state in enumerate(('capture_failed', 'failed'))]
    task = copy.deepcopy(FIX['tasks'][0])
    task.update(task_id='quality-layout', state='idle', phase='ready', prepared=True,
                started_at=None, quality='1080p', title='Sample video', platform='chzzk',
                metadata=dict(qualities=[dict(value=q, label=q) for q in
                    ('1080p', '720p', '480p', '360p', '144p')]))

    async def route_api(route):
        path = urlparse(route.request.url).path
        if path == '/api/recordings/jobs':
            return await route.fulfill(json={'jobs': jobs})
        if path == '/api/vod/status':
            return await route.fulfill(json={'tasks': [task], 'active_count': 0})
        return await mock(route)

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context()
        await context.add_init_script("window.EventSource=class{close(){}};localStorage.setItem('dashboardViewMode','grid');localStorage.setItem('downloadViewMode','grid')")
        await context.route('**/api/**', route_api)
        page = await context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        for locale in sorted(LOCALES.glob('*.json')):
            language = locale.stem
            labels = json.loads(locale.read_text(encoding='utf-8'))
            await page.goto(BASE)
            await page.evaluate('(language)=>localStorage.setItem("phrolova-language",language)', language)
            for width in (320, 390, 768, 1440):
                await page.set_viewport_size({'width': width, 'height': 1000})
                await page.goto(BASE)
                panel = page.get_by_role('region', name=labels['live.recordingProcessingHistory'])
                await expect(panel.locator('.recording-history-row')).to_have_count(2)
                assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (language, width, 'history')
                assert await panel.locator('.recording-history-row button svg').count() == 0
                assert await panel.evaluate('''e=>{
                    const rows=[...e.querySelectorAll('.recording-history-row')].map(x=>x.getBoundingClientRect());
                    return Math.abs(rows[0].bottom-rows[1].top)<1 &&
                    [...e.querySelectorAll('button')].every(b=>b.scrollWidth<=b.clientWidth+1);
                }'''), (language, width, 'history spacing/button text')
                if language == 'ko-KR' and width in (390, 1440):
                    await panel.screenshot(path=str(OUT / f'history-{width}.png'))
                await panel.get_by_role('button', name=labels['live.completed'], exact=True).click()
                await expect(panel.locator('.recording-history-row')).to_have_count(0)
                await expect(panel).to_contain_text(labels['live.noProcessingHistoryWithThisStatus'])

                await page.goto(BASE + '/vod')
                card = page.locator('[data-task-id="quality-layout"]')
                await expect(card.get_by_role('button', name='1080p', exact=True)).to_have_attribute('aria-pressed', 'true')
                assert labels['download.downloadResolution'] not in await card.inner_text()
                assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (language, width, 'quality')
                assert await card.evaluate('''e=>{
                    const c=e.getBoundingClientRect(), bs=[...e.querySelectorAll('.download-task-controls button, .download-task-controls select')].map(b=>b.getBoundingClientRect());
                    return bs.every(b=>b.left>=c.left && b.right<=c.right) && bs.every((b,i)=>bs.every((a,j)=>i===j || b.right<=a.left || a.right<=b.left || b.bottom<=a.top || a.bottom<=b.top));
                }'''), (language, width, 'quality/action overlap')
                if language == 'ko-KR' and width in (390, 1440):
                    await card.screenshot(path=str(OUT / f'quality-{width}.png'))
        assert not errors, errors
        await browser.close()
    print('PASS: history/quality, eight locales at 320/390/768/1440px, contiguous rows, empty filter, selected quality, no clipped buttons/overlap/overflow/runtime errors')


asyncio.run(main())
