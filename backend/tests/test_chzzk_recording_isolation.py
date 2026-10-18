"""Bounded, shared live requests and independent native recording receivers."""

import asyncio
import contextlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from streamlink import Streamlink

from app.engine.chzzk_continuity import ChzzkContinuityReader, Download
from app.engine.chzzk_stream import ChzzkHLSStream
from tests.test_chzzk_continuity import CDN, INITIALIZATION, MEDIA
from tests.test_recording_shutdown import PendingReader, TS, pipeline


def writer(stack, cdn, *, time_machine=False):
    session = Streamlink()
    session.set_option("stream-segment-threads", 2)
    session.set_option("hls-live-restart", True)
    session.set_option("stream-segment-timeout", 3)
    stack.callback(session.http.close)
    stream = ChzzkHLSStream(
        session, cdn.url("primary"), "test", live_id=1,
        source_paths=[(cdn.url("primary"), False)],
        recording_time_machine=time_machine,
    )
    stream.continuity.provider = lambda: (1, [], None)
    stream.continuity.discover()
    reader = ChzzkContinuityReader(stream)
    stack.callback(reader.writer.close)
    return reader, stream.continuity


def test_time_machine_uses_whole_segments_without_partial_copies():
    with contextlib.ExitStack() as stack:
        cdn = stack.enter_context(CDN())
        groups = cdn.ll_playlist("primary", duration=0.2)
        reader, source = writer(stack, cdn, time_machine=True)
        source.primary.mode = "llhls"
        reader.open()
        result = bytearray()
        while data := reader.read(65536):
            result.extend(data)
        assert bytes(result) == INITIALIZATION + b"".join(groups)
        assert all(cdn.hits[f"/primary/1080p/{i}.m4v"] == 1 for i in range(4))
        assert not any("_" in path and path.endswith(".m4v") for path in cdn.hits)


def test_recovery_and_foreground_share_and_promote_the_same_request():
    with contextlib.ExitStack() as stack:
        cdn = stack.enter_context(CDN())
        cdn.playlist("primary")
        reader, source = writer(stack, cdn)
        target = source.locate(source.primary.playlist.segments[1], source.primary)
        gate, entered = threading.Event(), threading.Event()
        stack.callback(gate.set)
        cdn.body_gates["/primary/1080p/1.m4v"] = gate
        cdn.request_events["/primary/1080p/1.m4v"] = entered
        capture_stop = threading.Event()
        deadline = time.monotonic() + 3
        first = reader.writer.submit_request(target, target, deadline, capture_event=capture_stop)
        assert entered.wait(2)
        second = reader.writer.submit_request(target, target, deadline)
        assert first is second
        capture_stop.set()
        gate.set()
        assert second.result(timeout=3).media == MEDIA[1]
        assert cdn.hits["/primary/1080p/1.m4v"] == 1


def test_capture_does_not_enqueue_more_requests_than_available_workers():
    with contextlib.ExitStack() as stack:
        cdn = stack.enter_context(CDN())
        cdn.playlist("primary")
        reader, source = writer(stack, cdn)
        gate = threading.Event()
        stack.callback(gate.set)
        for i in range(4):
            cdn.body_gates[f"/primary/1080p/{i}.m4v"] = gate
        source.recovering = True
        reader.writer.capture_thread = threading.current_thread()
        reader.writer.capture_playlist(source.primary, source.primary.playlist)
        # Two delivery workers permit three bounded network requests, not a
        # separate 128-item background queue which competes with live delivery.
        assert len(reader.writer.pending_requests) == 3
        assert len(reader.writer.capture_pending) == 3


def test_recovery_ends_only_after_the_whole_missing_interval():
    with contextlib.ExitStack() as stack:
        cdn = stack.enter_context(CDN())
        cdn.playlist("primary")
        reader, source = writer(stack, cdn)
        targets = [source.locate(raw, source.primary) for raw in source.primary.playlist.segments]
        output = reader.writer
        output.deliver(targets[0], Download(targets[0], INITIALIZATION, MEDIA[0]))
        source.recovering = True
        deadline = source.recovery_limit()
        output.output_target = targets[3]
        output.capture_thread = threading.current_thread()
        for target in targets[1:3]:
            output.deliver(target, Download(target, INITIALIZATION, MEDIA[target.num]))
            assert source.recovering and output.capture_active()
            assert source.recovery_limit() == deadline
        output.deliver(targets[3], Download(targets[3], INITIALIZATION, MEDIA[3]))
        assert not source.recovering and not output.capture_active()
        assert source.recovery_deadline is None


@pytest.mark.asyncio
async def test_recording_receivers_do_not_exhaust_the_default_executor(tmp_path):
    loop = asyncio.get_running_loop()
    loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
    readers = [PendingReader(), PendingReader(), PendingReader()]
    pipes = []
    for i, reader in enumerate(readers):
        directory = tmp_path / str(i)
        directory.mkdir()
        pipes.append(pipeline(directory, reader))
    tasks = [asyncio.create_task(pipe._receive_packets()) for pipe in pipes]
    try:
        async with asyncio.timeout(2):
            while not all(reader.entered.is_set() for reader in readers):
                await asyncio.sleep(0.01)
        assert await asyncio.wait_for(asyncio.to_thread(lambda: "available"), 1) == "available"
    finally:
        for pipe, reader in zip(pipes, readers):
            pipe._intentional_stop = True
            reader.close()
        await asyncio.wait_for(asyncio.gather(*tasks), 5)
    assert all(pipe._closed for pipe in pipes)
    assert all(Path(pipe.output_path).read_bytes() == TS for pipe in pipes)
