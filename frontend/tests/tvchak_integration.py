"""TVChak selection, episode queue, cookie controls and mobile layouts."""
import asyncio
import os
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright, expect
from browser_fixtures import mock
from download_redesign import make_task

BASE=os.environ.get('PHROLOVA_TEST_URL','http://127.0.0.1:3013')
OUT=Path(os.environ.get('PHROLOVA_TEST_OUTPUT',str(Path(__file__).resolve().parents[4]/'work/tvchak-ui')))
IDS=['chzzk','youtube','soop','cime','kick','twitch','tiktok','bilibili','anilife','linkani','ohli24','tvwiki','tvchak','external']
LABELS=['치지직','유튜브','숲','씨미','Kick','트위치','틱톡','Bilibili','애니라이프','Linkani','애니24','티비위키','티비착','외부 영상']
WORK='https://tvchak208.com/index.php/vod/detail/id/123703.html'
EPISODE='https://tvchak208.com/index.php/vod/play/id/123703/sid/1/nid/1.html'
SECOND=EPISODE.replace('nid/1','nid/2')


async def main():
    OUT.mkdir(parents=True,exist_ok=True)
    tasks,calls,errors=[],[],[]
    cookie={'configured':False,'valid':False,'expired':False}
    async def route_api(route):
        request=route.request;path=urlparse(request.url).path
        if path=='/api/vod/capabilities':
            return await route.fulfill(json={'sources':[{'id':key,'label':label} for key,label in zip(IDS,LABELS)],'prepare':True,'pause':True,'file_open':True})
        if path=='/api/vod/status':return await route.fulfill(json={'tasks':tasks,'imports':[],'active_count':0})
        if path=='/api/vod/catalog':
            calls.append(('catalog',request.post_data_json))
            return await route.fulfill(json={'source':'tvchak','id':'123703','title':'티비착 테스트 작품','url':WORK,
                'episodes':[{'id':f's1-n{index}','title':f'제{index}화','url':url,'available':True} for index,url in enumerate((EPISODE,SECOND),1)]})
        if path=='/api/vod/prepare':
            data=request.post_data_json;calls.append(('prepare',data));results=[]
            for url in data['urls']:
                task=make_task('tvchak-'+str(len(tasks)),url=url)
                task.update(platform='tvchak',title='티비착 테스트 회차')
                tasks.append(task);results.append({'url':url,'task_id':task['task_id']})
            return await route.fulfill(json={'results':results})
        if path=='/api/platforms/tvchak/cookie':
            if request.method=='POST':cookie.update(configured=True,valid=True)
            if request.method=='DELETE':cookie.update(configured=False,valid=False)
            return await route.fulfill(json=cookie)
        if path.endswith('/cookie'):return await route.fulfill(json={'configured':False,'valid':False,'expired':False})
        return await mock(route)

    async with async_playwright() as p:
        browser=await p.chromium.launch(channel='chrome')
        context=await browser.new_context(viewport={'width':1440,'height':900})
        await context.add_init_script('window.EventSource=class{close(){}}')
        await context.route('**/api/**',route_api)
        page=await context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
        await page.goto(BASE+'/vod')
        panel=page.get_by_test_id('vod-preparation')
        await panel.get_by_role('combobox',name='다운로드 플랫폼',exact=True).click()
        assert await page.get_by_role('listbox').get_by_role('option').all_text_contents()==LABELS
        await page.get_by_role('option',name='티비착',exact=True).click()
        await panel.get_by_role('textbox').fill(WORK+'?ref=tracking')
        await panel.get_by_role('button',name='목록에 추가',exact=True).click()
        dialog=page.get_by_role('dialog',name='회차 선택',exact=True)
        await expect(dialog.get_by_role('heading',name='티비착 테스트 작품')).to_be_visible()
        await dialog.get_by_role('checkbox').first.check()
        for width in (320,390,768,1440):
            await page.set_viewport_size({'width':width,'height':850})
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
            assert await dialog.evaluate('(e)=>e.scrollWidth<=e.clientWidth+1'),width
            if width in (390,1440):await page.screenshot(path=str(OUT/f'picker-{width}.png'))
        await dialog.get_by_role('button',name='선택한 회차 추가 (1)',exact=True).click()
        await expect(dialog).to_have_count(0)
        assert calls[-1]==('prepare',{'urls':[EPISODE],'source':'tvchak'}),calls
        await panel.get_by_role('textbox').fill(SECOND+'#tracking')
        await panel.get_by_role('button',name='목록에 추가',exact=True).click()
        await expect(dialog).to_have_count(0)
        assert calls[-1]==('prepare',{'urls':[SECOND],'source':'tvchak'}),calls
        values=await page.evaluate('''async()=>{
            const {parseEpisodeInput:p}=await import('/src/utils/episodeSites.ts');
            return [p('https://tvchak208.com/index.php/vod/play/id/42/sid/1/nid/2.html?ref=x'),
                    p('https://tvchak208.com.evil/index.php/vod/detail/id/42.html'),
                    p('https://u:p@tvchak208.com/index.php/vod/detail/id/42.html'),
                    p('https://tvchak208.com/index.php/vod/type/id/42.html')];
        }''')
        assert values[0]=={'url':'https://tvchak208.com/index.php/vod/play/id/42/sid/1/nid/2.html','source':'tvchak','collection':False}
        assert values[1:]==[None,None,None]
        await page.screenshot(path=str(OUT/'queue.png'))
        await page.goto(BASE+'/settings')
        await page.get_by_role('button',name='인증',exact=True).click()
        card=page.locator('[data-cookie-platform=tvchak]')
        await expect(page.locator('[data-cookie-platform]')).to_have_count(9)
        await expect(card.get_by_role('heading',name='티비착',exact=True)).to_be_visible()
        await expect(card).to_contain_text('같은 인터넷 연결')
        await card.locator('input[type=file]').set_input_files({'name':'fixture.txt','mimeType':'text/plain','buffer':b'# Netscape HTTP Cookie File\n.tvchak208.com\tTRUE\t/\tTRUE\t0\tsession\tFIXTURE_SECRET\n'})
        await expect(card).to_contain_text('쿠키 등록됨')
        await expect(card).not_to_contain_text('FIXTURE_SECRET')
        await card.get_by_role('button',name='티비착 쿠키 파일 삭제',exact=True).click()
        await page.get_by_role('dialog').get_by_role('button',name='삭제',exact=True).click()
        await expect(card).to_contain_text('등록된 쿠키 없음')
        await expect(page.get_by_role('button',name='알림 닫기',exact=True)).to_have_count(0,timeout=10000)
        for width in (320,390,768,1440):
            await page.set_viewport_size({'width':width,'height':850})
            await card.scroll_into_view_if_needed()
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
            assert await card.evaluate('e=>e.scrollWidth<=e.clientWidth+1'),width
            if width in (390,1440):await card.screenshot(path=str(OUT/f'auth-{width}.png'))
        assert not errors,errors
        await browser.close()
    print('PASS: 14 sources; TVChak episode picker/direct queue, URL normalization, scoped cookie UI, and 320/390/768/1440px layouts')


if __name__=='__main__':asyncio.run(main())
