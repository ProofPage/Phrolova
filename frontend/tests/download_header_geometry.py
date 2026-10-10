"""Real Chromium geometry regression for shared download headers and image slots.

API fixtures isolate layout from remote media services. Image success, missing
URLs, network failures and an explicitly delayed response use real browser loads.
"""
import asyncio
import copy
import json
import os
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright, expect
from browser_fixtures import FIX, mock

BASE = os.environ.get('PHROLOVA_TEST_URL', 'http://localhost:3000')
OUT = Path(os.environ.get('PHROLOVA_TEST_OUTPUT', '/tmp/phrolova-download-thumbnail'))
WIDTHS = (360, 390, 768, 1024, 1440, 1920)
SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540"><rect width="960" height="540" fill="#355680"/><text x="480" y="270" text-anchor="middle" fill="white">Thumbnail fixture</text></svg>'
GEOMETRY = """e => {
    const card=e.getBoundingClientRect();
    const rect=s=>{const r=e.querySelector(s).getBoundingClientRect();return {
        left:r.left-card.left, top:r.top-card.top, right:card.right-r.right,
        width:r.width, height:r.height, bottom:r.bottom-card.top};};
    return {cardWidth:card.width, header:rect('.download-task-header'),
        thumbnail:rect('.download-thumbnail'), title:rect('.download-title'),
        channel:rect('.download-task-meta'), media:rect('.download-media-meta'),
        management:rect('.download-task-management'), status:rect('.download-task-status'),
        buttons:[...e.querySelectorAll('.download-task-management > button')].map(b=>{
            const r=b.getBoundingClientRect();return {top:r.top-card.top,width:r.width,height:r.height,center:r.top+r.height/2-card.top};
        })};
}"""


def make_task(identifier, state, phase, thumbnail=None):
    task = copy.deepcopy(FIX['tasks'][0])
    task.update(task_id=identifier, url=f'https://chzzk.naver.com/video/{identifier}',
                title='영상 제목', state=state, phase=phase, prepared=True,
                quality='1080p', progress=68.4, downloaded_bytes=3_000_000_000,
                total_bytes=4_000_000_000, download_speed=12.5, eta_seconds=120,
                started_at=None, completed_at=None, output_path=None,
                error_message=None, inspection_state='pending', warning_message=None,
                download_warning_message=None, retry_task_id=None, cdn='akamai', cdn_applied=True,
                metadata={'id':identifier, 'duration':7370, 'uploader':'채널',
                          'thumbnail':thumbnail,
                          'qualities':[{'value':'1080p','label':'1080p'}, {'value':'720p','label':'720p'}]})
    if state == 'completed':
        task.update(completed_at='2026-10-10T10:00:00Z', file_size=4_000_000_000,
                    output_path='/영상/테스트 [1080p].mp4', inspection_state='failed',
                    inspection_message='파일 검사 시간이 초과되었습니다.')
    if state == 'error':
        task['error_message'] = 'Connection interrupted diagnostic'
    return task


def close(actual, expected, label, tolerance=0.6):
    assert abs(actual-expected) <= tolerance, (label, actual, expected)


def same_header(actual, expected, label):
    for element in ('header', 'thumbnail', 'title', 'channel', 'media'):
        for dimension in ('left', 'top', 'width', 'height'):
            close(actual[element][dimension], expected[element][dimension], (label,element,dimension))
    for dimension in ('top', 'right', 'width', 'height'):
        close(actual['management'][dimension], expected['management'][dimension], (label,'management',dimension))
    # Body height is state-specific; its first status row must share the header baseline.
    for dimension in ('left', 'top'):
        close(actual['status'][dimension], expected['status'][dimension], (label,'status',dimension))


async def placeholder_centered(card):
    return await card.evaluate("""e=>{
        const slot=e.querySelector('.download-thumbnail').getBoundingClientRect();
        const placeholder=e.querySelector('.download-thumbnail-placeholder');
        const range=document.createRange();range.selectNodeContents(placeholder);
        const text=range.getBoundingClientRect();
        return !placeholder.hidden && Math.abs((text.left+text.right-slot.left-slot.right)/2)<1
            && Math.abs((text.top+text.bottom-slot.top-slot.bottom)/2)<1.5;
    }""")


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    delayed_release = asyncio.Event()
    tasks = [make_task('ready','idle','ready',BASE+'/__thumbnail_test__/real.svg'),
             make_task('active','downloading','downloading'),
             make_task('paused','paused','downloading',BASE+'/__thumbnail_test__/broken.svg'),
             make_task('complete','completed','completed',BASE+'/__thumbnail_test__/delayed.svg'),
             make_task('failed','error','error',BASE+'/__thumbnail_test__/real.svg')]
    measurements=[]

    async def route_api(route):
        path = urlparse(route.request.url).path
        if path == '/api/vod/status':
            return await route.fulfill(json={'tasks':tasks,'imports':[],'active_count':1})
        if path == '/api/vod/capabilities':
            return await route.fulfill(json={'sources':[{'id':'chzzk','label':'치지직'}],
                                            'prepare':True,'pause':True,'file_open':True})
        return await mock(route)

    async def route_image(route):
        path = urlparse(route.request.url).path
        if path.endswith('/broken.svg'):
            return await route.fulfill(status=404, content_type='text/plain', body='Missing thumbnail')
        if path.endswith('/delayed.svg'):
            await delayed_release.wait()
        return await route.fulfill(content_type='image/svg+xml',body=SVG)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        context = await browser.new_context(viewport={'width':1440,'height':1000})
        await context.add_init_script('window.EventSource=class{close(){}}')
        await context.route('**/api/**', route_api)
        await context.route('**/__thumbnail_test__/**', route_image)
        page = await context.new_page()
        errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        try:
            await page.goto(BASE+'/vod',wait_until='domcontentloaded')
            await expect(page.locator('[data-task-id]')).to_have_count(5)
            await page.get_by_role('button',name='목록으로 보기',exact=True).click()
            complete = page.locator('[data-task-id="complete"]')
            await expect(complete.locator('.download-thumbnail')).to_have_attribute('data-image-state','loading')
            loading = await complete.evaluate(GEOMETRY)
            assert await placeholder_centered(complete), 'Loading placeholder is not centered'
            delayed_release.set()
            await expect(complete.locator('.download-thumbnail')).to_have_attribute('data-image-state','loaded')
            same_header(await complete.evaluate(GEOMETRY),loading,'delayed image load')
            await expect(page.locator('[data-task-id="ready"] .download-thumbnail')).to_have_attribute('data-image-state','loaded')
            await expect(page.locator('[data-task-id="paused"] .download-thumbnail')).to_have_attribute('data-image-state','failed')
            assert await placeholder_centered(page.locator('[data-task-id="paused"]')), 'Broken image placeholder is not centered'
            assert await placeholder_centered(page.locator('[data-task-id="active"]')), 'Missing image placeholder is not centered'

            # Long title/name should only truncate, never change the three header rows.
            short = await page.locator('[data-task-id="ready"]').evaluate(GEOMETRY)
            for task in tasks:
                task['title']='긴 영상 제목 ' * 30
                task['metadata']['uploader']='매우 긴 채널 이름 ' * 20
            await expect(page.locator('[data-task-id="ready"] .download-title')).to_have_attribute('title',tasks[0]['title'],timeout=6000)
            same_header(await page.locator('[data-task-id="ready"]').evaluate(GEOMETRY),short,'long text')

            for width in WIDTHS:
                await page.set_viewport_size({'width':width,'height':1000})
                for mode,label in (('grid','카드로 보기'),('list','목록으로 보기')):
                    await page.get_by_role('button',name=label,exact=True).click()
                    geometry = {}
                    for task in tasks:
                        card = page.locator(f'[data-task-id="{task["task_id"]}"]')
                        value = await card.evaluate(GEOMETRY)
                        geometry[task['task_id']] = value
                        close(value['thumbnail']['width']/value['thumbnail']['height'],16/9,(width,mode,'aspect'),0.001)
                        expected_width = 64 if value['cardWidth']-2 <= 500 else 96
                        close(value['thumbnail']['width'],expected_width,(width,mode,'thumbnail width'))
                        close(value['title']['top'],value['thumbnail']['top'],(width,mode,'title top'))
                        close(value['management']['top'],value['thumbnail']['top'],(width,mode,'management top'))
                        close(value['title']['left']-value['thumbnail']['left']-value['thumbnail']['width'],12,(width,mode,'thumbnail gap'))
                        close(value['channel']['left'],value['title']['left'],(width,mode,'channel left'))
                        close(value['media']['left'],value['title']['left'],(width,mode,'media left'))
                        close(value['channel']['top']-value['title']['bottom'],4,(width,mode,'channel gap'))
                        close(value['media']['top']-value['channel']['bottom'],4,(width,mode,'media gap'))
                        close(value['header']['height'],62,(width,mode,'header height'))
                        close(value['status']['top']-value['header']['bottom'],10,(width,mode,'status gap'))
                        assert len(value['buttons']) == 3, (width,mode,'management button count')
                        for button in value['buttons']:
                            close(button['center'],value['buttons'][0]['center'],(width,mode,'button center'))
                            assert button['width'] >= (44 if width < 640 else 30), (width,mode,'button width')
                            assert button['height'] >= (44 if width < 640 else 32), (width,mode,'button height')
                        assert await card.evaluate("""e=>{
                            const title=e.querySelector('.download-title').getBoundingClientRect();
                            const group=e.querySelector('.download-task-management').getBoundingClientRect();
                            const thumbnail=e.querySelector('.download-thumbnail').getBoundingClientRect();
                            const uploader=e.querySelector('.download-uploader').getBoundingClientRect();
                            const badge=e.querySelector('.platform-badge').getBoundingClientRect();
                            return title.right<=group.left && title.left>=thumbnail.right && badge.left>=uploader.right
                                && Math.abs(badge.left-uploader.right-6)<.5
                                && Math.abs((badge.top+badge.bottom-uploader.top-uploader.bottom)/2)<1;
                        }"""), (width,mode,'overlap/badge')
                    for identifier,value in geometry.items():
                        same_header(value,geometry['ready'],(width,mode,identifier,'state geometry'))
                    assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'), (width,mode,'page overflow')
                    assert await page.locator('.downloads-page').evaluate('e=>e.scrollWidth<=e.clientWidth'), (width,mode,'page content overflow')
                    measurements.append({'width':width,'mode':mode,'cards':geometry})
                    await page.screenshot(path=str(OUT/f'geometry-{mode}-{width}.png'),full_page=True)

            # Recover the same failed slot when a later metadata response has a valid URL.
            await page.set_viewport_size({'width':1440,'height':1000})
            await page.get_by_role('button',name='목록으로 보기',exact=True).click()
            paused = page.locator('[data-task-id="paused"]')
            broken = await paused.evaluate(GEOMETRY)
            tasks[2]['metadata']['thumbnail']=BASE+'/__thumbnail_test__/recovered.svg'
            await expect(paused.locator('.download-thumbnail')).to_have_attribute('data-image-state','loaded',timeout=6000)
            same_header(await paused.evaluate(GEOMETRY),broken,'failed image src recovery')
            assert await paused.locator('.download-thumbnail-image').evaluate('e=>e.naturalWidth===960 && getComputedStyle(e).opacity==="1"')

            # A real server-driven state transition must preserve identity/header coordinates.
            ready = page.locator('[data-task-id="ready"]')
            original = await ready.evaluate(GEOMETRY)
            await ready.evaluate('e=>e.dataset.geometryIdentity="same"')
            tasks[0].update(state='downloading',phase='downloading',started_at='2026-10-10T10:00:00Z')
            await expect(ready.get_by_role('button',name='일시정지',exact=True)).to_be_visible(timeout=6000)
            same_header(await ready.evaluate(GEOMETRY),original,'queued to downloading')
            tasks[0].update(state='completed',phase='completed',completed_at='2026-10-10T11:00:00Z',
                            output_path='/영상/복구 완료.mp4',file_size=4_000_000_000,inspection_state='passed')
            await expect(ready.get_by_role('link',name='파일 열기')).to_be_visible(timeout=6000)
            same_header(await ready.evaluate(GEOMETRY),original,'downloading to completed')
            assert await ready.get_attribute('data-geometry-identity') == 'same'
            tasks[0]['metadata'].update(thumbnail=None,uploader=None,duration=None)
            tasks[0]['media_duration']=None
            tasks[0]['cdn_applied']=False
            await expect(ready.locator('.download-uploader')).to_have_text('채널 정보 확인 중',timeout=6000)
            same_header(await ready.evaluate(GEOMETRY),original,'missing metadata rows')
            assert await placeholder_centered(ready)
            assert not errors, errors
            (OUT/'header-geometry.json').write_text(json.dumps(measurements,ensure_ascii=False,indent=2),encoding='utf-8')
            print('Download header geometry PASS: five states, real/missing/broken/delayed thumbnails, centered fallback, image load/source recovery, long/missing metadata, queued→active→complete, six widths x grid/list; no header shift or page overflow')
        except Exception:
            await page.screenshot(path=str(OUT/'geometry-failure.png'),full_page=True)
            raise
        finally:
            delayed_release.set()
            await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
