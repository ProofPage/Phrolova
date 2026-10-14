"""터치 환경의 표시·조작을 검증한다. playwright install chromium webkit으로 브라우저를 준비한다."""
import asyncio
import json
import os
from pathlib import Path
from playwright.async_api import async_playwright, expect
from browser_fixtures import mock

BASE = os.environ.get('PHROLOVA_TEST_URL','http://127.0.0.1:3002')
OUT = Path(os.environ.get('PHROLOVA_TEST_OUTPUT','/tmp/phrolova-mobile-touch'))
SIZES = ((320,740),(390,844),(430,932),(768,1024),(844,390),(1024,768))

async def verify(page, label):
    data = await page.evaluate('''()=>{
      const visible=e=>!!e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
      return {page:document.documentElement.scrollWidth-innerWidth,
        main:document.querySelector('#main-content').scrollWidth-document.querySelector('#main-content').clientWidth,
        inputs:[...document.querySelectorAll('input.ui-input,textarea.ui-input,select.ui-input')].filter(visible).map(e=>({
          name:e.id||e.getAttribute('aria-label')||e.placeholder,font:parseFloat(getComputedStyle(e).fontSize),height:e.getBoundingClientRect().height
        })).filter(e=>e.font<16||e.height<43.5)};
    }''')
    assert data['page'] == data['main'] == 0, (label,data)
    assert not data['inputs'], (label,data)
    return data

async def main():
    OUT.mkdir(parents=True,exist_ok=True)
    results=[]
    async with async_playwright() as p:
        for engine in os.environ.get('PHROLOVA_TEST_ENGINES','chromium,webkit').split(','):
            browser=await getattr(p,engine).launch(headless=True)
            for width,height in SIZES:
                context=await browser.new_context(viewport={'width':width,'height':height},is_mobile=True,has_touch=True,device_scale_factor=2)
                await context.add_init_script("window.EventSource=class{close(){}};localStorage.setItem('phrolova-language','ko-KR')")
                await context.route('**/api/**',mock)
                page=await context.new_page()
                errors=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                for route in ('/','/vod','/stats','/system-logs','/settings'):
                    await page.goto(BASE+route)
                    await expect(page.locator('.product-page')).to_be_visible()
                    if route=='/': await expect(page.locator('.media-add-form input')).to_be_visible()
                    if route=='/vod': await expect(page.locator('#vod-url')).to_be_visible()
                    if route=='/system-logs': await expect(page.locator('.logs-level-summary')).to_be_visible()
                    if route=='/settings': await expect(page.locator('.settings-tabs button').first).to_be_visible()
                    results.append(dict(engine=engine,width=width,height=height,route=route,**await verify(page,(engine,width,route))))
                    if width==390:
                        await page.screenshot(path=str(OUT/f'{engine}-{route.strip("/") or "live"}.png'),full_page=True)

                # 태블릿에서도 모든 설정 탭의 편집 필드가 충분한 입력 글자 크기를 유지한다.
                tabs=page.locator('.settings-tabs button')
                assert await tabs.count()==5
                for tab in await tabs.all():
                    await tab.tap()
                    await verify(page,(engine,width,await tab.inner_text()))

                await page.goto(BASE+'/vod')
                await page.locator('.media-platform-trigger').tap()
                options=page.get_by_role('listbox').get_by_role('option')
                await expect(options.first).to_be_visible()
                sizes=await options.evaluate_all('es=>es.map(e=>e.getBoundingClientRect().height)')
                assert sizes and all(h>=43.5 for h in sizes),(engine,width,'platform options',sizes)
                await options.first.tap()
                if width<1024:
                    await page.locator('.sidebar-mobile-trigger').tap()
                    drawer=page.locator('#mobile-sidebar')
                    await expect(drawer).to_be_visible()
                    await drawer.locator('a[href="/system-logs"]').tap()
                    await expect(drawer).to_have_count(0)
                    await expect(page.locator('.app-main')).not_to_have_attribute('inert','')
                else:
                    await page.goto(BASE+'/system-logs')
                await expect(page.locator('.logs-level-summary')).to_be_visible()
                if await page.locator('.logs-back button').is_visible():
                    await page.locator('.logs-back button').tap()
                    await expect(page.locator('.logs-file-panel')).to_be_visible()
                    await page.locator('.logs-file-option').first.tap()
                    await expect(page.locator('.logs-content-panel')).to_be_visible()
                actions=page.locator('.logs-actions')
                if width<500:
                    grid=await actions.evaluate('e=>getComputedStyle(e).gridTemplateColumns.split(" ").length')
                    assert grid==2,(engine,width,'logs action columns',grid)
                await page.locator('.page-actions button').tap()
                dialog=page.get_by_role('dialog')
                await expect(dialog).to_be_visible()
                await page.set_viewport_size({'width':width,'height':300})
                bounds=await dialog.bounding_box()
                assert bounds and bounds['y']>=0 and bounds['y']+bounds['height']<=301,(engine,width,bounds)
                await dialog.get_by_role('button',name='취소',exact=True).tap()
                assert not errors,(engine,width,errors)
                await context.close()
            await browser.close()
    (OUT/'geometry.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'PASS: {len(results)} mobile page states; 16px inputs, 44px platform options, settings tabs, drawer navigation, log file switching and short-height dialogs')

if __name__=='__main__':asyncio.run(main())
