"""Unified settings save, partial failure recovery and sticky responsive placement."""
import asyncio
import copy
import json
import os
from pathlib import Path
from urllib.parse import urlparse
from playwright.async_api import async_playwright, expect
from browser_fixtures import FIX, mock

BASE=os.environ.get('PHROLOVA_TEST_URL','http://127.0.0.1:3001')
OUT=Path(os.environ['PHROLOVA_TEST_OUTPUT'])
ROOT=Path(__file__).resolve().parents[1]

async def main():
    OUT.mkdir(parents=True,exist_ok=True)
    settings=copy.deepcopy(FIX['settings'])
    settings.update(live_download_dir='/recordings/live',vod_download_dir='/recordings/vod',chzzk_live_cdn='default',chzzk_vod_cdn='default')
    policy={'output_format':'mkv','keep_source_ts':True,'max_concurrent':1}
    calls=[]
    fail_processing=False
    fail_live=False
    async def route_api(route):
        nonlocal policy
        path=urlparse(route.request.url).path
        if path=='/api/settings/browse-dirs':
            return await route.fulfill(json={'current':'/recordings/선택한 폴더','parent':'/recordings','dirs':[]})
        if path=='/api/settings':return await route.fulfill(json=settings)
        if path=='/api/recordings/settings':
            if route.request.method=='PUT':
                calls.append((path,route.request.post_data_json))
                await asyncio.sleep(.2)
                if fail_processing:return await route.fulfill(status=500,json={'detail':'파일 처리 설정 저장 실패'})
                policy=route.request.post_data_json
            return await route.fulfill(json=policy)
        if path in ('/api/settings/vod','/api/settings/live','/api/settings/general'):
            calls.append((path,route.request.post_data_json))
            await asyncio.sleep(.2)
            if path.endswith('/live') and fail_live:return await route.fulfill(status=500,json={'detail':'라이브 설정 저장 실패'})
            settings.update(route.request.post_data_json)
            return await route.fulfill(json={'settings':settings})
        return await mock(route)

    async with async_playwright() as p:
        browser=await p.chromium.launch()
        context=await browser.new_context(viewport={'width':1440,'height':1100})
        await context.add_init_script('window.EventSource=class{close(){}}')
        await context.route('**/api/**',route_api)
        page=await context.new_page()
        errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        await page.goto(BASE+'/settings')
        root=page.locator('.download-settings')
        footer=root.locator('.download-settings-save')
        save=footer.get_by_role('button')
        await expect(save).to_have_count(1)
        await expect(save).to_be_disabled()
        await expect(root.locator('.settings-save-row')).to_have_count(0)
        await expect(page.locator('[data-settings-section]')).to_have_count(3)
        video=root.locator('[data-settings-section="video"]')
        processing=root.locator('[data-settings-section="processing"]')
        live=root.locator('[data-settings-section="live"]')
        await expect(processing).to_have_attribute('aria-busy','false')
        await video.get_by_role('button',name='폴더 찾아보기',exact=True).click()
        await page.get_by_role('dialog',name='폴더 선택').get_by_role('button',name='이 폴더 선택',exact=True).click()
        await live.get_by_role('textbox',name='라이브 저장 위치',exact=True).fill('/recordings/라이브 폴더')
        await live.get_by_role('spinbutton',name='라이브 확인 주기 (초)').fill('4')
        await processing.get_by_role('combobox',name='녹화 완료 후 저장 형식',exact=True).select_option('mp4')
        await expect(save).to_be_disabled()
        await expect(footer).to_contain_text('숫자 범위')
        await live.get_by_role('spinbutton',name='라이브 확인 주기 (초)').fill('45')
        await live.get_by_role('combobox',name='치지직 라이브 CDN').select_option('akamai')
        await video.get_by_role('spinbutton',name='동시 다운로드 개수').fill('2')
        await expect(save).to_be_enabled()
        # One click saves all changed sections; a failed middle request must not lose the last one.
        fail_processing=True
        await save.evaluate('e=>{e.click();e.click()}')
        await expect(root.locator('fieldset')).to_have_attribute('disabled','')
        await expect(video.get_by_role('spinbutton',name='동시 다운로드 개수')).to_be_disabled()
        await expect(live).to_have_attribute('aria-busy','false')
        await expect(processing.get_by_role('alert')).to_contain_text('저장')
        assert [path for path,_ in calls]==['/api/settings/vod','/api/recordings/settings','/api/settings/live'],calls
        assert settings['vod_download_dir']=='/recordings/선택한 폴더'
        assert settings['live_download_dir']=='/recordings/라이브 폴더' and settings['monitor_interval']==45
        assert settings['chzzk_live_cdn']=='akamai' and settings['vod_max_concurrent']==2
        assert policy['output_format']=='mkv'
        await expect(processing.get_by_role('combobox',name='녹화 완료 후 저장 형식',exact=True)).to_have_value('mp4')
        await expect(save).to_be_enabled()
        fail_processing=False
        await save.click()
        await expect(save).to_be_disabled()
        await expect(root.locator('fieldset')).not_to_have_attribute('disabled','')
        await expect(footer.get_by_role('status')).to_have_count(0)
        assert len(calls)==4 and calls[-1][0]=='/api/recordings/settings',calls
        assert policy['output_format']=='mp4'
        # A later live failure keeps input and the existing navigation warning.
        await live.get_by_role('spinbutton',name='라이브 확인 주기 (초)').fill('60')
        fail_live=True
        await save.click()
        await expect(live.get_by_role('alert')).to_contain_text('저장')
        await expect(save).to_be_enabled()
        await expect(live.get_by_role('spinbutton',name='라이브 확인 주기 (초)')).to_have_value('60')
        nav=page.get_by_role('navigation',name='설정 탭')
        await nav.get_by_role('button',name='외관',exact=True).click()
        dialog=page.get_by_role('dialog')
        await expect(dialog).to_be_visible()
        await dialog.get_by_role('button',name='취소',exact=True).click()
        await expect(live.get_by_role('spinbutton',name='라이브 확인 주기 (초)')).to_have_value('60')
        fail_live=False
        await save.click()
        await expect(root.locator('fieldset')).not_to_have_attribute('disabled','')
        await expect(footer.get_by_role('status')).to_have_count(0)
        assert len(calls)==6 and calls[-1][0]=='/api/settings/live',calls
        await page.reload()
        await expect(processing.get_by_role('combobox',name='녹화 완료 후 저장 형식',exact=True)).to_have_value('mp4')
        await expect(video.get_by_role('textbox',name='영상 저장 위치',exact=True)).to_have_value('/recordings/선택한 폴더')
        await expect(live.get_by_role('spinbutton',name='라이브 확인 주기 (초)')).to_have_value('60')
        await expect(save).to_be_disabled()
        # Keep the single save action visible at the top and middle of a long page.
        for width in (320,390,768,1024,1440,1920):
            await page.set_viewport_size({'width':width,'height':900})
            await page.get_by_role('heading',name='설정',exact=True).scroll_into_view_if_needed()
            bounds=await save.bounding_box()
            row=await footer.bounding_box()
            assert bounds and 0<=bounds['y'] and bounds['y']+bounds['height']<=901,(width,bounds)
            assert abs(row['x']+row['width']-bounds['x']-bounds['width'])<1,(width,row,bounds)
            await processing.get_by_role('heading').scroll_into_view_if_needed()
            bounds=await save.bounding_box()
            assert bounds and 0<=bounds['y'] and bounds['y']+bounds['height']<=901,(width,bounds)
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
            await page.screenshot(path=str(OUT/f'unified-save-{width}.png'))
        assert not errors,errors
        await context.close()
        # All eight locales retain a single unclipped save button in narrow/wide windows.
        for locale in ('ko-KR','en-US','ja-JP','es-ES','de-DE','zh-CN','zh-TW','ru-RU'):
            translations=json.loads((ROOT/'src/i18n/locales'/f'{locale}.json').read_text(encoding='utf-8'))
            context=await browser.new_context()
            await context.add_init_script('localStorage.setItem("phrolova-language",'+json.dumps(locale)+');window.EventSource=class{close(){}}')
            await context.route('**/api/**',route_api)
            page=await context.new_page()
            for width in (320,390,1440):
                await page.set_viewport_size({'width':width,'height':900})
                await page.goto(BASE+'/settings')
                save=page.locator('.download-settings-save').get_by_role('button',name=translations['settings.saveChanges'],exact=True)
                await expect(save).to_have_count(1)
                assert await save.evaluate('e=>e.scrollWidth<=e.clientWidth+1'),(locale,width,'clipped save')
                bounds=await save.bounding_box()
                assert bounds and bounds['y']+bounds['height']<=901,(locale,width,bounds)
                assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(locale,width)
            await context.close()
        await browser.close()
    print('PASS: one save for 3 scopes, sequential changed-only requests, pending/validation/partial failure/retry, navigation guard, persistence, sticky right alignment at 6 widths and 8 locales')

asyncio.run(main())
