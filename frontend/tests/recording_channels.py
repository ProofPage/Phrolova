"""Real Chromium regression for shared recording cards, API pending/error and layouts."""
import asyncio
import copy
import os
from urllib.parse import urlparse, unquote
from playwright.async_api import async_playwright, expect
from browser_fixtures import FIX, mock

BASE = os.environ.get('PHROLOVA_TEST_URL', 'http://localhost:3000')

async def main():
    channels = []
    for i in range(2):
        c = copy.deepcopy(FIX['channels'][1])
        c.update(platform='chzzk', composite_key=f'chzzk:recording-{i}', channel_id=f'recording-{i}', channel_name=['강지', '탬탬버린'][i],
                 title='아주 긴 방송 제목 ' * 30, tags=['방송', '게임', '즐겨찾기'],
                 is_live=True, auto_record=True, last_error='',
                 recording=dict(state='recording', is_recording=True, duration_seconds=360001,
                                start_time='2026-10-10T00:00:00Z', output_path='/영상/한글 파일 [1080p].ts',
                                file_size_bytes=8*1024**3, download_speed=1.62, bitrate=13570))
        channels.append(c)
    calls = []
    auto_fail = False
    async def route_api(route):
        nonlocal auto_fail
        path = unquote(urlparse(route.request.url).path)
        request = route.request
        if path == '/api/platforms/channels':
            return await route.fulfill(json=channels)
        if path == '/api/tags':
            return await route.fulfill(json={'tags': ['방송', '게임', '즐겨찾기', '추가']})
        if request.method != 'GET':
            calls.append((request.method, path, request.post_data_json))
        if path.endswith('/auto-record'):
            await asyncio.sleep(.4)
            if auto_fail: return await route.fulfill(status=500, json={'detail': 'test failure'})
            channels[0]['auto_record'] = not channels[0]['auto_record']
            return await route.fulfill(json={'auto_record': channels[0]['auto_record']})
        if path.startswith('/api/tags/channel/'):
            channels[0]['tags'] = request.post_data_json['tags']
            return await route.fulfill(json={'tags': channels[0]['tags']})
        if path.endswith('/download-options'):
            channels[0].update(request.post_data_json)
            return await route.fulfill(json={'status': 'ok'})
        if path.endswith('/stop'):
            await asyncio.sleep(.4)
            channels[0]['recording'] = None
            return await route.fulfill(json={'status': 'ok'})
        if path.startswith('/api/stream/channels/') and request.method == 'DELETE':
            channels.pop(0)
            return await route.fulfill(json={'status': 'ok'})
        return await mock(route)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(viewport={'width': 1440, 'height': 1000})
        await context.add_init_script("localStorage.setItem('dashboardViewMode','list');window.EventSource=class{close(){}}")
        await context.route('**/api/**', route_api)
        page = await context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        await page.goto(BASE)
        card = page.locator('[data-channel-key="chzzk:recording-0"]')
        await card.wait_for()
        await expect(card.locator('.recording-metrics')).to_contain_text('100:00:')
        await expect(card.locator('.recording-metrics')).to_contain_text('1.62 MB/s')
        await expect(card.locator('.recording-metrics')).to_contain_text('13.57 Mbps')
        assert await card.evaluate('(c)=>c.offsetHeight') <= 130
        await expect(card.locator('.recording-tag-overflow')).to_have_text('+1')
        # Details and state survive mode changes without remounting the card.
        await card.get_by_role('button', name='상세 보기: 강지').click()
        await expect(card.locator('.recording-details-fields')).to_contain_text('/영상/한글 파일 [1080p].ts')
        await card.evaluate('(c)=>c.dataset.testIdentity="preserved"')
        await page.get_by_role('button', name='카드로 보기', exact=True).click()
        assert await card.get_attribute('data-test-identity') == 'preserved'
        await card.get_by_role('button', name='상세 접기: 강지').click()
        await page.get_by_role('button', name='목록으로 보기', exact=True).click()
        # API pending state blocks repeat requests; failed update preserves server state.
        switch = card.get_by_role('switch')
        await switch.click()
        await expect(switch).to_be_disabled()
        await expect(card).to_contain_text('저장 중')
        await expect(switch).to_have_attribute('aria-checked', 'false')
        await expect(switch).to_be_enabled()
        auto_fail = True
        await switch.click()
        await expect(switch).to_be_enabled()
        await expect(switch).to_have_attribute('aria-checked', 'false')
        assert len([c for c in calls if c[1].endswith('/auto-record')]) == 2
        assert not any(c[1].endswith('/stop') for c in calls)
        # Compact tag menu must still allow both removing and adding tags.
        await card.get_by_role('button', name='태그 관리', exact=True).click()
        tags = page.get_by_role('dialog', name='태그 관리', exact=True)
        await tags.get_by_role('button', name='방송', exact=True).click()
        await expect(card.locator('.recording-channel-meta')).not_to_contain_text('방송')
        await tags.get_by_role('button', name='추가', exact=True).click()
        await expect(card.locator('.recording-tag-overflow')).to_have_attribute('title', '추가')
        await tags.get_by_role('button', name='닫기', exact=True).click()
        # Existing settings submit calls the real client endpoint.
        await card.get_by_role('button', name='녹화 설정', exact=True).click()
        settings = page.get_by_role('dialog')
        await settings.get_by_role('switch').click()
        await settings.get_by_role('button', name='설정 저장', exact=True).click()
        await expect(settings).not_to_be_visible()
        assert any(c[1].endswith('/download-options') for c in calls)
        # Stop pending is visible; final metrics remain when server removes the pipeline.
        previous = await card.locator('.recording-metrics dd').all_text_contents()
        await card.get_by_role('button', name='녹화 중지', exact=True).click()
        await page.get_by_role('dialog').get_by_role('button', name='중지', exact=True).click()
        await expect(card).to_contain_text('녹화 중지 중')
        await expect(card.get_by_role('button', name='녹화 시작', exact=True)).to_be_visible()
        assert (await card.locator('.recording-metrics dd').all_text_contents())[1:] == previous[1:]
        # Both modes across desktop/mobile widths: no overflow, labeled statistics and controls.
        for width in (390, 820, 1024, 1440, 1920):
            await page.set_viewport_size({'width': width, 'height': 1000})
            for mode in ('카드로 보기', '목록으로 보기'):
                await page.get_by_role('button', name=mode, exact=True).click()
                assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                for label in ('녹화 시간', '파일 크기', '저장 속도', '비트레이트'):
                    await expect(card.locator('.recording-metrics dt', has_text=label)).to_be_visible()
                if width < 500:
                    assert await card.locator('.recording-detail-action').evaluate('(b)=>b.offsetWidth >= 44 && b.offsetHeight >= 44')
        await page.set_viewport_size({'width': 1440, 'height': 1000})
        # Recording removal explains that recording stops and saved files remain.
        second = page.locator('[data-channel-key="chzzk:recording-1"]')
        await second.get_by_role('button', name='채널 제거: 탬탬버린', exact=True).click()
        confirm = page.get_by_role('dialog')
        await expect(confirm).to_contain_text('진행 중인 녹화도 중지됩니다.')
        await expect(confirm).to_contain_text('녹화 파일은 삭제되지 않습니다.')
        await confirm.get_by_role('button', name='취소', exact=True).click()
        assert await second.count() == 1
        assert not errors, errors
        print('Recording cards PASS: layouts, 100h timer, units, shared identity, details, auto-record pending/error, tags, settings, stop and retained metrics, removal confirmation')
        await browser.close()

asyncio.run(main())
