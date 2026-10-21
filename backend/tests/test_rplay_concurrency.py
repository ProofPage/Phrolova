"""Tests for RPLAY concurrency and non-blocking event-loop session loading."""
from __future__ import annotations

import asyncio
import threading
from typing import Any

import pytest

from app.engine import rplay_live as rp


@pytest.fixture(autouse=True)
def isolate_rplay_handles(monkeypatch):
    monkeypatch.setattr(rp, '_HANDLE_CACHE', {})


@pytest.mark.asyncio
@pytest.mark.parametrize('concurrency', [12, 16, 24])
async def test_concurrent_check_live_status_off_event_loop(monkeypatch, concurrency):
    channel_ids = [f'{i:024x}' for i in range(1, concurrency + 1)]
    assert len(set(channel_ids)) == concurrency

    gate = threading.Event()
    worker_entered = threading.Event()
    worker_thread_ids: set[int] = set()
    lock = threading.Lock()
    call_count = 0

    loop = asyncio.get_running_loop()
    loop_thread_id = threading.get_ident()

    def fake_account_session():
        nonlocal call_count
        tid = threading.get_ident()
        with lock:
            worker_thread_ids.add(tid)
            call_count += 1
            worker_entered.set()
        # Gated synchronous account_session with bounded wait (loop must stay responsive to release gate)
        if not gate.wait(timeout=5.0):
            raise TimeoutError('Gate timeout: event-loop callback failed to release gate (loop was blocked)')
        return {
            'accessToken': f'mock-token-{tid}',
            'requestorOid': '0' * 24,
            'loginType': 'rplay',
        }

    monkeypatch.setattr(rp, 'account_session', fake_account_session)

    api_called_cids: list[str] = []

    async def fake_api(path: str, params: dict[str, Any], session: Any, *, optional_permission: bool = False):
        assert path == '/play'
        cid = params['creatorOid']
        api_called_cids.append(cid)
        return {
            'creatorOid': cid,
            'creatorMetadata': {
                '_id': cid,
                'nickname': f'Streamer_{cid[:8]}',
                'channelImage': f'https://example.com/avatar_{cid[:8]}.png',
            },
            'streamState': 'live',
            'streamStartTime': '2026-10-16T12:00:00Z',
            'title': f'Live Title for {cid[:8]}',
            'accessible': True,
            'hashtags': ['gaming', f'tag_{cid[:4]}'],
        }

    engine = rp.RplayLiveEngine()
    monkeypatch.setattr(engine, '_api', fake_api)

    callback_executed = False
    callback_thread_id = None
    loop_ticks = 0

    def release_gate_callback():
        nonlocal callback_executed, callback_thread_id, loop_ticks
        loop_ticks += 1
        callback_thread_id = threading.get_ident()
        assert callback_thread_id == loop_thread_id
        if worker_entered.is_set():
            callback_executed = True
            gate.set()
        else:
            loop.call_soon(release_gate_callback)

    loop.call_soon(release_gate_callback)

    heartbeat_ticks = 0
    stop_heartbeat = False

    async def loop_heartbeat():
        nonlocal heartbeat_ticks
        while not stop_heartbeat:
            heartbeat_ticks += 1
            await asyncio.sleep(0.005)

    heartbeat_task = asyncio.create_task(loop_heartbeat())

    statuses = await asyncio.gather(*[engine.check_live_status(cid) for cid in channel_ids])

    stop_heartbeat = True
    await heartbeat_task

    # 1. Proving loop stays responsive and gate was released by event loop callback
    assert callback_executed is True
    assert callback_thread_id == loop_thread_id
    assert loop_ticks > 0
    assert heartbeat_ticks > 0

    # 2. Synchronous account_session executed off the event loop thread in worker threads
    assert call_count == concurrency
    assert len(worker_thread_ids) > 0
    assert loop_thread_id not in worker_thread_ids

    # 3. All channel IDs distinct
    assert len(statuses) == concurrency
    returned_cids = [s['channel_id'] for s in statuses]
    assert len(set(returned_cids)) == concurrency
    assert returned_cids == channel_ids
    assert set(api_called_cids) == set(channel_ids)

    # 4. Live metadata correct
    for status, expected_cid in zip(statuses, channel_ids):
        assert status['channel_id'] == expected_cid
        assert status['is_live'] is True
        assert status['channel_name'] == f'Streamer_{expected_cid[:8]}'
        assert status['title'] == f'Live Title for {expected_cid[:8]}'
        assert status['profile_image_url'] == f'https://example.com/avatar_{expected_cid[:8]}.png'
        assert status['broadcast_tags'] == ['gaming', f'tag_{expected_cid[:4]}']
        assert status['live_started_at'] == '2026-10-16T12:00:00Z'
        assert status.get('status_error') is None


@pytest.mark.asyncio
async def test_streams_session_loading_off_event_loop_offline_metadata(monkeypatch):
    cid = 'a' * 24

    gate = threading.Event()
    loop = asyncio.get_running_loop()
    loop_thread_id = threading.get_ident()
    session_thread_id = None
    callback_thread_id = None
    gate_released = False

    def fake_account_session():
        nonlocal session_thread_id
        session_thread_id = threading.get_ident()
        if not gate.wait(timeout=5.0):
            raise TimeoutError('Gate timeout: loop blocked during _streams session loading')
        return {
            'accessToken': 'streams-test-token',
            'requestorOid': 'b' * 24,
            'loginType': 'rplay',
        }

    monkeypatch.setattr(rp, 'account_session', fake_account_session)

    def release_gate():
        nonlocal callback_thread_id, gate_released
        callback_thread_id = threading.get_ident()
        assert callback_thread_id == loop_thread_id
        gate_released = True
        gate.set()

    loop.call_soon(release_gate)

    api_called = False

    async def fake_api(path: str, params: dict[str, Any], session: Any, *, optional_permission: bool = False):
        nonlocal api_called
        api_called = True
        assert path == '/play'
        assert params['creatorOid'] == cid
        assert session == {'accessToken': 'streams-test-token', 'requestorOid': 'b' * 24, 'loginType': 'rplay'}
        return {
            'creatorOid': cid,
            'creatorMetadata': {
                '_id': cid,
                'nickname': 'Offline Creator',
            },
            'streamState': 'offline',
            'streamStartTime': None,
            'title': 'Offline stream',
            'accessible': True,
        }

    engine = rp.RplayLiveEngine()
    monkeypatch.setattr(engine, '_api', fake_api)

    variants = await engine._streams(cid)

    # Returns empty variants without full HLS setup on offline metadata
    assert variants == []
    assert api_called is True

    # Gate was released by event loop callback proving loop remained responsive
    assert gate_released is True
    assert callback_thread_id == loop_thread_id

    # account_session ran in a thread off the event loop
    assert session_thread_id is not None
    assert session_thread_id != loop_thread_id
