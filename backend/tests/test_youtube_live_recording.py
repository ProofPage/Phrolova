"""YouTube live extraction must keep separate HLS audio connected."""

import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.engine.pipeline import YtdlpLivePipeline
from app.engine.recording_errors import RecordingError
from tests.test_new_platforms import local_hls


def extract(monkeypatch, payload, quality="1080p", page="https://www.youtube.com/watch?v=test"):
    commands = []

    class Process:
        returncode = 0

        async def communicate(self):
            return json.dumps(payload).encode(), b""

    async def execute(*command, **kwargs):
        commands.append(command)
        return Process()

    monkeypatch.setattr("app.engine.pipeline.ytdlp.require_runtime_cli_options", lambda: ["--js-runtimes", "node"])
    monkeypatch.setattr("app.engine.pipeline.ytdlp.asyncio.create_subprocess_exec", execute)
    result = asyncio.run(YtdlpLivePipeline("test")._extract_hls_url(page, quality, None))
    return result, commands[0]


@pytest.mark.parametrize("quality", ["1080p", "720p60", "best", "worst"])
def test_separate_youtube_audio_resolves_master_with_quality_fallback(monkeypatch, quality):
    selected = {"url": "https://cdn.example/video.m3u8", "acodec": "none",
                "manifest_url": "https://cdn.example/master?signature=private",
                "http_headers": {"Origin": "https://www.youtube.com"}, "cookies": "private-cookie"}
    (url, headers, cookies), command = extract(monkeypatch, selected, quality)
    assert url == selected["manifest_url"]
    assert headers == selected["http_headers"] and cookies == selected["cookies"]
    selector = command[command.index("--format") + 1]
    preference = "worst" if quality == "worst" else "best"
    assert f"{preference}video[protocol^=m3u8]" in selector
    if quality[0].isdigit():
        height = quality.split("p")[0]
        assert f"{preference}video[protocol^=m3u8][height<={height}]" in selector


def test_muxed_youtube_keeps_selected_rendition(monkeypatch):
    selected = {"url": "https://cdn.example/muxed.m3u8", "acodec": "mp4a.40.2",
                "manifest_url": "https://cdn.example/master.m3u8"}
    result, _ = extract(monkeypatch, selected)
    assert result[0] == selected["url"]


@pytest.mark.parametrize("master", [None, "file:///master.m3u8", "https://cdn.example/video.mp4",
                                    "https://user:secret@cdn.example/master.m3u8"])
def test_separate_youtube_without_valid_master_cannot_succeed_silently(monkeypatch, master):
    with pytest.raises(RecordingError, match="HLS 마스터") as error:
        extract(monkeypatch, {"url": "https://cdn.example/video.m3u8", "acodec": "none",
                              "manifest_url": master})
    assert error.value.code == "youtube_hls_audio"


def test_requested_formats_preserve_separate_audio_master(monkeypatch):
    master = "https://cdn.example/master.m3u8"
    payload = {"http_headers": {"Origin": "https://www.youtube.com"},
               "requested_formats": [{"url": "https://cdn.example/video.m3u8", "acodec": "none",
                                      "manifest_url": master}]}
    result, _ = extract(monkeypatch, payload)
    assert result == (master, payload["http_headers"], None)


@pytest.mark.asyncio
@pytest.mark.parametrize("quality,height", [("720p", 720), ("480p", 480)])
async def test_youtube_id3v23_audio_capture_and_finalization(local_hls, quality, height):
    from app.engine.base import Platform
    from app.engine.media_inspection import probe_media
    from app.engine.recording_finalizer import RecordingFinalizer
    from tests.test_recording_finalization import terminal

    base, directory = local_hls
    ffmpeg = shutil.which("ffmpeg")
    for resolution in (720, 480):
        folder = directory / f"video{resolution}"
        folder.mkdir()
        subprocess.run([ffmpeg, "-y", "-v", "error", "-i", str(directory / f"{resolution}/index.m3u8"),
                        "-an", "-c", "copy", "-f", "hls", "-hls_time", "1", "-hls_list_size", "0",
                        str(folder / "index.m3u8")], check=True)
    audio = directory / "audio.aac"
    subprocess.run([ffmpeg, "-y", "-v", "error", "-i", str(directory / "720/index.m3u8"),
                    "-vn", "-c", "copy", "-f", "adts", str(audio)], check=True)
    # A valid empty ID3v2.3 tag reproduces Streamlink's incompatible-version
    # exception before any audio bytes reach the recording file.
    tag = b"ID3\x03\x00\x00\x00\x00\x00\x00"
    audio.write_bytes(tag + audio.read_bytes())
    (directory / "audio.m3u8").write_text(
        "#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXTINF:3.04,\naudio.aac\n#EXT-X-ENDLIST\n")
    (directory / "youtube.m3u8").write_text(
        '#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="Audio",DEFAULT=YES,URI="audio.m3u8"\n'
        + "".join(f'#EXT-X-STREAM-INF:RESOLUTION={width}x{res},BANDWIDTH={res*4000},AUDIO="audio"\nvideo{res}/index.m3u8\n'
                  for res, width in ((720, 1280), (480, 854))))
    pipeline = YtdlpLivePipeline("fixture")
    manager = RecordingFinalizer()

    async def resolve(requested):
        assert requested == quality
        return base + "/youtube.m3u8", {}, None

    try:
        await pipeline.start_recording(stream_obj="https://www.youtube.com/watch?v=fixture",
                                       output_dir=str(directory / "capture"), quality=quality, source_resolver=resolve)
        await asyncio.wait_for(asyncio.shield(pipeline._feeder_task), 15)
        await pipeline.stop_recording()
        assert len(pipeline._source_files) == 2
        assert Path(pipeline._source_files[1]).read_bytes().startswith(tag)
        job_id = manager.register_capture("youtube:fixture", pipeline,
            SimpleNamespace(platform=Platform.YOUTUBE, channel_id="fixture", channel_name="YouTube"),
            {"output_format": "mkv", "keep_source_ts": True})
        await manager.capture_finished(job_id, pipeline)
        job = await terminal(manager, job_id)
        assert job["state"] == "completed", job
        media = probe_media(job["output_path"])
        assert media["streams"] == {"video", "audio"}
        assert next(track for track in media["tracks"] if track["codec_type"] == "video")["height"] == height
        check = subprocess.run([ffmpeg, "-v", "error", "-xerror", "-i", job["output_path"], "-f", "null", "-"],
                               capture_output=True, timeout=30)
        assert check.returncode == 0, check.stderr.decode(errors="replace")
    finally:
        await pipeline.stop_recording()
        await manager.close()
