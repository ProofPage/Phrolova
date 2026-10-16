"""Real browser Axios -> actual FastAPI multipart parsing, using synthetic sessions."""
import asyncio
from functools import lru_cache
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException
from playwright.async_api import async_playwright, expect

from app.api import platforms
from app.core import utils
from app.core.config import Settings
from app.core.error_messages import localized_http_error, localized_validation_error
from app.engine import rplay
from browser_fixtures import mock

BASE = os.environ.get('PHROLOVA_TEST_URL', 'http://127.0.0.1:3019')
SESSION = {'accessToken': 'transport-fixture-token-PRIVATE', 'requestorOid': 'a' * 24}


async def check(client, directory):
    uploads = []
    errors = []
    async def route_api(route):
        req = route.request
        path = urlsplit(req.url).path
        if path == '/api/platforms/rplay/session':
            response = await asyncio.to_thread(client.request, req.method, path,
                content=req.post_data_buffer,
                headers={'Content-Type': req.headers.get('content-type', '')})
            if req.method == 'POST':
                uploads.append((req.headers.get('content-type', ''), response.status_code))
            return await route.fulfill(status=response.status_code, content_type='application/json', body=response.content)
        return await mock(route)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel='chrome')
        try:
            context = await browser.new_context(viewport={'width': 390, 'height': 900})
            await context.add_init_script('window.EventSource=class{close(){}}')
            await context.route('**/api/**', route_api)
            page = await context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            await page.goto(BASE + '/settings')
            await page.get_by_role('button', name='인증', exact=True).click()
            card = page.locator('[data-auth-platform=rplay]')
            await card.locator('input[type=file]').set_input_files({
                'name': 'session.json', 'mimeType': 'application/json', 'buffer': json.dumps(SESSION).encode()})
            await expect(card).to_contain_text('세션 파일 등록됨')
            assert uploads[-1][0].startswith('multipart/form-data; boundary='), uploads
            assert uploads[-1][1] == 200, uploads
            assert json.loads((directory / 'rplay_session.json').read_text())['accessToken'] == SESSION['accessToken']
            assert not errors, errors
        finally:
            await browser.close()
    print('PASS: real browser multipart upload -> actual FastAPI validation -> saved session')


def main():
    app = FastAPI()
    app.include_router(platforms.router)
    app.add_exception_handler(HTTPException, localized_http_error)
    app.add_exception_handler(RequestValidationError, localized_validation_error)
    settings = Settings(_env_file=None, rplay_session_file=None)
    cached_settings = lru_cache()(lambda: settings)
    with tempfile.TemporaryDirectory(prefix='rplay-upload-') as temporary:
        directory = Path(temporary)
        with patch.object(platforms, '_COOKIE_SAVE_PATH', directory / 'cookies.txt'), \
             patch.object(platforms, 'get_settings', cached_settings), \
             patch.object(rplay, 'get_settings', cached_settings), \
             patch.object(utils, '_get_env_path', lambda: directory / '.env'), TestClient(app) as client:
            asyncio.run(check(client, directory))


if __name__ == '__main__':
    main()
