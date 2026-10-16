"""Production UI export code: isolated IndexedDB -> file -> real API import."""
import asyncio
from functools import lru_cache
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
from urllib.parse import urlsplit

from playwright.async_api import async_playwright, expect

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api import platforms
from app.core import utils
from app.core.config import Settings
from app.engine import rplay
from browser_fixtures import mock

BASE = os.environ.get('PHROLOVA_TEST_URL', 'http://127.0.0.1:3021')
OUT = Path(__file__).resolve().parents[4] / 'work/rplay-auth-export-ui'


async def check(client, directory):
    async def route_api(route):
        req = route.request
        path = urlsplit(req.url).path
        if path == '/api/platforms/rplay/session':
            response = await asyncio.to_thread(client.request, req.method, path, content=req.post_data_buffer,
                headers={'Content-Type': req.headers.get('content-type', '')})
            return await route.fulfill(status=response.status_code, content_type='application/json', body=response.content)
        return await mock(route)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel='chrome')
        try:
            context = await browser.new_context(viewport={'width': 390, 'height': 900})
            await context.add_init_script('window.EventSource=class{close(){}}')
            await context.route('**/api/**', route_api)
            page = await context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            await page.goto(BASE + '/settings')
            await page.get_by_role('button', name='인증', exact=True).click()
            card = page.locator('[data-auth-platform=rplay]')
            await card.locator('summary').click()
            script = await card.locator('textarea').input_value()
            assert 'rplay-account-session' in script and 'fetch(' not in script
            await page.evaluate("Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async()=>{throw new Error('denied')}}})")
            await card.get_by_role('button', name='내보내기 코드 복사').click()
            assert await card.locator('textarea').evaluate('(e)=>e.selectionStart===0 && e.selectionEnd===e.value.length')
            await page.evaluate("Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async(text)=>{window.__copiedExport=text}}})")
            await card.get_by_role('button', name='내보내기 코드 복사').click()
            assert await page.evaluate('window.__copiedExport') == script
            OUT.mkdir(exist_ok=True)
            for width in (320, 390, 768, 1440):
                await page.set_viewport_size({'width': width, 'height': 1000})
                assert await page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), width
                await card.screenshot(path=str(OUT / f'auth-{width}.png'))

            source = await context.new_page()
            await source.route('**/*', lambda route: route.fulfill(content_type='text/html', body='<title>Isolated RPLAY fixture</title>'))
            await source.goto('https://rplay.live/fixture')
            record = {'revision': 'fixture', 'session': {'user': {'oid': 'a' * 24, 'email': 'DO-NOT-EXPORT'},
                'token': 'PRIVATE-fixture-access-token', 'loginType': 'rplay', 'refreshToken': 'DO-NOT-EXPORT'}}
            await source.evaluate('''record => new Promise((resolve,reject)=>{
                const open=indexedDB.open('rplay-account-session',1);
                open.onupgradeneeded=()=>open.result.createObjectStore('records');
                open.onerror=()=>reject(open.error);
                open.onsuccess=()=>{const db=open.result;const tx=db.transaction('records','readwrite');
                    tx.objectStore('records').put(record,'session');tx.oncomplete=()=>{db.close();resolve()}};
            })''', record)
            async with source.expect_download() as download_event:
                await source.evaluate(script)
            download = await download_event.value
            assert download.suggested_filename == 'rplay_session.json'
            destination = directory / 'export.json'
            await download.save_as(destination)
            data = json.loads(destination.read_text())
            assert data == {'accessToken': record['session']['token'], 'requestorOid': 'a' * 24, 'loginType': 'rplay'}
            assert 'DO-NOT-EXPORT' not in destination.read_text()
            assert rplay.parse_session(destination.read_bytes()) == data
            # CDP omits disk-backed file bodies from intercepted request.postData;
            # use the actual downloaded bytes as an in-memory browser File instead.
            await card.locator('input[type=file]').set_input_files({
                'name': download.suggested_filename, 'mimeType': 'application/json', 'buffer': destination.read_bytes()})
            await expect(card).to_contain_text('세션 파일 등록됨')
            assert json.loads((directory / 'rplay_session.json').read_text()) == data
            # Wrong origins must never open browser storage; a signed-out session must not export.
            for target in ('wrong-origin', 'signed-out'):
                if target == 'wrong-origin':
                    await source.goto(BASE)
                else:
                    await source.goto('https://rplay.live/fixture')
                    await source.evaluate('''() => new Promise(resolve=>{const r=indexedDB.open('rplay-account-session');
                        r.onsuccess=()=>{const d=r.result;const t=d.transaction('records','readwrite');
                        t.objectStore('records').put({session:null},'session');t.oncomplete=()=>{d.close();resolve()}}})''')
                async with source.expect_event('dialog') as dialog_event:
                    task = asyncio.create_task(source.evaluate(script))
                dialog = await dialog_event.value
                assert ('로그인한 페이지' if target == 'wrong-origin' else '로그인 정보를 찾지 못했습니다') in dialog.message
                await dialog.dismiss()
                await task
            assert not errors, errors
        finally:
            await browser.close()
    print('PASS: production export code, readonly IndexedDB, minimal file/no refresh token, real multipart API import, wrong-origin/signed-out handling, 320–1440px')


def main():
    app = FastAPI()
    app.include_router(platforms.router)
    settings = Settings(_env_file=None, rplay_session_file=None)
    cached = lru_cache()(lambda: settings)
    with tempfile.TemporaryDirectory(prefix='rplay-export-test-') as temporary:
        directory = Path(temporary)
        with patch.object(platforms, '_COOKIE_SAVE_PATH', directory / 'cookies.txt'), \
             patch.object(platforms, 'get_settings', cached), patch.object(rplay, 'get_settings', cached), \
             patch.object(utils, '_get_env_path', lambda: directory / '.env'), TestClient(app) as client:
            asyncio.run(check(client, directory))


if __name__ == '__main__':
    main()
