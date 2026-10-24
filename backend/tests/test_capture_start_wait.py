"""Startup timeout keeps ownership of the receiver's eventual exception."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.engine.pipeline.ytdlp import YtdlpLivePipeline
from app.engine.recording_errors import RecordingError


@pytest.mark.asyncio
async def test_retryable_source_failure_reconnects_on_new_address(monkeypatch, tmp_path):
    """만료된 재생 주소로 끊긴 수신은 녹화를 끝내지 않고 새로 받은 주소로 다시 붙는다."""
    import threading

    from app.engine.pipeline.ytdlp import RecordingState

    pipeline = YtdlpLivePipeline("fixture")
    pipeline.capture_format = "ts"
    served, opened = [], []

    async def resolve(quality):
        served.append(quality)
        return (
            f"https://livestream.rplay.live/live/fixture_abrhd/index.m3u8?attempt={len(served)}",
            {"Referer": "https://livestream.rplay.live"},
            None,
        )

    def make_reader():
        loop = asyncio.get_running_loop()
        closed = threading.Event()

        def close():
            closed.set()
            loop.call_soon_threadsafe(lambda: None)

        def read(size=-1):
            if closed.is_set():
                return b""
            closed.wait(0.05)
            return b"" if closed.is_set() else (b"\x47" + bytes(187)) * 20

        return SimpleNamespace(close=close, read=read)

    async def open_raw(*args):
        opened.append(args)
        return SimpleNamespace(http=SimpleNamespace(close=Mock())), [make_reader()]

    monkeypatch.setattr(pipeline, "_open_raw_readers", open_raw)
    monkeypatch.setattr(pipeline, "_update_statistics_loop", AsyncMock())
    monkeypatch.setattr(pipeline, "_measure_ts", Mock())
    monkeypatch.setattr(pipeline, "_write_losscheck", AsyncMock())
    pipeline._source_resolver = resolve
    pipeline._quality = "720p"
    pipeline._resume_args = ("https://livestream.rplay.live/live/fixture_abrhd/index.m3u8", {}, None, 0, False, "720p")
    pipeline._source_files = [str(tmp_path / "fixture.ts.part")]
    (tmp_path / "fixture.ts.part").touch()
    pipeline._output_path = str(tmp_path / "fixture.ts")
    pipeline._state = RecordingState.RECORDING

    await asyncio.wait_for(pipeline._reconnect_source(), 10)

    # 주소는 한 번만 다시 받고, 그 새 주소로 한 번만 다시 연결한다.
    assert served == ["720p"]
    assert len(opened) == 1
    assert opened[0][0].endswith("attempt=1")
    assert opened[0][5] == "720p"
    assert pipeline._resume_args[0].endswith("attempt=1")
    assert pipeline.state == RecordingState.RECORDING
    pipeline._intentional_stop = True
    pipeline._force_stop.set()
    for reader in list(pipeline._readers):
        await asyncio.to_thread(reader.close)
    await asyncio.wait_for(pipeline._feeder_task, 10)


@pytest.mark.asyncio
@pytest.mark.parametrize("cancelled", [False, True])
async def test_startup_shutdown_consumes_late_failure_without_shield_warning(monkeypatch, cancelled):
    pipeline = YtdlpLivePipeline("fixture")
    pipeline._resume_args = ()
    pipeline._source_files = ["fixture.part"]
    loop = asyncio.get_running_loop()
    closed = asyncio.Event()
    reader = SimpleNamespace(close=lambda: loop.call_soon_threadsafe(closed.set))
    session = SimpleNamespace(http=SimpleNamespace(close=Mock()))
    monkeypatch.setattr(pipeline, "_open_raw_readers", AsyncMock(return_value=(session, [reader])))
    monkeypatch.setattr(pipeline, "_update_statistics_loop", AsyncMock())

    async def receive():
        await closed.wait()
        pipeline._capture_ready.set_exception(
            RecordingError("empty_stream", "녹화 데이터가 수신되지 않았습니다."))

    monkeypatch.setattr(pipeline, "_receive_packets", receive)

    async def expired_wait(futures, *, timeout):
        assert timeout == 45
        if cancelled:
            raise asyncio.CancelledError()
        return set(), set(futures)

    async def expired_wait_for(future, timeout):
        # Model the old wait_for(shield(...)) timeout/cancellation exactly.
        future.cancel()
        if cancelled:
            raise asyncio.CancelledError()
        raise asyncio.TimeoutError()

    monkeypatch.setattr(asyncio, "wait", expired_wait)
    monkeypatch.setattr(asyncio, "wait_for", expired_wait_for)
    errors = []
    previous = loop.get_exception_handler()
    loop.set_exception_handler(lambda _, context: errors.append(context))
    try:
        with pytest.raises(asyncio.CancelledError if cancelled else asyncio.TimeoutError):
            await pipeline._begin_receiver()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert pipeline._feeder_task.done()
        assert pipeline._capture_ready.exception().code == "empty_stream"
        assert not errors, errors
    finally:
        loop.set_exception_handler(previous)
