"""A stop must drain native Streamlink bytes and preserve integrity failures."""

import asyncio
import threading
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.engine.pipeline.ytdlp import YtdlpLivePipeline
from app.engine.pipeline.state import RecordingState


TS = (b"\x47" + b"\x00" * 187) * 4


class PendingReader:
    def __init__(self):
        self.entered = threading.Event()
        self.stopped = threading.Event()
        self.sent = False
        self.worker = SimpleNamespace(playlist_end=None)

    def read(self, size):
        self.entered.set()
        self.stopped.wait(3)
        if self.sent:
            return b""
        self.sent = True
        return TS

    def request_stop(self):
        self.stopped.set()

    def close(self):
        self.stopped.set()


def pipeline(tmp_path, reader):
    pipe = YtdlpLivePipeline("shutdown")
    pipe._output_path = str(tmp_path / "녹화 파일.ts")
    pipe._source_files = [pipe._output_path + ".part"]
    Path(pipe._source_files[0]).touch()
    pipe._readers = [reader]
    pipe._closed = False
    pipe._start_time = datetime.now()
    pipe._state = RecordingState.RECORDING
    return pipe


@pytest.mark.asyncio
async def test_stop_drains_bytes_already_accepted_by_reader(tmp_path):
    reader = PendingReader()
    pipe = pipeline(tmp_path, reader)
    # Start with no consumer scheduled yet: a stop must still drain the buffer.
    pipe._feeder_task = asyncio.create_task(pipe._receive_packets())
    await pipe.stop_recording()
    assert pipe._closed and pipe._feeder_task.done()
    assert Path(pipe._output_path).read_bytes() == TS
    assert pipe.state == RecordingState.COMPLETED


@pytest.mark.asyncio
async def test_sealing_failed_capture_does_not_erase_error(tmp_path):
    pipe = pipeline(tmp_path, PendingReader())
    Path(pipe._source_files[0]).write_bytes(TS)
    pipe._closed = True
    pipe._state = RecordingState.ERROR
    pipe.error_code = "forced_stop"
    pipe.end_reason = "forced_stop"
    await pipe._seal_sources()
    assert pipe.state == RecordingState.ERROR
    assert Path(pipe._source_files[0]).read_bytes() == TS


@pytest.mark.asyncio
async def test_cancelled_stop_drains_but_never_reports_success(tmp_path):
    class Delayed(PendingReader):
        def request_stop(self):
            self.entered.set()
            self.stopped.wait(3)
    reader = Delayed()
    pipe = pipeline(tmp_path, reader)
    pipe._feeder_task = asyncio.create_task(pipe._receive_packets())
    stopping = asyncio.create_task(pipe.stop_recording())
    await asyncio.to_thread(reader.entered.wait, 2)
    stopping.cancel()
    reader.stopped.set()
    with pytest.raises(asyncio.CancelledError):
        await stopping
    assert pipe._closed and pipe._feeder_task.done()
    assert pipe.state == RecordingState.ERROR
    assert pipe.output_errors == ['forced_stop']
    assert Path(pipe._source_files[0]).read_bytes() == TS


@pytest.mark.asyncio
async def test_drain_timeout_never_seals_open_writer(tmp_path):
    pipe = pipeline(tmp_path, PendingReader())
    done = asyncio.Event()
    pipe._feeder_task = asyncio.create_task(done.wait())
    pipe.STOP_DRAIN_SECONDS = 0.01
    with pytest.raises(Exception, match='녹화 종료가 완료되지'):
        await pipe.stop_recording()
    assert not pipe._closed and not pipe._feeder_task.done()
    assert pipe.state == RecordingState.ERROR and pipe.output_errors == ['forced_stop']
    assert Path(pipe._source_files[0]).exists() and not Path(pipe._output_path).exists()
    done.set()
    await pipe._feeder_task
    # After the actual writer exits, a second stop can finish ownership cleanup.
    pipe._closed = True
    await pipe.stop_recording()
    assert pipe._closed and pipe.state == RecordingState.ERROR


@pytest.mark.asyncio
async def test_failed_shutdown_is_durable_and_not_automatically_converted(tmp_path):
    from app.engine.recording_finalizer import RecordingFinalizer
    from tests.test_recording_finalization import channel
    pipe = pipeline(tmp_path, PendingReader())
    Path(pipe._source_files[0]).write_bytes(TS)
    pipe._closed = True
    pipe._record_output_error('forced_stop')
    manager = RecordingFinalizer()
    job_id = manager.register_capture('chzzk:shutdown', pipe, channel(),
        {'output_format': 'mkv', 'keep_source_ts': False})
    job = await manager.capture_finished(job_id, pipe)
    assert job['state'] == 'attention' and job['continuity_valid'] is False
    assert job['can_retry'] and job['source_available']
    assert job['diagnostics']['output_errors'] == ['forced_stop']
    assert RecordingFinalizer().get(job_id)['state'] == 'attention'
    assert job_id not in manager._active
    assert Path(job['source_paths'][0]).read_bytes() == TS


def test_cooperative_stop_waits_for_media_and_checkpoint():
    from app.engine.chzzk_continuity import ChzzkContinuityWriter, Download
    from tests.test_chzzk_continuity import INITIALIZATION, MEDIA, START
    from collections import OrderedDict
    from datetime import timedelta
    entered, release, stopped = threading.Event(), threading.Event(), threading.Event()
    output, events = bytearray(), []
    class Buffer:
        def write(self, data):
            if data == MEDIA[0]:
                output.extend(data[:5])
                entered.set()
                release.wait(3)
                output.extend(data[5:])
            else:
                output.extend(data)
    writer = ChzzkContinuityWriter.__new__(ChzzkContinuityWriter)
    writer.delivery_lock = threading.RLock()
    writer.stop_requested = threading.Event()
    writer.source = SimpleNamespace(stop=stopped, resume=None, recovering=False,
        emit=lambda kind, **fields: events.append({'kind': kind, **fields}), progressed=lambda: None)
    writer.reader = SimpleNamespace(buffer=Buffer(), worker=SimpleNamespace(close=lambda: None))
    writer.failed, writer.previous, writer.media_buffer = False, None, None
    writer.selected_source, writer.start_download = None, None
    writer.cache_lock, writer.parts = threading.Lock(), OrderedDict()
    writer.close = stopped.set
    target = SimpleNamespace(num=0, date=START, end=START+timedelta(seconds=4))
    located = SimpleNamespace(manifest=SimpleNamespace(cdn='korean'))
    delivering = threading.Thread(target=writer.deliver, args=(target, Download(located, INITIALIZATION, MEDIA[0])))
    delivering.start()
    assert entered.wait(2)
    stopping = threading.Thread(target=writer.request_stop)
    stopping.start()
    assert writer.stop_requested.wait(2) and not stopped.is_set()
    release.set()
    delivering.join(3)
    stopping.join(3)
    assert not delivering.is_alive() and not stopping.is_alive()
    assert bytes(output) == INITIALIZATION + MEDIA[0]
    assert any(event['kind'] == 'checkpoint' for event in events)
    assert not writer.deliver(target, Download(located, INITIALIZATION, MEDIA[0]))
