"""Anonymous YouTube requests and bounded, explicit authentication fallback."""
import asyncio
import threading
from pathlib import Path

import pytest
import yt_dlp

from app.core.config import get_settings
from app.engine.vod import VodEngine, VodDownloadTask, VodDownloadState, NonRetryableDownloadError
from app.engine.youtube_support import YouTubeAuthenticationError, youtube_auth_message

URL = "https://www.youtube.com/watch?v=abcdefghijk"
COOKIE = "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t2147483647\tSID\tsynthetic-session\n"


@pytest.fixture
def engine(tmp_path, monkeypatch):
    get_settings().youtube_cookie_file = None
    monkeypatch.setattr("app.core.config.Settings.resolve_ffmpeg_path", lambda _: "ffmpeg")
    engine = VodEngine()
    build = engine._build_ytdlp_options
    monkeypatch.setattr(engine, "_build_ytdlp_options", lambda *a, **kw: {**build(*a, **kw), "enable_file_urls": True})
    return engine


def metadata(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"local test video bytes")
    return {"id": "abcdefghijk", "title": "Public video", "uploader": "Test channel", "ext": "mp4",
            "extractor": "youtube", "extractor_key": "Youtube", "url": source.as_uri(), "webpage_url": URL}


@pytest.mark.asyncio
@pytest.mark.parametrize("configured", [None, "", "missing", "valid"])
async def test_public_info_and_download_always_start_without_cookies(engine, tmp_path, monkeypatch, configured):
    cookie = tmp_path / "cookies.txt"
    if configured == "valid":
        cookie.write_text(COOKIE)
    get_settings().youtube_cookie_file = str(cookie) if configured in {"missing", "valid"} else configured
    info = metadata(tmp_path)
    options = []
    def extract(ydl, *args, **kwargs):
        options.append(dict(ydl.params))
        return info.copy()
    monkeypatch.setattr(yt_dlp.YoutubeDL, "extract_info", extract)
    process = yt_dlp.YoutubeDL.process_ie_result
    def download(ydl, *args, **kwargs):
        options.append(dict(ydl.params))
        return process(ydl, *args, **kwargs)
    monkeypatch.setattr(yt_dlp.YoutubeDL, "process_ie_result", download)
    assert (await engine.get_video_info(URL))["title"] == "Public video"
    task = VodDownloadTask(url=URL, output_dir=str(tmp_path / "downloads"))
    engine._tasks[task.task_id] = task
    await engine._download_external(task.task_id, task)
    assert task.state == VodDownloadState.COMPLETED
    assert Path(task.output_path).read_bytes() == b"local test video bytes"
    assert all("cookiefile" not in opts and "cookiesfrombrowser" not in opts for opts in options)
    if configured == "valid":
        assert cookie.read_text() == COOKIE


@pytest.mark.asyncio
async def test_authenticated_download_uses_one_temporary_cookie_copy(engine, tmp_path, monkeypatch):
    cookie = tmp_path / "cookies.txt"
    cookie.write_text(COOKIE)
    get_settings().youtube_cookie_file = str(cookie)
    info = metadata(tmp_path)
    seen = []
    download_options = []
    def extract(ydl, *args, **kwargs):
        path = ydl.params.get("cookiefile")
        seen.append(path)
        if path is None:
            raise yt_dlp.utils.DownloadError("Sign in to confirm your age")
        assert path != str(cookie) and Path(path).is_file()
        return info.copy()
    monkeypatch.setattr(yt_dlp.YoutubeDL, "extract_info", extract)
    process = yt_dlp.YoutubeDL.process_ie_result
    def download(ydl, *args, **kwargs):
        download_options.append(dict(ydl.params))
        return process(ydl, *args, **kwargs)
    monkeypatch.setattr(yt_dlp.YoutubeDL, "process_ie_result", download)
    task = VodDownloadTask(url=URL, output_dir=str(tmp_path / "downloads"))
    engine._tasks[task.task_id] = task
    await engine._download_external(task.task_id, task)
    assert task.state == VodDownloadState.COMPLETED
    assert len(seen) == 2 and seen[0] is None and seen[1]
    assert download_options[0]["cookiefile"] == seen[1]
    assert download_options[0]["format"] == task.quality
    assert download_options[0]["merge_output_format"] == get_settings().vod_format
    assert not Path(seen[1]).exists()
    assert cookie.read_text() == COOKIE


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["Sign in to confirm your age", "Login required", "Sign in to confirm you're not a bot",
                                    "Private video", "Members-only content", "This video is available to members", "age-restricted content", "account required"])
async def test_authentication_without_cookies_is_actionable_and_not_retried(engine, tmp_path, monkeypatch, message):
    calls = []
    def denied(ydl, *args, **kwargs):
        calls.append(ydl.params.get("cookiefile"))
        raise yt_dlp.utils.DownloadError(message)
    monkeypatch.setattr(yt_dlp.YoutubeDL, "extract_info", denied)
    task = VodDownloadTask(url=URL, output_dir=str(tmp_path))
    engine._tasks[task.task_id] = task
    await asyncio.wait_for(engine._run_download(task.task_id), 3)
    assert task.state == VodDownloadState.ERROR and task.retry_count == 0
    assert "설정 → 인증 → 유튜브" in task.error_message
    assert calls == [None]


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["Network timed out", "Video has been removed", "Not available in your country", "Invalid URL", "HTTP Error 403"])
async def test_other_failures_do_not_trigger_cookie_fallback(engine, tmp_path, monkeypatch, message):
    cookie = tmp_path / "cookies.txt"
    cookie.write_text(COOKIE)
    get_settings().youtube_cookie_file = str(cookie)
    calls = []
    def denied(ydl, *args, **kwargs):
        calls.append(ydl.params.get("cookiefile"))
        raise yt_dlp.utils.DownloadError(message)
    monkeypatch.setattr(yt_dlp.YoutubeDL, "extract_info", denied)
    with pytest.raises(yt_dlp.utils.DownloadError):
        await engine.get_video_info(URL)
    assert calls == [None]
    assert youtube_auth_message(message) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["missing", "unreadable", "malformed"])
async def test_invalid_saved_cookie_is_safe_after_authentication_failure(engine, tmp_path, monkeypatch, invalid, caplog):
    cookie = tmp_path / "cookies.txt"
    if invalid != "missing":
        cookie.write_text("raw-secret-cookie-value" if invalid == "malformed" else COOKIE)
    if invalid == "unreadable":
        monkeypatch.setattr("app.engine.youtube_support.shutil.copyfile", lambda *a: (_ for _ in ()).throw(PermissionError("sensitive path")))
    get_settings().youtube_cookie_file = str(cookie)
    calls = []
    def denied(ydl, *args, **kwargs):
        calls.append(ydl.params.get("cookiefile"))
        raise yt_dlp.utils.DownloadError("Login required")
    monkeypatch.setattr(yt_dlp.YoutubeDL, "extract_info", denied)
    task = VodDownloadTask(url=URL, output_dir=str(tmp_path))
    with pytest.raises(NonRetryableDownloadError) as error:
        await engine._download_external(task.task_id, task)
    assert "다시 등록" in str(error.value)
    assert "raw-secret-cookie-value" not in str(error.value) + caplog.text
    assert calls == [None]


@pytest.mark.asyncio
async def test_private_video_with_cookies_still_requires_account_permission(engine, tmp_path, monkeypatch):
    cookie = tmp_path / "cookies.txt"
    cookie.write_text(COOKIE)
    get_settings().youtube_cookie_file = str(cookie)
    calls = []
    def denied(ydl, *args, **kwargs):
        calls.append(ydl.params.get("cookiefile"))
        raise yt_dlp.utils.DownloadError("Private video")
    monkeypatch.setattr(yt_dlp.YoutubeDL, "extract_info", denied)
    with pytest.raises(YouTubeAuthenticationError, match="계정.*시청 권한"):
        await engine.get_video_info(URL)
    assert len(calls) == 2 and calls[0] is None and calls[1]


def test_public_channel_collection_ignores_stale_cookie_path(tmp_path, monkeypatch):
    from app.engine.youtube_channel import channel_entries
    get_settings().youtube_cookie_file = str(tmp_path / "missing.txt")
    calls = []
    def extract(ydl, *args, **kwargs):
        calls.append(ydl.params.get("cookiefile"))
        return {"entries": [{"id": "abcdefghijk", "title": "Public video"}]}
    monkeypatch.setattr(yt_dlp.YoutubeDL, "extract_info", extract)
    assert len(list(channel_entries("https://www.youtube.com/@test", threading.Event()))) == 1
    assert calls == [None]


@pytest.mark.asyncio
async def test_cookie_fallback_also_handles_authentication_during_download(engine, tmp_path, monkeypatch):
    cookie = tmp_path / "cookies.txt"
    cookie.write_text(COOKIE)
    get_settings().youtube_cookie_file = str(cookie)
    info = metadata(tmp_path)
    monkeypatch.setattr(yt_dlp.YoutubeDL, "extract_info", lambda *a, **kw: info.copy())
    process = yt_dlp.YoutubeDL.process_ie_result
    calls = []
    def download(ydl, *args, **kwargs):
        calls.append(ydl.params.get("cookiefile"))
        if calls[-1] is None:
            raise yt_dlp.utils.DownloadError("Login required")
        return process(ydl, *args, **kwargs)
    monkeypatch.setattr(yt_dlp.YoutubeDL, "process_ie_result", download)
    task = VodDownloadTask(url=URL, output_dir=str(tmp_path / "downloads"))
    engine._tasks[task.task_id] = task
    await engine._download_external(task.task_id, task)
    assert task.state == VodDownloadState.COMPLETED
    assert calls[0] is None and calls[1] and len(calls) == 2


def test_channel_cookie_fallback_preserves_entries_without_duplicates(tmp_path, monkeypatch):
    from app.engine.youtube_channel import channel_entries
    cookie = tmp_path / "cookies.txt"
    cookie.write_text(COOKIE)
    get_settings().youtube_cookie_file = str(cookie)
    calls = []
    def extract(ydl, *args, **kwargs):
        path = ydl.params.get("cookiefile")
        calls.append(path)
        def entries():
            yield {"id": "abcdefghijk", "title": "Public video"}
            if not path:
                raise yt_dlp.utils.DownloadError("Login required")
            yield {"id": "lmnopqrstuv", "title": "Restricted video"}
        return {"entries": entries()}
    monkeypatch.setattr(yt_dlp.YoutubeDL, "extract_info", extract)
    entries = list(channel_entries("https://www.youtube.com/@test", threading.Event()))
    assert [entry["id"] for entry in entries] == ["abcdefghijk", "lmnopqrstuv"]
    assert len(calls) == 2 and calls[0] is None and calls[1]
