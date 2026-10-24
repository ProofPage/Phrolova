"""PopkonTV live/VOD/clip registration, scoped cookies and responsive layouts."""
import asyncio
import copy
import os
from pathlib import Path
import sys
from urllib.parse import unquote,urlsplit

from playwright.async_api import async_playwright,expect
from browser_fixtures import FIX,mock
from animaru_integration import IDS,LABELS
from download_redesign import make_task

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))
from app.engine.popkontv import normalize_popkontv_channel_id

BASE=os.environ.get('PHROLOVA_TEST_URL','http://127.0.0.1:3017')
OUT=Path(__file__).resolve().parents[4]/'work/popkontv-ui'
PLATFORMS=['chzzk','youtube','soop','cime','kick','twitch','tiktok','bilibili','pandalive','popkontv','rplay']
LIVE_LABELS=['치지직','유튜브','숲','씨미','Kick','트위치','틱톡','Bilibili','팬더티비','팝콘티비','알플레이']
PAGE='https://www.popkontv.com/live/view?castId=fixture&partnerCode=P-00117'

async def main():
    OUT.mkdir(exist_ok=True);calls=[];errors=[];authenticated=False;capabilities_failure=False;tasks=[]
    channel=copy.deepcopy(FIX['channels'][0])
    channel.update(platform='popkontv',composite_key='popkontv:fixture@P-00117',channel_id='fixture@P-00117',channel_name='팝콘티비 테스트',
        title='공개 방송',is_live=True,broadcast_status='live',viewer_count=123,viewer_count_type=None,recording=None,
        recording_quality='best',postprocess=None,auto_record=False,channel_url=PAGE,last_error='',monitor_error=None,tags=[])
    async def route_api(route):
        nonlocal authenticated
        request=route.request;path=unquote(urlsplit(request.url).path)
        if path=='/api/platforms/channels':
            if request.method=='POST':calls.append(('add',request.post_data_json))
            return await route.fulfill(json=[channel] if request.method=='GET' else {'status':'added'})
        if path=='/api/platforms/status':
            return await route.fulfill(json={p:{'enabled':True,'authenticated':authenticated if p=='popkontv' else False} for p in PLATFORMS})
        if path=='/api/platforms/popkontv/fixture@P-00117/qualities':
            calls.append(('qualities',path))
            return await route.fulfill(json={'live':True,'qualities':[{'value':str(h)+'p','label':str(h)+'p','height':h} for h in (1080,720,480)]})
        if path=='/api/platforms/popkontv/cookie':
            if request.method=='POST':authenticated=True
            if request.method=='DELETE':authenticated=False
            return await route.fulfill(json={'configured':authenticated,'valid':authenticated,'expired':False,
                'message':'쿠키 파일이 등록되었습니다.' if authenticated else '쿠키가 등록되지 않았습니다.'})
        if path=='/api/stream/preview/popkontv:fixture@P-00117':
            calls.append(('preview',path))
            return await route.fulfill(status=403,json={'detail':'팝콘티비 로그인 또는 본인인증이 필요합니다.'})
        if path=='/api/vod/status':return await route.fulfill(json={'tasks':tasks,'imports':[],'active_count':0})
        if path=='/api/vod/prepare':
            data=request.post_data_json;calls.append(('prepare',data));results=[]
            for url in data['urls']:
                task=make_task('popkon-'+str(len(tasks)),url)
                task.update(platform='popkontv',title='팝콘티비 '+('다시보기' if '/vod/' in url else '클립'),quality='best',progress=0,downloaded_bytes=0,total_bytes=None)
                task['metadata']['qualities']=[{'value':'best','label':'원본'}]
                tasks.append(task);results.append({'task_id':task['task_id'],'url':url,'duplicate':False})
            return await route.fulfill(json={'results':results})
        if path=='/api/vod/capabilities':
            if capabilities_failure:return await route.fulfill(status=503,json={'detail':'test failure'})
            return await route.fulfill(json={'sources':[{'id':i,'label':l} for i,l in zip(IDS,LABELS)],'prepare':True,'pause':True,'file_open':True})
        return await mock(route)
    async with async_playwright() as p:
        browser=await p.chromium.launch(channel='chrome')
        try:
            context=await browser.new_context(viewport={'width':1440,'height':900})
            await context.add_init_script('window.EventSource=class{close(){}}')
            await context.route('**/api/**',route_api)
            page=await context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
            await page.goto(BASE+'/')
            await expect(page.locator('[data-channel-key="popkontv:fixture@P-00117"] .platform-badge')).to_have_text('팝콘티비')
            await page.get_by_role('button',name='플랫폼 선택: 치지직',exact=True).click()
            assert await page.get_by_role('listbox').get_by_role('option').all_text_contents()==LIVE_LABELS
            await page.get_by_role('option',name='팝콘티비',exact=True).click()
            await page.get_by_placeholder('팝콘티비 방송 링크 또는 채널ID@파트너코드').fill(PAGE+'&from=share')
            await page.locator('.dashboard-add-channel button[type=submit]').click()
            dialog=page.get_by_role('dialog');quality=dialog.locator('#channel-recording-quality')
            await expect(quality.locator('option[value="1080p"]')).to_have_count(1)
            await quality.select_option('720p')
            for width in (320,390,768,1440):
                await page.set_viewport_size({'width':width,'height':900})
                assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
            await dialog.get_by_role('button',name='채널 추가',exact=True).click()
            assert any(kind=='add' and data['platform']=='popkontv' and data['channel_id']=='fixture@P-00117' and data['recording_quality']=='720p' for kind,data in calls)
            cases=['fixture','FIXTURE@p-00117',PAGE,PAGE+'&from=home',
                PAGE.replace('https:','http:'),PAGE+'&castId=other',PAGE+'&partnerCode=P-00001',
                PAGE.replace('.com/','.com.evil/'),PAGE.replace('www.','@www.'),
                PAGE.replace('www.','u:p@www.'),PAGE.replace('.com/','.com:444/'),
                PAGE.replace('https:','file:'),'fixture\nother','f@P-12']
            expected=[]
            for value in cases:
                try:expected.append(normalize_popkontv_channel_id(value))
                except ValueError:expected.append(None)
            actual=await page.evaluate('''async cases=>{
                const {parsePlatformChannelInput:parse}=await import('/src/utils/platformChannels.ts');
                return cases.map(value=>parse('popkontv',value));
            }''',cases)
            assert actual==expected,list(zip(cases,actual,expected))
            await page.locator('[data-channel-key="popkontv:fixture@P-00117"] .recording-detail-action').click()
            await expect(page.locator('.channel-preview-message')).to_be_visible()
            assert any(kind=='preview' for kind,_ in calls)
            await page.goto(BASE+'/settings');await page.get_by_role('button',name='인증',exact=True).click()
            cookie=page.locator('[data-cookie-platform="popkontv"]')
            await expect(cookie).to_contain_text('팝콘티비')
            await cookie.locator('input[type=file]').set_input_files({'name':'fixture.txt','mimeType':'text/plain',
                'buffer':b'# Netscape HTTP Cookie File\n.popkontv.com\tTRUE\t/\tTRUE\t0\tsession\tFIXTURE_SECRET\n'})
            await expect(cookie).to_contain_text('쿠키 파일이 등록되었습니다.')
            await expect(cookie).not_to_contain_text('FIXTURE_SECRET')
            for width in (320,390,768,1440):
                await page.set_viewport_size({'width':width,'height':900})
                assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
            await cookie.scroll_into_view_if_needed();await page.screenshot(path=str(OUT/'auth-1440.png'),full_page=True)
            await page.goto(BASE+'/vod')
            panel=page.get_by_test_id('vod-preparation');await panel.get_by_role('combobox').click()
            assert await page.get_by_role('listbox').get_by_role('option').all_text_contents()==LABELS
            await page.get_by_role('option',name='팝콘티비',exact=True).click()
            for kind in ('vod','clip'):
                url='https://www.popkontv.com/'+kind+'/0023501?share=1'
                await panel.get_by_role('textbox').fill(url)
                await panel.get_by_role('button',name='목록에 추가',exact=True).click()
                assert any(k=='prepare' and d=={'urls':['https://www.popkontv.com/'+kind+'/23501'],'source':'popkontv'} for k,d in calls),calls
            await expect(page.get_by_role('heading',name='팝콘티비 다시보기',exact=True)).to_be_visible()
            await expect(page.get_by_role('heading',name='팝콘티비 클립',exact=True)).to_be_visible()
            for width in (320,390,768,1440):
                await page.set_viewport_size({'width':width,'height':900})
                assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
                if width==390:await page.screenshot(path=str(OUT/'videos-390.png'),full_page=True)
            await page.screenshot(path=str(OUT/'videos-1440.png'),full_page=True)
            capabilities_failure=True
            await page.reload()
            panel=page.get_by_test_id('vod-preparation');await panel.get_by_role('combobox').click()
            assert await page.get_by_role('listbox').get_by_role('option').all_text_contents()==LABELS
            assert await page.get_by_role('option',name='팬더티비',exact=True).count()==0
            assert not errors,errors
        finally:await browser.close()
    print('PASS: PopkonTV registration/qualities/cookies/authentication preview errors, 14 URL parity cases, VOD/clip queue, 11 live and 18 video sources, 320/390/768/1440px layouts')

if __name__=='__main__':asyncio.run(main())
