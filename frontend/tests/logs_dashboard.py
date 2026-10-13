"""Log summary, filters, polling and file-switch isolation with mocked API data."""
import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

from playwright.async_api import async_playwright, expect
from browser_fixtures import mock

BASE = os.environ.get('PHROLOVA_TEST_URL', 'http://127.0.0.1:3001')
OUT = Path(os.environ.get('PHROLOVA_TEST_OUTPUT', '/tmp/phrolova-logs-dashboard'))
LOCALES = Path(__file__).resolve().parents[1] / 'src/i18n/locales'
BACKUP = 'service.2026-10-12.log'
ENTRIES = [
    '2026-10-13 20:00:00 | INFO     | service | Started',
    '2026-10-13 20:00:01 | INFO     | service | Message contains | ERROR | but is informational',
    '2026-10-13 20:00:02 | WARN     | service | Warning [sample]',
    '2026-10-13 20:00:03 | WARNING  | service | Retry scheduled',
    '2026-10-13 20:00:04 | ERROR    | service | Request failed',
    '2026-10-13 20:00:05 | CRITICAL | service | Critical failure',
    '2026-10-13 20:00:06 | DEBUG    | service | Debug detail',
    'Traceback continuation without a level column',
]


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    state = {'entries': ENTRIES.copy(), 'fail': False, 'delay': 0, 'calls': 0, 'clears': 0}
    files = [
        {'filename': 'service.log', 'size_bytes': 4096, 'modified_at': '2026-10-13T11:00:00Z'},
        {'filename': BACKUP, 'size_bytes': 2048, 'modified_at': '2026-10-12T11:00:00Z'},
    ]

    async def route_api(route):
        parsed = urlparse(route.request.url)
        if parsed.path == '/api/system/logs':
            if route.request.method == 'DELETE':
                state['clears'] += 1
                state['entries'] = []
                for file in files:
                    file['size_bytes'] = 0
                return await route.fulfill(json={'message': 'logs.logsCleared', 'cleared_files': 2})
            return await route.fulfill(json=files)
        if parsed.path.startswith('/api/system/logs/') and parsed.path.endswith('/export'):
            return await route.fulfill(content_type='application/octet-stream', body='ORIGINAL FULL LOG\n한국어\n', headers={'Content-Disposition':'attachment; filename="service.log"'})
        if parsed.path.startswith('/api/system/logs/'):
            filename = unquote(parsed.path.rsplit('/', 1)[1])
            state['calls'] += 1
            if filename == 'service.log' and state['delay']:
                await asyncio.sleep(state['delay'])
            if state['fail']:
                return await route.fulfill(status=503, json={'detail': 'Test unavailable'})
            entries = state['entries'] if filename == 'service.log' else ['2026-10-12 | INFO | service | Backup-only entry']
            limit = int(parse_qs(parsed.query).get('lines', ['1000'])[0])
            returned = entries[-limit:] if limit else entries
            return await route.fulfill(json={'filename': filename, 'content': '\r\n'.join(returned) + ('\r\n' if returned else ''), 'total_lines': 1500 if entries else 0, 'lines_returned': len(returned)})
        return await mock(route)

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        for locale in (() if os.environ.get('PHROLOVA_LOGS_ONLY') else ('ko-KR', 'en-US', 'ja-JP', 'es-ES', 'de-DE', 'zh-CN', 'zh-TW', 'ru-RU')):
            d = json.loads((LOCALES / f'{locale}.json').read_text(encoding='utf-8'))
            context = await browser.new_context()
            await context.add_init_script('localStorage.setItem("phrolova-language",' + json.dumps(locale) + '); window.EventSource=class{close(){}}')
            await context.route('**/api/**', route_api)
            page = await context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            for width in (320, 390, 768, 1440):
                await page.set_viewport_size({'width': width, 'height': 1000})
                await page.goto(BASE + '/system-logs')
                await expect(page.locator('.logs-entry')).to_have_count(8)
                await expect(page.locator('.logs-page svg')).to_have_count(0)
                for level, count in [('all', 8), ('error', 2), ('warning', 2), ('info', 2)]:
                    await expect(page.locator(f'[data-log-level="{level}"] strong')).to_have_text(str(count))
                await page.locator('[data-log-level="warning"]').click()
                await expect(page.locator('.logs-entry')).to_have_count(2)
                search = page.get_by_role('textbox', name=d['logs.searchLogsInSystemLogs'], exact=True)
                await search.fill('[sample]')
                assert await page.locator('.logs-entry').count()==1, await page.locator('.logs-content-panel').inner_text()
                await expect(page.locator('.logs-entry mark')).to_have_text('[sample]')
                await search.fill('no-match')
                await expect(page.get_by_text(d['common.noResultsFound'], exact=True)).to_be_visible()
                await search.fill('')
                await page.locator('[data-log-level="all"]').click()
                assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (locale, width)
                assert await page.locator('.logs-page').evaluate('e => e.getBoundingClientRect().height < 1700'), (locale, width)
            if locale == 'ko-KR':
                await page.screenshot(path=str(OUT / 'logs-summary.png'), full_page=True)
            assert not errors, errors
            await context.close()

        d = json.loads((LOCALES / 'ko-KR.json').read_text(encoding='utf-8'))
        context = await browser.new_context(viewport={'width': 1440, 'height': 2796})
        await context.add_init_script('window.EventSource=class{close(){}}')
        await context.route('**/api/**', route_api)
        page = await context.new_page()
        await page.goto(BASE + '/system-logs')
        await expect(page.locator('.logs-entry')).to_have_count(8)
        assert await page.locator('.logs-page').evaluate('e => e.getBoundingClientRect().height < 1000')
        left=await page.locator('.logs-file-panel').bounding_box()
        right=await page.locator('.logs-content-panel').bounding_box()
        assert abs(left['height']-right['height'])<2, (left,right)
        await page.locator('[data-log-level="warning"]').click()
        async with page.expect_download() as downloaded:
            await page.get_by_role('button',name=d['logs.export'],exact=True).click()
        download=await downloaded.value
        assert download.suggested_filename=='service.log'
        downloaded_path=await download.path()
        assert Path(downloaded_path).read_bytes()=='ORIGINAL FULL LOG\n한국어\n'.encode()
        await page.locator('[data-log-level="all"]').click()
        await page.get_by_role('button', name=d['logs.disableLiveRefresh'], exact=True).click()
        before = state['calls']
        await asyncio.sleep(2.3)
        assert state['calls'] == before, 'Paused refresh must not poll content'
        await page.get_by_role('button', name=d['logs.enableLiveRefresh'], exact=True).click()
        await asyncio.sleep(2.3)
        assert state['calls'] > before, 'Live refresh must resume polling'
        await page.get_by_role('button', name=d['logs.disableLiveRefresh'], exact=True).click()
        await page.locator('.logs-line-limits').get_by_role('button', name='100줄', exact=True).click()
        await expect(page.locator('.logs-line-limits').get_by_role('button', name='100줄', exact=True)).to_have_attribute('aria-pressed', 'true')
        state['fail'] = True
        await page.locator('.logs-actions').get_by_role('button', name=d['common.refresh'], exact=True).click()
        await expect(page.get_by_text(d['logs.couldNotRefreshLogsShowingThePreviousContent'], exact=True)).to_be_visible()
        await expect(page.locator('.logs-entry')).to_have_count(8)
        state['fail'] = False
        state['delay'] = 0.5
        await page.locator('.logs-actions').get_by_role('button', name=d['common.refresh'], exact=True).click()
        await page.locator('.logs-file-option').filter(has_text=BACKUP).click()
        await expect(page.locator('.logs-entry')).to_have_text('2026-10-12 | INFO | service | Backup-only entry')
        await asyncio.sleep(0.6)
        await expect(page.locator('.logs-entry')).to_have_count(1)
        await expect(page.get_by_role('button', name=d['logs.enableLiveRefresh'], exact=True)).to_have_attribute('aria-pressed', 'false')
        state['delay'] = 0
        await page.locator('.logs-file-option').filter(has_text='service.log').click()
        await expect(page.locator('.logs-entry')).to_have_count(8)
        state['entries'] = ENTRIES * 50
        await page.locator('.logs-actions').get_by_role('button', name=d['common.refresh'], exact=True).click()
        await expect(page.locator('.logs-entry')).to_have_count(400)
        assert await page.locator('.log-viewer').evaluate('e => e.clientHeight <= 540 && e.scrollTop > 0')
        await page.get_by_role('button', name=d['logs.clearLogs'], exact=True).click()
        await page.get_by_role('dialog').get_by_role('button', name=d['common.cancel'], exact=True).click()
        assert state['clears'] == 0
        await page.get_by_role('button', name=d['logs.clearLogs'], exact=True).click()
        await page.get_by_role('dialog').get_by_role('button', name=d['logs.clearLogs'], exact=True).click()
        await expect(page.locator('.logs-content-panel')).to_contain_text(d['logs.chooseALogFileFromTheListOnTheLeft'])
        assert state['clears'] == 1
        await page.locator('.logs-file-option').filter(has_text='service.log').click()
        await expect(page.get_by_text(d['logs.noLogsYetWaitingForNewEntries'], exact=True)).to_be_visible()
        await expect(page.locator('[data-log-level="all"] strong')).to_have_text('0')
        await browser.close()
    print('PASS: '+('functional checks' if os.environ.get('PHROLOVA_LOGS_ONLY') else '8 locales / 4 widths')+', summaries, severity and search, icon removal, bounded height, polling, failed refresh, file-switch isolation, export, empty and clear/cancel flows')


asyncio.run(main())
