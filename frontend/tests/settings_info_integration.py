"""System tab is retired; information owns tools and updates without losing actions."""
import asyncio
import copy
import os
from pathlib import Path
from urllib.parse import urlparse
from playwright.async_api import async_playwright, expect
from browser_fixtures import FIX, mock

BASE=os.environ.get('PHROLOVA_TEST_URL','http://127.0.0.1:3001')
OUT=Path(os.environ.get('PHROLOVA_TEST_OUTPUT','/tmp/phrolova-settings-info'))

async def main():
    OUT.mkdir(parents=True,exist_ok=True)
    settings=copy.deepcopy(FIX['settings'])
    settings.update(app_name='Phrolova',ffmpeg_version='9.0.2',streamlink_version='8.6.2',host='127.0.0.1',port=8000)
    tool_calls=0; update_calls=0; fail_update=False; fail_tools=False
    update={'has_update':False,'current_version':'2.0.60','latest_version':'2.0.60',
        'release_notes':'정보 탭 통합','environment':'windows-exe',
        'download_url':'https://github.com/ProofPage/Phrolova/releases/tag/v2.0.61'}
    async def route_api(route):
        nonlocal tool_calls,update_calls
        path=urlparse(route.request.url).path
        if path=='/api/settings': return await route.fulfill(json=settings)
        if path=='/api/system/update': return await route.fulfill(json=update)
        if path=='/api/system/update/check':
            update_calls+=1
            if fail_update:return await route.fulfill(status=503,json={'detail':'업데이트 서버 연결 실패'})
            update.update(has_update=True,latest_version='2.0.61')
            return await route.fulfill(json=update)
        if path=='/api/system/media-tools':
            tool_calls+=1
            if fail_tools:return await route.fulfill(status=503,json={'detail':'도구 조회 실패'})
            return await route.fulfill(json={key:{'available':True,
                'version':key+' version 9.0.2-full_build-www.gyan.dev Copyright',
                'path':'C:/한글 도구 폴더/'+('긴 경로/'*12)+key+'.exe'} for key in ('ffmpeg','ffprobe')})
        return await mock(route)
    async with async_playwright() as p:
        browser=await p.chromium.launch()
        context=await browser.new_context()
        await context.add_init_script('window.EventSource=class{close(){}}')
        await context.route('**/api/**',route_api)
        page=await context.new_page();errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        for width in (320,768,1440):
            update.update(has_update=False,latest_version='2.0.60')
            await page.set_viewport_size({'width':width,'height':1000})
            await page.goto(BASE+'/settings')
            nav=page.get_by_role('navigation',name='설정 탭')
            await expect(nav.get_by_role('button')).to_have_count(5)
            await expect(nav.get_by_role('button',name='시스템',exact=True)).to_have_count(0)
            info=nav.get_by_role('button',name='정보',exact=True)
            await info.click()
            for title in ('시스템 정보','미디어 도구','프로그램 업데이트','프로그램 정보'):
                await expect(page.get_by_role('heading',name=title,exact=True)).to_have_count(1)
            await expect(page.get_by_text('FFmpeg',exact=True)).to_have_count(1)
            await expect(page.get_by_text('FFprobe',exact=True)).to_have_count(1)
            await expect(page.get_by_text('FFmpeg 버전',exact=True)).to_have_count(0)
            await expect(page.get_by_text('v2.0.60',exact=True)).to_have_count(2) # current/latest only
            before=tool_calls
            await page.get_by_role('button',name='도구 다시 검사').click()
            await expect(page.get_by_role('button',name='도구 다시 검사')).to_be_enabled()
            assert tool_calls==before+1
            before=update_calls
            await page.get_by_role('button',name='업데이트 확인',exact=True).click()
            await expect(page.get_by_role('button',name='v2.0.61 업데이트 하기')).to_be_visible()
            assert update_calls==before+1
            await expect(info.locator('.bg-ok')).to_have_count(1)
            await page.get_by_role('button',name='v2.0.61 업데이트 하기').click()
            dialog=page.get_by_role('dialog')
            await expect(dialog.get_by_role('link',name='GitHub 릴리즈에서 다운로드')).to_have_attribute('href',update['download_url'])
            await page.keyboard.press('Escape')
            await expect(dialog).to_have_count(0)
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
            await page.screenshot(path=str(OUT/f'info-{width}.png'),full_page=True)
        fail_tools=True
        await page.get_by_role('button',name='도구 다시 검사').click()
        await expect(page.get_by_text('도구 상태를 불러오지 못했습니다.',exact=True)).to_have_count(2)
        fail_tools=False
        await page.get_by_role('button',name='도구 다시 검사').click()
        await expect(page.get_by_text('도구 상태를 불러오지 못했습니다.',exact=True)).to_have_count(0)
        fail_update=True
        await page.get_by_role('button',name='업데이트 확인',exact=True).click()
        await expect(page.get_by_text('업데이트 서버 연결 실패',exact=True)).to_be_visible()
        await expect(page.get_by_role('button',name='업데이트 확인',exact=True)).to_be_enabled()
        fail_update=False
        await page.get_by_role('button',name='업데이트 확인',exact=True).click()
        await expect(page.get_by_role('button',name='v2.0.61 업데이트 하기')).to_be_visible()
        assert not errors,errors
        await browser.close()
    print('PASS: five settings tabs, integrated information/tools/update/about, real button API calls/modal, update badge, failed requests/recovery, 320/768/1440px')

if __name__=='__main__':asyncio.run(main())
