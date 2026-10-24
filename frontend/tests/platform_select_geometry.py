"""Both platform pickers align identically; SOOP current viewers reach the card."""
import asyncio
import copy
import os
from pathlib import Path
from urllib.parse import urlparse
from playwright.async_api import async_playwright, expect
from browser_fixtures import FIX, mock

LABELS = {'chzzk':'치지직', 'youtube':'유튜브', 'soop':'숲', 'cime':'씨미'}
BASE = os.environ.get('PHROLOVA_TEST_URL', 'http://127.0.0.1:3001')
OUT = Path(os.environ.get('PHROLOVA_TEST_OUTPUT', '/tmp/phrolova-platform-select'))
GEOMETRY = '''e=>{const r=e.getBoundingClientRect(),d=e.children[0].getBoundingClientRect(),t=e.children[1].getBoundingClientRect(),a=e.children[2].getBoundingClientRect(),s=getComputedStyle(e);return {width:r.width,height:r.height,dot:d.left-r.left,label:t.left-r.left,arrow:r.right-a.right,font:s.fontSize,padding:s.paddingLeft,color:getComputedStyle(e.children[1]).color}}'''

async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    channel = copy.deepcopy(FIX['channels'][1])
    channel.update(platform='soop', composite_key='soop:alice', channel_id='alice',
        channel_name='숲 시청자 테스트', viewer_count=17916, is_live=True, title='시청자 수 확인',
        recording=None, last_error='', tags=[])
    async def route_api(route):
        path = urlparse(route.request.url).path
        if path == '/api/platforms/status':
            return await route.fulfill(json={key:{'enabled':True,'authenticated':True} for key in LABELS})
        if path == '/api/platforms/channels': return await route.fulfill(json=[channel])
        if path == '/api/vod/capabilities':
            return await route.fulfill(json={'sources':[{'id':k,'label':v} for k,v in LABELS.items()], 'prepare':True})
        return await mock(route)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context()
        await context.add_init_script('window.EventSource=class{close(){}}')
        await context.route('**/api/**', route_api)
        page = await context.new_page()
        errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        for width in (360,768,1440):
            await page.set_viewport_size({'width':width,'height':1000})
            await page.goto(BASE)
            await expect(page.locator('[data-channel-key="soop:alice"]')).to_contain_text('17,916')
            live = page.locator('.dashboard-add-channel .media-platform-trigger')
            metrics = {}
            for platform,label in LABELS.items():
                await live.click()
                await page.get_by_role('option',name=label,exact=True).click()
                await expect(live).to_have_text(label)
                metrics[platform] = await live.evaluate(GEOMETRY)
            await live.click()
            await page.keyboard.press('Escape')
            await expect(page.get_by_role('listbox')).to_have_count(0)
            await page.screenshot(path=str(OUT/f'live-{width}.png'),full_page=True)
            await page.goto(BASE+'/vod')
            download=page.get_by_role('combobox',name='다운로드 플랫폼')
            for platform,label in LABELS.items():
                await download.click()
                await page.get_by_role('option',name=label,exact=True).click()
                await expect(download).to_have_text(label)
                assert await download.evaluate(GEOMETRY) == metrics[platform], (width,platform,metrics[platform],await download.evaluate(GEOMETRY))
                await expect(download).to_be_focused()
            await download.focus()
            await page.keyboard.press('ArrowDown')
            await expect(page.get_by_role('listbox')).to_be_visible()
            await page.keyboard.press('Escape')
            await expect(page.get_by_role('listbox')).to_have_count(0)
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            await page.screenshot(path=str(OUT/f'download-{width}.png'),full_page=True)
        assert not errors,errors
        await browser.close()
    print('PASS: SOOP viewers, 4 platform labels/dot/text/arrow geometry, menu selection/keyboard/focus, 360/768/1440px')

if __name__=='__main__': asyncio.run(main())
