"""TVWiki platform selection, episode picker and responsive queue integration."""
import asyncio
import os
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright, expect
from browser_fixtures import mock
from download_redesign import make_task

BASE = os.environ.get('PHROLOVA_TEST_URL', 'http://127.0.0.1:3012')
OUT = Path(os.environ.get('PHROLOVA_TEST_OUTPUT', str(Path(__file__).resolve().parents[3]/'work/tvwiki-ui')))
IDS = ['chzzk','youtube','soop','cime','kick','twitch','tiktok','bilibili','anilife','linkani','ohli24','tvwiki','external']
LABELS = ['치지직','유튜브','숲','씨미','Kick','트위치','틱톡','Bilibili','애니라이프','Linkani','애니24','티비위키','외부 영상']
WORK = 'https://tvwiki54.net/drama/42'


async def main():
    OUT.mkdir(parents=True,exist_ok=True)
    tasks,calls,errors = [],[],[]

    async def route_api(route):
        request=route.request; path=urlparse(request.url).path
        if path=='/api/vod/capabilities':
            return await route.fulfill(json={'sources':[{'id':key,'label':label} for key,label in zip(IDS,LABELS)],'prepare':True,'pause':True,'file_open':True})
        if path=='/api/vod/status':return await route.fulfill(json={'tasks':tasks,'imports':[],'active_count':0})
        if path=='/api/vod/catalog':
            calls.append(('catalog',request.post_data_json))
            return await route.fulfill(json={'source':'tvwiki','id':'drama-42','title':'티비위키 테스트 작품','url':WORK,
                'episodes':[{'id':str(index),'title':f'테스트 작품 {index-10}화','url':f'{WORK}/{index}','available':True} for index in (11,12)]})
        if path=='/api/vod/prepare':
            data=request.post_data_json;calls.append(('prepare',data))
            results=[]
            for url in data['urls']:
                task=make_task('tvwiki-'+str(len(tasks)),url=url)
                task.update(platform='tvwiki',title='티비위키 테스트 회차')
                tasks.append(task);results.append({'url':url,'task_id':task['task_id']})
            return await route.fulfill(json={'results':results})
        return await mock(route)

    async with async_playwright() as playwright:
        browser=await playwright.chromium.launch(channel='chrome')
        context=await browser.new_context(viewport={'width':1440,'height':900})
        await context.add_init_script('window.EventSource=class{close(){}}')
        await context.route('**/api/**',route_api)
        page=await context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
        await page.goto(BASE+'/vod')
        await page.get_by_role('combobox',name='다운로드 플랫폼',exact=True).click()
        options=await page.get_by_role('listbox').get_by_role('option').all_text_contents()
        assert options==LABELS,options
        await page.get_by_role('option',name='티비위키',exact=True).click()
        panel=page.get_by_test_id('vod-preparation')
        await panel.get_by_role('textbox').fill(WORK+'?ref=tracking')
        await panel.get_by_role('button',name='목록에 추가',exact=True).click()
        dialog=page.get_by_role('dialog',name='회차 선택',exact=True)
        await expect(dialog.get_by_role('heading',name='티비위키 테스트 작품')).to_be_visible()
        await dialog.get_by_role('checkbox').first.check()
        for width in (320,390,768,1440):
            await page.set_viewport_size({'width':width,'height':850})
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
            assert await dialog.evaluate('(el)=>el.scrollWidth<=el.clientWidth+1'),width
            if width in (390,1440):await page.screenshot(path=str(OUT/f'picker-{width}.png'))
        await dialog.get_by_role('button',name='선택한 회차 추가 (1)',exact=True).click()
        await expect(dialog).to_have_count(0)
        assert calls[-1]==('prepare',{'urls':[WORK+'/11'],'source':'tvwiki'}),calls
        await panel.get_by_role('textbox').fill(WORK+'/12#tracking')
        await panel.get_by_role('button',name='목록에 추가',exact=True).click()
        await expect(dialog).to_have_count(0)
        assert calls[-1]==('prepare',{'urls':[WORK+'/12'],'source':'tvwiki'}),calls
        values=await page.evaluate('''async()=>{
            const {parseEpisodeInput:p}=await import('/src/utils/episodeSites.ts');
            return [p('https://tvwiki54.net/movie/1/2?ref=x'),p('https://tvwiki54.net.evil/drama/1/2'),
                    p('https://u:p@tvwiki54.net/drama/1/2'),p('https://tvwiki54.net/notice/1/2')];
        }''')
        assert values[0]=={'url':'https://tvwiki54.net/movie/1/2','source':'tvwiki','collection':False}
        assert values[1:]==[None,None,None]
        await page.screenshot(path=str(OUT/'queue.png'))
        assert not errors,errors
        await browser.close()
    print('PASS: 13 sources retained; TVWiki label, URL normalization, episode selection, direct episode queue and 320/390/768/1440px layouts')


if __name__=='__main__':asyncio.run(main())
