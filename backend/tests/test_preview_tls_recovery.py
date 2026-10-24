"""Actual verified HTTPS HLS and dependency repair. Keys are localhost-only test fixtures."""
import asyncio, functools, http.server, shutil, ssl, threading
from pathlib import Path
from unittest.mock import AsyncMock
import certifi
import pytest
from app.core.config import Settings
from app.engine.preview_frames import FramePreviewService, PreviewError
from tests.test_new_platforms import local_hls

@pytest.mark.asyncio
async def test_untrusted_tls_is_rejected_then_trusted_nested_segments_decode(local_hls, monkeypatch, caplog):
    _, directory = local_hls
    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args): pass
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(directory)))
    certificates = Path(__file__).parent/'fixtures/tls'
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificates/'localhost.pem', certificates/'localhost-key.pem')
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    engine = type('Engine', (), {})()
    engine.get_qualities = AsyncMock(return_value=[{'height':720, 'value':'720p'}])
    url = f'https://127.0.0.1:{server.server_port}/720/index.m3u8?hdntl=SECRET'
    engine.resolve_stream_spec = AsyncMock(return_value={'url':url, 'preview_url':url, 'headers':{}, 'cookies':None})
    service = FramePreviewService()
    monkeypatch.setattr('app.engine.preview_transport.preview_ca_bundle', lambda: certifi.where())
    try:
        with pytest.raises(PreviewError) as caught:
            await service.get_frame('cime:tls', 'cime', 'tls', engine)
        assert caught.value.code == 'tls_certificate'
        assert 'SECRET' not in caplog.text
        monkeypatch.setattr('app.engine.preview_transport.preview_ca_bundle', lambda: str(certificates/'localhost.pem'))
        monkeypatch.setattr('app.engine.preview_frames.time.monotonic', lambda: 100000000000)
        data, width, height = await service.get_frame('cime:tls', 'cime', 'tls', engine)
        assert data.startswith(b'\xff\xd8') and (width,height)==(1280,720)
        assert 'cime:tls' not in service._failures
    finally:
        await asyncio.to_thread(server.shutdown); server.server_close(); thread.join(timeout=2)

@pytest.mark.asyncio
async def test_missing_ffprobe_preserves_raw_file_and_same_job_recovers(local_hls, monkeypatch):
    from app.engine.recording_finalizer import RecordingFinalizer
    from tests.test_recording_finalization import stopped_job, terminal
    _, directory = local_hls
    source = directory/'복구 원본 [공백].ts'; shutil.copy(directory/'720/index0.ts', source)
    original = source.read_bytes(); resolver = Settings.resolve_ffprobe_path
    monkeypatch.setattr(Settings, 'resolve_ffprobe_path', lambda _: (_ for _ in ()).throw(FileNotFoundError('not installed')))
    manager = RecordingFinalizer()
    try:
        job_id = await stopped_job(manager, source, fmt='mkv', keep=True)
        failed = await terminal(manager, job_id)
        assert failed['state']=='failed' and failed['error_code']=='tool_missing'
        assert failed['processing_stage']=='source_inspection'
        assert 'FFprobe' in failed['error_message'] and source.read_bytes()==original
        assert failed['can_retry'] and failed['can_inspect'] and failed['can_open']
        monkeypatch.setattr(Settings, 'resolve_ffprobe_path', resolver)
        await manager.retry(job_id, inspect_only=True)
        repaired = await terminal(manager, job_id)
        # Inspection of the original alone must not falsely report that MKV exists.
        assert source.read_bytes()==original
        await manager.retry(job_id)
        completed = await terminal(manager, job_id)
        assert completed['state']=='completed' and completed['error_code'] is None
        assert completed['output_available'] and source.read_bytes()==original
        assert len(manager.list_jobs())==1
    finally: await manager.close()
