"""TikTok 인증·화질 선택·준비 목록과 모바일 레이아웃을 브라우저에서 검증한다."""
import asyncio
import base64
import copy
import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from playwright.async_api import async_playwright, expect
from browser_fixtures import FIX, mock
from download_redesign import make_task

BASE = os.environ.get('PHROLOVA_TEST_URL','http://127.0.0.1:3001')
OUT = Path(os.environ.get('PHROLOVA_TEST_OUTPUT',str(Path(__file__).resolve().parents[3]/'work/tiktok-ui')))
VIDEO = 'https://www.tiktok.com/@alice/video/7100000000000000000'
SHORT = 'https://vt.tiktok.com/AbC123/'

async def main():
    OUT.mkdir(parents=True,exist_ok=True)
    authenticated = False
    tasks, calls, errors = [], [], []
    channel = copy.deepcopy(FIX['channels'][0])
    channel.update(platform='tiktok',composite_key='tiktok:alice',channel_id='alice',channel_name='TikTok 샘플',
        is_live=True,broadcast_status='live',recording=None,recording_quality='best',auto_record=False,postprocess=None,
        channel_url='https://www.tiktok.com/@alice/live',last_error='',monitor_error=None,tags=[])
    async def route_api(route):
        nonlocal authenticated
        request = route.request
        path = unquote(urlparse(request.url).path)
        if path == '/api/stream/preview-frame/tiktok:alice':
            calls.append(('preview-frame',path))
            return await route.fulfill(content_type='image/png',body=base64.b64decode(
                'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aK1sAAAAASUVORK5CYII='))
        if path == '/api/stream/preview/tiktok:alice':
            raise AssertionError('TikTok FLV must use the image preview endpoint')
        if path == '/api/platforms/channels':
            if request.method == 'POST': calls.append((path,request.post_data_json))
            return await route.fulfill(json=[channel] if request.method == 'GET' else {'status':'ok'})
        if path == '/api/platforms/status':
            return await route.fulfill(json={p:{'enabled':True,'authenticated':authenticated if p=='tiktok' else False} for p in ['chzzk','youtube','soop','cime','tiktok']})
        if path == '/api/platforms/tiktok/cookie':
            if request.method == 'POST': authenticated = True
            if request.method == 'DELETE': authenticated = False
            return await route.fulfill(json={'configured':authenticated,'valid':authenticated,'expired':False,
                'message':'쿠키 파일이 등록되었습니다.' if authenticated else '쿠키가 등록되지 않았습니다.'})
        if path.endswith('/qualities'):
            heights = [1080,720,480]
            calls.append(('qualities',authenticated))
            return await route.fulfill(json={'live':True,'qualities':[{'value':f'{h}p','label':f'{h}p','height':h} for h in heights]})
        if path == '/api/vod/capabilities':
            return await route.fulfill(json={'sources':[{'id':'chzzk','label':'치지직'},{'id':'tiktok','label':'TikTok'}],'prepare':True,'pause':True,'file_open':True})
        if path == '/api/vod/status': return await route.fulfill(json={'tasks':tasks,'imports':[],'active_count':0})
        if path == '/api/vod/prepare':
            data = request.post_data_json; calls.append((path,data))
            url = data['urls'][0]
            task_id = 'tiktok-short' if url == SHORT else 'tiktok-video'
            task = make_task(task_id,url=url)
            task['title'] = 'TikTok 동영상'
            task['platform'] = 'tiktok'
            tasks.append(task)
            return await route.fulfill(json={'results':[{'url':url,'task_id':task_id,'duplicate':False}]})
        return await mock(route)

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(viewport={'width':1440,'height':1000})
        await context.add_init_script('window.EventSource=class{close(){}}')
        await context.route('**/api/**',route_api)
        page = await context.new_page()
        page.on('pageerror',lambda error:errors.append(str(error)))
        await page.goto(BASE)
        await page.locator('[data-channel-key="tiktok:alice"] .recording-detail-action').click()
        preview = page.locator('.channel-preview-player img')
        await expect(preview).to_be_visible()
        assert await preview.evaluate('(image)=>image.naturalWidth>0')
        assert ('preview-frame','/api/stream/preview-frame/tiktok:alice') in calls
        for width in (360,390,768,1440):
            await page.set_viewport_size({'width':width,'height':1000})
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
        await page.get_by_role('button',name='상세 접기',exact=True).click()
        values = await page.evaluate('''async()=>{
            const {parseTikTokChannelInput: channel,canonicalTikTokVideoUrl: video}=await import('/src/utils/tiktokUrls.ts');
            const {normalizeDownloadInput: download,detectDownloadPlatform: detect}=await import('/src/utils/downloads.ts');
            return [channel('@Alice'),channel('https://tiktok.com.evil/@alice'),channel('https://tiktok.com/@alice/video/1'),
                channel('https://tiktok.com/%ZZ'),video('https://vt.tiktok.com/AbC123/?ref=share'),video('https://tiktok.com/@alice/live'),
                download('https://m.tiktok.com/@Alice/video/7100000000000000000?ref=share','tiktok'),detect('https://vt.tiktok.com/AbC123/')];
        }''')
        assert values == ['alice',None,None,None,SHORT,None,{'url':VIDEO,'collection':False,'source':'tiktok'},'tiktok'],values
        await page.get_by_role('button',name='플랫폼 선택: 치지직').click()
        await page.get_by_role('option',name='틱톡',exact=True).click()
        await page.get_by_placeholder('틱톡 @사용자 이름 또는 https://www.tiktok.com/@...').fill('https://www.tiktok.com/@Alice/live')
        await page.locator('.dashboard-add-channel button[type="submit"]').click()
        dialog = page.get_by_role('dialog')
        quality = dialog.locator('#channel-recording-quality')
        await expect(quality.locator('option[value="720p"]')).to_have_count(1)
        await expect(quality.locator('option[value="1080p"]')).to_have_count(1)
        await dialog.get_by_role('button',name='취소',exact=True).click()
        await page.goto(BASE+'/settings')
        await page.get_by_role('button',name='인증',exact=True).click()
        cookie = page.locator('[data-cookie-platform="tiktok"]')
        await expect(cookie).to_contain_text('등록된 쿠키 없음')
        await cookie.locator('input[type=file]').set_input_files({'name':'fixture.txt','mimeType':'text/plain',
            'buffer':b'# Netscape HTTP Cookie File\n.tiktok.com\tTRUE\t/\tTRUE\t0\tsessionid\tFIXTURE_SECRET\n'})
        await expect(cookie).to_contain_text('쿠키 파일이 등록되었습니다.')
        await expect(cookie).not_to_contain_text('FIXTURE_SECRET')
        for width in (360,390,768,1440):
            await page.set_viewport_size({'width':width,'height':1000})
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
            if width in (390,1440):
                await cookie.scroll_into_view_if_needed()
                await page.screenshot(path=str(OUT/f'auth-{width}.png'),full_page=True)
        await page.goto(BASE)
        await page.get_by_role('button',name='플랫폼 선택: 치지직').click()
        await page.get_by_role('option',name='틱톡',exact=True).click()
        await page.get_by_placeholder('틱톡 @사용자 이름 또는 https://www.tiktok.com/@...').fill('alice')
        await page.locator('.dashboard-add-channel button[type="submit"]').click()
        await expect(quality.locator('option[value="1080p"]')).to_have_count(1)
        await quality.select_option('1080p')
        await dialog.get_by_role('button',name='채널 추가',exact=True).click()
        assert any(path=='/api/platforms/channels' and data['platform']=='tiktok' and data['recording_quality']=='1080p' for path,data in calls),calls
        await page.goto(BASE+'/vod')
        panel = page.get_by_test_id('vod-preparation')
        await panel.get_by_role('combobox').click()
        await panel.get_by_role('option',name='틱톡',exact=True).click()
        await panel.get_by_role('textbox').fill(VIDEO+'?ref=share')
        await panel.get_by_role('button',name='목록에 추가',exact=True).click()
        await expect(page.locator('[data-task-id="tiktok-video"]')).to_be_visible()
        assert ('/api/vod/prepare',{'urls':[VIDEO],'source':'tiktok'}) in calls,calls
        await panel.get_by_role('textbox').fill(SHORT+'?ref=share')
        await panel.get_by_role('button',name='목록에 추가',exact=True).click()
        await expect(page.locator('[data-task-id="tiktok-short"]')).to_be_visible()
        assert ('/api/vod/prepare',{'urls':[SHORT],'source':'tiktok'}) in calls,calls
        for width in (360,390,768,1440):
            await page.set_viewport_size({'width':width,'height':1000})
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
            if width in (390,1440): await page.screenshot(path=str(OUT/f'vod-{width}.png'),full_page=True)
        assert not errors,errors
        await browser.close()
    print('PASS: TikTok frame preview, URL validation, public quality lists, cookie upload, 1080p channel registration, video/short-link preparation and 360/390/768/1440px layouts')

if __name__ == '__main__': asyncio.run(main())
