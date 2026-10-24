"""All disclosure combinations preserve order and avoid tall empty grid cells."""
import asyncio
import copy
import os
from pathlib import Path
from urllib.parse import urlparse
from playwright.async_api import async_playwright, expect
from browser_fixtures import FIX, mock

BASE = os.environ.get('PHROLOVA_TEST_URL', 'http://127.0.0.1:3001')
OUT = Path(os.environ['PHROLOVA_TEST_OUTPUT'])

async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    channels = []
    for i in range(4):
        c = copy.deepcopy(FIX['channels'][0])
        c.update(composite_key=f'chzzk:expand-{i}', channel_id=f'expand-{i}', channel_name=f'채널 {i}',
                 title=None, is_live=False, recording=None, postprocess=None, last_error=None, category=None, tags=[])
        if i == 0:
            c.update(is_live=True,title='방송 제목',viewer_count=10808,tags=['방송','즐겨찾기'])
        if i == 1:
            c.update(is_live=True,title='긴 방송 제목 ' * 20,viewer_count=7681,last_error='이 방송에 접근하려면 인증 설정을 확인하세요. '+('인증 오류 ' * 8))
        if i in (2,3):
            c['postprocess']=dict(id=f'layout-{i}',state='converting' if i==2 else 'completed',target_format='mkv',progress=42.7 if i==2 else 100,
                source_available=True,output_available=i==3,can_open=i==3,can_inspect=i==3,can_retry=i==3,diagnostics={})
        channels.append(c)
    async def route(route):
        if urlparse(route.request.url).path == '/api/platforms/channels':
            return await route.fulfill(json=channels)
        return await mock(route)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context()
        await context.add_init_script("localStorage.setItem('dashboardViewMode','grid');window.EventSource=class{close(){}}")
        await context.route('**/api/**', route)
        page = await context.new_page()
        for width in (320, 1440, 1920):
            await page.set_viewport_size({'width':width,'height':1000})
            await page.goto(BASE)
            await expect(page.locator('[data-channel-key]')).to_have_count(4)
            await page.locator('.dashboard-channel-grid.is-measured').wait_for()
            previous = 0
            for pattern in range(16):
                for i in range(4):
                    if bool(pattern & (1 << i)) != bool(previous & (1 << i)):
                        await page.locator(f'[data-channel-key="chzzk:expand-{i}"] .recording-detail-action').click()
                previous = pattern
                await page.wait_for_timeout(100)
                geometry = await page.evaluate("""()=>{
                    const grid=document.querySelector('.dashboard-channel-grid');
                    return {width:grid.clientWidth,overflow:document.documentElement.scrollWidth-innerWidth,
                        cards:[...grid.querySelectorAll(':scope > [data-channel-key]')].map(e=>{const r=e.getBoundingClientRect();return {key:e.dataset.channelKey,x:r.x,y:r.y,bottom:r.bottom,width:r.width,selected:e.classList.contains('is-selected'),metrics:e.querySelector('.recording-metrics').getBoundingClientRect().y,controls:e.querySelector('.recording-channel-controls').getBoundingClientRect().y}})};
                }""")
                assert geometry['overflow'] == 0, (width,pattern,geometry)
                cards = geometry['cards']
                assert [c['key'] for c in cards] == [c['composite_key'] for c in channels]
                for i, card in enumerate(cards):
                    expected_width = geometry['width'] if width == 320 else (geometry['width']-12)/2
                    assert abs(card['width']-expected_width) < 2,(width,pattern,card)
                    if width != 320 and i % 2:
                        left=cards[i-1]
                        assert abs(card['y']-left['y'])<1,(width,pattern,'row baseline',cards)
                        assert abs(card['metrics']-left['metrics'])<1,(width,pattern,'metrics baseline',cards)
                        assert abs(card['controls']-left['controls'])<1,(width,pattern,'controls baseline',cards)
                    if i >= (1 if width == 320 else 2):
                        assert card['y'] >= cards[i-(1 if width == 320 else 2)]['bottom']+10,(width,pattern,'visual source order',cards)
                panels = await page.locator('.recording-detail-panel:not([hidden])').evaluate_all("es=>es.map(e=>{const r=e.getBoundingClientRect();return {id:e.id,y:r.y,width:r.width,bottom:r.bottom,preview:e.querySelector('.channel-preview-stage').getBoundingClientRect().toJSON()}})")
                assert len(panels)==pattern.bit_count()
                # A panel close returns keyboard focus to the same channel disclosure.
                if pattern==15:
                    panel=page.locator('.recording-detail-panel:not([hidden])').last
                    panel_id=await panel.get_attribute('id')
                    await panel.get_by_role('button',name='상세 접기',exact=True).click()
                    await expect(page.locator(f'button[aria-controls="{panel_id}"]')).to_be_focused()
                    await page.locator(f'button[aria-controls="{panel_id}"]').click()
                for panel in panels:
                    i=int(panel['id'].rsplit('-',1)[-1])
                    end=i if width==320 else i//2*2+1
                    assert panel['y'] >= max(c['bottom'] for c in cards[end-(0 if width==320 else 1):end+1])+10,(width,pattern,panel,cards)
                    if end+1<len(cards):
                        assert cards[end+1]['y']>=panel['bottom']+10,(width,pattern,panel,cards)
                    assert abs(panel['width']-geometry['width'])<2
                    assert abs(panel['preview']['height']-panel['preview']['width']*9/16)<1.5
                if pattern == 2 and width == 1440:
                    await page.screenshot(path=str(OUT/'one-expanded.png'), full_page=True)
        await browser.close()
    print('PASS: 48 expansion combinations, fixed visual channel order, aligned summary rows and full-width 16:9 detail panels without horizontal overflow')

if __name__ == '__main__':
    asyncio.run(main())
