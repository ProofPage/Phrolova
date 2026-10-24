import pytest
from unittest.mock import AsyncMock
from app.engine.channel import ChannelTask
from app.engine.base import Platform
from app.engine.conductor import Conductor

@pytest.mark.parametrize("platform", list(Platform))
def test_offline_status_has_platform_scoped_key(platform):
    task = ChannelTask("sameid", platform=platform)
    Conductor._apply_status(task, {"is_live": False, "channel_name": "offline"})
    assert task.composite_key == f"{platform.value}:sameid"
    assert task.channel_name == "offline"

@pytest.mark.asyncio
async def test_monitor_transitions_and_restart_keep_distinct_platforms():
    conductor = Conductor()
    for platform in (Platform.CHZZK, Platform.KICK, Platform.CIME):
        conductor.add_channel("sameid", platform=platform, auto_record=False)
    restored = Conductor()
    assert set(restored._channels) == {f"{p.value}:sameid" for p in (Platform.CHZZK,Platform.KICK,Platform.CIME)}
    key = "kick:sameid"
    engine = type("Engine", (), {})()
    engine.get_stream_url = lambda cid: "https://example.com/" + cid
    engine.check_live_status = AsyncMock(side_effect=[{"is_live": False}, {"is_live": True}, {"is_live": False}])
    restored._get_engine = lambda _: engine
    restored._handle_live_started = AsyncMock(return_value=0)
    restored._handle_live_ended = AsyncMock()
    count = 0
    async def next_scan(*_):
        nonlocal count
        count += 1
        if count == 3: restored._running = False
    restored._wait_for_next_scan = next_scan
    restored._running = True
    await restored._monitor_channel(key)
    assert engine.check_live_status.await_count == 3
    restored._handle_live_started.assert_awaited_once()
    restored._handle_live_ended.assert_awaited_once()
    assert restored._channels[key].last_error is None


@pytest.mark.asyncio
async def test_monitor_failure_recovers_without_blocking_recording_and_keeps_history():
    conductor = Conductor()
    conductor.add_channel("sameid", auto_record=False)
    task = conductor._channels["chzzk:sameid"]
    task.last_error = "previous capture error"
    task.retry_count = 2
    task.retry_blocked = True
    conductor._monitor_failure(task, "metadata timeout")
    assert task.last_error == "previous capture error"
    assert task.retry_count == 2 and task.retry_blocked
    assert task.broadcast_status == "error" and task.monitor_error == "metadata timeout"
    engine = type("Engine", (), {})()
    engine.check_live_status = AsyncMock(return_value={"is_live": True})
    conductor._get_engine = lambda _: engine
    async def stop_scan(*_): conductor._running = False
    conductor._wait_for_next_scan = stop_scan
    conductor._running = True
    await conductor._monitor_channel("chzzk:sameid")
    assert task.monitor_error is None and task.broadcast_status == "live"
    assert task.last_error == "previous capture error"
    restored = Conductor()._channels["chzzk:sameid"]
    assert restored.recent_errors[-1]["message"] == "metadata timeout"

@pytest.mark.asyncio
async def test_monitor_automatically_starts_and_stops_after_offline_transition():
    conductor = Conductor()
    conductor.add_channel("sameid", auto_record=True)
    engine = type("Engine", (), {})()
    engine.check_live_status = AsyncMock(side_effect=[{"is_live":False},{"is_live":True},{"is_live":False}])
    conductor._get_engine = lambda _: engine
    conductor._start_recording = AsyncMock()
    conductor._stop_recording = AsyncMock()
    count = 0
    async def scan(*_):
        nonlocal count
        count += 1
        if count == 3: conductor._running = False
    conductor._wait_for_next_scan = scan
    conductor._running = True
    await conductor._monitor_channel("chzzk:sameid")
    conductor._start_recording.assert_awaited_once()
    conductor._stop_recording.assert_awaited_once_with("chzzk:sameid")


@pytest.mark.asyncio
@pytest.mark.parametrize("was_live", [False, True])
async def test_rplay_access_denial_keeps_monitoring_and_recovers_without_reimport(was_live):
    conductor = Conductor()
    cid = "a" * 24
    conductor.add_channel(cid, platform=Platform.RPLAY, auto_record=True)
    key = f"rplay:{cid}"
    task = conductor._channels[key]
    task.is_live = was_live
    engine = type("Engine", (), {})()
    engine.get_stream_url = lambda _: f"https://rplay.live/live/{cid}"
    engine.check_live_status = AsyncMock(side_effect=[
        {"is_live": False, "status_error": "permission not confirmed",
         "error_detail": "accessible=False", "status_error_retryable": False},
        {"is_live": True},
    ])
    conductor._get_engine = lambda _: engine
    conductor._start_recording = AsyncMock()
    conductor._stop_recording = AsyncMock()
    scans = 0
    async def scan(*_):
        nonlocal scans
        scans += 1
        if scans == 1:
            assert task.is_live == was_live
            assert task.monitor_status == "retry_wait" and not task.retry_blocked
            conductor._start_recording.assert_not_awaited()
        else:
            conductor._running = False
    conductor._wait_for_next_scan = scan
    conductor._running = True
    await conductor._monitor_channel(key)
    assert engine.check_live_status.await_count == 2
    assert task.is_live and task.monitor_error is None and task.monitor_status == "watching"
    conductor._start_recording.assert_awaited_once()
    conductor._stop_recording.assert_not_awaited()

@pytest.mark.asyncio
async def test_deleted_channel_cannot_start_recording_after_slow_status_response():
    import asyncio
    conductor = Conductor()
    conductor.add_channel("sameid")
    entered, release = asyncio.Event(), asyncio.Event()
    async def check(_):
        entered.set()
        await release.wait()
        return {"is_live": True}
    engine = type("Engine", (), {"check_live_status":staticmethod(check)})()
    conductor._get_engine = lambda _: engine
    conductor._start_recording = AsyncMock()
    conductor._running = True
    run = asyncio.create_task(conductor._monitor_channel("chzzk:sameid"))
    await entered.wait()
    await conductor.remove_channel("chzzk:sameid")
    release.set()
    await run
    conductor._start_recording.assert_not_awaited()
    conductor._running = False
    conductor.add_channel("sameid", auto_record=False)
    assert conductor._channels["chzzk:sameid"].last_error is None


def test_conductor_channel_attributes_exist():
    import ast
    from pathlib import Path
    tree = ast.parse((Path(__file__).parents[1] / "app/engine/conductor.py").read_text(encoding="utf-8"))
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n,ast.Attribute) and isinstance(n.value,ast.Name) and n.value.id == "task"}
    assert not (attrs - set(ChannelTask.__dataclass_fields__) - set(dir(ChannelTask)))


def test_legacy_monitor_error_does_not_block_recording_after_restart():
    conductor = Conductor()
    conductor.add_channel('sameid')
    task = conductor._channels['chzzk:sameid']
    task.last_error = "감시 오류: 'ChannelTask' object has no attribute 'composite_key'"
    task.retry_code = 'status_query'
    task.retry_blocked = True
    conductor._persist_retry(task)
    restored = Conductor()._channels['chzzk:sameid']
    assert restored.last_error is None and not restored.retry_blocked
    assert restored.recent_errors[-1]['kind'] == 'monitor'
    assert 'composite_key' in restored.recent_errors[-1]['message']


@pytest.mark.asyncio
async def test_changed_monitor_interval_applies_without_restart():
    from app.core.config import get_settings
    conductor = Conductor()
    conductor.add_channel('sameid', auto_record=False)
    engine = type('Engine', (), {})()
    engine.check_live_status = AsyncMock(return_value={'is_live':False})
    conductor._get_engine = lambda _: engine
    settings = get_settings()
    settings.monitor_interval = 10
    delays = []
    async def scan(_, delay):
        delays.append(delay)
        settings.monitor_interval = 30
        if len(delays) == 2:
            conductor._running = False
    conductor._wait_for_next_scan = scan
    conductor._running = True
    await conductor._monitor_channel('chzzk:sameid')
    assert delays == [10,30]
