"""Regressions: monitor states, 16:9 preview stages, logs and forms."""
import asyncio, copy, json, os
from pathlib import Path
from urllib.parse import urlparse
from playwright.async_api import async_playwright, expect
from browser_fixtures import FIX, mock
BASE=os.environ.get("PHROLOVA_TEST_URL","http://127.0.0.1:3001")
OUT=Path(os.environ["PHROLOVA_TEST_OUTPUT"])
WIDTHS=(320,375,430,640,768,1024,1280,1440,1920,2560)
async def main():
    OUT.mkdir(parents=True,exist_ok=True)
    channels=[]
    for i,platform in enumerate(("cime","chzzk","rplay")):
        c=copy.deepcopy(FIX["channels"][0])
        c.update(platform=platform,composite_key=f"{platform}:audit",channel_id="audit",channel_name=platform,
            is_live=False,recording=None,last_error=None,monitor_error="상태 조회 시간 초과" if i==0 else None,
            monitor_status="retry_wait" if i==0 else "watching",broadcast_status="error" if i==0 else "offline",
            title=None,postprocess=None,recording_quality="best",recent_errors=[])
        channels.append(c)
    job=dict(id="warn",composite_key="rplay:old",platform="rplay",channel_name="경고 완료 파일",state="completed",target_format="mkv",
        progress=100,output_path="/output/result.mkv",source_paths=["/output/source.ts"],source_available=True,output_available=True,
        can_open=True,can_inspect=True,can_retry=True,inspection_state="passed",error_message=None,
        warning_message="변환 결과 검사를 통과했지만 FFmpeg 경고가 있습니다. 원본 파일은 보관합니다.",
        diagnostics={"returncode":0,"stderr":("Packet corrupt (stream = 0)\r\ncorrupt input packet in stream 0\n"*20)})
    async def route_api(route):
        path=urlparse(route.request.url).path
        if path=="/api/platforms/channels":return await route.fulfill(json=channels)
        if path=="/api/recordings/jobs":return await route.fulfill(json={"jobs":[job]})
        if path=="/api/system/media-tools":return await route.fulfill(json={p:{"available":True,"path":"C:/bin/"+p+".exe"} for p in ("ffmpeg","ffprobe")})
        return await mock(route)
    async with async_playwright() as p:
        browser=await p.chromium.launch()
        context=await browser.new_context(permissions=["clipboard-read","clipboard-write"])
        await context.add_init_script("window.EventSource=class{close(){}};window.opened=[];window.open=u=>window.opened.push(u)")
        await context.route("**/api/**",route_api)
        page=await context.new_page();errors=[];page.on("pageerror",lambda e:errors.append(str(e)))
        results=[]
        async def verify(label):
            geometry=await page.evaluate("""()=>({page:document.documentElement.scrollWidth-innerWidth,main:document.querySelector('#main-content').scrollWidth-document.querySelector('#main-content').clientWidth})""")
            assert geometry["page"]==geometry["main"]==0,(label,geometry)
            assert not errors,(label,errors)
        for width in WIDTHS:
            await page.set_viewport_size({"width":width,"height":1000})
            await page.goto(BASE)
            await expect(page.locator("[data-channel-key]")).to_have_count(3)
            await expect(page.get_by_text("녹화 시작 실패",exact=True)).to_have_count(0)
            await expect(page.get_by_text("상태 확인 실패",exact=True)).to_be_visible()
            await page.get_by_role('button',name='오프라인 2',exact=True).click()
            await expect(page.locator('[data-channel-key]')).to_have_count(2)
            await expect(page.get_by_text('상태 확인 실패',exact=True)).to_have_count(0)
            await page.get_by_role('button',name='전체 3',exact=True).click()
            await expect(page.locator('[data-channel-key]')).to_have_count(3)
            for c in channels:
                await page.locator(f'[data-channel-key="{c["composite_key"]}"] .recording-detail-action').click()
            for mode,label in (("grid","카드로 보기"),("list","목록으로 보기")):
                await page.get_by_role("button",name=label,exact=True).click()
                await verify((width,mode))
                stages=await page.locator(".channel-preview-stage").evaluate_all("es=>es.map(e=>{const r=e.getBoundingClientRect();return {width:r.width,height:r.height}})")
                assert all(abs(s['width']*9/16-s['height'])<1.5 for s in stages),(width,mode,stages)
                if width in (320,1440):await page.screenshot(path=str(OUT/f"live-{width}-{mode}.png"),full_page=True)
                results.append({"width":width,"mode":mode,"previewStages":stages})
            if width==1440:
                history=page.locator(".recording-history-row").first
                await history.locator("summary").click()
                log=await history.locator("pre").inner_text()
                assert "\\n" not in log and "\n" in log,log
                await history.get_by_role("button",name="로그 복사").click()
                await expect(page.get_by_text("로그를 복사했습니다.",exact=True)).to_be_visible()
                copied=await page.evaluate("navigator.clipboard.readText()")
                assert copied.replace("\r\n","\n")==log.replace("\r\n","\n"),(repr(copied[:150]),repr(log[:150]),len(copied),len(log))
                # Insecure remote HTTP lacks Clipboard API: fallback must not throw.
                await page.evaluate("""()=>{Object.defineProperty(navigator,'clipboard',{configurable:true,value:undefined});document.execCommand=command=>{window.fallbackLog=document.activeElement.value;return command==='copy'}}""")
                await history.get_by_role("button",name="로그 복사").click()
                assert (await page.evaluate("window.fallbackLog")).replace("\r\n","\n")==log.replace("\r\n","\n")
                assert not errors,errors
                await history.get_by_role("button",name="원본 파일 열기",exact=True).click()
                assert await page.evaluate("window.opened.at(-1)")=="/api/recordings/warn/file?source=true"
            live=await page.locator(".media-add-form .ui-input").evaluate_all("es=>es.map(e=>e.getBoundingClientRect().height)")
            await page.goto(BASE+"/vod")
            await page.get_by_test_id("vod-preparation").wait_for()
            await verify((width,"vod"))
            sizes=await page.locator(".media-add-form .ui-input").evaluate_all("es=>es.map(e=>e.getBoundingClientRect().height)")
            assert all(abs(h-live[0])<2 for h in sizes),(width,live,sizes)
            assert await page.get_by_test_id("vod-preparation").evaluate("e=>getComputedStyle(e).borderTopWidth")=="0px"
            if width in (320,1440):await page.screenshot(path=str(OUT/f"vod-{width}.png"),full_page=True)
            for route in ("stats","system-logs","settings"):
                await page.goto(BASE+"/"+route)
                await page.wait_for_timeout(200)
                await verify((width,route))
        (OUT/"geometry.json").write_text(json.dumps(results,indent=2),encoding="utf-8")
        await browser.close()
    print("PASS: 20 live states/modes, five menus at 10 widths, shared input heights, readable/copyable logs and source file action")
if __name__=="__main__":asyncio.run(main())
