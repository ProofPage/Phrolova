"""자동 다운로드 필터, 개별 설정 저장, 기존 DB 이관 검증."""

import sqlite3
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.engine.base import Platform
from app.engine.conductor import Conductor
from app.engine.download_condition import matches_download_condition
from app.store.db import Database
from app.store.repositories import ChannelRepository
from app.store.schema import MIGRATIONS


@pytest.mark.parametrize("condition,tags,markers,expected", [
    ("all", None, "같이보기", True),
    ("watchalong", ["게임", "같이보기"], "같이보기", True),
    ("watchalong", ["게임"], "같이보기", False),
    ("exclude_watchalong", ["같이보기"], "같이보기", False),
    ("exclude_watchalong", [], "같이보기", True),
    ("watchalong", None, "같이보기", False),
    ("exclude_watchalong", None, "같이보기", False),
    ("watchalong", ["같이보기아님"], "같이보기", False),
    ("watchalong", ["동시시청"], "같이보기, 동시시청", True),
    ("watchalong", ["ＷＡＴＣＨ", "같이 보기"], "#watch, 같이보기", True),
    ("exclude_watchalong", [], ", ,", False),
])
def test_condition_matching(condition, tags, markers, expected):
    assert matches_download_condition(condition, tags, markers) is expected


def test_existing_database_upgrades_without_losing_channels(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as conn:
        for version, sql in MIGRATIONS[:2]:
            conn.executescript(sql)
            conn.execute(f"PRAGMA user_version = {version}")
        conn.execute("INSERT INTO channels (composite_key, platform, channel_id, tags) VALUES (?, ?, ?, ?)",
                     ("chzzk:old", "chzzk", "old", '["favorite"]'))
    db = Database(path)
    db.connect()
    try:
        record = ChannelRepository(db).list_all()[0]
        assert record["tags"] == ["favorite"]
        assert record["auto_record"] is True
        assert record["download_condition"] is None
        assert record["watchalong_tags"] is None
    finally:
        db.close()


def test_per_channel_overrides_and_reload():
    settings = get_settings()
    settings.live_download_condition = "watchalong"
    settings.watchalong_tags = "같이보기"
    conductor = Conductor()
    conductor.add_channel("test", download_condition="exclude_watchalong", watchalong_tags="동시시청")
    task = conductor._channels["chzzk:test"]
    task.broadcast_tags = ["같이보기"]
    assert conductor._can_auto_record(task)
    restored = Conductor()._channels["chzzk:test"]
    assert restored.download_condition == "exclude_watchalong"
    assert restored.watchalong_tags == "동시시청"
    conductor.set_download_options("chzzk:test", True, None, None)
    task.broadcast_tags = []
    assert not conductor._can_auto_record(task)
    assert ChannelRepository().list_all()[0]["download_condition"] is None
    other = type(task)(channel_id="other", platform=Platform.YOUTUBE)
    assert conductor._can_auto_record(other)


def test_channel_registration_failure_does_not_create_runtime_channel(monkeypatch):
    conductor = Conductor()

    def fail_save(**_):
        raise OSError("write failed")

    monkeypatch.setattr(conductor._channel_repo, "upsert", fail_save)
    with pytest.raises(OSError):
        conductor.add_channel("test", download_condition="watchalong")
    assert conductor.channel_count == 0


@pytest.mark.asyncio
async def test_blocked_start_and_toggle_do_not_download(monkeypatch):
    conductor = Conductor()
    conductor.add_channel("test", download_condition="watchalong", watchalong_tags="같이보기")
    task = conductor._channels["chzzk:test"]
    task.is_live = True
    task.broadcast_tags = []
    start = AsyncMock()
    monkeypatch.setattr(conductor, "_start_recording", start)
    await conductor._handle_live_started("chzzk:test", task, 0)
    start.assert_not_awaited()
    task.auto_record = False
    await conductor.toggle_auto_record("chzzk:test")
    start.assert_not_awaited()
    task.broadcast_tags = ["같이보기"]
    await conductor._handle_live_started("chzzk:test", task, 0)
    assert start.await_args.kwargs["automatic"] is True


@pytest.mark.asyncio
async def test_manual_start_ignores_automatic_condition(monkeypatch):
    conductor = Conductor()
    conductor.add_channel("test", download_condition="watchalong")
    monkeypatch.setattr(conductor, "_start_recording", AsyncMock())
    engine = type("Engine", (), {"check_live_status": AsyncMock(return_value={"is_live": True})})()
    monkeypatch.setattr(conductor, "_get_engine", lambda _: engine)
    await conductor.start_manual_recording("chzzk:test")
    conductor._start_recording.assert_awaited_once_with("chzzk:test")


def test_channel_api_saves_options_before_monitoring_and_edits_existing(monkeypatch):
    from app.api import stream
    from app.services.recorder import RecorderService
    import app.main

    conductor = Conductor()
    service = RecorderService(conductor)
    monkeypatch.setattr(app.main, "get_recorder_service", lambda: service)
    app = FastAPI()
    app.include_router(stream.router)
    client = TestClient(app)
    cid = "a" * 32
    response = client.post("/api/stream/channels", json={
        "channel_id": cid, "auto_record": True,
        "download_condition": "watchalong", "watchalong_tags": "#같이보기, 동시시청",
    })
    assert response.status_code == 200
    task = conductor._channels[f"chzzk:{cid}"]
    assert task.download_condition == "watchalong"
    assert task.watchalong_tags == "같이보기, 동시시청"
    path = f"/api/stream/channels/{cid}/download-options"
    assert client.put(path, json={"auto_record": False, "download_condition": None}).status_code == 200
    assert not task.auto_record
    assert task.download_condition is None
    assert client.put(path, json={"download_condition": "invalid"}).status_code == 422
    assert client.put(path, json={"download_condition": "watchalong", "watchalong_tags": " , "}).status_code == 422
    assert client.put(f"/api/stream/channels/{'b' * 32}/download-options", json={}).status_code == 404


@pytest.mark.asyncio
async def test_waiting_channel_starts_when_broadcast_tags_change(monkeypatch):
    conductor = Conductor()
    conductor.add_channel("test", download_condition="watchalong", watchalong_tags="같이보기")
    statuses = [
        {"is_live": True, "broadcast_tags": [], "channel_name": "test"},
        {"is_live": True, "broadcast_tags": ["같이보기"], "channel_name": "test"},
    ]
    engine = type("Engine", (), {"check_live_status": AsyncMock(side_effect=statuses)})()
    monkeypatch.setattr(conductor, "_get_engine", lambda _: engine)
    start = AsyncMock()
    monkeypatch.setattr(conductor, "_start_recording", start)
    scans = 0

    async def next_scan(*_):
        nonlocal scans
        scans += 1
        if scans == 2:
            conductor._running = False

    monkeypatch.setattr(conductor, "_wait_for_next_scan", next_scan)
    conductor._running = True
    await conductor._monitor_channel("chzzk:test")
    start.assert_awaited_once()
    assert start.await_args.kwargs["automatic"] is True


def test_default_condition_api_persists_and_validates(monkeypatch):
    from unittest.mock import Mock
    from app.api.settings import media
    from app.core import utils
    from app.core.config import Settings
    import app.main

    service = Mock()
    monkeypatch.setattr(app.main, "get_recorder_service", lambda: service)
    app = FastAPI()
    app.include_router(media.router)
    client = TestClient(app)
    response = client.put("/api/settings/live-condition", json={
        "live_download_condition": "exclude_watchalong", "watchalong_tags": "#같이보기, 동시시청",
    })
    assert response.status_code == 200
    settings = Settings(_env_file=utils._get_env_path())
    assert settings.live_download_condition == "exclude_watchalong"
    assert settings.watchalong_tags == "같이보기, 동시시청"
    service.scan_now.assert_called_once()
    assert client.put("/api/settings/live-condition", json={"live_download_condition": "invalid"}).status_code == 422
    response = client.put("/api/settings/live-condition", json={
        "live_download_condition": "watchalong", "watchalong_tags": "문자 #태그",
    })
    assert response.status_code == 200
    assert Settings(_env_file=utils._get_env_path()).watchalong_tags == "문자 #태그"


def test_default_condition_write_failure_does_not_change_runtime_settings(monkeypatch):
    from pathlib import Path
    from unittest.mock import Mock
    from app.api.settings import media
    import app.main

    settings = get_settings()
    settings.live_download_condition = "all"
    service = Mock()
    monkeypatch.setattr(app.main, "get_recorder_service", lambda: service)
    app = FastAPI()
    app.include_router(media.router)

    def fail_write(*args, **kwargs):
        raise PermissionError("read only")

    monkeypatch.setattr(Path, "write_text", fail_write)
    client = TestClient(app, raise_server_exceptions=False)
    assert client.put("/api/settings/live-condition", json={
        "live_download_condition": "watchalong", "watchalong_tags": "같이보기",
    }).status_code == 500
    assert settings.live_download_condition == "all"
    service.scan_now.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("raw_tags,expected", [
    (["같이보기", "게임"], ["같이보기", "게임"]),
    ([], []),
    (None, None),
    ("같이보기", None),
    ([{"name": "같이보기"}], None),
])
async def test_chzzk_broadcast_tag_metadata_is_separate_from_channel_tags(monkeypatch, raw_tags, expected):
    from unittest.mock import Mock
    from app.engine import downloader

    response = Mock()
    response.json.return_value = {"content": {"status": "OPEN", "tags": raw_tags}}
    http = Mock(get=AsyncMock(return_value=response))
    monkeypatch.setattr(downloader, "get_http_client", lambda: http)
    status = await downloader.ChzzkLiveEngine().check_live_status("test")
    assert status["broadcast_tags"] == expected


@pytest.mark.asyncio
async def test_retry_rechecks_condition_after_wait(monkeypatch):
    from app.engine.pipeline import RecordingState
    from unittest.mock import Mock
    import app.engine.conductor as module

    conductor = Conductor()
    conductor.add_channel("test", download_condition="watchalong", watchalong_tags="같이보기")
    task = conductor._channels["chzzk:test"]
    task.broadcast_tags = ["같이보기"]
    task.pipeline = Mock(state=RecordingState.ERROR)
    conductor._running = True

    async def wait(*_):
        task.broadcast_tags = []

    monkeypatch.setattr(module.asyncio, "sleep", wait)
    factory = Mock()
    monkeypatch.setattr(module, "YtdlpLivePipeline", factory)
    assert await conductor._retry_stalled_recording("chzzk:test", task, 0, 3) == 1
    factory.assert_not_called()
