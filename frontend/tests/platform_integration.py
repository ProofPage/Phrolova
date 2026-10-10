"""Chromium integration checks with isolated platform APIs and genuine frame bytes."""
import asyncio
import copy
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse
from playwright.async_api import async_playwright, expect
from browser_fixtures import FIX, mock
from download_redesign import make_task

BASE = os.environ.get('PHROLOVA_TEST_URL', 'http://127.0.0.1:3001')
OUT = Path(os.environ.get('PHROLOVA_TEST_OUTPUT', str(Path(tempfile.gettempdir()) / 'phrolova-platform-integration')))
FRAME = OUT / 'fixture-frame.png'
LABELS = dict(chzzk='치지직', youtube='유튜브', soop='숲', cime='씨미')

async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    bundled=Path(__file__).resolve().parents[4] / 'work/media-tools/ffmpeg-9.0.2-essentials_build/bin/ffmpeg.exe'
    ffmpeg=os.environ.get('PHROLOVA_FFMPEG') or shutil.which('ffmpeg') or (str(bundled) if bundled.exists() else 'ffmpeg')
    subprocess.run([ffmpeg,'-y','-v','error','-f','lavfi','-i','testsrc2=size=1920x1080:rate=1','-frames:v','1','-threads','1',str(FRAME)],check=True)
    channels = []
    for platform in LABELS:
        channel = copy.deepcopy(FIX['channels'][1])
        channel.update(platform=platform, composite_key=platform+':alice', channel_id='alice', channel_name=LABELS[platform]+' 샘플',
                       title='[미리보기 샘플] 긴 방송 제목 ' * 10, tags=[], is_live=True, auto_record=True,
                       recording_quality='1080p60', last_error='', category='게임', profile_image_url='',
                       channel_url='https://ci.me/@alice/live' if platform=='cime' else 'https://play.sooplive.com/alice',
                       recording=dict(state='recording', is_recording=True, duration_seconds=7264, file_size_bytes=8*1024**3, download_speed=1.62, bitrate=13570, output_path='/샘플/녹화.ts', start_time=None))
        channels.append(channel)
    calls=[]; frames={}; fail_frame=False; tasks=[]; cookie={platform:False for platform in ('soop','cime')}
    async def route_api(route):
        nonlocal fail_frame
        request=route.request; path=unquote(urlparse(request.url).path)
        if request.method != 'GET' and 'cookie' not in path:
            calls.append((path,request.method,request.post_data_json if request.post_data else None))
        if path=='/api/platforms/status': return await route.fulfill(json={p:{'enabled':True,'authenticated':True} for p in LABELS})
        if path=='/api/platforms/channels': return await route.fulfill(json=channels if request.method=='GET' else {'status':'ok'})
        if path.endswith('/qualities'):
            return await route.fulfill(json={'live':True,'qualities':[{'value':str(h)+'p60','label':str(h)+'p60','width':h*16//9,'height':h,'fps':60} for h in (2160,1080,720)]})
        if path.endswith('/download-options'): return await route.fulfill(json={'status':'ok'})
        if '/preview-frame/' in path:
            key=path.split('/')[-1]; frames[key]=frames.get(key,0)+1
            if fail_frame: return await route.fulfill(status=502,json={'detail':'미리보기 실패'})
            return await route.fulfill(body=FRAME.read_bytes(),content_type='image/png')
        if path in ('/api/platforms/soop/cookie','/api/platforms/cime/cookie'):
            platform=path.split('/')[-2]
            if request.method=='POST': cookie[platform]=True
            if request.method=='DELETE': cookie[platform]=False
            return await route.fulfill(json={'configured':cookie[platform],'valid':cookie[platform],'expired':False,'message':'쿠키 파일 등록됨' if cookie[platform] else '등록된 쿠키 없음'})
        if path=='/api/vod/capabilities': return await route.fulfill(json={'sources':[{'id':p,'label':LABELS[p]} for p in ('chzzk','youtube','soop','cime')]+[{'id':'external','label':'외부 영상'}], 'prepare':True,'pause':True,'file_open':True})
        if path=='/api/vod/status': return await route.fulfill(json={'tasks':tasks,'imports':[],'active_count':0})
        if path=='/api/vod/prepare':
            results=[]
            for url in request.post_data_json['urls']:
                task=make_task(str(len(tasks)+1),url); tasks.append(task); results.append({'task_id':task['task_id'],'url':url,'duplicate':False})
            return await route.fulfill(json={'results':results})
        return await mock(route)
    async with async_playwright() as p:
        browser=await p.chromium.launch()
        context=await browser.new_context(viewport={'width':1440,'height':1000})
        await context.add_init_script("window.EventSource=class{close(){}};localStorage.setItem('dashboardViewMode','list')")
        await context.route('**/api/**',route_api)
        page=await context.new_page(); errors=[]; page.on('pageerror',lambda e:errors.append(str(e)))
        await page.goto(BASE)
        await expect(page.locator('[data-channel-key]')).to_have_count(4)
        for platform in ('soop','cime'):
            await page.get_by_role('button',name='플랫폼 선택:',exact=False).click()
            await page.get_by_role('option',name=LABELS[platform],exact=True).click()
            field=page.get_by_role('textbox',name=LABELS[platform]+' 채널 ID 또는 채널 링크')
            await field.fill('https://example.com/wrong')
            await page.get_by_role('button',name='채널 추가 설정 열기').click()
            await expect(page.get_by_role('alert').first).to_contain_text('올바른 '+LABELS[platform])
            await field.fill('https://play.sooplive.co.kr/ALICE' if platform=='soop' else 'https://ci.me/@alice/live')
            await page.get_by_role('button',name='채널 추가 설정 열기').click()
            dialog=page.get_by_role('dialog')
            quality=dialog.locator('#channel-recording-quality')
            await expect(quality).to_be_enabled()
            await quality.select_option('2160p60')
            await dialog.get_by_role('button',name='채널 추가',exact=True).click()
            await expect(dialog).not_to_be_visible()
            data=[call[2] for call in calls if call[0]=='/api/platforms/channels'][-1]
            assert data['platform']==platform and data['channel_id']=='alice' and data['recording_quality']=='2160p60',data
        for platform in ('soop','cime'):
            card=page.locator('[data-channel-key="'+platform+':alice"]')
            await card.get_by_role('button',name='녹화 설정',exact=True).click()
            dialog=page.get_by_role('dialog')
            await expect(dialog.locator('#channel-recording-quality')).to_be_enabled()
            await dialog.locator('#channel-recording-quality').select_option('720p60')
            await dialog.get_by_role('button',name='설정 저장',exact=True).click()
            assert [call[2] for call in calls if call[0].endswith('/download-options')][-1]['recording_quality']=='720p60'
            await card.get_by_role('button',name='상세 보기: '+LABELS[platform]+' 샘플').click()
            image=card.get_by_role('img',name=LABELS[platform]+' 샘플 방송 미리보기')
            await expect(image).to_be_visible()
            assert await image.evaluate('(image)=>image.naturalWidth')==1920
        before=frames['soop:alice']; await asyncio.sleep(5.3); assert frames['soop:alice']>before
        for width in (360,390,768,1024,1440):
            await page.set_viewport_size({'width':width,'height':1000})
            for mode in ('카드로 보기','목록으로 보기'):
                await page.get_by_role('button',name=mode,exact=True).click()
                assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(width,mode)
                if width in (390,1440): await page.screenshot(path=str(OUT/f'live-{width}-{mode}.png'),full_page=True)
            if width in (390,1440):
                for platform in ('soop','cime'):
                    await page.locator('[data-channel-key="'+platform+':alice"]').screenshot(path=str(OUT/f'{platform}-card-{width}.png'))
        for platform in ('soop','cime'):
            await page.locator('[data-channel-key="'+platform+':alice"]').get_by_role('button',name='상세 접기: '+LABELS[platform]+' 샘플').click()
        before=dict(frames); await asyncio.sleep(5.3); assert frames==before
        fail_frame=True
        card=page.locator('[data-channel-key="cime:alice"]')
        await card.get_by_role('button',name='상세 보기: 씨미 샘플').click()
        await expect(card).to_contain_text('미리보기를 불러올 수 없습니다.')
        fail_frame=False; await card.get_by_role('button',name='다시 시도',exact=True).click()
        await expect(card.get_by_role('img',name='씨미 샘플 방송 미리보기')).to_be_visible()
        await page.goto(BASE+'/vod')
        panel=page.get_by_test_id('vod-preparation')
        await panel.get_by_role('combobox').click()
        for platform in ('soop','cime'): await expect(panel.get_by_role('option',name=LABELS[platform],exact=True)).to_be_visible()
        await panel.get_by_role('option',name='씨미',exact=True).click()
        await panel.get_by_role('textbox').fill('https://ci.me/@alice/vods/1\nhttps://vod.sooplive.co.kr/player/123\nhttps://youtu.be/abcdefghijk')
        await panel.get_by_role('button',name='목록에 추가',exact=True).click()
        await expect(page.locator('[data-task-id]')).to_have_count(3)
        data=[call[2] for call in calls if call[0]=='/api/vod/prepare'][-1]
        assert 'source' not in data and 'https://vod.sooplive.com/player/123' in data['urls'],data
        for width in (360,390,768,1024,1440):
            await page.set_viewport_size({'width':width,'height':1000})
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
        await page.goto(BASE+'/settings')
        await page.get_by_role('button',name='인증',exact=True).click()
        for platform in ('soop','cime'):
            card=page.locator('[data-cookie-platform="'+platform+'"]')
            await expect(card).to_contain_text('등록된 쿠키 없음')
            await card.locator('input[type=file]').set_input_files({'name':'fixture.txt','mimeType':'text/plain','buffer':b'# Netscape HTTP Cookie File\n.ci.me\tTRUE\t/\tTRUE\t2147483647\tsession-id\tFIXTURE_SECRET\n'})
            await expect(card).to_contain_text('쿠키 파일 등록됨')
            await expect(card).not_to_contain_text('FIXTURE_SECRET')
            await card.get_by_role('button',name=LABELS[platform]+' 쿠키 파일 삭제').click()
            await page.get_by_role('dialog').get_by_role('button',name='삭제',exact=True).click()
            await expect(card).to_contain_text('등록된 쿠키 없음')
        assert not errors, errors
        await page.set_viewport_size({'width':1440,'height':1000})
        await page.screenshot(path=str(OUT/'auth-1440.png'),full_page=True)
        print('PASS: 4 platforms, URL validation/normalization, dynamic qualities, shared cards, genuine 1080p frames, refresh/cleanup/retry, mixed VOD registration, cookies and responsive widths 360/390/768/1024/1440')
        await browser.close()

if __name__=='__main__': asyncio.run(main())
