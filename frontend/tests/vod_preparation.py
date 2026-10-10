"""Browser UI tests using mock API; never download an external broadcast."""
import asyncio,copy,os,tempfile
from pathlib import Path
from urllib.parse import urlparse
from playwright.async_api import async_playwright
from browser_fixtures import FIX,mock
BASE=os.environ.get('PHROLOVA_TEST_URL','http://127.0.0.1:3000')
OUT=Path(os.environ.get('PHROLOVA_TEST_OUTPUT',tempfile.gettempdir()+'/phrolova-vod-ui'));OUT.mkdir(exist_ok=True)

async def check(browser,width):
 tasks=[];requests=[];errors=[]
 context=await browser.new_context(viewport={'width':width,'height':900},is_mobile=width<500,has_touch=width<500)
 await context.add_init_script("if(!localStorage.getItem('phrolova-language'))localStorage.setItem('phrolova-language','ko');window.EventSource=class{close(){}}")
 async def api(route):
  path=urlparse(route.request.url).path;data=route.request.post_data_json if route.request.post_data else {};method=route.request.method
  requests.append((path,method,data))
  if path=='/api/vod/status':return await route.fulfill(json={'tasks':tasks,'active_count':sum(t['state']=='downloading' for t in tasks),'imports':[]})
  if path=='/api/vod/prepare':
   results=[]
   for url in data['urls']:
    existing=next((task for task in tasks if task['url']==url),None)
    if existing:results.append({'url':url,'task_id':existing['task_id'],'duplicate':True});continue
    id=url.rsplit('/',1)[-1];task=copy.deepcopy(FIX['tasks'][0]);task.update(task_id=id,url=url,title='Test VOD '+id,state='idle',phase='ready',prepared=True,started_at=None,quality='1080p',error_message=None,progress=0,cdn='default',metadata={'id':id,'duration':123,'uploader':'Test streamer','thumbnail':'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="160" height="90"><rect width="160" height="90" fill="purple"/></svg>','profile_image':'','upload_date':'20261009','qualities':[{'value':'1080p','label':'1080p'},{'value':'720p','label':'720p'}]})
    if id=='99':task.update(phase='metadata_error',error_message='restricted')
    tasks.append(task);results.append({'url':url,'task_id':id,'duplicate':False})
   return await route.fulfill(json={'results':results})
  if path=='/api/vod/start-prepared':
   for task in tasks:
    if task['task_id'] in data['task_ids']:task.update(state='downloading',phase='downloading',started_at='2026-10-09T00:00:00')
   return await route.fulfill(json={'results':[{'task_id':id,'started':True} for id in data['task_ids']]})
  if path=='/api/vod/clear-completed':
   assert 'completed_only=true' in route.request.url
   old=len(tasks);tasks[:]=[task for task in tasks if task['state']!='completed']
   return await route.fulfill(json={'deleted_count':old-len(tasks),'remaining_count':len(tasks)})
  if path.startswith('/api/vod/'):
   parts=path.split('/');id=parts[3];task=next((task for task in tasks if task['task_id']==id),None)
   if method=='DELETE':tasks.remove(task)
   elif task:
    action=parts[-1]
    if action=='quality':task['quality']=data['quality']
    elif action=='metadata':task.update(phase='ready',error_message=None)
    elif action=='start':task.update(state='downloading',phase='downloading')
    elif action=='pause':task['state']='paused'
    elif action=='resume':task['state']='downloading'
    elif action=='cancel':task.update(state='idle',phase='cancelled')
    elif action=='retry':
     new=copy.deepcopy(task);new.update(task_id=id+'-retry',state='idle',phase='queued');tasks.append(new)
     return await route.fulfill(json={'new_task_id':new['task_id'],'old_task_id':id,'message':'ok'})
   return await route.fulfill(json={})
  return await mock(route)
 await context.route('**/api/**',api)
 page=await context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
 await page.goto(BASE+'/vod');panel=page.get_by_test_id('vod-preparation')
 await panel.get_by_role('textbox').fill('https://chzzk.naver.com/video/1\nhttps://chzzk.naver.com/video/2?tracking=1\nhttps://chzzk.naver.com/video/1\nfile:///tmp/unsafe')
 await panel.get_by_role('button',name='목록에 추가',exact=True).click()
 await page.locator('[data-task-id="2"]').wait_for();assert len(tasks)==2
 assert await panel.get_by_role('alert').count()==1
 card=page.locator('[data-task-id="1"]');assert 'Test streamer' in await card.inner_text()
 assert await card.get_by_role('button',name='480p',exact=True).count()==0
 await card.get_by_role('button',name='720p',exact=True).click()
 await page.wait_for_function("document.querySelector('[data-task-id=\"1\"] button[aria-pressed=true]')?.textContent==='720p'")
 for kind,value,id in [('text/uri-list','# comment\nhttps://chzzk.naver.com/video/3','3'),('text/plain','https://chzzk.naver.com/video/4','4'),('text/html','<a href="https://chzzk.naver.com/video/99">VOD</a><script>window.__unsafe=true</script>','99')]:
  transfer=await page.evaluate_handle('([kind,value])=>{const dt=new DataTransfer();dt.setData(kind,value);return dt}',[kind,value])
  await panel.dispatch_event('dragenter',{'dataTransfer':transfer})
  assert await panel.get_by_role('textbox').count()==1
  await panel.dispatch_event('drop',{'dataTransfer':transfer});await panel.get_by_role('button',name='목록에 추가',exact=True).click();await page.locator(f'[data-task-id="{id}"]').wait_for()
 assert not await page.evaluate('Boolean(window.__unsafe)')
 failed=page.locator('[data-task-id="99"]');await failed.get_by_role('button',name='정보 다시 조회',exact=True).click()
 await failed.get_by_role('button',name='다운로드 시작',exact=True).wait_for()
 await page.locator('[data-testid=vod-preparation]').scroll_into_view_if_needed()
 await page.wait_for_timeout(300)
 await page.screenshot(path=str(OUT/f'vod-ready-{width}.png'),full_page=True)
 await page.reload();await page.locator('[data-task-id="1"]').wait_for();assert len(tasks)==5
 await page.locator('[data-task-id="4"]').get_by_role('button',name='다운로드 시작',exact=True).click()
 await page.get_by_role('button',name='전체 다운로드',exact=False).click()
 await card.get_by_role('button',name='일시정지',exact=True).wait_for()
 await card.get_by_role('button',name='일시정지',exact=True).click()
 await card.get_by_role('button',name='재개',exact=True).click()
 tasks[1]['state']='completed';await page.wait_for_timeout(2200)
 await page.get_by_role('button',name='완료 목록 정리',exact=True).click()
 await page.get_by_role('dialog').get_by_role('button',name='목록 정리',exact=True).click()
 await page.locator('[data-task-id="2"]').wait_for(state="detached");assert len(tasks)==4
 await page.locator('[data-task-id="99"]').get_by_role('button',name='취소',exact=True).click()
 await page.get_by_role('dialog').get_by_role('button',name='다운로드 취소',exact=True).click()
 await page.locator('[data-task-id="99"]').get_by_role('button',name='작업 메뉴',exact=False).click();await page.get_by_role('dialog').get_by_role('button',name='다시 다운로드',exact=True).click()
 await page.get_by_role('dialog').get_by_role('button',name='다시 다운로드',exact=True).click()
 await page.locator('[data-task-id="99-retry"]').wait_for()
 await page.locator('[data-task-id="99"]').get_by_role('button',name='작업 메뉴',exact=False).click();await page.get_by_role('dialog').get_by_role('button',name='목록에서 제거',exact=True).click();await page.get_by_role('dialog').get_by_role('button',name='목록에서 제거',exact=True).click()
 await page.locator('[data-task-id="99"]').wait_for(state="detached")
 count=len(tasks)
 await panel.get_by_role('textbox').fill('https://chzzk.naver.com/clips/Clip_123?tracking=1')
 await panel.get_by_role('button',name='목록에 추가',exact=True).click()
 await page.locator('[data-task-id="Clip_123"]').wait_for();assert len(tasks)==count+1
 await page.locator('[data-task-id="Clip_123"]').get_by_role('button',name='상세 보기',exact=False).click();assert '클립 번호' in await page.locator('[data-task-id="Clip_123"]').inner_text()
 await panel.get_by_role('textbox').fill('https://chzzk.naver.com/clips/Clip_123')
 await panel.get_by_role('button',name='목록에 추가',exact=True).click()
 await page.wait_for_timeout(300);assert len(tasks)==count+1
 assert '이미 목록에 있는 영상입니다.' in await panel.get_by_role('alert').inner_text()
 assert any(path.endswith('/1/quality') and data['quality']=='720p' for path,method,data in requests)
 assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
 assert not errors,errors
 await page.screenshot(path=str(OUT/f'vod-{width}.png'),full_page=True)
 for lang,label in [('en','Add to list'),('ja','リストに追加')]:
  await page.evaluate('([lang])=>localStorage.setItem("phrolova-language",lang)',[lang]);await page.reload()
  await panel.get_by_role('button',name=label,exact=True).wait_for()
 await context.close();print('VOD preparation browser PASS',width)

async def main():
 async with async_playwright() as p:
  browser=await p.chromium.launch(executable_path=os.environ.get('PHROLOVA_CHROMIUM_EXECUTABLE'))
  for width in (390,1440):await check(browser,width)
  await browser.close()
if __name__=='__main__':asyncio.run(main())
