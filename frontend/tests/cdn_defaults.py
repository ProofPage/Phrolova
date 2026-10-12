"""Akamai defaults, exact CDN labels and explicit Naver/Akamai save restoration."""
import asyncio, copy, os
from pathlib import Path
from urllib.parse import urlparse
from playwright.async_api import async_playwright, expect
from browser_fixtures import FIX, mock
BASE=os.environ.get('PHROLOVA_TEST_URL','http://127.0.0.1:3001')
OUT=Path(os.environ['PHROLOVA_TEST_OUTPUT'])
async def main():
    settings=copy.deepcopy(FIX['settings'])
    settings.pop('chzzk_live_cdn',None);settings.pop('chzzk_vod_cdn',None)
    calls=[]
    async def route_api(route):
        path=urlparse(route.request.url).path
        if path=='/api/settings':return await route.fulfill(json=settings)
        if path in ('/api/settings/live','/api/settings/vod'):
            data=route.request.post_data_json;calls.append((path,data));settings.update(data)
            return await route.fulfill(json={'settings':settings})
        return await mock(route)
    async with async_playwright() as p:
        browser=await p.chromium.launch();context=await browser.new_context(viewport={'width':1440,'height':1000})
        await context.add_init_script('window.EventSource=class{close(){}}')
        await context.route('**/api/**',route_api);page=await context.new_page();errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        await page.goto(BASE+'/settings')
        live=page.get_by_role('combobox',name='치지직 라이브 CDN',exact=True)
        vod=page.get_by_role('combobox',name='치지직 다운로드 CDN',exact=True)
        for select in (live,vod):
            await expect(select).to_have_value('akamai')
            assert await select.locator('option').all_text_contents()==['Naver CDN','Akamai CDN']
        for selection in ('default','akamai'):
            await live.select_option(selection);await vod.select_option(selection)
            await page.get_by_role('button',name='라이브 설정 저장',exact=True).click()
            await expect(vod).to_have_value(selection)
            await page.get_by_role('button',name='영상 다운로드 설정 저장',exact=True).click()
            await expect(page.get_by_role('button',name='영상 다운로드 설정 저장',exact=True)).to_be_disabled()
            await page.reload();await expect(live).to_have_value(selection);await expect(vod).to_have_value(selection)
            assert any(path.endswith('/live') and data['chzzk_live_cdn']==selection for path,data in calls)
            assert any(path.endswith('/vod') and data['chzzk_vod_cdn']==selection for path,data in calls)
        OUT.mkdir(parents=True,exist_ok=True)
        await page.screenshot(path=str(OUT/'akamai-default-settings.png'),full_page=True)
        assert not errors,errors
        await browser.close()
    print('PASS: Akamai fallback defaults, exact Naver CDN/Akamai CDN labels, independent save and reload for both selections')
if __name__=='__main__':asyncio.run(main())
