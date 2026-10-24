"""채널별 예약 감시 시간대."""

from datetime import datetime

import pytest

from app.engine.monitor_schedule import is_active, is_within, next_check_at, parse_schedule

# 2026-10-23은 금요일(월요일=0 기준 weekday()==4)이다.
FRIDAY_NOON = datetime(2026, 10, 23, 12, 0)
FRIDAY_NIGHT = datetime(2026, 10, 23, 22, 30)


def schedule(**overrides):
    data = {
        "mode": "scheduled",
        "windows": [{"days": [4], "start": "22:00", "end": "23:00"}],
        "lead_minutes": 10,
        "delay_minutes": 30,
    }
    data.update(overrides)
    return data


def test_always_mode_never_blocks():
    assert is_active(parse_schedule(None), None, FRIDAY_NOON)
    assert is_active({"mode": "always", "windows": []}, None, FRIDAY_NOON)
    assert is_within({"mode": "scheduled", "windows": []}, FRIDAY_NOON) is False


def test_only_inside_window():
    current = schedule()
    assert is_active(current, None, FRIDAY_NIGHT)
    assert not is_active(current, None, FRIDAY_NOON)


def test_wrong_weekday_is_skipped():
    assert not is_active(schedule(windows=[{"days": [0], "start": "22:00", "end": "23:00"}]), None, FRIDAY_NIGHT)


def test_lead_time_opens_early():
    # 22:00 시작, 10분 전부터 확인.
    assert is_active(schedule(), None, datetime(2026, 10, 23, 21, 51))
    assert not is_active(schedule(), None, datetime(2026, 10, 23, 21, 45))


def test_lead_time_crosses_previous_day():
    current = schedule(windows=[{"days": [5], "start": "00:05", "end": "01:00"}])
    assert is_active(current, None, datetime(2026, 10, 23, 23, 56))


def test_delay_checks_even_before_broadcast_is_detected():
    assert is_active(schedule(), None, datetime(2026, 10, 23, 23, 20))
    assert not is_active(schedule(), None, datetime(2026, 10, 23, 23, 31))


def test_timezone_broadcast_timestamp_does_not_crash():
    assert isinstance(is_active(schedule(), "2026-10-23T12:00:00Z", FRIDAY_NOON), bool)


def test_window_past_midnight():
    window = schedule(windows=[{"days": [4], "start": "23:30", "end": "01:00"}])
    assert is_active(window, None, datetime(2026, 10, 24, 0, 30))
    assert not is_active(window, None, datetime(2026, 10, 24, 2, 0))


def test_late_start_keeps_checking_during_delay():
    late = datetime(2026, 10, 23, 23, 20).isoformat()
    assert is_active(schedule(), late, datetime(2026, 10, 23, 23, 40))
    # 이미 잡은 방송은 끝까지 본다.
    assert is_active(schedule(), datetime(2026, 10, 23, 22, 5).isoformat(), datetime(2026, 10, 24, 3, 0))


def test_start_before_window_keeps_checking():
    # 예정보다 일찍 켠 방송도 시작 여유 안이면 시간대까지 계속 확인한다.
    early = datetime(2026, 10, 23, 21, 55).isoformat()
    assert is_active(schedule(), early, datetime(2026, 10, 23, 22, 10))


def test_next_check_at():
    assert next_check_at(schedule(), FRIDAY_NOON) == datetime(2026, 10, 23, 21, 50)
    assert next_check_at(schedule(), datetime(2026, 10, 23, 23, 30)) == datetime(2026, 10, 30, 21, 50)
    assert next_check_at(None, FRIDAY_NOON) is None


@pytest.mark.parametrize("raw", [None, "", "{", "[]", '"text"'])
def test_broken_storage_is_always_mode(raw):
    assert is_active(parse_schedule(raw), None, FRIDAY_NOON)


def test_channel_api_saves_and_restores_schedule(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import app.main
    from app.api import stream
    from app.engine.conductor import Conductor
    from app.services.recorder import RecorderService

    conductor = Conductor()
    service = RecorderService(conductor)
    monkeypatch.setattr(app.main, "get_recorder_service", lambda: service)
    app = FastAPI()
    app.include_router(stream.router)
    client = TestClient(app)
    cid = "c" * 32
    payload = {
        "auto_record": True,
        "monitor_schedule": {
            "mode": "scheduled",
            "windows": [{"days": [0, 2], "start": "10:00", "end": "11:00"}],
            "lead_minutes": 5,
            "delay_minutes": 20,
        },
    }
    assert client.post("/api/stream/channels", json={"channel_id": cid, **payload}).status_code == 200
    task = conductor._channels[f"chzzk:{cid}"]
    assert parse_schedule(task.monitor_schedule)["windows"][0]["start"] == "10:00"
    restored = Conductor()._channels[f"chzzk:{cid}"]
    assert parse_schedule(restored.monitor_schedule)["delay_minutes"] == 20

    path = f"/api/stream/channels/{cid}/download-options"
    # 시간대 없는 예약 감시는 거절한다.
    assert client.put(path, json={"auto_record": True, "monitor_schedule": {
        "mode": "scheduled", "windows": [],
    }}).status_code == 422
    assert client.put(path, json={"auto_record": True, "monitor_schedule": {
        "mode": "scheduled", "windows": [{"days": [9], "start": "10:00", "end": "11:00"}],
    }}).status_code == 422
    assert parse_schedule(conductor._channels[f"chzzk:{cid}"].monitor_schedule)["delay_minutes"] == 20

    assert client.put(path, json={"auto_record": True, "monitor_schedule": {"mode": "always"}}).status_code == 200
    assert conductor._channels[f"chzzk:{cid}"].monitor_schedule is None


@pytest.mark.asyncio
async def test_scheduled_channel_outside_window_skips_status_lookup(monkeypatch):
    from unittest.mock import AsyncMock

    from app.engine import conductor as conductor_module
    from app.engine.conductor import Conductor
    from app.services.recorder import RecorderService

    conductor = Conductor()
    conductor.add_channel("late", monitor_schedule=__import__("json").dumps(schedule()))
    RecorderService(conductor)
    engine = type("Engine", (), {"check_live_status": AsyncMock()})()
    monkeypatch.setattr(conductor, "_get_engine", lambda _: engine)
    monkeypatch.setattr(conductor_module, "schedule_is_active", lambda *_: False)
    intervals = []

    async def next_scan(_key, delay):
        intervals.append(delay)
        conductor._running = False

    monkeypatch.setattr(conductor, "_wait_for_next_scan", next_scan)
    monkeypatch.setattr(conductor, "_idle_delay", lambda task, interval: 42.0)
    conductor._running = True
    await conductor._monitor_channel("chzzk:late")
    engine.check_live_status.assert_not_awaited()
    assert intervals == [42.0]
