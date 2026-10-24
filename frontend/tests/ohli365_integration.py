"""Ani365 source retention, query-based episode links and responsive queue integration."""
import asyncio
import os
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright, expect
from animaru_integration import IDS, LABELS
from browser_fixtures import mock
from download_redesign import make_task

BASE = os.environ.get('PHROLOVA_TEST_URL','http://127.0.0.1:3013')
OUT = Path(__file__).resolve().parents[4]/'work/ohli365-ui'
WORK_ID = '11111111-1111-4111-8111-111111111111'
EP_ID = '22222222-2222-4222-8222-222222222222'
SECOND_ID = '33333333-3333-4333-8333-333333333333'
WORK = 'https://v2.ohli365.org/?title='+WORK_ID


async def main():
    OUT.mkdir(exist_ok=True)
    tasks,calls,errors = [],[],[]
    async def route_api(route):
        request=route.request
        path=urlsplit(request.url).path
        if path=='/api/vod/capabilities':
            return await route.fulfill(json={'sources':[{'id':key,'label':label}for key,label in zip(IDS,LABELS)],
                                            'prepare':True,'pause':True,'file_open':True})
        if path=='/api/vod/status':return await route.fulfill(json={'tasks':tasks,'imports':[],'active_count':0})
        if path=='/api/vod/catalog':
            calls.append(('catalog',request.post_data_json))
            return await route.fulfill(json={'source':'ohli365','id':WORK_ID,'title':'애니365 테스트 작품','url':WORK,
                'episodes':[{'id':EP_ID,'title':'1화 · 첫 번째 이야기','number':1,'url':WORK+'&episode='+EP_ID,'available':True},
                            {'id':SECOND_ID,'title':'2화 · 다음 이야기','number':2,'url':WORK+'&episode='+SECOND_ID,'available':True}]})
        if path=='/api/vod/prepare':
            data=request.post_data_json;calls.append(('prepare',data));results=[]
            for url in data['urls']:
                task=make_task('ohli365-'+str(len(tasks)),url=url)
                task.update(platform='ohli365',title='애니365 테스트 회차')
                tasks.append(task);results.append({'url':url,'task_id':task['task_id']})
            return await route.fulfill(json={'results':results})
        return await mock(route)

    async with async_playwright() as playwright:
        browser=await playwright.chromium.launch(channel='chrome')
        try:
            context=await browser.new_context(viewport={'width':1440,'height':900})
            await context.add_init_script('window.EventSource=class{close(){}}')
            await context.route('**/api/**',route_api)
            page=await context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
            await page.goto(BASE+'/vod')
            panel=page.get_by_test_id('vod-preparation')
            await panel.get_by_role('combobox',name='다운로드 플랫폼',exact=True).click()
            assert await page.get_by_role('listbox').get_by_role('option').all_text_contents()==LABELS
            await page.get_by_role('option',name='애니365',exact=True).click()
            await expect(panel.get_by_role('textbox')).to_have_attribute('placeholder','https://v2.ohli365.org/?title=...')
            await panel.get_by_role('textbox').fill(WORK+'&utm_source=tracking#top')
            await panel.get_by_role('button',name='목록에 추가',exact=True).click()
            dialog=page.get_by_role('dialog',name='회차 선택',exact=True)
            await expect(dialog.get_by_role('heading',name='애니365 테스트 작품')).to_be_visible()
            assert calls[-1]==('catalog',{'url':WORK})
            for width in (320,390,768,1440):
                await page.set_viewport_size({'width':width,'height':850})
                assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
                assert await dialog.evaluate('(el)=>el.scrollWidth<=el.clientWidth+1'),width
                if width in (390,1440):await page.screenshot(path=str(OUT/f'picker-{width}.png'))
            await dialog.get_by_role('checkbox').first.check()
            await dialog.get_by_role('button',name='선택한 회차 추가 (1)',exact=True).click()
            await expect(dialog).to_have_count(0)
            assert calls[-1]==('prepare',{'urls':[WORK+'&episode='+EP_ID],'source':'ohli365'})
            await panel.get_by_role('textbox').fill(WORK+'&episode='+SECOND_ID+'&ref=x')
            await panel.get_by_role('button',name='목록에 추가',exact=True).click()
            await expect(panel.get_by_role('textbox')).to_have_value('')
            assert calls[-1]==('prepare',{'urls':[WORK+'&episode='+SECOND_ID],'source':'ohli365'})
            for width in (320,390,768,1440):
                await page.set_viewport_size({'width':width,'height':850})
                await panel.get_by_role('combobox',name='다운로드 플랫폼',exact=True).click()
                listbox=page.get_by_role('listbox');box=await listbox.bounding_box()
                assert box and box['x']>=-1 and box['x']+box['width']<=width+1 and box['y']+box['height']<=851,(width,box)
                await page.get_by_role('option',name='애니365',exact=True).scroll_into_view_if_needed()
                if width==390:await page.screenshot(path=str(OUT/'sources-390.png'))
                await page.get_by_role('option',name='애니365',exact=True).click()
            cases=[WORK,WORK+'&episode='+EP_ID,WORK+'&episode=movie',
                   WORK.replace('.org/','.org.evil/'),WORK+'&title='+WORK_ID,WORK+'&episode=',
                   WORK.replace('v2.ohli365.org','u:p@v2.ohli365.org'),WORK.replace('https:','http:'),
                   WORK.replace('v2.ohli365.org','v3.ohli365.org')]
            results=await page.evaluate('''async cases=>{
                const {parseEpisodeInput}=await import('/src/utils/episodeSites.ts');
                const {normalizeDownloadInput,detectDownloadPlatform}=await import('/src/utils/downloads.ts');
                return cases.map(value=>({parsed:parseEpisodeInput(value),normalized:normalizeDownloadInput(value,'ohli365'),detected:detectDownloadPlatform(value)}));
            }''',cases)
            for index,item in enumerate(results):
                if index<3:
                    assert item['parsed']==item['normalized']=={'url':cases[index],'source':'ohli365','collection':index==0}
                    assert item['detected']=='ohli365'
                else:assert item['parsed'] is None and item['normalized'] is None,(index,item)
            assert not errors,errors
        finally:await browser.close()
    print('PASS: 16 sources retained; Ani365 label/placeholder, work picker, direct query-based episodes, invalid URL rejection and 320/390/768/1440px layouts')


if __name__=='__main__':asyncio.run(main())
