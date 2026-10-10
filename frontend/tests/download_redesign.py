"""Unified download UI, real API requests, all states and responsive Chromium rendering."""
import asyncio
import copy
import os
from pathlib import Path
from urllib.parse import urlparse
from playwright.async_api import async_playwright, expect
from browser_fixtures import FIX, mock

BASE = os.environ.get('PHROLOVA_TEST_URL', 'http://localhost:3000')
OUT = Path(os.environ.get('PHROLOVA_TEST_OUTPUT', '/tmp/phrolova-download-redesign'))
VIDEO = 'dQw4w9WgXcQ'

def make_task(id, url=None, state='idle', phase='ready'):
    task = copy.deepcopy(FIX['tasks'][0])
    task.update(task_id=id, url=url or f'https://chzzk.naver.com/video/{id}', title=f'영상 {id} '+ '긴 영상 제목 ' * 20,
                state=state, phase=phase, prepared=True, quality='1080p', progress=68.4,
                downloaded_bytes=int(3.12*1024**3), total_bytes=int(4.55*1024**3), download_speed=12.5, eta_seconds=120,
                created_at='2026-10-10T10:00:00Z', started_at=None, completed_at=None, output_path=None,
                error_message=None, inspection_state='pending', warning_message=None,
                download_warning_message=None, retry_task_id=None,
                metadata={'id':id, 'duration':7370, 'uploader':'샘플 채널', 'qualities':[{'value':f'{height}p','label':f'{height}p'} for height in (1080,720,480,360,144)]})
    return task

async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    tasks=[]; requests=[]; imports=[]
    async def route_api(route):
        request=route.request; path=urlparse(request.url).path
        data=request.post_data_json if request.post_data else None
        requests.append((path,request.method,data))
        if path=='/api/vod/capabilities':
            return await route.fulfill(json={'sources':[{'id':id,'label':label} for id,label in [('chzzk','치지직'),('youtube','유튜브'),('external','외부 영상')]],'prepare':True,'pause':True,'file_open':True})
        if path=='/api/vod/status':return await route.fulfill(json={'tasks':tasks,'imports':imports,'active_count':sum(t['state'] in ('downloading','paused') for t in tasks)})
        if path=='/api/vod/prepare':
            results=[]
            for url in data['urls']:
                id=str(len(tasks)+1);tasks.append(make_task(id,url));results.append({'task_id':id,'url':url,'duplicate':False})
            return await route.fulfill(json={'results':results})
        if path=='/api/vod/download':
            if '/@' in data['url']:
                imports.append({'id':'collection','url':data['url'],'state':'collecting','added_count':0,'skipped_count':0,'error':None})
                return await route.fulfill(json={'task_id':None,'task_ids':[],'import_id':'collection','added_count':0,'message':'ok'})
            id=str(len(tasks)+1);tasks.append(make_task(id,data['url'],'downloading','downloading'))
            return await route.fulfill(json={'task_id':id,'task_ids':[id],'added_count':1,'message':'ok'})
        if path=='/api/vod/start-prepared':
            for task in tasks:
                if task['task_id'] in data['task_ids']:task.update(state='downloading',phase='downloading')
            return await route.fulfill(json={'results':[{'task_id':id,'started':True} for id in data['task_ids']]})
        if path=='/api/vod/reorder':
            lookup={task['task_id']:task for task in tasks};tasks[:]=[lookup[id] for id in data['task_ids']]
            return await route.fulfill(json={'message':'ok'})
        if path=='/api/vod/clear-completed':
            tasks[:]=[task for task in tasks if task['state']!='completed']
            return await route.fulfill(json={'deleted_count':1,'remaining_count':len(tasks)})
        if path.startswith('/api/vod/'):
            id=path.split('/')[3];task=next((task for task in tasks if task['task_id']==id),None)
            if task and request.method=='DELETE':tasks.remove(task);return await route.fulfill(json={'message':'ok'})
            if task and path.endswith('/quality'):task['quality']=data['quality']
            if task and path.endswith(('/start','/resume')):task.update(state='downloading',phase='downloading')
            if task and path.endswith('/pause'):task.update(state='paused')
            if task and path.endswith('/cancel'):task.update(state='idle',phase='cancelled')
            if task and path.endswith('/inspect'):task.update(inspection_state='running')
            if task and path.endswith('/retry'):
                new=make_task(id+'-retry',task['url']);new.update(phase='queued');tasks.append(new);task['retry_task_id']=new['task_id']
                return await route.fulfill(json={'new_task_id':new['task_id'],'old_task_id':id})
            if task and path.endswith('/open-location'):return await route.fulfill(json={'message':'샘플 폴더 경로'})
            if task:return await route.fulfill(json={'message':'ok'})
        return await mock(route)
    async with async_playwright() as p:
        browser=await p.chromium.launch()
        context=await browser.new_context(viewport={'width':1440,'height':1000})
        await context.add_init_script('window.EventSource=class{close(){}}')
        await context.route('**/api/**',route_api)
        page=await context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        await page.goto(BASE+'/vod')
        panel=page.get_by_test_id('vod-preparation');field=panel.get_by_role('textbox')
        await expect(page.get_by_text('등록된 다운로드가 없습니다',exact=True)).to_be_visible()
        assert await page.locator('textarea').count()==1
        assert await panel.get_by_role('combobox').evaluate('(e)=>e.offsetHeight') == await field.evaluate('(e)=>e.offsetHeight')
        assert await panel.evaluate('(e)=>e.offsetHeight') < 100
        await expect(panel.get_by_text('새 다운로드',exact=True)).to_have_count(0)
        await expect(panel.locator('.download-source-trigger .bg-chzzk')).to_have_count(1)
        await expect(page.get_by_text('일부 영상은 로그인 쿠키가 필요할 수 있습니다.', exact=True)).not_to_be_visible()
        await page.get_by_label('다운로드 도움말', exact=True).click()
        await expect(page.get_by_text('일부 영상은 로그인 쿠키가 필요할 수 있습니다.', exact=True)).to_be_visible()
        await page.get_by_label('다운로드 도움말', exact=True).click()
        await expect(panel.get_by_role('button',name='목록에 추가',exact=True)).to_be_disabled()
        await expect(panel.get_by_role('button',name='다운로드 시작',exact=True)).to_be_disabled()
        assert await page.locator('.ui-empty').evaluate('(e)=>e.offsetHeight') < 200
        await field.fill('https://chzzk.naver.com/video/1\nhttps://chzzk.naver.com/clips/Clip_2\nhttps://chzzk.naver.com/video/1\nfile:///bad')
        await expect(panel).to_contain_text('입력한 링크 4개')
        await panel.get_by_role('button',name='목록에 추가',exact=True).click()
        await expect(page.locator('[data-task-id]')).to_have_count(2)
        assert len([r for r in requests if r[0]=='/api/vod/prepare'])==1
        assert len([r for r in requests if r[0]=='/api/vod/download'])==0
        await field.fill('https://chzzk.naver.com/video/1')
        await panel.get_by_role('button',name='목록에 추가',exact=True).click()
        await expect(panel.get_by_role('alert')).to_contain_text('이미 목록에 있는 영상입니다.')
        assert len(tasks)==2
        await panel.get_by_role('combobox',name='다운로드 플랫폼').click()
        await panel.get_by_role('option',name='유튜브',exact=True).click()
        await field.fill(VIDEO+'\nhttps://youtu.be/'+VIDEO)
        await panel.get_by_role('button',name='목록에 추가',exact=True).click()
        await expect(page.locator('[data-task-id]')).to_have_count(3)
        assert [r for r in requests if r[0]=='/api/vod/prepare'][-1][2]['source']=='youtube'
        style_read = '(e)=>{const s=getComputedStyle(e);return ["color","backgroundColor","fontSize","lineHeight","borderRadius","borderTopWidth","borderTopColor","paddingLeft","paddingRight"].map(k=>s[k])}'
        download_badge_style = await page.locator('.download-task-meta .platform-chzzk').first.evaluate(style_read)
        live = await context.new_page();await live.goto(BASE+'/')
        await expect(live.locator('.recording-channel .platform-chzzk').first).to_be_visible()
        assert await live.locator('.recording-channel .platform-chzzk').first.evaluate(style_read) == download_badge_style
        await live.close()
        await page.locator('[data-task-id="3"]').get_by_role('button',name='720p',exact=True).click()
        await expect(page.locator('[data-task-id="3"]').get_by_role('button',name='720p',exact=True)).to_have_attribute('aria-pressed','true')
        await expect(page.locator('[data-task-id="3"] .download-task-meta')).not_to_contain_text('720p')
        await expect(page.locator('[data-task-id="3"] .download-task-controls')).not_to_contain_text('화질 선택')
        await expect(page.locator('[data-task-id="3"] [role=group][aria-label="다운로드 해상도"]')).to_be_visible()
        for quality in ('480p','360p','144p'):
            option=page.locator('[data-task-id="3"]').get_by_role('button',name=quality,exact=True)
            await option.click();await expect(option).to_have_attribute('aria-pressed','true')
        await field.fill('abcdefghijk')
        await panel.get_by_role('button',name='다운로드 시작',exact=True).click()
        await expect(page.locator('[data-task-id]')).to_have_count(4)
        assert [r for r in requests if r[0]=='/api/vod/download'][-1][2]['url']=='https://www.youtube.com/watch?v=abcdefghijk'
        await field.fill('@samplechannel')
        await expect(panel.get_by_role('button',name='목록에 추가',exact=True)).to_be_disabled()
        await panel.get_by_role('button',name='다운로드 시작',exact=True).click()
        await expect(page.locator('.download-import')).to_contain_text('채널 영상 목록을 불러오는 중')
        await panel.get_by_role('combobox').click();await panel.get_by_role('option',name='외부 영상',exact=True).click();await field.fill('https://example.com/video.mp4')
        await panel.get_by_role('button',name='목록에 추가',exact=True).click()
        await expect(page.locator('[data-task-id]')).to_have_count(5)
        await page.get_by_role('button',name='전체 다운로드 (4)',exact=True).click()
        await expect(page.get_by_role('button',name='전체 다운로드 (0)',exact=True)).to_be_disabled()
        assert [r for r in requests if r[0]=='/api/vod/start-prepared'][-1][2]['task_ids']==['1','2','3','5']
        # Server-driven collection of all real task states, including completion plus inspection failure.
        imports.clear();tasks[:]=[make_task('ready'),make_task('active',state='downloading',phase='downloading'),make_task('paused',state='paused'),make_task('complete',state='completed',phase='completed'),make_task('error',state='error',phase='error'),make_task('merging',state='downloading',phase='merging'),make_task('cancelled',phase='cancelled')]
        tasks[0]['metadata']['uploader']='아주 긴 채널 이름 ' * 12
        complete=tasks[3];complete.update(inspection_state='failed',inspection_message='파일 검사 시간이 초과되었습니다.',inspection_diagnostics={'stderr':'probe failed'},completed_at='2026-10-10T10:00:00Z',file_size=int(4.55*1024**3),output_path='/영상/한글 파일 [1080p].mp4')
        tasks[4]['error_message']='Connection interrupted diagnostic'
        await expect(page.locator('[data-task-id="complete"]')).to_be_visible(timeout=6000)
        summary=page.get_by_label('전체 작업 현황')
        for label in ('진행 중 2','대기 중 1','완료 1','실패 1'):await expect(summary).to_contain_text(label)
        completed=page.locator('[data-task-id="complete"]')
        await expect(completed).to_contain_text('다운로드 완료');await expect(completed).to_contain_text('파일 확인 필요')
        await completed.get_by_role('button',name='다시 검사',exact=True).click()
        await expect(completed).to_contain_text('파일 정보를 확인하고 있습니다.')
        assert len([r for r in requests if r[0]=='/api/vod/complete/inspect'])==1
        complete.update(inspection_state='passed',inspection_message='파일 검사 완료')
        await expect(completed).to_contain_text('파일 검사 완료',timeout=6000)
        await expect(completed.get_by_role('link',name='파일 열기')).to_have_attribute('href','/api/vod/complete/file')
        await completed.get_by_role('button',name=re.compile('^상세 보기')).click()
        await expect(completed).to_contain_text('/영상/한글 파일 [1080p].mp4')
        await completed.evaluate('(e)=>e.dataset.testIdentity="same"')
        await page.get_by_role('button',name='카드로 보기',exact=True).click()
        assert await completed.get_attribute('data-test-identity')=='same'
        await completed.get_by_role('button',name=re.compile('^상세 접기')).click()
        merging=page.locator('[data-task-id="merging"]')
        await expect(merging).to_contain_text('병합 중');await expect(merging.get_by_role('button',name='일시정지',exact=True)).to_have_count(0)
        paused=page.locator('[data-task-id="paused"]');await paused.get_by_role('button',name='재개',exact=True).click()
        await expect(paused.get_by_role('button',name='일시정지',exact=True)).to_be_visible()
        await paused.get_by_role('button',name='일시정지',exact=True).click();await expect(paused).to_contain_text('일시정지')
        filters=page.get_by_role('group',name='다운로드 상태 필터')
        await filters.get_by_role('button',name='실패 (1)',exact=True).click();await expect(page.locator('[data-task-id]')).to_have_count(1)
        failed=page.locator('[data-task-id="error"]');await failed.get_by_role('button',name='다시 시도',exact=True).click()
        await page.get_by_role('dialog').get_by_role('button',name='다시 다운로드',exact=True).click()
        await filters.get_by_role('button',name='전체 (8)',exact=True).click()
        await expect(page.locator('[data-task-id="error-retry"]')).to_be_visible()
        await expect(failed.get_by_role('button',name='다시 시도',exact=True)).to_be_disabled()
        while await page.get_by_role('button',name='알림 닫기',exact=True).count():
            await page.get_by_role('button',name='알림 닫기',exact=True).first.click()
        for width in (360,390,768,1024,1440,1920):
            await page.set_viewport_size({'width':width,'height':1000})
            for mode,label in [('grid','카드로 보기'),('list','목록으로 보기')]:
                await page.get_by_role('button',name=label,exact=True).click()
                assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(width,mode)
                await expect(page.locator('[data-task-id="active"]')).to_contain_text('68.4%')
                await expect(page.locator('[data-task-id="active"] [role=progressbar]')).to_have_attribute('aria-valuenow','68.4')
                await expect(page.locator('[data-task-id="active"] .download-task-meta')).not_to_contain_text('1080p')
                await expect(page.locator('[data-task-id="active"] .download-selected-quality')).to_contain_text('1080p')
                await expect(page.locator('[data-task-id="active"] .download-quality-segments')).to_have_count(0)
                ready_card = page.locator('[data-task-id="ready"]')
                await expect(ready_card).not_to_contain_text('화질 선택')
                await expect(ready_card.get_by_role('button',name='1080p',exact=True)).to_have_attribute('aria-pressed','true')
                assert await ready_card.evaluate('e=>{const q=e.querySelector(".download-task-quality").getBoundingClientRect(), m=e.querySelector(".download-task-management").getBoundingClientRect();return q.right<=m.left || m.right<=q.left || q.bottom<=m.top || m.bottom<=q.top}')
                if await ready_card.evaluate('e=>e.clientWidth') > 500:
                    assert await ready_card.evaluate('e=>{const q=e.querySelector(".download-quality-segments").getBoundingClientRect(),a=e.querySelector(".download-actions").getBoundingClientRect();return Math.abs((q.top+q.bottom)/2-(a.top+a.bottom)/2)<2}'),(width,mode,'ready alignment')
                for id in ('ready','active','paused','complete'):
                    card=page.locator(f'[data-task-id="{id}"]')
                    assert await card.evaluate('e=>{const t=e.querySelector(".download-title").getBoundingClientRect(),a=e.querySelector(".download-task-management").getBoundingClientRect(),s=e.querySelector(".download-thumbnail").getBoundingClientRect();return Math.abs(t.top-a.top)<1 && Math.abs(t.top-s.top)<1 && t.right<=a.left}'),(width,mode,id,'header top')
                    assert await card.evaluate('e=>Array.from(e.querySelectorAll(".download-task-controls .ui-button")).every(b=>{const r=b.getBoundingClientRect(),c=e.getBoundingClientRect();return r.left>=c.left&&r.right<=c.right})'),(width,mode,id,'action bounds')
                    assert await card.evaluate('e=>{const b=[...e.querySelectorAll(".download-task-management > button")].map(e=>e.getBoundingClientRect());return b.length===3 && b.every(r=>Math.abs((r.top+r.bottom)/2-(b[0].top+b[0].bottom)/2)<1)}'),(width,mode,id,'three action centers')
                assert await ready_card.evaluate('e=>{const n=e.querySelector(".download-uploader").getBoundingClientRect(),b=e.querySelector(".platform-badge").getBoundingClientRect();return Math.abs((n.top+n.bottom)/2-(b.top+b.bottom)/2)<1 && b.left-n.right>=6 && b.left-n.right<=8}'),(width,mode,'channel badge')
                if width < 640:
                    assert await ready_card.evaluate('e=>[...e.querySelectorAll(".download-task-management > button")].every(b=>{const r=b.getBoundingClientRect();return r.width>=44&&r.height>=44})'),(width,mode,'touch targets')
                if 700 <= await page.locator('[data-task-id="active"]').evaluate('e=>e.clientWidth') < 1000:
                    assert await page.locator('[data-task-id="active"]').evaluate('e=>{const m=e.querySelector(".download-task-metrics").getBoundingClientRect(),a=e.querySelector(".download-task-controls").getBoundingClientRect();return Math.abs((m.top+m.bottom)/2-(a.top+a.bottom)/2)<2}'),(width,mode,'footer')
                await page.screenshot(path=str(OUT/f'{mode}-{width}.png'),full_page=True)
        await page.set_viewport_size({'width':1440,'height':1000})
        await paused.get_by_role('button',name='취소',exact=True).click()
        await page.get_by_role('dialog').get_by_role('button',name='다운로드 취소',exact=True).click()
        await expect(paused).to_contain_text('취소됨')
        await completed.get_by_role('button',name=re.compile('^작업 메뉴')).click()
        await page.get_by_role('dialog').get_by_role('button',name='목록에서 제거',exact=True).click()
        await expect(page.get_by_role('dialog')).to_contain_text('저장된 영상 파일은 삭제하지 않습니다.')
        await page.get_by_role('dialog').get_by_role('button',name='목록에서 제거',exact=True).click()
        await expect(completed).to_have_count(0)
        assert not errors,errors
        print('Download redesign PASS: single/multi URLs, queue/start/all, duplicate validation, external/YouTube/channel import, quality, real states/stats, pause/resume/retry/inspect/file links, same card identity, 6 widths x 2 views')
        await browser.close()

import re
if __name__ == '__main__': asyncio.run(main())
