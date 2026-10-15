"""녹화 중 미리보기가 추가 CDN 연결을 만들지 않고 완성된 FLV 패킷만 재사용한다."""
import asyncio
import io
from pathlib import Path
import shutil
import subprocess
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from app.engine.tiktok import TikTokLiveEngine
from app.engine.tiktok_transport import FLVPacketReader, TikTokMuxedReader, _ClosingReader, _closing_chunks
from app.engine.tiktok_preview import CapturePreview, capture_snapshot, register_capture
from app.engine.preview_frames import FramePreviewService, PreviewError, preview_error
from app.engine.recording_errors import RecordingError
from tests.test_new_platforms import local_hls
from app.engine.media_http_compat import install_media_http_compat

# 서버 진입점과 같은 초기화로 두 미디어 라이브러리의 import 순서에 영향을 받지 않게 한다.
install_media_http_compat()


HEADER = b'FLV\x01\x05\x00\x00\x00\x09\x00\x00\x00\x00'

def tag(kind, payload):
    return bytes([kind])+len(payload).to_bytes(3,'big')+bytes(7)+payload+(11+len(payload)).to_bytes(4,'big')


def drain(reader, size=7):
    output = bytearray()
    while data := reader.read(size):
        assert len(data) <= size
        output.extend(data)
    return bytes(output)


@pytest.mark.parametrize('size',[1, 7, 8192, 65536])
def test_packet_boundaries_preserve_encoded_bytes_and_observer(size):
    data = HEADER+tag(9,b'\x90hvc1header')+tag(9,b'\x91hvc1frame')+tag(8,b'\xaf\x01audio')
    capture = CapturePreview('fixture')
    reader = FLVPacketReader(io.BytesIO(data), observer=capture)
    assert drain(reader,size) == data and reader.error is None
    assert capture.snapshot() == data


@pytest.mark.parametrize('cut',[1, 5, 12, 22])
def test_cut_tag_is_not_forwarded_as_a_corrupt_nal_unit(cut):
    good = tag(9,b'\x91hvc1good-frame')
    partial = tag(9,b'\xa1hvc1next-frame')[:cut]
    reader = FLVPacketReader(io.BytesIO(HEADER+good+partial))
    assert drain(reader) == HEADER+good
    assert reader.error.code == 'tiktok_stream_truncated' and reader.error.retryable


def test_bad_flv_header_and_tag_lengths_are_rejected():
    reader = FLVPacketReader(io.BytesIO(b'<html>denied</html>'))
    assert drain(reader) == b'' and reader.error.code == 'tiktok_container'
    reader = FLVPacketReader(io.BytesIO(HEADER+tag(9,b'packet')[:-4]+b'\x00\x00\x00\x01'))
    assert drain(reader) == HEADER and reader.error.code == 'tiktok_container'


def test_source_timeout_is_reported_separately_from_ffmpeg_failure():
    raw = Mock(); raw.read.side_effect = OSError('Read timeout https://cdn.example/?token=SECRET')
    source = FLVPacketReader(raw)
    assert source.read(8192) == b''
    muxer = Mock(); muxer.read.return_value = b''; muxer.process.wait.return_value = 1
    with pytest.raises(RecordingError) as caught:
        TikTokMuxedReader(muxer,source).read(8192)
    assert caught.value.code == 'tiktok_connection' and caught.value.retryable
    assert 'SECRET' not in str(caught.value)


def test_intentional_stop_does_not_become_remux_failure():
    muxer, source = Mock(), Mock()
    muxer.read.return_value = b''; muxer.process.wait.return_value = -1
    reader = TikTokMuxedReader(muxer,source)
    reader.request_stop()
    assert reader.read(1024) == b''
    source.close.assert_called_once()


def test_streaming_response_closes_before_reader_join_and_only_once():
    calls = []
    response = SimpleNamespace(close=lambda:calls.append('response'))
    reader = SimpleNamespace(close=lambda:calls.append('reader'))
    closing = _ClosingReader(reader,response)
    closing.close();closing.close()
    assert calls == ['response','reader']


@pytest.mark.parametrize('stopping',[False,True])
def test_response_close_race_is_quiet_but_unexpected_read_errors_are_kept(stopping):
    event = threading.Event()
    if stopping:
        event.set()
    def chunks():
        yield b'accepted'
        raise AttributeError('closed socket has no readline')
    reader = _closing_chunks(chunks(),event)
    assert next(reader) == b'accepted'
    if stopping:
        assert list(reader) == []
    else:
        with pytest.raises(OSError,match='closed socket'):
            next(reader)


def test_preview_buffer_is_bounded_and_old_capture_cannot_remove_replacement(monkeypatch):
    old = register_capture('boundary')
    current = register_capture('boundary')
    old.close()
    assert capture_snapshot('boundary')[0]
    try:
        current.feed(HEADER,header=True)
        current.feed(tag(9,b'\x90hvc1header'))
        current.feed(tag(9,b'\x91hvc1key'))
        assert current.snapshot()
        current.MAX_BYTES = 32
        current.feed(tag(9,b'\xa1'+b'x'*100))
        assert current.size == 0 and current.snapshot() is None
        current.feed(tag(9,b'\x91new-key'))
        monkeypatch.setattr('app.engine.tiktok_preview.time.monotonic',lambda:100000000000)
        assert current.snapshot() is None
    finally:
        current.close()
    assert capture_snapshot('boundary') == (False,None)


@pytest.mark.parametrize('reason',[
    '[hevc @ 000001f403abc400] Invalid NAL unit size (401 > 398)',
    'Invalid NAL unit size (4031 > 4012)',
    'frame 404, sample 429, return 503',
])
def test_decoder_numbers_are_not_http_authentication_errors(reason):
    error = preview_error(reason)
    assert error.code != 'authentication' and error.status != 403


@pytest.mark.parametrize('status,code',[(401,'authentication'),(403,'authentication'),(404,'stream_expired'),(429,'rate_limited')])
def test_real_structured_http_status_still_has_its_own_reason(status,code):
    response = httpx.Response(status, request=httpx.Request('GET','https://cdn.example/'))
    assert preview_error(httpx.HTTPStatusError('upstream denied',request=response.request,response=response)).code == code


@pytest.mark.asyncio
async def test_best_prefers_original_at_same_resolution_and_preview_preserves_it(monkeypatch):
    engine = TikTokLiveEngine()
    rows = [dict(value='h265_origin',url='https://cdn.example/original.flv',width=1920,height=1080,weight=1000012,fps=None),
            dict(value='h265_uhd_60',url='https://cdn.example/converted.flv',width=1920,height=1080,weight=812,fps=60)]
    monkeypatch.setattr(engine,'_streams',AsyncMock(return_value=rows))
    assert (await engine.resolve_stream('alice','best'))[0] == rows[0]['url']
    assert (await engine.resolve_preview_stream('alice'))[0] == rows[0]['url']


@pytest.mark.asyncio
async def test_active_capture_preview_decodes_real_frame_without_any_upstream_request(local_hls,monkeypatch):
    _, directory = local_hls
    flv = directory/'preview.flv'
    subprocess.run([shutil.which('ffmpeg'),'-v','error','-i',str(directory/'720/index.m3u8'),'-c','copy','-f','flv',str(flv)],check=True)
    capture = register_capture('snapshot-fixture')
    try:
        assert drain(FLVPacketReader(io.BytesIO(flv.read_bytes()),observer=capture),8192)
        engine = SimpleNamespace(resolve_preview_stream=AsyncMock(side_effect=AssertionError('duplicate CDN request')))
        monkeypatch.setattr('app.engine.preview_frames.decode_preview',AsyncMock(side_effect=AssertionError('duplicate media request')))
        service = FramePreviewService()
        data,w,h = await service.get_frame('tiktok:snapshot-fixture','tiktok','snapshot-fixture',engine)
        assert data.startswith(b'\xff\xd8') and (w,h)==(1280,720)
        import app.main
        from app.api.stream import router
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        conductor = SimpleNamespace(_channels={'tiktok:snapshot-fixture':SimpleNamespace(is_live=True)},_get_engine=lambda platform:engine)
        monkeypatch.setattr(app.main,'get_recorder_service',lambda:SimpleNamespace(_conductor=conductor))
        monkeypatch.setattr('app.engine.preview_frames.frame_previews',FramePreviewService())
        app = FastAPI();app.include_router(router)
        with TestClient(app) as client:
            response = client.get('/api/stream/preview-frame/tiktok%3Asnapshot-fixture')
        assert response.status_code == 200 and response.headers['content-type'] == 'image/jpeg'
        assert response.content.startswith(b'\xff\xd8')
        engine.resolve_preview_stream.assert_not_awaited()
    finally:
        capture.close()


@pytest.mark.asyncio
async def test_recording_transition_survives_cancelled_previous_preview():
    service = FramePreviewService()
    closed = asyncio.Event()

    async def old_preview():
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()

    pending = asyncio.create_task(old_preview())
    service._inflight['tiktok:cancelled-transition'] = pending
    finishing = asyncio.create_task(service.finish_current_frame('tiktok:cancelled-transition'))
    await asyncio.sleep(0)
    pending.cancel()
    await finishing
    assert closed.is_set() and finishing.cancelling() == 0


@pytest.mark.asyncio
async def test_recording_transition_preserves_recording_cancellation():
    service = FramePreviewService()
    pending = asyncio.create_task(asyncio.Event().wait())
    service._inflight['tiktok:cancel-recording'] = pending
    finishing = asyncio.create_task(service.finish_current_frame('tiktok:cancel-recording'))
    try:
        await asyncio.sleep(0)
        finishing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await finishing
        assert not pending.done()
    finally:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.asyncio
async def test_capture_waiting_for_keyframe_never_opens_a_competing_connection():
    capture = register_capture('waiting-fixture')
    engine = SimpleNamespace(resolve_preview_stream=AsyncMock(side_effect=AssertionError('duplicate connection')))
    try:
        with pytest.raises(PreviewError) as caught:
            await FramePreviewService().get_frame('tiktok:waiting-fixture','tiktok','waiting-fixture',engine)
        assert caught.value.code == 'connecting' and caught.value.retryable
        engine.resolve_preview_stream.assert_not_awaited()
    finally:
        capture.close()


@pytest.mark.asyncio
async def test_recording_transition_waits_for_previous_preview_to_close():
    service = FramePreviewService()
    released, closed = asyncio.Event(), asyncio.Event()
    async def old_preview():
        try:
            await released.wait()
            return b'image',1280,720
        finally:
            closed.set()
    pending = asyncio.create_task(old_preview())
    service._inflight['tiktok:transition'] = pending
    capture = register_capture('transition')
    try:
        finishing = asyncio.create_task(service.finish_current_frame('tiktok:transition'))
        await asyncio.sleep(0)
        assert capture_snapshot('transition') == (True,None) and not finishing.done()
        released.set()
        await finishing
        assert closed.is_set() and pending.done()
    finally:
        capture.close()
