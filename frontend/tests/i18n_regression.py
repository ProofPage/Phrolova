"""Exercise the actual app in eight locales, without changing the user's browser data."""
import asyncio
import json
import os
import re
import copy
from urllib.parse import urlparse, unquote
from pathlib import Path
from playwright.async_api import async_playwright, expect
from browser_fixtures import mock, FIX

BASE = os.environ.get('PHROLOVA_TEST_URL', 'http://127.0.0.1:3001')
ROOT = Path(__file__).resolve().parents[1]
LOCALES = ['ko-KR', 'en-US', 'ja-JP', 'es-ES', 'de-DE', 'zh-CN', 'zh-TW', 'ru-RU']

async def main():
    issues = []
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        setup = False
        update_environment = 'windows-exe'
        calls = []
        channels = copy.deepcopy(FIX['channels'][:2])
        for index, channel in enumerate(channels):
            channel.update(channel_name=f'CHANNEL_{index}', title=f'TITLE_{index}', is_live=bool(index), auto_record=False,
                           channel_id=f'fixture-{index}', composite_key=f'chzzk:fixture-{index}', last_error='', tags=[],
                           recording={'state':'idle', 'is_recording':False})
        async def route_api(route):
            path = unquote(urlparse(route.request.url).path)
            request = route.request
            if request.method != 'GET': calls.append((request.method,path,request.post_data_json))
            if path == '/api/setup/status': return await route.fulfill(json={'needs_setup':setup,'default_directories':{'live_download_dir':'C:/Recordings/Live','vod_download_dir':'C:/Recordings/Video'}})
            if path == '/api/platforms/channels': return await route.fulfill(json=channels)
            if path == '/api/recordings/jobs': return await route.fulfill(json={'jobs':[]})
            if path.endswith('/auto-record'):
                channels[1]['auto_record'] = not channels[1]['auto_record']
                return await route.fulfill(json={'auto_record':channels[1]['auto_record']})
            if path.endswith('/start'):
                channels[1]['recording']={'state':'recording','is_recording':True}
                return await route.fulfill(json={'status':'ok'})
            if path.endswith('/stop'):
                channels[1]['recording']={'state':'completed','is_recording':False}
                return await route.fulfill(json={'status':'ok'})
            if path == '/api/settings':
                settings=copy.deepcopy(FIX['settings'])
                settings.update(app_name='Phrolova', host='127.0.0.1', discord_notify_enabled='all', notification_kinds=[{'value':value,'label':'fixture'} for value in ['live_detected','recording_started','recording_completed','recording_failed','vod_completed','vod_failed','cookie_expired','update_available','system']])
                return await route.fulfill(json=settings)
            if path == '/api/settings/recording-processing': return await route.fulfill(json={'output_format':'mkv','keep_source_ts':True,'max_concurrent':1})
            if path == '/api/system/media-tools': return await route.fulfill(json={name:{'available':True,'version':'8.6.2' if name=='streamlink' else '9.0.2','path':f'C:/Tools/{name}'} for name in ['streamlink','ffmpeg','ffprobe']})
            if path.startswith('/api/system/update'): return await route.fulfill(json={'current_version':'2.0.62','latest_version':'2.0.63','has_update':True,'checked_at':'2026-10-13T00:00:00','environment':update_environment,'download_url':'https://github.com/ProofPage/Phrolova/releases','release_notes':''})
            if path.endswith('/cookie') or path.endswith('/cookie/refresh'): return await route.fulfill(json={'configured':False, 'message':'쿠키가 등록되지 않았습니다.'})
            if path == '/api/platforms/status': return await route.fulfill(json={platform:{'enabled':True,'authenticated':False} for platform in ['chzzk','youtube','soop','cime']})
            return await mock(route)
        for locale in LOCALES:
            d=json.loads((ROOT/'src/i18n/locales'/f'{locale}.json').read_text(encoding='utf-8'))
            channels[1]['recording']={'state':'idle','is_recording':False}
            context = await browser.new_context(viewport={'width': 390, 'height': 844})
            # 초기화 코드는 매 페이지마다 언어를 덮어쓰지 않아 복원 검사에 영향을 주지 않는다.
            await context.add_init_script(f"if (!localStorage.getItem('phrolova-language')) localStorage.setItem('phrolova-language', {json.dumps(locale)}); window.EventSource=class{{close(){{}}}}")
            await context.route('**/api/**', route_api)
            page = await context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('console', lambda message: errors.append(message.text) if '[i18n] Missing' in message.text else None)
            for route in ('/', '/vod', '/stats', '/system-logs', '/settings'):
                await page.goto(BASE + route)
                await expect(page.locator('h1')).to_have_count(1)
                await expect(page.locator('html')).to_have_attribute('lang', locale)
                await page.wait_for_timeout(150)
                text = await page.locator('main').inner_text()
                leaked = sorted(set(re.findall(r'\b(?:common|live|download|settings|logs|stats|setup|platform)\.[A-Za-z][A-Za-z0-9.]*', text)))
                if leaked: issues.append((locale, route, 'keys', leaked))
                for width in (320, 390, 1440):
                    await page.set_viewport_size({'width':width,'height':844})
                    if not await page.evaluate('document.documentElement.scrollWidth <= innerWidth'):
                        issues.append((locale, route, width, 'horizontal overflow'))
                    clipped = await page.locator('button').evaluate_all("nodes => nodes.filter(n => n.getBoundingClientRect().width > 0 && n.scrollWidth > n.clientWidth + 2).map(n => n.textContent.trim())")
                    if clipped: issues.append((locale, route, width, 'clipped buttons',clipped))
                await page.set_viewport_size({'width':390,'height':844})
                if re.search(r'X Spaces|채팅 기록|라이브 채팅 저장', text):
                    issues.append((locale, route, 'removed feature'))
            nav=page.get_by_role('navigation',name=d['settings.settingsTabs'])
            for key in ['settings.authentication','settings.notifications','settings.appearanceInSettings','settings.aboutInSettings']:
                await nav.get_by_role('button',name=d[key],exact=True).click()
                text=await page.locator('main').inner_text()
                leaked=re.findall(r'\b(?:common|live|download|settings|logs|stats|setup|platform)\.[A-Za-z][A-Za-z0-9.]*',text)
                if leaked:issues.append((locale,key,leaked))
                assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth'),(locale,key)
                if key == 'settings.authentication':
                    await expect(page.locator('[data-cookie-platform]').first.get_by_role('status')).to_have_text(d['settings.cookieNotRegistered'])
                if key == 'settings.notifications':
                    for kind in ['live_detected','recording_started','recording_completed','recording_failed','vod_completed','vod_failed','cookie_expired','update_available','system']:
                        assert d[f'settings.notification.{kind}'] in text,(locale,kind)
            await page.get_by_role('button',name=d['settings.checkTools'],exact=True).click()
            await expect(page.get_by_role('button',name=d['settings.checkTools'],exact=True)).to_be_enabled()
            for environment in ['windows-exe','linux-native','windows-native']:
                update_environment=environment
                await page.get_by_role('button',name=d['settings.checkForUpdates'],exact=True).click()
                await page.get_by_role('button',name=d['settings.updateToVVersion'].replace('{version}','2.0.63'),exact=True).click()
                dialog=page.get_by_role('dialog',name=d['common.updateInstructions'])
                await expect(dialog).to_be_visible()
                text=await dialog.inner_text()
                assert not re.search(r'\b(?:common|settings)\.[A-Za-z]',text),(locale,environment)
                await page.set_viewport_size({'width':320,'height':844})
                assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth'),(locale,environment)
                await dialog.get_by_role('button',name=d['common.close'],exact=True).click()
                await page.set_viewport_size({'width':390,'height':844})
            await nav.get_by_role('button',name=d['settings.appearanceInSettings'],exact=True).click()
            selector=page.get_by_role('combobox',name=d['settings.language'],exact=True)
            await expect(selector.locator('option')).to_have_count(8)
            target='de-DE' if locale!='de-DE' else 'ja-JP'
            await selector.select_option(target)
            await expect(page.locator('html')).to_have_attribute('lang',target)
            target_d=json.loads((ROOT/'src/i18n/locales'/f'{target}.json').read_text(encoding='utf-8'))
            await expect(page.locator('.toast-stack')).to_contain_text(target_d['settings.aNewVersionIsAvailable'])
            await page.reload()
            await expect(page.locator('html')).to_have_attribute('lang',target)
            await page.get_by_role('navigation',name=target_d['settings.settingsTabs']).get_by_role('button',name=target_d['settings.appearanceInSettings'],exact=True).click()
            await page.get_by_role('combobox',name=target_d['settings.language'],exact=True).select_option(locale)
            await page.goto(BASE+'/')
            await expect(page.get_by_role('button',name=d['live.startRecording'],exact=True)).to_be_visible()
            await page.get_by_role('switch',name=f"CHANNEL_1 {d['live.autoRecord']}").click()
            await page.get_by_role('button',name=d['live.recordingSettings'],exact=True).last.click()
            dialog=page.get_by_role('dialog')
            await expect(dialog).to_be_visible()
            assert 'platform.chzzk' not in await dialog.inner_text()
            await page.set_viewport_size({'width':320,'height':844})
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth'),(locale,'recording modal')
            await dialog.get_by_role('button',name=d['common.cancel'],exact=True).click()
            await page.get_by_role('button',name=d['live.startRecording'],exact=True).click()
            await expect(page.get_by_role('button',name=d['live.stopRecording'],exact=True)).to_be_visible()
            await page.get_by_role('button',name=d['live.stopRecording'],exact=True).click()
            await page.get_by_role('dialog').get_by_role('button',name=d['live.stop'],exact=True).click()
            await expect(page.get_by_role('button',name=d['live.startRecording'],exact=True)).to_be_visible()
            assert any(path.endswith('/auto-record') for _,path,_ in calls)
            assert any(path.endswith('/start') for _,path,_ in calls)
            assert any(path.endswith('/stop') for _,path,_ in calls)
            setup=True
            await page.goto(BASE+'/')
            await expect(page.get_by_role('dialog')).to_be_visible()
            await expect(page.get_by_role('heading',name=d['setup.basicSettings'],exact=True)).to_be_visible()
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth'),(locale,'setup modal')
            assert not re.search(r'\b(?:common|live|download|settings|setup)\.[A-Za-z]',await page.get_by_role('dialog').inner_text())
            setup=False
            assert not errors, (locale, errors)
            await context.close()
        await browser.close()
    assert not issues, issues
    print('PASS: eight locales across five pages and all settings tabs; 320/390/1440px, immediate switching/reload restoration, setup/recording/update dialogs and existing toasts, auto-record/start/stop, cookies, media tools, no missing/leaked keys/overflow/removed features')

if __name__ == '__main__': asyncio.run(main())
