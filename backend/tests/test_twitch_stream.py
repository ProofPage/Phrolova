import time
from types import SimpleNamespace
from pathlib import Path
import asyncio
import shutil
import subprocess
import pytest

from streamlink import Streamlink

from app.engine.twitch_stream import TwitchCaptureStream
from app.engine.pipeline.ytdlp import YtdlpLivePipeline
from tests.test_new_platforms import local_hls
from tests.test_recording_finalization import terminal, channel
from app.engine.recording_finalizer import RecordingFinalizer
from app.engine.media_inspection import probe_media
from app.engine.twitch_stream import TwitchCaptureWriter, _Writer
from streamlink.exceptions import StreamError


@pytest.mark.parametrize("method,args", [
    ("_write_plain", (None, None)), ("_write_decrypt", (None, None, None)),
])
def test_failed_segment_is_not_silently_accepted(monkeypatch, method, args):
    monkeypatch.setattr(_Writer, method, lambda *a: False)
    writer = object.__new__(TwitchCaptureWriter)
    with pytest.raises(StreamError, match="could not be fully received"):
        getattr(writer, method)(*args)


def test_boundaries_split_exact_bytes_without_dropping_data():
    session = Streamlink()
    try:
        stream = TwitchCaptureStream(session, "https://video.ttvnw.net/live.m3u8")
        stream._boundaries.extend([(3, "advertisement_excluded"), (7, "stream_discontinuity")])
        assert list(stream.split_capture_data(b"abcde")) == [
            (None, b"abc"), ("advertisement_excluded", b"de")]
        assert list(stream.split_capture_data(b"fghij")) == [
            (None, b"fg"), ("stream_discontinuity", b"hij")]
        assert not stream._boundaries
    finally:
        session.http.close()


def test_boundary_at_end_is_applied_to_the_next_bytes():
    session = Streamlink()
    try:
        stream = TwitchCaptureStream(session, "https://video.ttvnw.net/live.m3u8")
        stream._boundaries.append((3, "advertisement_excluded"))
        assert list(stream.split_capture_data(b"abc")) == [(None, b"abc")]
        assert list(stream.split_capture_data(b"d")) == [("advertisement_excluded", b"d")]
    finally:
        session.http.close()


def test_ad_state_requires_recent_upstream_activity_and_is_visible():
    session = Streamlink()
    try:
        stream = TwitchCaptureStream(session, "https://video.ttvnw.net/live.m3u8")
        pipe = YtdlpLivePipeline("humzh")
        pipe._readers = [SimpleNamespace(stream=stream)]
        stream.ad_active = True
        assert pipe.get_status()["warning_message"] == "live.twitchAdWaiting"
        stream.last_activity = time.monotonic() - 91
        assert not pipe._twitch_ad_waiting()
        stream.last_activity = time.monotonic()
        stream.ad_active = False
        pipe.warning_message = "live.twitchCaptureSplit"
        assert pipe.get_status()["warning_message"] == "live.twitchCaptureSplit"
    finally:
        session.http.close()


@pytest.mark.asyncio
async def test_sequential_sources_remux_without_duplicate_tracks(local_hls):
    _, directory = local_hls
    first = directory / "part one.ts"
    subprocess.run([shutil.which("ffmpeg"), "-v", "error", "-i", str(directory / "720/index.m3u8"),
                    "-c", "copy", str(first)], check=True)
    second = directory / "part 'two.ts"
    shutil.copyfile(first, second)
    pipe = YtdlpLivePipeline("fixture")
    pipe._output_path = str(first)
    pipe._source_files = [str(first), str(second)]
    pipe._sequential_sources = True
    pipe._file_size_bytes = first.stat().st_size + second.stat().st_size
    pipe._closed = True
    pipe.end_reason = "manual"
    manager = RecordingFinalizer()
    job_id = manager.register_capture("twitch:fixture", pipe, channel("twitch"),
                                     dict(output_format="mp4", keep_source_ts=False))
    try:
        await manager.capture_finished(job_id, pipe)
        job = await terminal(manager, job_id)
        assert job["state"] == "completed", job
        media = probe_media(job["output_path"])
        assert len([t for t in media["tracks"] if t["codec_type"] == "audio"]) == 1
        assert len([t for t in media["tracks"] if t["codec_type"] == "video"]) == 1
        assert abs(media["duration"] - 6) < .2
        assert first.exists() and second.exists()
        assert not list(directory.glob("*.concat"))
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_advertisement_capture_splits_and_preserves_media(local_hls):
    base, directory = local_hls
    playlist = directory / "720/ads.m3u8"
    playlist.write_text(
        '#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXT-X-MEDIA-SEQUENCE:0\n'
        '#EXT-X-DATERANGE:ID="stitched-ad-test",CLASS="twitch-stitched-ad",'
        'START-DATE="2026-10-19T00:00:01Z",DURATION=1.0\n'
        '#EXT-X-PROGRAM-DATE-TIME:2026-10-19T00:00:00Z\n#EXTINF:1,\nindex0.ts\n'
        '#EXT-X-PROGRAM-DATE-TIME:2026-10-19T00:00:01Z\n#EXTINF:1,\nindex1.ts\n'
        '#EXT-X-DISCONTINUITY\n#EXT-X-PROGRAM-DATE-TIME:2026-10-19T00:00:02Z\n'
        '#EXTINF:1,\nindex2.ts\n#EXT-X-ENDLIST\n')
    pipe = YtdlpLivePipeline("fixture")
    async def resolve(_):
        return base + "/720/ads.m3u8", {}, None
    await pipe.start_recording(stream_obj="https://www.twitch.tv/fixture", output_dir=str(directory / "capture"),
                               source_resolver=resolve, quality="720p")
    await asyncio.wait_for(pipe._feeder_task, 15)
    assert pipe.state.value == "completed", pipe.get_status()
    assert len(pipe._source_files) == 2
    assert pipe.continuity_events[-1]["reason"] == "advertisement_excluded"
    assert not pipe.output_errors
    for source in pipe._source_files:
        info = probe_media(source)
        assert {"video", "audio"}.issubset(info["streams"])
    # Five video frames per one-second segment: each segment's PCR span is
    # four frame intervals. The excluded advertisement must not enter the sum.
    assert pipe.duration_seconds == pytest.approx(2 * 4 / 5)
