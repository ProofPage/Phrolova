"""Exercise real discontinuity boundaries without touching a live broadcast."""
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.engine import rplay_live, rplay_stream
from app.engine.base import Platform
from app.engine.media_inspection import probe_media
from app.engine.pipeline import YtdlpLivePipeline
from app.engine.recording_finalizer import RecordingFinalizer
from tests.test_new_platforms import local_hls
from tests.test_recording_finalization import terminal


@pytest.mark.asyncio
async def test_real_discontinuity_splits_preserves_and_remuxes(local_hls, monkeypatch, caplog):
    base, directory = local_hls
    # The sequence numbers are continuous: this must not rely on sequence gaps.
    playlist = directory / "720/discontinuous.m3u8"
    playlist.write_text(
        "#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXT-X-MEDIA-SEQUENCE:0\n"
        "#EXTINF:1,\nindex0.ts\n#EXTINF:1,\nindex1.ts\n"
        "#EXT-X-DISCONTINUITY\n#EXTINF:1,\nindex2.ts\n#EXT-X-ENDLIST\n")
    allowed = lambda url: isinstance(url, str) and url.startswith(base + "/")
    monkeypatch.setattr(rplay_live, "media_allowed", allowed)
    monkeypatch.setattr(rplay_stream, "media_allowed", allowed)
    pipe = YtdlpLivePipeline("686fbe0b0d7dc463f4a6efd1")
    manager = RecordingFinalizer()
    try:
        await pipe.start_recording(
            stream_obj="https://rplay.live/live/686fbe0b0d7dc463f4a6efd1",
            output_dir=str(directory / "capture"), quality="720p",
            source_resolver=AsyncMock(return_value=(base + "/720/discontinuous.m3u8", {}, None)))
        await asyncio.wait_for(asyncio.shield(pipe._feeder_task), 15)
        assert pipe.state.value == "completed", pipe.get_status()
        assert len(pipe._source_files) == 2
        parts = [Path(p).read_bytes() for p in pipe._source_files]
        assert parts[0] == (directory / "720/index0.ts").read_bytes() + (directory / "720/index1.ts").read_bytes()
        assert parts[1] == (directory / "720/index2.ts").read_bytes()
        report = pipe._loss_report.snapshot()
        assert report["tracks"]["0"]["sequence_gaps"] == []
        assert report["time_gaps"][0]["reason"] == "stream_discontinuity"
        assert not any("incoherent output" in r.message for r in caplog.records)
        job_id = manager.register_capture(
            "rplay:fixture", pipe,
            SimpleNamespace(platform=Platform.RPLAY, channel_id="fixture", channel_name="fixture"),
            dict(output_format="mkv", keep_source_ts=False))
        await manager.capture_finished(job_id, pipe)
        job = await terminal(manager, job_id)
        assert job["state"] == "completed", job
        assert job["inspection_state"] == "passed" and job["continuity_valid"] is False
        assert job["keep_source_ts"] and all(Path(p).is_file() for p in pipe._source_files)
        assert probe_media(job["output_path"])["streams"] == {"video", "audio"}
    finally:
        await pipe.stop_recording()
