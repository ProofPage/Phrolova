import asyncio
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.core.config import Settings
from app.engine.preview_frames import FramePreviewService, PreviewError, preview_error
from app.engine.media_tools import check_media_tool

@pytest.mark.parametrize('reason,code,status', [
    ('Peer certificate failed verification', 'tls_certificate', 502),
    ('HTTP 401', 'authentication', 403), ('HTTP 403', 'authentication', 403),
    ('HTTP 404', 'stream_expired', 502), ('HTTP 429', 'rate_limited', 429),
    ('HTTP 500', 'upstream_error', 502), ('HTTP 503', 'upstream_error', 502),
    ('read timeout', 'timeout', 502), ('offline connection', 'connection', 502),
])
def test_distinct_safe_preview_errors(reason, code, status):
    error = preview_error(reason + ' https://example.com?token=SECRET')
    assert (error.code, error.status) == (code, status)
    assert 'SECRET' not in str(error)

@pytest.mark.asyncio
async def test_failure_coalescing_backoff_and_recovery(monkeypatch):
    service = FramePreviewService()
    generate = AsyncMock(side_effect=RuntimeError('HTTP 429 private-url'))
    monkeypatch.setattr(service, '_generate', generate)
    errors = await asyncio.gather(*(service.get_frame('cime:a', 'cime', 'a', None) for _ in range(10)), return_exceptions=True)
    assert all(isinstance(error, PreviewError) and error.code == 'rate_limited' for error in errors)
    generate.assert_awaited_once()
    monkeypatch.setattr('app.engine.preview_frames.time.monotonic', lambda: 100000000000)
    generate.side_effect = None
    generate.return_value = (b'image', 1920, 1080)
    assert await service.get_frame('cime:a', 'cime', 'a', None) == generate.return_value
    assert 'cime:a' not in service._failures

@pytest.mark.asyncio
async def test_deleted_or_offline_channel_cancels_preview_without_recording_access(monkeypatch):
    service = FramePreviewService()
    started = asyncio.Event(); closed = asyncio.Event()
    async def generate(*args):
        started.set()
        try: await asyncio.sleep(100)
        finally: closed.set()
    monkeypatch.setattr(service, '_generate', generate)
    task = asyncio.create_task(service.get_frame('cime:a', 'cime', 'a', None))
    await started.wait(); service.invalidate('cime:a')
    with pytest.raises(asyncio.CancelledError): await task
    assert closed.is_set() and not service._inflight

@pytest.mark.parametrize('tool', ['ffmpeg', 'ffprobe'])
@pytest.mark.parametrize('case', ['missing', 'permission', 'timeout', 'bad_exit', 'wrong_binary', 'success'])
def test_tools_are_independently_executed(monkeypatch, tool, case):
    monkeypatch.setattr(Settings, f'resolve_{tool}_path', lambda _: 'configured-tool')
    def run(args, **kwargs):
        assert args == ['configured-tool', '-version'] and kwargs['timeout'] == 5
        if case == 'missing': raise FileNotFoundError()
        if case == 'permission': raise PermissionError()
        if case == 'timeout': raise subprocess.TimeoutExpired(args, 5)
        return subprocess.CompletedProcess(args, 1 if case == 'bad_exit' else 0,
            (f'{tool} version fixture' if case == 'success' else 'not a media tool').encode(), b'')
    monkeypatch.setattr('app.engine.media_tools.subprocess.run', run)
    result = check_media_tool(tool)
    assert result['available'] == (case == 'success')
    if case == 'missing': assert result['code'] == 'tool_missing'

def test_ffprobe_beside_configured_ffmpeg_and_frozen_bundle(tmp_path, monkeypatch):
    import sys
    ffmpeg = tmp_path / 'ffmpeg.exe'; ffmpeg.touch()
    probe = tmp_path / 'ffprobe.exe'; probe.touch()
    monkeypatch.setattr('app.core.config.sys.platform', 'win32')
    monkeypatch.setattr('app.core.config.shutil.which', lambda _: None)
    assert Settings(ffmpeg_path=str(ffmpeg)).resolve_ffprobe_path() == str(probe.resolve())
    bundle = tmp_path / 'bundle'; (bundle / 'bin').mkdir(parents=True)
    (bundle / 'bin' / 'ffprobe.exe').touch()
    monkeypatch.setattr(sys, '_MEIPASS', str(bundle), raising=False)
    monkeypatch.setattr(Settings, 'resolve_ffmpeg_path', lambda _: (_ for _ in ()).throw(FileNotFoundError()))
    assert Settings(ffprobe_path='absent').resolve_ffprobe_path() == str((bundle / 'bin' / 'ffprobe.exe').resolve())

def test_remote_folder_request_never_opens_server_shell(tmp_path, monkeypatch):
    from app.api.recordings import router
    monkeypatch.setattr('app.api.recordings.output', lambda _: tmp_path / 'video.ts')
    monkeypatch.setattr('app.api.recordings.asyncio.to_thread', AsyncMock(side_effect=AssertionError('remote shell')))
    app = FastAPI(); app.include_router(router)
    result = TestClient(app, client=('192.0.2.1', 123)).post('/api/recordings/registered/open-location')
    assert result.status_code == 200 and result.json()['opened'] is False

def test_vod_retries_are_bounded_and_missing_fragments_are_not_completed(monkeypatch, tmp_path):
    from app.engine.vod import VodDownloadTask, VodEngine
    monkeypatch.setattr(Settings, 'resolve_ffmpeg_path', lambda _: 'ffmpeg')
    task = VodDownloadTask(task_id='a', url='https://chzzk.naver.com/video/1', output_dir=str(tmp_path))
    options = VodEngine()._build_ytdlp_options(task)
    assert options['skip_unavailable_fragments'] is False
    assert options['concurrent_fragment_downloads'] == 2
    assert options['fragment_retries'] == 10
    assert 0 < options['retry_sleep_functions']['fragment'](1000) <= 30

@pytest.mark.asyncio
@pytest.mark.parametrize('recover', [True, False])
async def test_metadata_timeout_retries_once_and_reports_timeout(monkeypatch, recover):
    from app.engine.vod import VodEngine
    calls = []
    class Extractor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def extract_info(self, *args, **kwargs):
            calls.append(1)
            if len(calls) == 1 or not recover: raise TimeoutError('HTTP timeout https://example.com?token=SECRET')
            return {'id':'1', 'title':'Recovered', 'formats':[]}
    monkeypatch.setattr('app.engine.vod.platform_ydl', lambda *args: Extractor())
    if recover:
        assert (await VodEngine().get_video_info('https://example.com/video'))['title'] == 'Recovered'
    else:
        with pytest.raises(ValueError, match='시간이 초과') as error:
            await VodEngine().get_video_info('https://example.com/video')
        assert 'SECRET' not in str(error.value)
    assert len(calls) == 2


@pytest.mark.parametrize('case', ['success', 'missing', 'broken'])
def test_streamlink_health_uses_recording_package(monkeypatch, case):
    import sys
    from unittest.mock import Mock
    close = Mock()
    def create_session():
        if case == 'broken':
            raise RuntimeError('package initialization failed')
        return SimpleNamespace(http=SimpleNamespace(close=close))
    package = SimpleNamespace(__file__='C:/app/streamlink/__init__.py', __version__='8.6.2', Streamlink=create_session)
    monkeypatch.setitem(sys.modules, 'streamlink', None if case == 'missing' else package)
    result = check_media_tool('streamlink')
    assert result['available'] == (case == 'success')
    if case == 'success':
        assert result['path'] == package.__file__ and result['version'] == '8.6.2'
        close.assert_called_once()
    else:
        assert result['code'] == ('tool_missing' if case == 'missing' else 'tool_failed')


def test_tools_api_includes_all_runtime_media_tools(monkeypatch):
    from app.api.system import router
    calls = []
    def inspect(name):
        calls.append(name)
        return {'available': name != 'streamlink', 'path': name, 'version': 'fixture'}
    monkeypatch.setattr('app.engine.media_tools.check_media_tool', inspect)
    app = FastAPI()
    app.include_router(router)
    result = TestClient(app).get('/api/system/media-tools')
    assert result.status_code == 200
    assert set(result.json()) == set(calls) == {'streamlink', 'yt-dlp', 'ffmpeg', 'ffprobe', 'N_m3u8DL-RE'}
    assert result.json()['yt-dlp'] == {'available': True, 'path': 'yt-dlp', 'version': 'fixture'}
    assert result.json()['streamlink']['available'] is False
    assert result.json()['ffmpeg']['available'] is True


@pytest.mark.parametrize('case', ['stable', 'nightly', 'missing', 'permission', 'timeout', 'bad_exit', 'empty', 'wrong_binary'])
def test_ytdlp_inspection_uses_runtime_binary_without_download(monkeypatch, case):
    binary = 'C:/한글 도구/bin/yt-dlp.exe'
    def resolve(_, *, auto_download):
        assert auto_download is False
        if case == 'missing':
            raise FileNotFoundError()
        return binary
    monkeypatch.setattr(Settings, 'resolve_ytdlp_path', resolve)
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        assert args == [binary, '--version']
        assert kwargs['timeout'] == 5 and not kwargs.get('shell')
        if case == 'permission': raise PermissionError('access denied')
        if case == 'timeout': raise subprocess.TimeoutExpired(args, 5)
        output = {'stable': b'2026.10.14\r\n', 'nightly': b'2026.10.14.232354.dev0\n',
                  'empty': b'', 'wrong_binary': b'Python 3.12.10'}.get(case, b'2026.10.14')
        return subprocess.CompletedProcess(args, 1 if case == 'bad_exit' else 0, output, b'')
    monkeypatch.setattr('app.engine.media_tools.subprocess.run', run)
    result = check_media_tool('yt-dlp')
    assert result['available'] == (case in ('stable', 'nightly'))
    if case == 'missing':
        assert not calls and result['code'] == 'tool_missing' and 'path' not in result
    else:
        assert result['path'] == binary
        if case in ('stable', 'nightly'):
            assert result['version'] == ('2026.10.14' if case == 'stable' else '2026.10.14.232354.dev0')
        else:
            assert result['code'] == 'tool_failed'
