"""Animaru platform selection, episode picker and responsive queue integration."""
import asyncio
import os
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright, expect
from browser_fixtures import mock
from download_redesign import make_task

BASE = os.environ.get('PHROLOVA_TEST_URL', 'http://127.0.0.1:3013')
OUT = Path(os.environ.get('PHROLOVA_TEST_OUTPUT', str(Path(__file__).resolve().parents[4]/'work/animaru-ui')))
IDS = ['chzzk','youtube','soop','cime','kick','twitch','tiktok','bilibili','anilife','linkani','ohli24','ohli365','tvwiki','tvchak','animaru','external']
LABELS = ['치지직','유튜브','숲','씨미','Kick','트위치','틱톡','Bilibili','애니라이프','Linkani','애니24','애니365','티비위키','티비착','애니마루','외부 영상']
WORK = 'https://animaru1.com/content/42'


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
            return await route.fulfill(json={'source':'animaru','id':'drama-42','title':'애니마루 테스트 작품','url':WORK,
                'episodes':[{'id':str(index),'title':f'테스트 작품 {index}화','url':f'{WORK}/{index}','available':True} for index in (0,1.5)]})
        if path=='/api/vod/prepare':
            data=request.post_data_json;calls.append(('prepare',data))
            results=[]
            for url in data['urls']:
                task=make_task('animaru-'+str(len(tasks)),url=url)
                task.update(platform='animaru',title='애니마루 테스트 회차')
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
        await page.get_by_role('option',name='애니마루',exact=True).click()
        panel=page.get_by_test_id('vod-preparation')
        await panel.get_by_role('textbox').fill(WORK+'?ref=tracking')
        await panel.get_by_role('button',name='목록에 추가',exact=True).click()
        dialog=page.get_by_role('dialog',name='회차 선택',exact=True)
        await expect(dialog.get_by_role('heading',name='애니마루 테스트 작품')).to_be_visible()
        await dialog.get_by_role('checkbox').first.check()
        for width in (320,390,768,1440):
            await page.set_viewport_size({'width':width,'height':850})
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
            assert await dialog.evaluate('(el)=>el.scrollWidth<=el.clientWidth+1'),width
            if width in (390,1440):await page.screenshot(path=str(OUT/f'picker-{width}.png'))
        await dialog.get_by_role('button',name='선택한 회차 추가 (1)',exact=True).click()
        await expect(dialog).to_have_count(0)
        assert calls[-1]==('prepare',{'urls':[WORK+'/0'],'source':'animaru'}),calls
        await panel.get_by_role('textbox').fill(WORK+'/1.50#tracking')
        await panel.get_by_role('button',name='목록에 추가',exact=True).click()
        await expect(dialog).to_have_count(0)
        assert calls[-1]==('prepare',{'urls':[WORK+'/1.5'],'source':'animaru'}),calls
        for width in (320,390,768,1440):
            await page.set_viewport_size({'width':width,'height':850})
            await panel.get_by_role('combobox',name='다운로드 플랫폼',exact=True).click()
            listbox=page.get_by_role('listbox')
            box=await listbox.bounding_box()
            assert box and box['x']>=-1 and box['x']+box['width']<=width+1 and box['y']+box['height']<=851,(width,box)
            await page.get_by_role('option',name='애니마루',exact=True).scroll_into_view_if_needed()
            if width in (390,1440):await page.screenshot(path=str(OUT/f'sources-{width}.png'))
            await page.get_by_role('option',name='애니마루',exact=True).click()
        values=await page.evaluate('''async()=>{
            const {parseEpisodeInput:p}=await import('/src/utils/episodeSites.ts');
            return [p('https://animaru1.com/contents/1/1.50?ref=x'),p('https://animaru1.com.evil/content/1/2'),
                    p('https://u:p@animaru1.com/content/1/2'),p('https://animaru1.com/content/1/-1')];
        }''')
        assert values[0]=={'url':'https://animaru1.com/content/1/1.5','source':'animaru','collection':False}
        assert values[1:]==[None,None,None]
        await page.screenshot(path=str(OUT/'queue.png'))
        assert not errors,errors
        await browser.close()
    print('PASS: 16 sources retained; Animaru label, URL normalization, episode selection, direct episode queue and 320/390/768/1440px layouts')


if __name__=='__main__':asyncio.run(main())
