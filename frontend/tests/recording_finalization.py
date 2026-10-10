"""Headless Chromium checks with isolated APIs; never records an upstream broadcast."""
import asyncio,copy,os,tempfile
from pathlib import Path
from urllib.parse import urlparse
from playwright.async_api import async_playwright,expect
from browser_fixtures import FIX,mock

BASE=os.environ.get('PHROLOVA_TEST_URL','http://127.0.0.1:3001')
OUT=Path(os.environ.get('PHROLOVA_TEST_OUTPUT',str(Path(tempfile.gettempdir())/'phrolova-finalization-ui')))

async def main():
    OUT.mkdir(parents=True,exist_ok=True)
    jobs=[];channels=[];calls=[]
    policy=dict(output_format='mp4',keep_source_ts=True,max_concurrent=1)
    for index,(platform,state) in enumerate(zip(['chzzk','youtube','soop','cime'],['pending','converting','completed','failed'])):
        job=dict(id=str(index),composite_key=platform+':sample',channel_name='[미리보기 샘플] '+platform,state=state,target_format='mp4',progress=42.7 if state=='converting' else None,
                 source_paths=['/sample/한글 원본.ts'],output_path='/sample/final.mp4' if state=='completed' else None,
                 error_message='파일 검사 시간이 초과되었습니다. 원본 TS를 보관했습니다.' if state=='failed' else None,
                 inspection_state='failed' if state=='failed' else 'passed' if state=='completed' else 'pending',diagnostics={'detail':'fixture diagnostic'} if state=='failed' else {})
        jobs.append(job)
        c=copy.deepcopy(FIX['channels'][1]);c.update(platform=platform,composite_key=platform+':sample',channel_id='sample',channel_name=job['channel_name'],title='긴 영상 제목 '*20,
                  tags=[],recording=None,is_live=False,auto_record=False,last_error=None,postprocess=job,profile_image_url='')
        channels.append(c)
    historic=copy.deepcopy(jobs[3]);historic.update(id='old',composite_key='cime:removed',channel_name='[미리보기 샘플] 제거한 채널');jobs.append(historic)
    async def route_api(route):
        path=urlparse(route.request.url).path;request=route.request
        if request.method!='GET':calls.append((path,request.post_data_json))
        if path=='/api/platforms/channels':return await route.fulfill(json=channels)
        if path=='/api/platforms/status':return await route.fulfill(json={p:{'enabled':True,'authenticated':True} for p in ['chzzk','youtube','soop','cime']})
        if path=='/api/recordings/settings':
            if request.method=='PUT':policy.update(request.post_data_json)
            return await route.fulfill(json=policy)
        if path=='/api/recordings/jobs':return await route.fulfill(json={'jobs':jobs})
        if path.startswith('/api/recordings/') and request.method=='POST':
            job=next(j for j in jobs if j['id']==path.split('/')[3])
            await asyncio.sleep(.2)
            if path.endswith('/retry'):job.update(state='pending',error_message=None,target_format=request.post_data_json.get('output_format',job['target_format']))
            if path.endswith('/inspect'):job.update(state='completed',inspection_state='passed',error_message=None)
            return await route.fulfill(json={'message':'샘플 저장 위치: /sample'} if path.endswith('/open-location') else job)
        return await mock(route)
    async with async_playwright() as p:
        browser=await p.chromium.launch();context=await browser.new_context(viewport={'width':1440,'height':1050})
        await context.add_init_script("window.EventSource=class{close(){}};localStorage.setItem('dashboardViewMode','list')")
        await context.route('**/api/**',route_api);page=await context.new_page();errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        await page.goto(BASE)
        await expect(page.locator('[data-channel-key]')).to_have_count(4)
        await expect(page.get_by_text('MP4 변환 중',exact=True)).to_be_visible()
        await expect(page.get_by_text('42.7%',exact=True)).to_be_visible()
        await expect(page.get_by_text('녹화 완료 · MP4',exact=True)).to_be_visible()
        await expect(page.get_by_text('녹화 파일 처리 이력',exact=True)).to_be_visible()
        await expect(page.get_by_text('[미리보기 샘플] 제거한 채널',exact=True)).to_be_visible()
        assert '채팅' not in await page.locator('body').inner_text()
        await expect(page.get_by_text('스페이스',exact=True)).to_have_count(0)
        failed=page.locator('[data-channel-key="cime:sample"]')
        await failed.get_by_role('button',name='MKV로 변환',exact=True).click()
        await expect(failed.get_by_role('button',name='다시 변환',exact=True)).to_be_disabled()
        await asyncio.sleep(.3)
        assert [c for c in calls if c[0]=='/api/recordings/3/retry']==[('/api/recordings/3/retry',{'output_format':'mkv'})]
        completed=page.locator('[data-channel-key="soop:sample"]')
        await completed.get_by_role('button',name='다시 검사',exact=True).click();await asyncio.sleep(.3)
        assert any(c[0]=='/api/recordings/2/inspect' for c in calls)
        for width in (360,390,768,1024,1440):
            await page.set_viewport_size({'width':width,'height':1050})
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
            await page.screenshot(path=str(OUT/f'live-finalization-{width}.png'),full_page=True)
        await page.goto(BASE+'/settings')
        await page.get_by_role('button',name='다운로드',exact=True).click()
        await expect(page.get_by_role('combobox',name='녹화 완료 후 저장 형식',exact=True)).to_have_value('mp4')
        await page.get_by_role('combobox',name='녹화 완료 후 저장 형식',exact=True).select_option('mkv')
        await page.get_by_role('switch',name='변환 후 원본 TS 보관',exact=True).click()
        await page.get_by_role('combobox',name='동시 파일 변환 수',exact=True).select_option('2')
        await page.get_by_role('button',name='녹화 저장 설정 저장',exact=True).click()
        await expect(page.get_by_role('button',name='녹화 저장 설정 저장',exact=True)).to_be_disabled()
        assert policy==dict(output_format='mkv',keep_source_ts=False,max_concurrent=2)
        await page.reload();await page.get_by_role('button',name='다운로드',exact=True).click()
        await expect(page.get_by_role('combobox',name='녹화 완료 후 저장 형식',exact=True)).to_have_value('mkv')
        for width in (360,390,768,1024,1440):
            await page.set_viewport_size({'width':width,'height':1050})
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
        assert '채팅' not in await page.locator('body').inner_text()
        await page.set_viewport_size({'width':1440,'height':1050});await page.screenshot(path=str(OUT/'recording-settings-1440.png'),full_page=True)
        assert not errors,errors
        print('PASS: real Chromium, 4 platforms, pending/converting/completed/failed jobs, retry payload, inspection, removed-channel history, persistent settings UI, no retired menus, widths 360/390/768/1024/1440')
        await browser.close()

if __name__=='__main__':asyncio.run(main())
