"""Browser contracts for recording repair states, grouped history and CDN settings."""

import asyncio, copy, os
from pathlib import Path
from urllib.parse import urlparse
from playwright.async_api import async_playwright, expect
from browser_fixtures import FIX, mock

BASE = os.environ.get("PHROLOVA_TEST_URL", "http://127.0.0.1:3001")
OUT = Path(os.environ["PHROLOVA_TEST_OUTPUT"])


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    settings = copy.deepcopy(FIX["settings"])
    settings["chzzk_live_cdn"] = "default"
    settings["chzzk_vod_cdn"] = "default"
    policy = dict(output_format="mkv", keep_source_ts=True, max_concurrent=1)
    calls = []
    channels = []
    jobs = []
    for index in range(2):
        c = copy.deepcopy(FIX["channels"][1])
        c.update(
            platform="chzzk",
            composite_key=f"chzzk:repair-{index}",
            channel_id=f"repair-{index}",
            channel_name=["녹화 중인 채널", "연결 실패 채널"][index],
            title="긴 방송 제목 " * 20,
            is_live=True,
            auto_record=index == 0,
            tags=[],
            postprocess=None,
            last_error=None if index == 0 else "설정 → 인증에서 쿠키를 확인하세요.",
            recording=dict(
                session_id=f"session-{index}",
                state="recording" if index == 0 else "error",
                is_recording=index == 0,
                has_data=index == 0,
                duration_seconds=7200 if index == 0 else 0,
                file_size_bytes=800000000 if index == 0 else 0,
                download_speed=1.62 if index == 0 else 0,
                bitrate=13570 if index == 0 else 0,
                start_time="2026-10-11T00:00:00Z" if index == 0 else None,
                output_path="/sample/녹화.ts",
            ),
        )
        channels.append(c)
    for index, state in enumerate(["idle", "reconnecting", "offline"], start=2):
        c = copy.deepcopy(channels[1])
        c.update(
            composite_key=f"chzzk:repair-{index}",
            channel_id=f"repair-{index}",
            channel_name=state,
            last_error=None,
            auto_record=True,
            is_live=state != "offline",
        )
        c["recording"] = (
            None
            if state == "offline"
            else dict(
                state=state, is_recording=False, has_data=False, file_size_bytes=0
            )
        )
        channels.append(c)
    for index, state in enumerate(
        [
            "capture_failed",
            "capture_failed",
            "capture_failed",
            "completed",
            "normalizing",
        ]
    ):
        jobs.append(
            dict(
                id=f"job-{index}",
                composite_key="chzzk:old" if index < 3 else f"chzzk:old-{index}",
                platform="chzzk",
                channel_name=(
                    "이전 시작 실패"
                    if index < 3
                    else "완료한 녹화" if index == 3 else "원본 변환 작업"
                ),
                state=state,
                capture_format="fmp4" if index == 4 else "ts",
                started_at="2026-10-11T09:00:00",
                target_format="mkv",
                progress=None,
                file_size_bytes=0 if index < 3 else 60000000,
                source_paths=["/sample/녹화.ts"],
                output_path="/sample/녹화.mkv" if index == 3 else None,
                source_available=index >= 3,
                output_available=index == 3,
                can_open=index == 3,
                can_retry=False,
                can_inspect=index == 3,
                error_message=(
                    "녹화가 시작되지 않아 변환할 파일이 없습니다."
                    if index < 3
                    else None
                ),
                inspection_state="passed" if index == 3 else "pending",
                diagnostics={"detail": "sample startup failure"} if index < 3 else {},
            )
        )

    fail_auto = True

    async def route_api(route):
        path = urlparse(route.request.url).path
        request = route.request
        if request.method != "GET":
            calls.append((path, request.post_data_json))
        if path == "/api/platforms/channels":
            return await route.fulfill(json=channels)
        if "/download-options" in path and request.method == "PUT":
            channels[1].update(request.post_data_json)
            return await route.fulfill(json={"message": "saved"})
        if path.endswith("/auto-record"):
            await asyncio.sleep(0.2)
            if fail_auto:
                return await route.fulfill(status=500, json={"detail": "save failed"})
            channels[0]["auto_record"] = not channels[0]["auto_record"]
            return await route.fulfill(json={"message": "saved"})
        if path.startswith("/api/stream/record/"):
            await asyncio.sleep(0.2)
            if path.endswith("/start"):
                channels[1]["last_error"] = None
                channels[1]["recording"].update(
                    state="recording",
                    is_recording=True,
                    has_data=True,
                    file_size_bytes=1024,
                    duration_seconds=1,
                )
            elif path.endswith("/stop"):
                channels[1]["recording"].update(state="completed", is_recording=False)
            return await route.fulfill(json={"message": "saved"})
        if path == "/api/settings":
            return await route.fulfill(json=settings)
        if path == "/api/settings/live":
            settings.update(request.post_data_json)
            return await route.fulfill(json={"settings": settings})
        if path == "/api/settings/vod":
            settings.update(request.post_data_json)
            return await route.fulfill(json={"settings": settings})
        if path == "/api/recordings/settings":
            return await route.fulfill(json=policy)
        if path == "/api/recordings/jobs":
            return await route.fulfill(json={"jobs": jobs})
        if path == "/api/recordings/history/clear":
            ids = request.post_data_json["job_ids"]
            jobs[:] = [job for job in jobs if job["id"] not in ids]
            return await route.fulfill(
                json={"message": "이력을 목록에서 제거했습니다."}
            )
        return await mock(route)

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(viewport={"width": 1440, "height": 1000})
        await context.add_init_script(
            "window.EventSource=class{close(){}};localStorage.setItem('dashboardViewMode','list')"
        )
        await context.route("**/api/**", route_api)
        page = await context.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.goto(BASE)
        failed = page.locator('[data-channel-key="chzzk:repair-1"]')
        await expect(failed).to_contain_text("녹화 시작 실패")
        assert await failed.locator(".recording-metrics dd").all_text_contents() == [
            "—",
            "0 B",
            "—",
            "—",
        ]
        history = page.get_by_role("region", name="녹화 파일 처리 이력")
        await expect(history.locator(".recording-history-row")).to_have_count(3)
        await expect(history).to_contain_text("파일 없는 시작 실패 3건")
        empty = history.locator(".recording-history-row").filter(
            has_text="이전 시작 실패"
        )
        await expect(
            empty.get_by_role("button", name="원본 파일 열기")
        ).to_be_disabled()
        await expect(empty.get_by_role("button", name="다시 변환")).to_be_disabled()
        for width in (360, 390, 768, 1024, 1440, 1920):
            await page.set_viewport_size({"width": width, "height": 1000})
            for name, mode in [("카드로 보기", "grid"), ("목록으로 보기", "list")]:
                await page.get_by_role("button", name=name, exact=True).click()
                assert await page.evaluate(
                    "document.documentElement.scrollWidth<=innerWidth"
                ), (width, mode)
                if mode == "grid":
                    rows = await page.locator(".recording-channel").evaluate_all(
                        """cs=>cs.map(c=>({subgrid:getComputedStyle(c).gridTemplateRows.includes('subgrid'),metrics:c.querySelector('.recording-metrics').getBoundingClientRect().y,controls:c.querySelector('.recording-channel-controls').getBoundingClientRect().y,auto:c.querySelector('.recording-auto-control').getBoundingClientRect().x-c.getBoundingClientRect().x}))"""
                    )
                    for i in range(0, len(rows) - 1, 2):
                        if rows[i]["subgrid"]:
                            assert (
                                abs(rows[i]["metrics"] - rows[i + 1]["metrics"]) < 1
                            ), rows
                            assert (
                                abs(rows[i]["controls"] - rows[i + 1]["controls"]) < 1
                            ), rows
                            assert abs(rows[i]["auto"] - rows[i + 1]["auto"]) < 1, rows
                for card in await page.locator(".recording-channel").all():
                    await expect(
                        card.locator(".recording-channel-controls .recording-status")
                    ).to_have_count(0)
                    await expect(
                        card.locator(".recording-channel-identity .recording-status")
                    ).not_to_have_count(0)
                    boxes = await card.evaluate(
                        """c=>{let r=e=>{let b=e.getBoundingClientRect();return {x:b.x,y:b.y,right:b.right,center:b.y+b.height/2}};return {card:r(c),identity:r(c.querySelector('.recording-channel-identity')),metrics:r(c.querySelector('.recording-metrics')),controls:r(c.querySelector('.recording-channel-controls')),auto:r(c.querySelector('.recording-auto-control')),settings:r(c.querySelector('.recording-primary-controls button'))}}"""
                    )
                    assert boxes["identity"]["x"] < boxes["controls"]["right"]
                    assert boxes["controls"]["right"] <= boxes["card"]["right"], (
                        width,
                        mode,
                        boxes,
                    )
                    if (
                        boxes["card"]["right"] - boxes["card"]["x"] >= 1000
                        and mode == "list"
                    ):
                        assert (
                            boxes["identity"]["x"]
                            < boxes["metrics"]["x"]
                            < boxes["controls"]["x"]
                        ), boxes
                        assert (
                            abs(boxes["auto"]["center"] - boxes["settings"]["center"])
                            < 1
                        ), boxes
                        assert boxes["auto"]["x"] < boxes["settings"]["x"], boxes
                    # No empty start/stop slot may remain after an offline settings button.
                    last_button = card.locator(
                        ".recording-primary-controls button"
                    ).last
                    end = await last_button.bounding_box()
                    controls = await card.locator(
                        ".recording-channel-controls"
                    ).bounding_box()
                    assert (
                        abs(end["x"] + end["width"] - controls["x"] - controls["width"])
                        < 1
                    ), (width, mode, end, controls)
                    cells = await card.locator(".recording-metrics dt").evaluate_all(
                        "(es)=>es.map(e=>e.getBoundingClientRect().y)"
                    )
                    if boxes["card"]["right"] - boxes["card"]["x"] >= 440:
                        assert max(cells) - min(cells) < 1, cells
                await expect(
                    page.locator('[data-channel-key="chzzk:repair-4"]').get_by_role(
                        "button", name="녹화 시작", exact=True
                    )
                ).to_have_count(0)
                if width >= 1024 and mode == "list":
                    centers = (
                        await page.locator(".recording-channel")
                        .first.locator(".recording-channel-actions .icon-button")
                        .evaluate_all(
                            "(buttons)=>buttons.filter(b=>b.offsetWidth).map(b=>b.getBoundingClientRect().y+b.offsetHeight/2)"
                        )
                    )
                    assert max(centers) - min(centers) < 1
                await page.screenshot(
                    path=str(OUT / f"repaired-{mode}-{width}.png"), full_page=True
                )
        await page.set_viewport_size({"width": 1440, "height": 1000})
        running = page.locator('[data-channel-key="chzzk:repair-0"]')
        toggle = running.get_by_role("switch")
        await toggle.click()
        await expect(toggle).to_be_disabled()
        await expect(toggle).to_be_enabled()
        await expect(toggle).to_have_attribute("aria-checked", "true")
        fail_auto = False
        await toggle.click()
        await expect(toggle).to_have_attribute("aria-checked", "false")
        assert channels[0]["recording"]["is_recording"] is True
        await failed.get_by_role("button", name="녹화 시작", exact=True).click()
        await expect(failed.locator(".recording-channel-statuses")).to_contain_text(
            "녹화 준비 중"
        )
        await expect(
            failed.get_by_role("button", name="녹화 중지", exact=True)
        ).to_be_enabled()
        await failed.get_by_role("button", name="녹화 중지", exact=True).click()
        await page.get_by_role("dialog").get_by_role(
            "button", name="중지", exact=True
        ).click()
        await expect(failed.locator(".recording-channel-statuses")).to_contain_text(
            "녹화 완료"
        )
        assert len([path for path, _ in calls if path.endswith("/start")]) == 1
        assert len([path for path, _ in calls if path.endswith("/stop")]) == 1
        await failed.get_by_role("button", name="녹화 설정", exact=True).click()
        dialog = page.get_by_role("dialog")
        output = dialog.get_by_role(
            "combobox", name="녹화 완료 후 저장 형식", exact=True
        )
        assert await output.locator("option").all_text_contents() == [
            "전역 설정 사용",
            "MKV - Matroska",
            "MP4 - MPEG-4",
        ]
        await output.select_option("mp4")
        await dialog.get_by_role("button", name="설정 저장", exact=True).click()
        await expect(dialog).to_have_count(0)
        assert any(
            "/download-options" in path and body["output_format"] == "mp4"
            for path, body in calls
        )
        await failed.get_by_role("button", name="녹화 설정", exact=True).click()
        await expect(
            page.get_by_role("dialog").get_by_role(
                "combobox", name="녹화 완료 후 저장 형식", exact=True
            )
        ).to_have_value("mp4")
        await page.get_by_role("button", name="설정 닫기", exact=True).click()
        await history.get_by_role("button", name="실패", exact=True).click()
        await expect(history.locator(".recording-history-row")).to_have_count(1)
        await history.get_by_role("button", name="이력 정리", exact=True).click()
        assert any(
            path == "/api/recordings/history/clear"
            and sorted(body["job_ids"]) == ["job-0", "job-1", "job-2"]
            for path, body in calls
        )
        await page.goto(BASE + "/settings")
        await page.get_by_role("button", name="다운로드", exact=True).click()
        await expect(
            page.get_by_role("combobox", name="녹화 완료 후 저장 형식", exact=True)
        ).to_have_value("mkv")
        labels = (
            await page.get_by_role(
                "combobox", name="녹화 완료 후 저장 형식", exact=True
            )
            .locator("option")
            .all_text_contents()
        )
        assert labels == ["MKV - Matroska", "MP4 - MPEG-4"], labels
        live = page.get_by_role("combobox", name="치지직 라이브 CDN", exact=True)
        vod = page.get_by_role("combobox", name="치지직 다운로드 CDN", exact=True)
        await live.select_option("akamai")
        await page.get_by_role("button", name="라이브 설정 저장", exact=True).click()
        await expect(vod).to_have_value("default")
        assert any(
            path == "/api/settings/live" and body["chzzk_live_cdn"] == "akamai"
            for path, body in calls
        )
        await vod.select_option("akamai")
        await page.get_by_role(
            "button", name="영상 다운로드 설정 저장", exact=True
        ).click()
        assert any(
            path == "/api/settings/vod" and body["chzzk_vod_cdn"] == "akamai"
            for path, body in calls
        )
        await page.reload()
        await page.get_by_role("button", name="다운로드", exact=True).click()
        await expect(
            page.get_by_role("combobox", name="치지직 라이브 CDN", exact=True)
        ).to_have_value("akamai")
        await expect(
            page.get_by_role("combobox", name="치지직 다운로드 CDN", exact=True)
        ).to_have_value("akamai")
        for width in (360, 390, 768, 1024, 1440, 1920):
            await page.set_viewport_size({"width": width, "height": 1000})
            assert await page.evaluate(
                "document.documentElement.scrollWidth<=innerWidth"
            ), width
        await page.set_viewport_size({"width": 1440, "height": 1000})
        await page.screenshot(path=str(OUT / "cdn-settings-1440.png"), full_page=True)
        await page.get_by_role(
            "combobox", name="치지직 라이브 CDN", exact=True
        ).scroll_into_view_if_needed()
        await page.screenshot(
            path=str(OUT / "live-cdn-settings-1440.png"), full_page=True
        )
        assert not errors, errors
        print(
            "PASS: grid/list at 360/390/768/1024/1440/1920, aligned management buttons, 0B failure metrics, grouped history, disabled unavailable actions, history clear IDs, live/VOD CDN save and restore, MKV default, no overflow or JS errors"
        )
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
