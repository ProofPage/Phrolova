"""필터로 숨긴 항목 때문에 이동 버튼이 무반응처럼 보이는 회귀를 막는다."""
import asyncio, copy, json, os
from playwright.async_api import async_playwright
from browser_fixtures import FIX, mock
BASE = os.environ.get('PHROLOVA_TEST_URL', 'http://localhost:3000')

async def main():
 channels, tasks = copy.deepcopy(FIX['channels']), copy.deepcopy(FIX['tasks'])
 FIX['imports'] = []
 FIX['channels'] = []
 for i in range(4):
  channel = copy.deepcopy(channels[1 if i % 2 == 0 else 0])
  channel.update(channel_id=chr(65+i), channel_name=chr(65+i), last_error='')
  FIX['channels'].append(channel)
 async with async_playwright() as p:
  browser = await p.chromium.launch(executable_path=os.environ.get("PHROLOVA_CHROMIUM_EXECUTABLE"))
  context = await browser.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True)
  await context.add_init_script("localStorage.setItem('dashboardViewMode','grid');window.EventSource=class{close(){}}")
  await context.route('**/api/**',mock)
  await context.route('https://fonts.googleapis.com/**',lambda r:r.abort())
  await context.route('https://fonts.gstatic.com/**',lambda r:r.abort())
  page = await context.new_page()
  await page.goto(BASE)
  cards = page.locator('[data-channel-key]')
  await cards.first.wait_for()
  await page.locator('.dashboard-filter').nth(2).click()
  assert await cards.count() == 2
  await cards.first.locator('.channel-card-more').tap()
  dialog = page.get_by_role('dialog')
  assert await dialog.get_by_role('button',name='위로 이동',exact=True).is_disabled()
  await dialog.get_by_role('button',name='아래로 이동',exact=True).tap()
  order = await page.evaluate("JSON.parse(localStorage.getItem('dashboardChannelOrder'))")
  assert [key.split(':')[-1] for key in order] == ['C','B','A','D'],order
  await cards.first.locator('.channel-card-more').focus()
  await page.keyboard.press('ArrowUp')
  assert await page.evaluate("JSON.parse(localStorage.getItem('dashboardChannelOrder'))") == order
  await page.keyboard.press('ArrowDown')
  assert [key.split(':')[-1] for key in await page.evaluate("JSON.parse(localStorage.getItem('dashboardChannelOrder'))")] == ['A','B','C','D']
  FIX['tasks'] = []
  for i in range(4):
   task = copy.deepcopy(tasks[0])
   task.update(task_id=chr(65+i),title=chr(65+i),state='paused' if i%2==0 else 'idle')
   FIX['tasks'].append(task)
  payloads = []
  async def reorder(route):
   payload = route.request.post_data_json
   payloads.append(payload)
   lookup = {task['task_id']:task for task in FIX['tasks']}
   FIX['tasks'] = [lookup[key] for key in payload['task_ids']]
   await route.fulfill(json={'message':'ok'})
  await page.route('**/api/vod/reorder',reorder)
  await page.goto(BASE+'/vod')
  rows = page.locator('.download-row')
  await rows.first.wait_for()
  await page.get_by_role('button',name='일시정지 (2)',exact=True).click()
  assert await rows.count() == 2
  await rows.first.locator('.download-mobile-menu').tap()
  dialog = page.get_by_role('dialog')
  assert await dialog.get_by_role('button',name='위로 이동',exact=True).is_disabled()
  await dialog.get_by_role('button',name='아래로 이동',exact=True).tap()
  await page.wait_for_function("document.querySelector('.download-title')?.textContent==='C'")
  assert payloads == [{'task_ids':['C','B','A','D']}],payloads
  assert [task['state'] for task in FIX['tasks']] == ['paused','idle','paused','idle']
  await rows.last.locator('.download-mobile-menu').tap()
  assert await page.get_by_role('dialog').get_by_role('button',name='아래로 이동',exact=True).is_disabled()
  await browser.close()
 print('Live / Downloads filtered reorder: passed; hidden B D positions and API payload preserved')

if __name__ == '__main__': asyncio.run(main())
