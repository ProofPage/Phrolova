from datetime import datetime, timedelta

from app.engine.pipeline import YtdlpLivePipeline


def test_media_bitrate_is_stable_between_hls_segment_bursts(tmp_path):
    path = tmp_path / "capture.ts"
    path.write_bytes(b"x" * 3_000_000)
    pipeline = YtdlpLivePipeline("rplay-fixture")
    pipeline._output_path = str(path)
    pipeline._source_files = [str(path)]
    pipeline._start_time = datetime.now() - timedelta(seconds=6)
    pipeline._media_duration = 6.0
    pipeline._last_check_time = datetime.now() - timedelta(seconds=2)
    pipeline._update_statistics()
    # Three million bytes over six media seconds is exactly 4,000 kbit/s,
    # independent of the two-second disk sampling interval.
    assert pipeline.bitrate == 4000.0
    assert pipeline.download_speed > 0

    pipeline._last_check_time = datetime.now() - timedelta(seconds=2)
    pipeline._update_statistics()
    assert pipeline.download_speed == 0
    assert pipeline.bitrate == 4000.0

    with path.open("ab") as output:
        output.write(b"x" * 3_000_000)
    pipeline._media_duration = 12.0
    pipeline._last_check_time = datetime.now() - timedelta(seconds=2)
    pipeline._update_statistics()
    assert pipeline.bitrate == 4000.0
    assert pipeline.download_speed > 0


def test_media_bitrate_before_first_timestamp_is_zero(tmp_path):
    path = tmp_path / "starting.ts"
    path.write_bytes(b"x" * 188)
    pipeline = YtdlpLivePipeline("rplay-fixture")
    pipeline._output_path = str(path)
    pipeline._update_statistics()
    assert pipeline.bitrate == 0.0


def test_chzzk_speed_covers_segment_interval_but_reports_real_stalls(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from streamlink.stream.hls.m3u8 import M3U8
    from app.engine.pipeline import ytdlp
    current = datetime(2026, 10, 18)
    class Clock(datetime):
        @classmethod
        def now(cls):
            return current
    monkeypatch.setattr(ytdlp, "datetime", Clock)
    path = tmp_path / "chzzk.ts"
    path.write_bytes(b"")
    pipeline = YtdlpLivePipeline("chzzk-fixture")
    pipeline._output_path = str(path)
    pipeline._start_time = current
    playlist = M3U8()
    playlist.targetduration = 6
    pipeline._readers = [SimpleNamespace(stream=SimpleNamespace(continuity=SimpleNamespace(
        primary=SimpleNamespace(playlist=playlist))))]
    pipeline._update_statistics()
    for seconds in range(2, 15, 2):
        current = datetime(2026, 10, 18) + timedelta(seconds=seconds)
        if seconds in (6, 12):
            with path.open("ab") as output:
                output.write(b"x" * (6 * 1024 * 1024))
        pipeline._update_statistics()
        if seconds >= 6:
            assert pipeline.download_speed == 1.0
    for seconds in (16, 18, 20):
        current = datetime(2026, 10, 18) + timedelta(seconds=seconds)
        pipeline._update_statistics()
    assert pipeline.download_speed == 0.0
