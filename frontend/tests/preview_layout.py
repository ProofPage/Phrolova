"""대표 콘텐츠 폭과 미리보기 상태/동일 video 보존을 실제 브라우저로 확인한다."""
import asyncio, json, os, subprocess, tempfile
from pathlib import Path
from playwright.async_api import async_playwright
from browser_fixtures import mock, FIX
BASE = os.environ.get('PHROLOVA_TEST_URL', 'http://localhost:3000')
OUT = Path(os.environ.get('PHROLOVA_TEST_OUTPUT', tempfile.gettempdir()+'/phrolova-preview-layout'))

async def geometry(page):
 return await page.evaluate('''()=>({viewport:innerWidth,main:document.querySelector('#main-content').clientWidth,content:document.querySelector('.page-content').clientWidth,overflow:document.documentElement.scrollWidth-innerWidth,mainOverflow:document.querySelector('#main-content').scrollWidth-document.querySelector('#main-content').clientWidth,cards:[...document.querySelectorAll('[data-channel-key]')].map(c=>({width:c.offsetWidth,height:c.offsetHeight})),players:[...document.querySelectorAll('.channel-preview-player:not([hidden])')].map(c=>({width:c.offsetWidth,height:c.offsetHeight})),panels:[...document.querySelectorAll('.channel-preview-status')].map(c=>({width:c.offsetWidth,height:c.offsetHeight})),downloadTitles:[...document.querySelectorAll('.download-title')].map(c=>getComputedStyle(c).fontSize)})''')

async def shot(page,name,focus=None):
 if focus: await focus.evaluate("e=>e.scrollIntoView({block:'start'})")
 await page.screenshot(path=str(OUT/(name+'.png')),animations='disabled')
 result=await geometry(page)
 assert result['overflow']==result['mainOverflow']==0,result
 centered=await page.locator('.channel-preview-status').evaluate_all('''panels=>panels.every(panel=>{
  const rect=panel.getBoundingClientRect(),style=getComputedStyle(panel);
  const children=[...panel.children].map(child=>child.getBoundingClientRect());
  return style.textAlign==='center'&&children.every(child=>Math.abs((child.left+child.right)/2-(rect.left+rect.right)/2)<1)&&Math.abs((children[0].top-rect.top)-(rect.bottom-children.at(-1).bottom))<1;
 })''')
 assert centered,(name,'Preview status group is not centered')
 print(name,json.dumps(result),flush=True)
 return result

async def expand(card):
 await card.locator('button[aria-expanded]:visible').filter(has=card.page.locator('svg.lucide-chevron-down')).first.click()

async def main():
 OUT.mkdir(parents=True,exist_ok=True)
 media=OUT/'media';media.mkdir(exist_ok=True)
 subprocess.run([os.environ.get('PHROLOVA_FFMPEG','ffmpeg'),'-y','-hide_banner','-loglevel','error','-f','lavfi','-i','smptebars=size=320x180:rate=10','-t','8','-c:v','libx264','-g','10','-f','hls','-hls_time','1','-hls_list_size','0',str(media/'preview.m3u8')],check=True)
 FIX['imports']=[]
 for c,name in zip(FIX['channels'],['게임 채널','라이브 스튜디오','라이브 채널']):
  c.update(channel_name=name,title='오늘의 라이브 · 함께 즐기는 게임' if c['is_live'] else '',category='게임',tags=['즐겨찾기'],last_error='')
 FIX['channels']=FIX['channels'][:2]
 for t,name in zip(FIX['tasks'],['주말 하이라이트','오늘의 라이브 다시보기','음악 플레이리스트','지난 방송 모음','완료된 다운로드','다시 확인할 영상']):
  t.update(title=name,output_path='/recordings/video.mp4',error_message='다운로드 서버 연결에 실패했습니다.' if t['state']=='error' else '')
 results=[]
 async with async_playwright() as p:
  browser=await p.chromium.launch(executable_path=os.environ.get("PHROLOVA_CHROMIUM_EXECUTABLE"))
  for w,h in [(320,568),(390,844),(820,1180),(1024,768),(1440,900)]:
   if os.environ.get('PHROLOVA_PREVIEW_WIDTHS') and str(w) not in os.environ['PHROLOVA_PREVIEW_WIDTHS'].split(','):continue
   ctx=await browser.new_context(viewport={'width':w,'height':h},is_mobile=w<1024,has_touch=w<1024)
   await ctx.add_init_script("localStorage.setItem('dashboardViewMode','grid');window.EventSource=class{close(){}}")
   await ctx.route('**/api/**',mock)
   await ctx.route('https://fonts.googleapis.com/**',lambda r:r.abort());await ctx.route('https://fonts.gstatic.com/**',lambda r:r.abort())
   page=await ctx.new_page();await page.goto(BASE);cards=page.locator('[data-channel-key]');await cards.first.wait_for()
   results.append(await shot(page,f'{w}-compact',page.locator('.dashboard-channel-grid')))
   await expand(cards.first)
   assert await cards.first.locator('video').count()==0
   off=await shot(page,f'{w}-offline',cards.first)
   assert abs(off['panels'][0]['width']/off['panels'][0]['height']-16/9)<.02,off
   await expand(cards.nth(1));await cards.nth(1).get_by_role('button',name='다시 시도',exact=True).wait_for()
   unavail=await shot(page,f'{w}-unavailable',cards.nth(1));assert all(abs(x['width']/x['height']-16/9)<.02 for x in unavail['panels']),unavail
   resolver=[];gate=asyncio.Event()
   if w!=390:gate.set()
   async def resolve(route):
    resolver.append(route.request.url);await gate.wait();await route.fulfill(json={'url':BASE+'/preview-test/preview.m3u8'})
   async def stream(route):
    file=media/route.request.url.rsplit('/',1)[-1]
    await route.fulfill(path=file,content_type='application/vnd.apple.mpegurl' if file.suffix=='.m3u8' else 'video/mp2t')
   await page.route('**/api/stream/preview/**',resolve);await page.route('**/preview-test/**',stream)
   await cards.nth(1).get_by_role('button',name='다시 시도',exact=True).click()
   if w==390:
    await cards.nth(1).get_by_text('미리보기를 불러오는 중',exact=True).wait_for();await shot(page,'390-loading',cards.nth(1));gate.set()
   await page.wait_for_function('document.querySelector("video")?.readyState >= 2')
   await page.locator('.channel-preview-player').wait_for(state='visible')
   active=await shot(page,f'{w}-active',cards.nth(1))
   assert abs(active['players'][0]['width']/active['players'][0]['height']-16/9)<.02,active
   assert await page.locator('.channel-preview-player').evaluate('(p)=>Math.abs(p.getBoundingClientRect().width-p.closest(".channel-live-preview").getBoundingClientRect().width)<1')
   video=page.locator('video');await video.evaluate('(v)=>window.retainedVideo=v');count=len(resolver)
   if w==1440:
    for width,height in [(820,1180),(1024,768),(390,844),(1440,900)]:
     await page.set_viewport_size({'width':width,'height':height});await page.wait_for_timeout(50)
     assert await video.evaluate('(v)=>v===window.retainedVideo') and len(resolver)==count
    await cards.nth(1).locator('.channel-move-up').click();assert await video.evaluate('(v)=>v===window.retainedVideo') and len(resolver)==count
   if not os.environ.get('PHROLOVA_PREVIEW_ONLY'):
    await page.goto(BASE+'/vod');await page.locator('.download-row').first.wait_for()
    await shot(page,f'{w}-downloads')
    if w==820:
     for i,state in enumerate(['queued','downloading','paused','cancelling','completed','error']):
      await shot(page,f'820-download-{state}',page.locator('.download-row').nth(i))
   await ctx.close()
  await browser.close()
 (OUT/'geometry.json').write_text(json.dumps(results,indent=2))
 print('Representative screenshots and HLS resize/reorder identity checks passed.',flush=True)
if __name__=='__main__':asyncio.run(main())
