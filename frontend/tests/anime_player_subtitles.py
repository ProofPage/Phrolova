"""Exercise the real player with local subtitle input, without external media."""
import asyncio
import os
from playwright.async_api import async_playwright, expect

HTML = """<html><body><div id="root"></div><script type="module">
import RefreshRuntime from '/@react-refresh';
RefreshRuntime.injectIntoGlobalHook(window);
window.$RefreshReg$ = () => {};
window.$RefreshSig$ = () => (type) => type;
window.__vite_plugin_react_preamble_installed__ = true;
const React = (await import('/node_modules/.vite/deps/react.js')).default;
const {createRoot} = (await import('/node_modules/.vite/deps/react-dom_client.js')).default;
const {AnimePlayerModal} = await import('/src/components/anime/AnimePlayerModal.tsx');
const root = createRoot(document.getElementById('root'));
window.mountPlayer = (ep=1) => root.render(React.createElement(AnimePlayerModal, {
 anime: {mal_id: 1, title: 'Subtitle test'}, episodeNumber: ep,
 streamUrl: '/test-media.mp4', onClose: () => root.unmount()
}));
window.mountPlayer();
</script></body></html>"""


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        await page.route("**/player-audit", lambda r: r.fulfill(body=HTML, content_type="text/html"))
        await page.route("**/api/**", lambda r: r.fulfill(json={"found": False, "results": []}))
        await page.route("**/test-media.mp4", lambda r: r.fulfill(status=204))
        try:
            await page.goto(os.environ.get("PHROLOVA_TEST_URL", "http://127.0.0.1:3000").rstrip("/") + "/player-audit")
            await page.get_by_role("button", name="Settings", exact=True).click()
            await page.get_by_role("button", name="자막", exact=True).click()
            await expect(page.get_by_text("[Official] Episode 01 Dialogue.srt")).to_have_count(0)
            await page.locator('input[type=file]').set_input_files({
                "name": "test.vtt", "mimeType": "text/vtt",
                "buffer": b"WEBVTT\n\n00:00:00.000 --> 00:00:10.000\nSubtitle test\n",
            })
            await page.wait_for_function("""() => {
                const t = document.querySelector('video')?.textTracks[0];
                return t?.mode === 'showing' && t.cues?.length === 1;
            }""")
            await page.locator('input[type=checkbox]').check()
            await page.wait_for_function("document.querySelector('video').textTracks[0].mode === 'disabled'")
            await page.locator('input[type=checkbox]').uncheck()
            await page.wait_for_function("document.querySelector('video').textTracks[0].mode === 'showing'")
            await page.locator('input[type=file]').set_input_files({
                "name": "bad.vtt", "mimeType": "text/vtt", "buffer": b"not a subtitle",
            })
            await expect(page.get_by_text("올바른 WebVTT 자막 파일을 선택하세요.", exact=True)).to_be_visible()
            await page.evaluate("window.mountPlayer(2)")
            await expect(page.locator("video track")).to_have_count(0)
            assert not errors, errors
            print("PASS: actual track cues, hide/show, invalid file, episode cleanup")
        except Exception:
            print("Page errors:", errors)
            print("Page text:", (await page.locator("body").inner_text())[:1000])
            raise
        finally:
            await browser.close()


asyncio.run(main())
