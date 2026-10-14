"""Kick 인증·화질 선택·준비 목록과 모바일 레이아웃을 브라우저에서 검증한다."""
import asyncio
import copy
import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from playwright.async_api import async_playwright, expect
from browser_fixtures import FIX, mock
from download_redesign import make_task

BASE = os.environ.get('PHROLOVA_TEST_URL','http://127.0.0.1:3001')
OUT = Path(os.environ.get('PHROLOVA_TEST_OUTPUT',str(Path(__file__).resolve().parents[3]/'work/kick-ui')))
VIDEO = 'https://kick.com/alice/videos/49d06353-e235-48c3-97fd-99c0d5e432c6'

async def main():
    OUT.mkdir(parents=True,exist_ok=True)
    authenticated = False
    tasks, calls, errors = [], [], []
    channel = copy.deepcopy(FIX['channels'][0])
    channel.update(platform='kick',composite_key='kick:alice',channel_id='alice',channel_name='Kick 샘플',
        is_live=False,recording=None,recording_quality='best',auto_record=False,postprocess=None,
        channel_url='https://kick.com/alice',last_error='',monitor_error=None,tags=[])
    async def route_api(route):
        nonlocal authenticated
        request = route.request
        path = unquote(urlparse(request.url).path)
        if path == '/api/platforms/channels':
            if request.method == 'POST': calls.append((path,request.post_data_json))
            return await route.fulfill(json=[channel] if request.method == 'GET' else {'status':'ok'})
        if path == '/api/platforms/status':
            return await route.fulfill(json={p:{'enabled':True,'authenticated':authenticated if p=='kick' else False} for p in ['chzzk','youtube','soop','cime','kick']})
        if path == '/api/platforms/kick/cookie':
            if request.method == 'POST': authenticated = True
            if request.method == 'DELETE': authenticated = False
            return await route.fulfill(json={'configured':authenticated,'valid':authenticated,'expired':False,
                'message':'쿠키 파일이 등록되었습니다.' if authenticated else '쿠키가 등록되지 않았습니다.'})
        if path.endswith('/qualities'):
            heights = [1080,720,480] if authenticated else [720,480]
            calls.append(('qualities',authenticated))
            return await route.fulfill(json={'live':True,'qualities':[{'value':f'{h}p','label':f'{h}p','height':h} for h in heights]})
        if path == '/api/vod/capabilities':
            return await route.fulfill(json={'sources':[{'id':'chzzk','label':'치지직'},{'id':'kick','label':'Kick'}],'prepare':True,'pause':True,'file_open':True})
        if path == '/api/vod/status': return await route.fulfill(json={'tasks':tasks,'imports':[],'active_count':0})
        if path == '/api/vod/prepare':
            data = request.post_data_json; calls.append((path,data))
            task = make_task('kick-video',url=VIDEO)
            task['title'] = 'Kick 동영상'
            task['platform'] = 'kick'
            tasks.append(task)
            return await route.fulfill(json={'results':[{'url':VIDEO,'task_id':'kick-video','duplicate':False}]})
        return await mock(route)

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(viewport={'width':1440,'height':1000})
        await context.add_init_script('window.EventSource=class{close(){}}')
        await context.route('**/api/**',route_api)
        page = await context.new_page()
        page.on('pageerror',lambda error:errors.append(str(error)))
        await page.goto(BASE)
        values = await page.evaluate('''async()=>{
            const {parseKickChannelInput: channel,canonicalKickVideoUrl: video}=await import('/src/utils/kickUrls.ts');
            const {normalizeDownloadInput: download,detectDownloadPlatform: detect}=await import('/src/utils/downloads.ts');
            return [channel('https://www.kick.com/Alice'),channel('https://kick.com.evil/alice'),channel('https://kick.com/alice?clip=clip_x'),
                channel('https://kick.com/%ZZ'),video('https://kick.com/alice?clip=clip_ABC'),video('https://kick.com/alice'),
                download('https://kick.com/Alice/videos/49d06353-e235-48c3-97fd-99c0d5e432c6?ref=share','kick'),detect('https://kick.com/alice')];
        }''')
        assert values == ['alice',None,None,None,'https://kick.com/alice/clips/clip_ABC',None,{'url':VIDEO,'collection':False,'source':'kick'},'kick'],values
        await page.get_by_role('button',name='플랫폼 선택: 치지직').click()
        await page.get_by_role('option',name='Kick',exact=True).click()
        await page.get_by_placeholder('Kick 채널 ID 또는 https://kick.com/...').fill('https://kick.com/Alice')
        await page.locator('.dashboard-add-channel button[type="submit"]').click()
        dialog = page.get_by_role('dialog')
        quality = dialog.locator('#channel-recording-quality')
        await expect(quality.locator('option[value="720p"]')).to_have_count(1)
        await expect(quality.locator('option[value="1080p"]')).to_have_count(0)
        await dialog.get_by_role('button',name='취소',exact=True).click()
        await page.goto(BASE+'/settings')
        await page.get_by_role('button',name='인증',exact=True).click()
        cookie = page.locator('[data-cookie-platform="kick"]')
        await expect(cookie).to_contain_text('등록된 쿠키 없음')
        await cookie.locator('input[type=file]').set_input_files({'name':'fixture.txt','mimeType':'text/plain',
            'buffer':b'# Netscape HTTP Cookie File\n.kick.com\tTRUE\t/\tTRUE\t0\tsession_token\tFIXTURE_SECRET\n'})
        await expect(cookie).to_contain_text('쿠키 파일이 등록되었습니다.')
        await expect(cookie).not_to_contain_text('FIXTURE_SECRET')
        for width in (360,390,768,1440):
            await page.set_viewport_size({'width':width,'height':1000})
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
            if width in (390,1440): await page.screenshot(path=str(OUT/f'auth-{width}.png'),full_page=True)
        await page.goto(BASE)
        await page.get_by_role('button',name='플랫폼 선택: 치지직').click()
        await page.get_by_role('option',name='Kick',exact=True).click()
        await page.get_by_placeholder('Kick 채널 ID 또는 https://kick.com/...').fill('alice')
        await page.locator('.dashboard-add-channel button[type="submit"]').click()
        await expect(quality.locator('option[value="1080p"]')).to_have_count(1)
        await quality.select_option('1080p')
        await dialog.get_by_role('button',name='채널 추가',exact=True).click()
        assert any(path=='/api/platforms/channels' and data['platform']=='kick' and data['recording_quality']=='1080p' for path,data in calls),calls
        await page.goto(BASE+'/vod')
        panel = page.get_by_test_id('vod-preparation')
        await panel.get_by_role('combobox').click()
        await panel.get_by_role('option',name='Kick',exact=True).click()
        await panel.get_by_role('textbox').fill(VIDEO+'?ref=share')
        await panel.get_by_role('button',name='목록에 추가',exact=True).click()
        await expect(page.locator('[data-task-id="kick-video"]')).to_be_visible()
        assert ('/api/vod/prepare',{'urls':[VIDEO],'source':'kick'}) in calls,calls
        for width in (360,390,768,1440):
            await page.set_viewport_size({'width':width,'height':1000})
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
            if width in (390,1440): await page.screenshot(path=str(OUT/f'vod-{width}.png'),full_page=True)
        assert not errors,errors
        await browser.close()
    print('PASS: Kick URL validation, unauthenticated/authenticated quality lists, cookie upload, 1080p channel registration, VOD preparation and 360/390/768/1440px layouts')

if __name__ == '__main__': asyncio.run(main())
