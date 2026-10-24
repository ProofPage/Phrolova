"""Live resizing, cancellation and persisted settings failure regressions."""

import asyncio

import pytest

from app.core.config import get_settings
from app.engine.download_slots import DownloadSlots


async def until(predicate):
    async def wait():
        while not predicate():
            await asyncio.sleep(0)

    await asyncio.wait_for(wait(), 2)


@pytest.mark.asyncio
async def test_resize_preserves_running_jobs_and_wakes_queued_jobs():
    slots = DownloadSlots(2)
    started, ended = [], []
    finish = [asyncio.Event() for _ in range(6)]

    async def job(index):
        async with slots:
            started.append(index)
            await finish[index].wait()
            ended.append(index)

    jobs = [asyncio.create_task(job(index)) for index in range(6)]
    await until(lambda: len(started) == 2)
    assert started == [0, 1]
    slots.set_limit(5)
    await until(lambda: len(started) == 5)
    assert started == [0, 1, 2, 3, 4] and slots.active == 5
    slots.set_limit(1)
    for index in range(4):
        finish[index].set()
    await until(lambda: len(ended) == 4)
    assert len(started) == 5 and slots.active == 1
    finish[4].set()
    await until(lambda: len(started) == 6)
    finish[5].set()
    await asyncio.gather(*jobs)
    assert slots.active == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("granted", [False, True])
async def test_cancelled_waiter_does_not_leak_download_slot(granted):
    slots = DownloadSlots(1)
    await slots.acquire()
    waiter = asyncio.create_task(slots.acquire())
    await asyncio.sleep(0)
    if granted:
        slots.release()  # Grant, then cancel before the task resumes.
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    if not granted:
        slots.release()
    await asyncio.wait_for(slots.acquire(), 1)
    assert slots.active == 1
    slots.release()


@pytest.mark.parametrize("limit", [0, 11])
def test_invalid_runtime_limit_preserves_slots(limit):
    slots = DownloadSlots(5)
    with pytest.raises(ValueError):
        slots.set_limit(limit)
    assert slots.limit == 5


def test_vod_settings_api_resizes_same_live_queue(api_client):
    import app.main

    engine = app.main.get_recorder_service()._vod_engine
    queue = engine._semaphore
    for limit in (2, 5, 1):
        response = api_client.put(
            "/api/settings/vod", json={"vod_max_concurrent": limit}
        )
        assert response.status_code == 200
        assert engine._semaphore is queue
        assert engine._max_concurrent == queue.limit == limit
        assert (
            "즉시" in response.json()["message"]
            and "재시작" not in response.json()["message"]
        )


@pytest.mark.parametrize(
    "path, payload, module",
    [
        ("general", {"monitor_interval": 55}, "general"),
        ("live", {"max_record_retries": 9, "chzzk_stream_mode": "standard"}, "media"),
        ("vod", {"vod_max_concurrent": 7}, "media"),
    ],
)
def test_failed_save_preserves_running_and_persisted_settings(
    api_client, monkeypatch, path, payload, module
):
    import app.main
    from app.api.settings import general, media

    before = get_settings().model_dump()
    engine = app.main.get_recorder_service()._vod_engine
    limit = engine._semaphore.limit

    def denied(*_, **__):
        raise OSError("read-only file")

    monkeypatch.setattr(
        general if module == "general" else media, "_update_env_file", denied
    )
    response = api_client.put("/api/settings/" + path, json=payload)
    assert response.status_code == 500
    assert get_settings().model_dump() == before
    assert engine._semaphore.limit == limit


@pytest.mark.parametrize(
    "path, payload",
    [
        ("general", {"monitor_interval": 55, "live_format": "invalid"}),
        ("live", {"max_record_retries": 9, "recording_quality": "invalid"}),
    ],
)
def test_invalid_setting_does_not_partially_apply(api_client, path, payload):
    before = get_settings().model_dump()
    assert api_client.put("/api/settings/" + path, json=payload).status_code == 400
    assert get_settings().model_dump() == before


def test_legacy_format_api_still_works(api_client):
    assert (
        api_client.put("/api/settings/general", json={"live_format": "mp4"}).status_code
        == 200
    )
    assert get_settings().live_format == "mp4"


def test_relocated_directories_and_interval_persist(api_client, tmp_path):
    from app.core.config import Settings

    live = str(tmp_path / "라이브 폴더")
    vod = str(tmp_path / "영상 폴더")
    assert (
        api_client.put("/api/settings/vod", json={"vod_download_dir": vod}).status_code
        == 200
    )
    assert (
        api_client.put(
            "/api/settings/live",
            json={
                "live_download_dir": live,
                "monitor_interval": 45,
                "max_record_retries": 3,
            },
        ).status_code
        == 200
    )
    saved = Settings(_env_file=tmp_path / ".env")
    assert saved.live_download_dir == live
    assert saved.vod_download_dir == vod
    assert saved.monitor_interval == 45
    assert (tmp_path / "라이브 폴더").is_dir()
    assert (tmp_path / "영상 폴더").is_dir()


@pytest.mark.parametrize(
    "route,field", [("live", "live_download_dir"), ("vod", "vod_download_dir")]
)
@pytest.mark.parametrize("invalid", ["blank", "file"])
def test_invalid_relocated_directory_preserves_settings(
    api_client, tmp_path, route, field, invalid
):
    blocked = tmp_path / "파일"
    blocked.write_text("preserve", encoding="utf-8")
    before = get_settings().model_dump()
    value = "  " if invalid == "blank" else str(blocked)
    assert (
        api_client.put(
            "/api/settings/" + route,
            json={
                field: value,
                **({"max_record_retries": 3} if route == "live" else {}),
            },
        ).status_code
        == 400
    )
    assert get_settings().model_dump() == before
    assert blocked.read_text(encoding="utf-8") == "preserve"


@pytest.mark.parametrize("interval", [4, 301])
def test_relocated_interval_validation(api_client, interval):
    before = get_settings().monitor_interval
    assert (
        api_client.put(
            "/api/settings/live",
            json={"monitor_interval": interval, "max_record_retries": 3},
        ).status_code
        == 422
    )
    assert get_settings().monitor_interval == before
