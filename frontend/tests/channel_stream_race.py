"""A late initial GET must not overwrite a newer SSE status snapshot."""
import asyncio, copy, os
from urllib.parse import urlparse
from playwright.async_api import async_playwright, expect
from browser_fixtures import FIX, mock
BASE=os.environ.get("PHROLOVA_TEST_URL","http://127.0.0.1:3001")
async def main():
    old=copy.deepcopy(FIX["channels"][:1])
    newer=copy.deepcopy(old)
    newer[0].update(channel_name="최신 SSE 이름", last_error="", recording=None, is_live=False)
    gate=asyncio.Event()
    pending=asyncio.Event()
    async with async_playwright() as p:
        browser=await p.chromium.launch()
        context=await browser.new_context()
        await context.add_init_script("window.sources=[];window.EventSource=class{constructor(){window.sources.push(this)}close(){this.closed=true}}")
        async def route(route):
            if urlparse(route.request.url).path=="/api/platforms/channels":
                pending.set();await gate.wait();return await route.fulfill(json=old)
            return await mock(route)
        await context.route("**/api/**",route)
        page=await context.new_page()
        await page.goto(BASE)
        await pending.wait()
        await page.evaluate("data=>window.sources.filter(s=>!s.closed).forEach(s=>s.onmessage({data:JSON.stringify({type:'status_update',data})}))",newer)
        await expect(page.get_by_text("최신 SSE 이름",exact=True)).to_be_visible()
        gate.set();await page.wait_for_timeout(400)
        await expect(page.get_by_text("최신 SSE 이름",exact=True)).to_be_visible()
        await browser.close()
    print("PASS: delayed GET cannot replace newer SSE status")
if __name__=='__main__':asyncio.run(main())
