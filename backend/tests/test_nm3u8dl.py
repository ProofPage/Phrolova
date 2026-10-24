from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.engine.nm3u8dl import fallback_stream, download_hls


INFO = {"url": "https://cdn.example/video.m3u8", "protocol": "m3u8_native",
        "http_headers": {"Referer": "https://example.com/", "User-Agent": "fixture"}}


def test_only_resolved_clear_single_hls_is_eligible():
    assert fallback_stream(INFO, RuntimeError("fragment failed"))["url"] == INFO["url"]
    for extra in ({"has_drm": True}, {"is_live": True}, {"requested_formats": [INFO]},
                  {"protocol": "http"}, {"_type": "multi_video"},
                  {"requested_downloads": [INFO, INFO]},
                  {"http_headers": {"Cookie": "secret"}}):
        assert fallback_stream({**INFO, **extra}, RuntimeError("failed")) is None
    for error in ("HTTP Error 403", "login required", "DRM protected", "disk full"):
        assert fallback_stream(INFO, RuntimeError(error)) is None


@pytest.mark.asyncio
async def test_independent_process_and_output(monkeypatch, tmp_path):
    from pathlib import Path
    calls = []
    process = SimpleNamespace(returncode=0, wait=AsyncMock(return_value=0))

    async def spawn(*args, **kwargs):
        calls.append((args, kwargs))
        folder = Path(args[args.index("--save-dir") + 1])
        (folder / "fallback.mp4").write_bytes(b"download-fixture")
        return process

    monkeypatch.setattr("app.engine.nm3u8dl.asyncio.create_subprocess_exec", spawn)
    task = SimpleNamespace(cancel_flag=False, process=None)
    result = await download_hls(task, INFO, "N_m3u8DL-RE.exe", "ffmpeg.exe", tmp_path / "video.mp4")
    assert Path(result).read_bytes() == b"download-fixture" and task.process is None
    args, kwargs = calls[0]
    assert args[0] == "N_m3u8DL-RE.exe" and "--no-log" in args
    assert "Referer: https://example.com/" in args
    assert not kwargs.get("shell")


@pytest.mark.asyncio
async def test_cancelled_task_never_starts_process(monkeypatch, tmp_path):
    from app.engine.vod import DownloadCancelledError
    spawn = AsyncMock()
    monkeypatch.setattr("app.engine.nm3u8dl.asyncio.create_subprocess_exec", spawn)
    with pytest.raises(DownloadCancelledError):
        await download_hls(SimpleNamespace(cancel_flag=True), INFO, "tool", "ffmpeg", tmp_path / "x.mp4")
    spawn.assert_not_awaited()


@pytest.mark.asyncio
async def test_old_tool_does_not_receive_global_auth_headers(monkeypatch, tmp_path):
    monkeypatch.setattr("app.engine.nm3u8dl.supports_cookie_file", lambda _: False)
    spawn = AsyncMock()
    monkeypatch.setattr("app.engine.nm3u8dl.asyncio.create_subprocess_exec", spawn)
    with pytest.raises(RuntimeError, match="쿠키 파일"):
        await download_hls(SimpleNamespace(cancel_flag=False), INFO, "old-tool", "ffmpeg",
                           tmp_path / "x.mp4", "scoped-cookies.txt")
    spawn.assert_not_awaited()


@pytest.mark.asyncio
async def test_actual_optional_tool_local_hls(tmp_path):
    import functools
    import http.server
    import shutil
    import subprocess
    import threading
    from app.core.config import get_settings
    tool = get_settings().resolve_nm3u8dl_path()
    ffmpeg = shutil.which("ffmpeg")
    if not tool or not ffmpeg:
        pytest.skip("Optional N_m3u8DL-RE and FFmpeg are required")
    subprocess.run([
        ffmpeg, "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=5",
        "-f", "lavfi", "-i", "sine=frequency=440", "-t", "2", "-c:v", "libx264",
        "-c:a", "aac", "-g", "5", "-f", "hls", "-hls_time", "1", "-hls_list_size",
        "0", str(tmp_path / "index.m3u8"),
    ], check=True, timeout=30)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(Handler, directory=str(tmp_path)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        task = SimpleNamespace(cancel_flag=False, process=None)
        output = await download_hls(
            task, {**INFO, "url": f"http://127.0.0.1:{server.server_port}/index.m3u8"},
            tool, ffmpeg, tmp_path / "actual.mp4")
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
             "-of", "csv=p=0", output], capture_output=True, check=True, timeout=10)
        assert set(probe.stdout.decode().split()) == {"video", "audio"}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
