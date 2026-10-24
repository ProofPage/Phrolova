"""공개 요청의 런타임 일치, 잘못된 인증 안내와 워커 취소를 회귀 검사한다."""
import asyncio
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import yt_dlp
from yt_dlp.version import __version__
from app.core.config import get_settings
from app.engine import youtube_support as support
from app.engine.vod import VodEngine, VodDownloadTask
from app.engine.recording_errors import classify_recording_error


def test_worker_fallback_uses_same_package_without_external_cli(monkeypatch):
    monkeypatch.setattr(type(get_settings()), 'resolve_ytdlp_path',
                        lambda _: (_ for _ in ()).throw(FileNotFoundError("fixture")))
    result = subprocess.run([*support.youtube_extractor_command(), '--ignore-config', '--version'],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0 and result.stdout.strip() == __version__


def test_frozen_worker_command_and_desktop_worker_entry(monkeypatch):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(type(get_settings()), 'resolve_ytdlp_path',
                        lambda _: (_ for _ in ()).throw(FileNotFoundError("fixture")))
    assert support.youtube_extractor_command() == [sys.executable, '--youtube-worker']
    result = subprocess.run([sys.executable, str(Path(__file__).parents[1] / 'run.py'),
                             '--youtube-worker', '--ignore-config', '--version'],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0 and result.stdout.strip() == __version__


@pytest.mark.asyncio
async def test_metadata_and_download_share_runtime_and_public_options(monkeypatch, tmp_path):
    get_settings().youtube_cookie_file = str(tmp_path / 'stale.txt')
    monkeypatch.setattr(support, 'runtime_options', lambda: {'js_runtimes': {'node': {'path': '/app/node'}}})
    monkeypatch.setattr(type(get_settings()), 'resolve_ffmpeg_path', lambda _: 'ffmpeg')
    seen = []
    def extract(ydl, *args, **kwargs):
        seen.append(ydl.params)
        return {'id': 'MFRcNvE-dGA', 'title': 'Public video', 'formats': []}
    monkeypatch.setattr(yt_dlp.YoutubeDL, 'extract_info', extract)
    engine = VodEngine()
    await engine.get_video_info('https://www.youtube.com/watch?v=MFRcNvE-dGA')
    seen.append(engine._build_ytdlp_options(VodDownloadTask(url='https://youtu.be/MFRcNvE-dGA', output_dir=str(tmp_path))))
    assert len(seen) == 2
    for options in seen:
        assert options['js_runtimes'] == {'node': {'path': '/app/node'}}
        assert options['sleep_interval_requests'] == 1
        assert 'cookiefile' not in options and 'cookiesfrombrowser' not in options
        assert not options.get('extractor_args', {}).get('youtube', {}).get('player_client')


@pytest.mark.asyncio
@pytest.mark.parametrize('message,code', [("Sign in to confirm you're not a bot", 'youtube_bot_check'),
                                        ('HTTP Error 429: Too Many Requests', 'youtube_rate_limit')])
async def test_public_access_failures_do_not_demand_cookies_or_retry(monkeypatch, tmp_path, message, code):
    get_settings().youtube_cookie_file = None
    calls = []
    async def denied(cookie_file):
        calls.append(cookie_file)
        raise RuntimeError(message + ' https://example.com/?token=SECRET')
    with pytest.raises(support.YouTubeAccessError) as error:
        await support.with_youtube_cookie_fallback(denied)
    assert error.value.code == code and calls == [None]
    assert 'SECRET' not in str(error.value) and '쿠키' not in str(error.value)
    failure = classify_recording_error(error.value)
    assert failure.code == code and not failure.retryable
    assert support.youtube_auth_message(message) is None


@pytest.mark.asyncio
async def test_public_preview_does_not_open_stale_cookie(monkeypatch):
    from app.engine.conductor import Conductor
    from app.engine.base import Platform
    from app.engine.pipeline import YtdlpLivePipeline
    conductor = Conductor.__new__(Conductor)
    conductor._channels = {'youtube:x': SimpleNamespace(is_live=True, channel_id='x', platform=Platform.YOUTUBE)}
    conductor._get_engine = lambda _: SimpleNamespace(get_stream_url=lambda _: 'https://www.youtube.com/@x/live')
    monkeypatch.setattr(support, 'youtube_cookies', lambda: pytest.fail('public preview opened saved cookies'))
    resolve = AsyncMock(return_value=('https://cdn.example/live.m3u8', {}, None))
    monkeypatch.setattr(YtdlpLivePipeline, '_extract_preview_hls_url', resolve)
    assert await conductor.get_live_preview_url('youtube:x') == 'https://cdn.example/live.m3u8'
    resolve.assert_awaited_once_with('https://www.youtube.com/@x/live', cookie_file=None)


@pytest.mark.asyncio
async def test_worker_is_killed_and_reaped_when_live_resolution_is_cancelled(monkeypatch):
    from app.engine.pipeline import YtdlpLivePipeline
    started = asyncio.Event()
    class Process:
        returncode = None
        killed = False
        calls = 0
        async def communicate(self):
            self.calls += 1
            if self.killed: return b'', b''
            started.set()
            await asyncio.Future()
        def kill(self):
            self.killed = True
            self.returncode = -1
    process = Process()
    monkeypatch.setattr('app.engine.pipeline.ytdlp.require_runtime_cli_options', lambda: ['--js-runtimes', 'node:/app/node'])
    monkeypatch.setattr('asyncio.create_subprocess_exec', AsyncMock(return_value=process))
    task = asyncio.create_task(YtdlpLivePipeline('x')._extract_hls_url('https://www.youtube.com/@x/live', 'best', None))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    assert process.killed and process.calls == 2
