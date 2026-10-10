"""Download success/inspection failure, retry, diagnostics and mobile regression."""
import asyncio
import copy
import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright, expect
from browser_fixtures import FIX, mock

BASE = os.environ.get('PHROLOVA_TEST_URL', 'http://127.0.0.1:3000')
OUT = Path(os.environ.get('PHROLOVA_TEST_OUTPUT', tempfile.gettempdir() + '/phrolova-vod-ui'))
OUT.mkdir(parents=True, exist_ok=True)


async def check(browser, width):
    task = copy.deepcopy(FIX['tasks'][0])
    task.update(task_id='completed', url='https://chzzk.naver.com/video/15513116', title='[채널] 한글 영상 제목 ' * 12,
                state='completed', phase='verifying', prepared=True, progress=100,
                quality='1080p', cdn='akamai', output_path='/storage/한글 영상 [1080p].ts',
                file_size=4885525299, completed_at='2026-10-10T16:42:42', error_message=None,
                inspection_state='failed', inspection_code='timeout', inspection_message='파일 검사 시간이 초과되었습니다.',
                inspection_diagnostics={'stderr': 'ffprobe diagnostic ' * 100, 'returncode': None},
                metadata={'id': '15513116', 'duration': 7370, 'uploader': '테스트 채널'})
    tasks = [task]; requests = []; errors = []
    context = await browser.new_context(viewport={'width': width, 'height': 1000}, is_mobile=width < 500, has_touch=width < 500)
    await context.add_init_script("localStorage.setItem('phrolova-language','ko');window.EventSource=class{close(){}}")
    async def route_api(route):
        path = urlparse(route.request.url).path
        requests.append(path)
        if path == '/api/vod/status': return await route.fulfill(json={'tasks': tasks, 'active_count': 0, 'imports': []})
        if path == '/api/vod/completed/inspect':
            task.update(inspection_state='running', inspection_message='파일 정보를 확인하고 있습니다.')
            return await route.fulfill(status=202, json=task)
        if path == '/api/vod/completed/open-location':
            return await route.fulfill(json={'message': '헤드리스 서버에서는 표시된 저장 경로를 사용하세요.', 'path': task['output_path']})
        if path == '/api/vod/completed' and route.request.method == 'DELETE':
            tasks.clear(); return await route.fulfill(json={'deleted_count': 1})
        return await mock(route)
    await context.route('**/api/**', route_api)
    page = await context.new_page(); page.on('pageerror', lambda e: errors.append(str(e)))
    await page.goto(BASE + '/vod')
    card = page.locator('[data-task-id="completed"]')
    await expect(card.get_by_text('다운로드 완료', exact=True)).to_be_visible()
    await expect(card.get_by_text('파일 확인 필요', exact=True)).to_be_visible()
    await expect(card.get_by_text('파일 검사 시간이 초과되었습니다.', exact=True)).to_be_visible()
    if width < 500:
        box = await card.get_by_role('button', name='다시 검사', exact=True).bounding_box()
        assert box['height'] >= 44
    await expect(page.get_by_text('전체 1건 · 완료 1건 · 진행 중 0건 · 실패 0건', exact=False)).to_be_visible()
    assert 'FFprobe' not in await card.inner_text()  # Diagnostic details start collapsed.
    await card.get_by_text('파일 검사 상세 정보', exact=True).click()
    await expect(card.locator('pre')).to_contain_text('FFprobe')
    assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    await card.get_by_text('파일 검사 상세 정보', exact=True).click()
    await page.screenshot(path=str(OUT / f'vod-inspection-warning-{width}.png'), full_page=True)
    await card.get_by_role('button', name='다시 검사', exact=True).click()
    await expect(card.get_by_role('button', name='파일 검사 중', exact=True)).to_be_disabled()
    await expect(card.get_by_role('button', name='다시 다운로드', exact=True)).to_be_disabled()
    await expect(card.get_by_role('button', name='목록에서 제거', exact=True)).to_be_disabled()
    assert requests.count('/api/vod/completed/inspect') == 1
    task.update(inspection_state='passed', inspection_message='파일 검사 완료', inspection_code=None, inspection_diagnostics={})
    await expect(card.get_by_text('파일 검사 완료', exact=True)).to_be_visible(timeout=6000)
    await expect(card.get_by_text('파일 확인 필요', exact=True)).to_have_count(0)
    await page.reload(); await expect(card.get_by_text('파일 검사 완료', exact=True)).to_be_visible()
    await card.get_by_role('button', name='저장 폴더 열기', exact=True).click()
    await expect(page.get_by_text('헤드리스 서버에서는 표시된 저장 경로를 사용하세요.', exact=True)).to_be_visible()
    await card.get_by_text('저장 위치', exact=True).click()
    await expect(card.get_by_text('/storage/한글 영상 [1080p].ts', exact=True)).to_be_visible()
    await card.get_by_role('button', name='목록에서 제거', exact=True).click()
    await expect(card).to_have_count(0)
    panel = page.get_by_test_id('vod-preparation')
    await expect(panel.get_by_role('button', name='목록에 추가', exact=True)).to_be_disabled()
    await expect(panel.get_by_role('button', name='전체 다운로드 (0)', exact=True)).to_be_disabled()
    await panel.get_by_role('textbox').fill('https://chzzk.naver.com/clips/Clip_123\nhttps://chzzk.naver.com/live/unsupported')
    await panel.get_by_role('textbox').focus()
    await page.keyboard.press('ArrowRight')
    await expect(panel.get_by_role('textbox')).to_have_css('outline-width', '2px')
    await expect(panel.get_by_text('입력 2건 · 목록에 추가한 후 화질을 선택하세요.', exact=True)).to_be_visible()
    assert not errors, errors
    await context.close()
    print('VOD inspection browser PASS', width)


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=os.environ.get('PHROLOVA_CHROMIUM_EXECUTABLE'))
        for width in (390, 1440): await check(browser, width)
        await browser.close()


if __name__ == '__main__': asyncio.run(main())
