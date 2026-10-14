"""기존 플랫폼 보존, 연결 오류, 회차 선택과 모바일 UI 회귀 검사."""
import asyncio,copy,os
from pathlib import Path
from urllib.parse import urlparse
from playwright.async_api import async_playwright,expect
from browser_fixtures import FIX,mock
from download_redesign import make_task

BASE=os.environ.get('PHROLOVA_TEST_URL','http://127.0.0.1:3001')
OUT=Path(os.environ.get('PHROLOVA_TEST_OUTPUT',str(Path(__file__).resolve().parents[3]/'work/episode-ui')))
IDS=['chzzk','youtube','soop','cime','kick','twitch','tiktok','anilife','linkani','ohli24','external']
LABELS=['치지직','유튜브','숲','씨미','Kick','트위치','틱톡','애니라이프','Linkani','애니24','외부 영상']
WORK='https://linkani.tv/ani/42/'

async def main():
    OUT.mkdir(parents=True,exist_ok=True)
    tasks,calls,errors=[],[],[]
    failure=True
    catalog_error=False
    async def route_api(route):
        nonlocal failure,catalog_error
        req=route.request;path=urlparse(req.url).path
        if path=='/api/vod/capabilities':
            if failure:return await route.fulfill(status=503,json={'detail':'temporary outage'})
            return await route.fulfill(json={'sources':[{'id':id,'label':label}for id,label in zip(IDS,LABELS)],'prepare':True,'pause':True,'file_open':True})
        if path=='/api/vod/status':return await route.fulfill(json={'tasks':tasks,'imports':[],'active_count':0})
        if path=='/api/vod/catalog':
            calls.append(('catalog',req.post_data_json))
            if catalog_error:return await route.fulfill(status=403,json={'detail':'접근 거부'})
            return await route.fulfill(json={'source':'linkani','id':'42','title':'회차 선택 테스트 작품','url':WORK,'incomplete':True,
                'episodes':[{'id':f'a1-k{i}','title':f'{i:03d}화 — 회차 선택 테스트','url':f'https://linkani.tv/watch/42/a1/k{i}/','available':i!=2}for i in range(1,121)]})
        if path=='/api/vod/prepare':
            data=req.post_data_json;calls.append(('prepare',data))
            results=[]
            for url in data['urls']:
                task=make_task('episode-'+str(len(tasks)),url=url);task.update(platform='linkani',title='테스트 작품 · 회차')
                tasks.append(task);results.append({'url':url,'task_id':task['task_id']})
            return await route.fulfill(json={'results':results})
        return await mock(route)
    async with async_playwright() as p:
        browser=await p.chromium.launch();ctx=await browser.new_context(viewport={'width':1440,'height':1000})
        await ctx.add_init_script('window.EventSource=class{close(){}}')
        await ctx.route('**/api/**',route_api)
        page=await ctx.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
        await page.goto(BASE+'/vod')
        await expect(page.get_by_role('alert')).to_contain_text('플랫폼 목록을 불러오지 못했습니다')
        await page.get_by_role('combobox',name='다운로드 플랫폼',exact=True).click()
        actual=await page.get_by_role('listbox').get_by_role('option').all_text_contents()
        assert actual==LABELS,actual
        await page.keyboard.press('Escape')
        failure=False
        await page.get_by_role('button',name='다시 시도',exact=True).click()
        await expect(page.get_by_role('alert')).to_have_count(0)
        value=await page.evaluate('''async()=>{
          const {parseEpisodeInput:p}=await import('/src/utils/episodeSites.ts');
          return [p('https://linkani.tv/ani/42/?x=1'),p('https://www.ohli24.net/2/한글.html'),p('https://linkani.tv.evil/ani/42'),p('https://u:p@linkani.tv/ani/42')];
        }''')
        assert value[0]=={'url':WORK,'collection':True,'source':'linkani'} and value[1]['collection'] and value[2:]==[None,None]
        await page.get_by_role('combobox',name='다운로드 플랫폼',exact=True).click()
        await page.get_by_role('option',name='Linkani',exact=True).click()
        panel=page.get_by_test_id('vod-preparation')
        await panel.get_by_role('textbox').fill(WORK)
        await panel.get_by_role('button',name='목록에 추가',exact=True).click()
        dialog=page.get_by_role('dialog',name='회차 선택',exact=True)
        await expect(dialog.get_by_role('heading',name='회차 선택 테스트 작품')).to_be_visible()
        await expect(dialog.get_by_role('checkbox').nth(1)).to_be_disabled()
        await expect(dialog).to_contain_text('일부 이전 회차가 목록에서 빠져 있습니다')
        await dialog.get_by_role('button',name='검색 결과 선택 (최대 100개)',exact=True).click()
        await expect(dialog).to_contain_text('120개 중 100개 선택')
        await dialog.get_by_role('button',name='선택 해제',exact=True).click()
        await dialog.get_by_role('textbox',name='회차 검색').fill('120화')
        await dialog.get_by_role('checkbox').check()
        for width in (320,390,768,1440):
            await page.set_viewport_size({'width':width,'height':850})
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
            assert await dialog.evaluate('(el)=>el.scrollWidth<=el.clientWidth+1'),width
            if width in (390,1440):await page.screenshot(path=str(OUT/f'picker-{width}.png'))
        await dialog.get_by_role('button',name='선택한 회차 추가 (1)',exact=True).click()
        await expect(dialog).to_have_count(0)
        assert calls[-1]==('prepare',{'urls':['https://linkani.tv/watch/42/a1/k120/'],'source':'linkani'}),calls[-1]
        await panel.get_by_role('textbox').fill(WORK)
        catalog_error=True
        await panel.get_by_role('button',name='목록에 추가',exact=True).click()
        await expect(dialog.get_by_role('alert')).to_contain_text('접근 거부')
        catalog_error=False
        await dialog.get_by_role('button',name='다시 시도',exact=True).click()
        await expect(dialog.get_by_role('checkbox')).to_have_count(50)
        await dialog.get_by_role('button',name='취소',exact=True).click()
        assert not errors,errors
        await browser.close()
    print('PASS: 11 platforms retained on API failure, retry, episode URL boundaries, unavailable episodes, partial list, 100-item limit, search, queue payload, retry/cancel and 320/390/768/1440px layouts')

if __name__=='__main__':asyncio.run(main())
