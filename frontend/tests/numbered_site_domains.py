"""Check frontend/backend URL parity and rotated domains in actual picker/queue requests."""
import asyncio
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

from playwright.async_api import async_playwright, expect
from browser_fixtures import mock
from download_redesign import make_task
from animaru_integration import IDS, LABELS

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from app.engine.episode_sites import EpisodeSiteError, parse_episode_url

BASE = os.environ.get('PHROLOVA_TEST_URL', 'http://127.0.0.1:3013')
SOURCES = [
    ('animaru', '애니마루', 'animaru2.com', '/content/42', '/content/42/1.5'),
    ('tvchak', '티비착', 'tvchak209.com', '/index.php/vod/detail/id/123703.html',
     '/index.php/vod/play/id/123703/sid/1/nid/1.html'),
    ('tvwiki', '티비위키', 'tvwiki55.net', '/drama/42', '/drama/42/11'),
    ('anilife', '애니라이프', 'anilife02.tv', '/content/1', '/content/1/one'),
]


def url_cases():
    cases = []
    for site, _, host, work, episode in SOURCES:
        for number in ('0', '1', '02', '209', '123456'):
            numbered = site + number + '.' + host.rsplit('.', 1)[1]
            cases.extend('https://' + numbered + path + '?ref=x#top' for path in (work, episode))
        cases.append('https://' + host.upper() + ':443' + episode)
        for authority in (host + '.evil.example', 'evil.' + host, host + '@evil.example',
                          'u:p@' + host, '@' + host, 'u@' + host, ':@' + host,
                          host + ':444', host + '.', host + '%2eevil.example',
                          host.replace('.', '%2e'), site + '.com', site + '１２.' + host.rsplit('.', 1)[1],
                          site + '1' * 64 + '.' + host.rsplit('.', 1)[1]):
            cases.append('https://' + authority + episode)
        cases.extend(('http://' + host + episode, 'https://' + host + '/ads/1',
                      'https://' + host + episode + '/%0a', 'https://' + host + '\\' + episode,
                      'https://' + host + '\t' + episode))
    cases.extend(('https://tvwiki55.com/drama/42/11', 'https://tvwiki55.network/drama/42/11',
                  'https://tvchak209.net/index.php/vod/detail/id/123703.html',
                  'https://anilife02.net/content/1/one', 'https://animaru2.tv/content/42/1.5',
                  'https://animaru2.com/contents/42/0', 'https://animaru2.com/content/42/1.50'))
    return cases


async def main():
    tasks, calls, errors = [], [], []
    async def route_api(route):
        request = route.request
        path = urlsplit(request.url).path
        if path == '/api/vod/capabilities':
            return await route.fulfill(json={'sources': [{'id': key, 'label': label} for key, label in zip(IDS, LABELS)],
                                            'prepare': True, 'pause': True, 'file_open': True})
        if path == '/api/vod/status':
            return await route.fulfill(json={'tasks': tasks, 'imports': [], 'active_count': 0})
        if path == '/api/vod/catalog':
            payload = request.post_data_json
            calls.append(('catalog', payload))
            parsed = parse_episode_url(payload['url'])
            source = next(row for row in SOURCES if row[0] == parsed['site'])
            return await route.fulfill(json={
                'source': source[0], 'id': '42', 'title': source[1] + ' 새 주소 테스트', 'url': parsed['url'],
                'episodes': [{'id': 'one', 'title': '등록된 회차', 'available': True,
                              'url': 'https://' + source[2] + source[4]}],
            })
        if path == '/api/vod/prepare':
            payload = request.post_data_json
            calls.append(('prepare', payload))
            results = []
            for url in payload['urls']:
                task = make_task('rotated-' + str(len(tasks)), url=url)
                task.update(platform=payload['source'], title='새 주소 회차')
                tasks.append(task)
                results.append({'url': url, 'task_id': task['task_id']})
            return await route.fulfill(json={'results': results})
        return await mock(route)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel='chrome')
        try:
            context = await browser.new_context(viewport={'width': 1440, 'height': 900})
            await context.add_init_script('window.EventSource=class{close(){}}')
            await context.route('**/api/**', route_api)
            page = await context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            await page.goto(BASE + '/vod')
            panel = page.get_by_test_id('vod-preparation')
            cases = url_cases()
            expected = []
            for value in cases:
                try:
                    route = parse_episode_url(value)
                    expected.append({'url': route['url'], 'source': route['site'], 'collection': route['collection']})
                except EpisodeSiteError:
                    expected.append(None)
            actual = await page.evaluate('''async inputs => {
                const {parseEpisodeInput} = await import('/src/utils/episodeSites.ts');
                const {normalizeDownloadInput, detectDownloadPlatform} = await import('/src/utils/downloads.ts');
                return inputs.map(value => ({parsed:parseEpisodeInput(value),
                    normalized:normalizeDownloadInput(value, 'animaru'), detected:detectDownloadPlatform(value)}));
            }''', cases)
            for value, result, wanted in zip(cases, actual, expected):
                assert result['parsed'] == wanted, (value, result, wanted)
                assert result['normalized'] == wanted, (value, result, wanted)
                if wanted:
                    assert result['detected'] == wanted['source'], (value, result)
            for site, label, host, work, episode in SOURCES:
                await panel.get_by_role('combobox', name='다운로드 플랫폼', exact=True).click()
                assert await page.get_by_role('listbox').get_by_role('option').all_text_contents() == LABELS
                await page.get_by_role('option', name=label, exact=True).click()
                await panel.get_by_role('textbox').fill('https://' + host + work + '?ref=x')
                await panel.get_by_role('button', name='목록에 추가', exact=True).click()
                dialog = page.get_by_role('dialog', name='회차 선택', exact=True)
                await expect(dialog.get_by_role('heading', name=label + ' 새 주소 테스트')).to_be_visible()
                assert calls[-1] == ('catalog', {'url': 'https://' + host + work}), calls[-1]
                for width in (320, 390, 768, 1440):
                    await page.set_viewport_size({'width': width, 'height': 850})
                    assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (site, width)
                    assert await dialog.evaluate('(el) => el.scrollWidth <= el.clientWidth + 1'), (site, width)
                await dialog.get_by_role('checkbox').first.check()
                await dialog.get_by_role('button', name='선택한 회차 추가 (1)', exact=True).click()
                await expect(dialog).to_have_count(0)
                assert calls[-1] == ('prepare', {'urls': ['https://' + host + episode], 'source': site}), calls[-1]
                direct_host = site + '777.' + host.rsplit('.', 1)[1]
                await panel.get_by_role('textbox').fill('https://' + direct_host + episode + '#tracking')
                await panel.get_by_role('button', name='목록에 추가', exact=True).click()
                await expect(panel.get_by_role('textbox')).to_have_value('')
                assert calls[-1] == ('prepare', {'urls': ['https://' + direct_host + episode], 'source': site}), calls[-1]
            assert not errors, errors
        finally:
            await browser.close()
    print(f'PASS: {len(cases)} URL cases agree across frontend/backend; 16 sources retained; '
          '4 rotated-domain catalogs and direct episode queues; 320/390/768/1440px layouts')


if __name__ == '__main__':
    asyncio.run(main())
