"""Twenty viewport/mode combinations and HLS failure/recovery with real video segments."""
import asyncio, copy, json, os, shutil, subprocess, tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse
from playwright.async_api import async_playwright, expect
from browser_fixtures import FIX, mock
BASE = os.environ.get('PHROLOVA_TEST_URL', 'http://127.0.0.1:3001')
OUT = Path(os.environ.get('PHROLOVA_TEST_OUTPUT', tempfile.gettempdir()+'/preview-platform-regressions'))
WIDTHS = (320,375,430,640,768,1024,1280,1440,1920,2560)

async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    media = OUT/'media'
    media.mkdir(exist_ok=True)
    bundled = Path(__file__).resolve().parents[4]/'work/media-tools/ffmpeg-9.0.2-essentials_build/bin/ffmpeg.exe'
    ffmpeg = os.environ.get('PHROLOVA_FFMPEG') or shutil.which('ffmpeg') or str(bundled)
    subprocess.run([ffmpeg,'-y','-v','error','-f','lavfi','-i','testsrc2=size=640x360:rate=10','-t','20','-c:v','libx264','-g','10','-f','hls','-hls_time','1','-hls_list_size','0',str(media/'video.m3u8')],check=True)
    channels = []
    for platform in ('chzzk','soop','cime'):
        item = copy.deepcopy(FIX['channels'][1])
        item.update(platform=platform,composite_key=platform+':audit',channel_id='audit',channel_name=platform,
            title='긴 방송 제목 '*20,is_live=True,tags=[],last_error='',postprocess=None,profile_image_url='',recording_quality='best',
            recording=dict(state='recording',is_recording=True,has_data=True,file_size_bytes=1000000,duration_seconds=60,download_speed=.5,bitrate=4000,
                output_path='/recordings/한글 긴 파일 경로 '+('제목'*60)+'.ts',start_time='2026-10-11T18:00:00'))
        channels.append(item)
    results=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch()
        for mode in ('grid','list'):
            for width in WIDTHS:
                context=await browser.new_context(viewport={'width':width,'height':1000})
                await context.add_init_script(f"localStorage.setItem('dashboardViewMode','{mode}');window.EventSource=class{{close(){{}}}}")
                calls=[]; failures={'cime':True}; errors=[]
                async def api_route(route):
                    path=unquote(urlparse(route.request.url).path)
                    if path=='/api/platforms/channels':return await route.fulfill(json=channels)
                    if '/preview/' in path:
                        platform=path.split('/')[-1].split(':')[0];calls.append(platform)
                        if failures.get(platform):return await route.fulfill(status=503,json={'detail':'일시적인 연결 오류'})
                        return await route.fulfill(json={'url':BASE+'/platform-media/video.m3u8'})
                    return await mock(route)
                await context.route('**/api/**',api_route)
                async def media_route(route):
                    path=media/Path(urlparse(route.request.url).path).name
                    return await route.fulfill(body=path.read_bytes(),content_type='application/vnd.apple.mpegurl' if path.suffix=='.m3u8' else 'video/mp2t')
                await context.route('**/platform-media/**',media_route)
                page=await context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
                await page.goto(BASE)
                cards=page.locator('[data-channel-key]');await expect(cards).to_have_count(3)
                for platform in ('soop','cime'):
                    card=page.locator(f'[data-channel-key="{platform}:audit"]')
                    await card.locator('button[aria-expanded]:visible').first.click()
                await expect(page.locator('[data-channel-key="cime:audit"] .channel-preview-status')).to_be_visible()
                await page.wait_for_function("""document.querySelector('[data-channel-key="soop:audit"] video')?.videoWidth > 0""")
                geometry=await cards.evaluate_all('''cards=>cards.map(c=>{const s=c.querySelector('.channel-preview-stage'),r=s?.getBoundingClientRect();return {key:c.dataset.channelKey,height:c.offsetHeight,stage:r?{width:r.width,height:r.height}:null}})''')
                for item in geometry:
                    if item['stage']:assert abs(item['stage']['width']*9/16-item['stage']['height'])<2,(width,mode,item)
                assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(width,mode)
                await page.screenshot(path=str(OUT/f'{mode}-{width}-error.png'),full_page=True)
                if width==1440:
                    failed_card=page.locator('[data-channel-key="cime:audit"]')
                    before=await failed_card.evaluate('c=>c.offsetHeight')
                    failures['cime']=False
                    # Transient resolver failure retries automatically without a click.
                    await page.wait_for_function("""document.querySelector('[data-channel-key="cime:audit"] video')?.videoWidth > 0""",timeout=12000)
                    await expect(failed_card.locator('.channel-preview-status')).to_have_count(0)
                    assert abs(await failed_card.evaluate('c=>c.offsetHeight')-before)<2
                    await page.screenshot(path=str(OUT/f'{mode}-{width}-recovered.png'),full_page=True)
                    assert calls.count('cime')<=3,calls
                assert not errors,errors
                results.append({'width':width,'mode':mode,'cards':geometry})
                await context.close()
        await browser.close()
    (OUT/'geometry.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    print('20 viewport/mode combinations and automatic HLS recovery passed.')
if __name__=='__main__':asyncio.run(main())
