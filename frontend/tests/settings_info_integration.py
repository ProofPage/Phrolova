"""Information shows tool status automatically and retains the update actions."""
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
        'checked_at':'2026-10-13T00:00:00','release_notes':'정보 탭 통합','environment':'windows-exe',
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
                'version':'8.6.2' if key=='streamlink' else key+' version 9.0.2-full_build-www.gyan.dev Copyright',
                'path':'C:/한글 도구 폴더/'+('긴 경로/'*12)+key+'.exe'} for key in ('streamlink','ffmpeg','ffprobe')})
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
            await expect(page.locator('.download-settings-save')).to_have_count(1)
            assert await page.locator('.download-settings-save').evaluate('e=>getComputedStyle(e).borderTopWidth') == '0px'
            await nav.get_by_role('button',name='인증',exact=True).click()
            await expect(page.locator('[data-cookie-platform]')).to_have_count(4)
            hint = await page.locator('.auth-guidance').bounding_box()
            last_cookie = await page.locator('[data-cookie-platform]').last.bounding_box()
            assert hint['y'] >= last_cookie['y'] + last_cookie['height'], (width, hint, last_cookie)
            assert abs(hint['y'] - last_cookie['y'] - last_cookie['height'] - 16) < 1, (width, hint, last_cookie)
            assert abs(hint['x'] - last_cookie['x']) < 1 and abs(hint['width'] - last_cookie['width']) < 1
            assert await page.locator('.auth-settings').evaluate('''e=>{
                const p=e.querySelector('.settings-shared-hint'), r=document.createRange();
                r.selectNodeContents(p);
                return Math.abs(r.getClientRects()[0].left-e.querySelector('.ui-section-header h3').getBoundingClientRect().left)<1;
            }'''), (width, 'cookie hint alignment')
            await nav.get_by_role('button',name='외관',exact=True).click()
            await expect(page.get_by_role('heading',name='외관 설정',exact=True)).to_have_count(0)
            await expect(page.locator('.appearance-settings .ui-field')).to_have_count(3)
            await expect(page.get_by_role('combobox',name='언어',exact=True)).to_be_visible()
            info=nav.get_by_role('button',name='정보',exact=True)
            await info.click()
            for title in ('기본 정보','소프트웨어 업데이트','Phrolova 정보'):
                await expect(page.get_by_role('heading',name=title,exact=True)).to_have_count(0)
            await expect(page.locator('.info-settings > :last-child')).to_have_class('info-section info-update-section')
            assert await page.locator('.info-version-summary > :last-child').evaluate('e=>getComputedStyle(e).borderLeftWidth') == '0px'
            await expect(page.get_by_text('FFmpeg',exact=True)).to_have_count(1)
            await expect(page.get_by_text('FFprobe',exact=True)).to_have_count(1)
            await expect(page.get_by_text('FFmpeg 버전',exact=True)).to_have_count(0)
            await expect(page.get_by_text('v2.0.60',exact=True)).to_have_count(2) # current/latest only
            await expect(page.get_by_role('button',name='도구 다시 검사')).to_have_count(0)
            await expect(page.get_by_label('미디어 도구 상태')).to_have_attribute('aria-busy','false')
            await expect(page.locator(".info-settings.ui-panel")).to_have_count(1)
            await expect(page.locator(".info-settings .ui-panel")).to_have_count(0)
            license_value = page.locator('.info-license-value')
            await expect(license_value).to_contain_text('MIT')
            await expect(license_value.locator('.info-copyright')).to_contain_text('Copyright © 2026 ProofPage.')
            assert await license_value.evaluate('e=>getComputedStyle(e).textAlign') == 'right'
            assert await license_value.evaluate('e=>e.closest(".ui-info-row").contains(e.querySelector(".info-copyright"))')
            row_geometry=await page.locator('.media-tool-list .ui-info-row').evaluate_all('es => es.map(e => { const r=e.getBoundingClientRect(); return {height:r.height,bottom:r.bottom,cardBottom:e.closest(".info-section").getBoundingClientRect().bottom}; })')
            assert max(row['height'] for row in row_geometry)-min(row['height'] for row in row_geometry)<=2, row_geometry
            assert row_geometry[-1]['cardBottom']-row_geometry[-1]['bottom']<=2, row_geometry
            assert tool_calls > 0
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
        await nav.get_by_role('button',name='외관',exact=True).click()
        await info.click()
        await expect(page.get_by_text('도구 상태를 불러오지 못했습니다.',exact=True)).to_have_count(3)
        fail_tools=False
        await nav.get_by_role('button',name='외관',exact=True).click()
        await info.click()
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
    print('PASS: five settings tabs, automatic tool status without recheck button, update actions/modal/badge, failed requests/recovery, 320/768/1440px')

if __name__=='__main__':asyncio.run(main())
