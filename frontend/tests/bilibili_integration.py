"""Bilibili 방송실·회차 URL, 인증, 화질과 모바일 UI를 외부 접속 없이 검증한다."""
import asyncio
import copy
import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from playwright.async_api import async_playwright, expect
from browser_fixtures import FIX, mock
from download_redesign import make_task

BASE = os.environ.get('PHROLOVA_TEST_URL', 'http://127.0.0.1:3001')
OUT = Path(os.environ.get('PHROLOVA_TEST_OUTPUT', str(Path(__file__).resolve().parents[3] / 'work/bilibili-ui')))
ROOM = '1726019661'
VIDEO = 'https://www.bilibili.com/video/BV1cSec6tEux/'
PART = VIDEO + '?p=2'
SHORT = 'https://b23.tv/AbC123'
PLATFORMS = ['chzzk', 'youtube', 'soop', 'cime', 'kick', 'twitch', 'tiktok', 'bilibili']


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    authenticated = False
    tasks, calls, errors = [], [], []
    channel = copy.deepcopy(FIX['channels'][0])
    channel.update(platform='bilibili', composite_key='bilibili:' + ROOM, channel_id=ROOM,
        channel_name='Bilibili 샘플', title='방송실 테스트', is_live=True, broadcast_status='live', viewer_count=12345, viewer_count_type='popularity',
        recording=None, recording_quality='best', auto_record=False, postprocess=None,
        channel_url='https://live.bilibili.com/' + ROOM, last_error='', monitor_error=None, tags=[],
        profile_image_url=BASE + '/__test__/avatar-broken.png')

    async def route_api(route):
        nonlocal authenticated
        request = route.request
        path = unquote(urlparse(request.url).path)
        if path == '/api/stream/preview/bilibili:' + ROOM:
            calls.append(('preview', path))
            return await route.fulfill(status=503, json={'detail': 'test unavailable'})
        if path == '/api/stream/preview-frame/bilibili:' + ROOM:
            raise AssertionError('Bilibili HLS must retain the video preview endpoint')
        if path == '/api/platforms/channels':
            if request.method == 'POST':
                calls.append((path, request.post_data_json))
            return await route.fulfill(json=[channel] if request.method == 'GET' else {'status': 'ok'})
        if path == '/api/platforms/status':
            return await route.fulfill(json={platform: {'enabled': True, 'authenticated': authenticated if platform == 'bilibili' else False} for platform in PLATFORMS})
        if path == '/api/platforms/bilibili/cookie':
            if request.method == 'POST':
                authenticated = True
            if request.method == 'DELETE':
                authenticated = False
            return await route.fulfill(json={'configured': authenticated, 'valid': authenticated, 'expired': False,
                'message': '쿠키 파일이 등록되었습니다.' if authenticated else '쿠키가 등록되지 않았습니다.'})
        if path == '/api/platforms/bilibili/' + ROOM + '/qualities':
            calls.append(('qualities', ROOM))
            return await route.fulfill(json={'live': True, 'qualities': [{'value': 'best', 'label': 'Original · HLS'}] + [
                {'value': 'qn_' + str(value), 'label': label} for value, label in [(10000, '원본'), (250, '초고화질'), (150, '고화질')]]})
        if path == '/api/vod/capabilities':
            return await route.fulfill(json={'sources': [{'id': platform, 'label': platform} for platform in PLATFORMS] + [{'id': 'external', 'label': '외부 영상'}],
                'prepare': True, 'pause': True, 'file_open': True})
        if path == '/api/vod/status':
            return await route.fulfill(json={'tasks': tasks, 'imports': [], 'active_count': 0})
        if path == '/api/vod/prepare':
            data = request.post_data_json
            calls.append((path, data))
            results = []
            for url in data['urls']:
                task_id = 'bilibili-' + str(len(tasks) + 1)
                task = make_task(task_id, url=url)
                task.update(title='Bilibili 동영상', platform='bilibili')
                tasks.append(task)
                results.append({'url': url, 'task_id': task_id, 'duplicate': False})
            return await route.fulfill(json={'results': results})
        return await mock(route)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel=os.environ.get('PHROLOVA_TEST_BROWSER') or None)
        context = await browser.new_context(viewport={'width': 1440, 'height': 1000})
        await context.add_init_script('window.__bilibiliEvents=[];window.EventSource=class{constructor(){window.__bilibiliEvents.push(this)}close(){this.closed=true}}')
        await context.route('**/api/**', route_api)
        async def avatar_fixture(route):
            assert 'referer' not in route.request.headers
            if route.request.url.endswith('avatar-valid.svg'):
                return await route.fulfill(content_type='image/svg+xml', body='<svg xmlns="http://www.w3.org/2000/svg" width="2" height="2"><rect width="2" height="2" fill="black"/></svg>')
            return await route.fulfill(status=404, body='missing avatar')
        await context.route('**/__test__/avatar-*', avatar_fixture)
        page = await context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        await page.goto(BASE)
        await expect(page.locator('[data-channel-key="bilibili:' + ROOM + '"] .platform-badge')).to_have_text('Bilibili')
        popularity = page.locator('[data-channel-key="bilibili:' + ROOM + '"] .recording-viewers')
        await expect(popularity).to_have_text('인기도 12,345')
        await expect(popularity).to_have_attribute('title', '인기도: 12,345')
        avatar = page.locator('[data-channel-key="bilibili:' + ROOM + '"] .recording-avatar')
        await expect(avatar).to_have_class('recording-avatar recording-avatar-fallback')
        channel['profile_image_url'] = BASE + '/__test__/avatar-valid.svg'
        await page.evaluate('channel=>{for(const source of window.__bilibiliEvents)if(!source.closed)source.onmessage?.({data:JSON.stringify({type:"status_update",data:[channel]})})}', channel)
        await expect(avatar).to_have_attribute('src', channel['profile_image_url'])
        await expect(avatar).to_have_attribute('referrerpolicy', 'no-referrer')
        await page.wait_for_function('''()=>document.querySelector('[data-channel-key="bilibili:1726019661"] img.recording-avatar')?.naturalWidth===2''')
        channel.pop('viewer_count_type')
        await page.reload()
        await expect(popularity).to_have_text('인기도 12,345')
        values = await page.evaluate("""async () => {
            const {parseBilibiliChannelInput: channel, canonicalBilibiliVideoUrl: video} = await import('/src/utils/bilibiliUrls.ts');
            const {parsePlatformChannelInput: platformChannel} = await import('/src/utils/platformChannels.ts');
            const {normalizeDownloadInput: download, detectDownloadPlatform: detect, parseDownloadInputs: inputs} = await import('/src/utils/downloads.ts');
            return {
                room: channel('https://live.bilibili.com/1726019661?hotRank=0&live_from=81003'),
                rawRoom: platformChannel('bilibili', '1726019661'),
                invalidRooms: ['0', '-1', '@name', 'https://live.bilibili.com.evil/123', 'https://live.bilibili.com@evil/123',
                    'https://user@live.bilibili.com/123', 'https://www.bilibili.com/video/BV1cSec6tEux/', 'https://live.bilibili.com/123/video',
                    'ftp://live.bilibili.com/123', 'https://live.bilibili.com/%ZZ'].map(channel),
                video: video('https://www.bilibili.com/video/BV1cSec6tEux/?trackid=share&spm_id_from=333'),
                firstPart: video('https://m.bilibili.com/video/BV1cSec6tEux?p=1&share_source=copy_web'),
                part: video('https://www.bilibili.com/video/BV1cSec6tEux/?p=2&spm_id_from=333'),
                rawVideo: download('BV1cSec6tEux', 'bilibili'),
                legacy: download('av170001', 'bilibili'),
                short: download('https://b23.tv/AbC123?share_source=copy_web', 'external'),
                detected: ['https://www.bilibili.com/video/BV1cSec6tEux/', 'https://b23.tv/AbC123', 'https://bilibili.com.evil/video/BV1cSec6tEux/'].map(detect),
                invalidVideos: ['https://live.bilibili.com/123', 'https://www.bilibili.com/video/invalid', 'https://b23.tv/',
                    'https://b23.tv/abc/def', 'https://b23.tv.evil/abc', 'https://user@b23.tv/abc', 'https://www.bilibili.com/video/BV1cSec6tEux/?p=0',
                    'https://www.bilibili.com/video/BV1cSec6tEux/?p=2&p=3', 'https://www.bilibili.com/video/BV1cSec6tEux/?p=oops',
                    'https://www.bilibili.com/%ZZ', 'file:///video/BV1cSec6tEux/'].map(video),
                dedup: inputs('https://www.bilibili.com/video/BV1cSec6tEux/?spm_id_from=333 https://www.bilibili.com/video/BV1cSec6tEux/?p=1 https://www.bilibili.com/video/BV1cSec6tEux/?p=2', 'bilibili'),
            };
        }""")
        assert values['room'] == values['rawRoom'] == ROOM, values
        assert values['invalidRooms'] == [None] * 10, values
        assert values['video'] == values['firstPart'] == VIDEO, values
        assert values['part'] == PART, values
        assert values['rawVideo'] == {'url': VIDEO, 'collection': False, 'source': 'bilibili'}, values
        assert values['legacy'] == {'url': 'https://www.bilibili.com/video/av170001/', 'collection': False, 'source': 'bilibili'}, values
        assert values['short'] == {'url': SHORT, 'collection': False, 'source': 'bilibili'}, values
        assert values['detected'] == ['bilibili', 'bilibili', 'external'], values
        assert values['invalidVideos'] == [None] * 11, values
        assert len(values['dedup']['items']) == 2 and len(values['dedup']['duplicates']) == 1, values
        await page.locator('[data-channel-key="bilibili:' + ROOM + '"] .recording-detail-action').click()
        for _ in range(30):
            if ('preview', '/api/stream/preview/bilibili:' + ROOM) in calls:
                break
            await page.wait_for_timeout(100)
        assert ('preview', '/api/stream/preview/bilibili:' + ROOM) in calls, calls
        await page.get_by_role('button', name='상세 접기', exact=True).click()
        await page.get_by_role('button', name='플랫폼 선택: 치지직').click()
        for name in ['치지직', '유튜브', '숲', '씨미', 'Kick', '트위치', '틱톡', 'Bilibili']:
            await expect(page.get_by_role('option', name=name, exact=True)).to_be_visible()
        await page.get_by_role('option', name='Bilibili', exact=True).click()
        await page.get_by_placeholder('Bilibili 방송실 ID 또는 https://live.bilibili.com/...').fill('https://live.bilibili.com/' + ROOM + '?live_from=81003')
        await page.locator('.dashboard-add-channel button[type="submit"]').click()
        dialog = page.get_by_role('dialog')
        quality = dialog.locator('#channel-recording-quality')
        await expect(quality.locator('option[value="qn_10000"]')).to_have_count(1)
        await expect(quality.locator('option[value="best"]')).to_have_count(1)
        await quality.select_option('qn_10000')
        await dialog.get_by_role('button', name='채널 추가', exact=True).click()
        assert any(path == '/api/platforms/channels' and data['platform'] == 'bilibili'
            and data['channel_id'] == ROOM and data['recording_quality'] == 'qn_10000' for path, data in calls), calls
        await page.goto(BASE + '/settings')
        await page.get_by_role('button', name='인증', exact=True).click()
        cookie = page.locator('[data-cookie-platform="bilibili"]')
        await expect(cookie).to_contain_text('등록된 쿠키 없음')
        await cookie.locator('input[type=file]').set_input_files({'name': 'fixture.txt', 'mimeType': 'text/plain',
            'buffer': b'# Netscape HTTP Cookie File\n.bilibili.com\tTRUE\t/\tTRUE\t0\tSESSDATA\tFIXTURE_SECRET\n'})
        await expect(cookie).to_contain_text('쿠키 파일이 등록되었습니다.')
        await expect(cookie).not_to_contain_text('FIXTURE_SECRET')
        for width in (360, 390, 768, 1440):
            await page.set_viewport_size({'width': width, 'height': 1000})
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'), width
            if width in (390, 1440):
                await cookie.scroll_into_view_if_needed()
                await page.screenshot(path=str(OUT / f'auth-{width}.png'), full_page=True)
        await page.goto(BASE + '/vod')
        panel = page.get_by_test_id('vod-preparation')
        await panel.get_by_role('combobox').click()
        for name in ['치지직', '유튜브', '숲', '씨미', 'Kick', '트위치', '틱톡', 'Bilibili']:
            await expect(panel.get_by_role('option', name=name, exact=True)).to_be_visible()
        await panel.get_by_role('option', name='Bilibili', exact=True).click()
        for url in [VIDEO + '?trackid=share', PART + '&spm_id_from=333', SHORT + '?share_source=copy_web', 'av170001']:
            await panel.get_by_role('textbox').fill(url)
            await panel.get_by_role('button', name='목록에 추가', exact=True).click()
            await expect(page.locator('[data-task-id="bilibili-' + str(len(tasks)) + '"]')).to_be_visible()
        prepared = [data for path, data in calls if path == '/api/vod/prepare']
        assert prepared == [{'urls': [url], 'source': 'bilibili'} for url in [VIDEO, PART, SHORT, 'https://www.bilibili.com/video/av170001/']], prepared
        for width in (360, 390, 768, 1440):
            await page.set_viewport_size({'width': width, 'height': 1000})
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'), width
            if width in (390, 1440):
                await page.screenshot(path=str(OUT / f'vod-{width}.png'), full_page=True)
        assert not errors, errors
        await browser.close()
    print('PASS: Bilibili live room, HLS preview routing, BV/av/part/short URL normalization, source preservation, cookie upload, dynamic quality registration and 360/390/768/1440px layouts')


if __name__ == '__main__':
    asyncio.run(main())
