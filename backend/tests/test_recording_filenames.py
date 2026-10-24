"""Readable names, exclusive concurrent reservations and original preservation."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
import pytest

from app.engine.pipeline import ytdlp
from app.engine.pipeline.ytdlp import YtdlpLivePipeline


class StopNaming(Exception):
    """Raised once a pipeline has fixed its output name, before any recording."""

@pytest.mark.parametrize('suffix',['.ts','.ts.part','.native.mp4','.native.mp4.part','.native.ts','.native.mkv','.mkv','.mp4','.jpg','.ts.audio1','.ts.audio1.part','.native.mp4.audio1','.native.mp4.audio1.part'])
def test_existing_capture_family_is_never_overwritten(tmp_path,suffix):
    original=tmp_path/('한글 방송 제목'+suffix);original.write_bytes(b'preserved')
    selected=YtdlpLivePipeline._reserve_capture_file(tmp_path/'한글 방송 제목.ts')
    assert selected.name=='한글 방송 제목 (2).ts'
    assert original.read_bytes()==b'preserved'
    assert Path(str(selected)+'.part').is_file()

def test_concurrent_same_title_has_short_unique_names(tmp_path):
    base=tmp_path/'[채널] 방송 제목.ts'
    with ThreadPoolExecutor(max_workers=8) as pool:
        paths=list(pool.map(lambda _:YtdlpLivePipeline._reserve_capture_file(base),range(8)))
    assert len(set(paths))==8
    assert {p.name for p in paths}=={'[채널] 방송 제목.ts',*(f'[채널] 방송 제목 ({i}).ts' for i in range(2,9))}
    assert all(Path(str(p)+'.part').is_file() for p in paths)
    assert not any(len(part)==32 for p in paths for part in p.stem.split())


def _started_pipeline(monkeypatch, tmp_path, settings):
    """Build a pipeline that fixes its name, then stops before resolving the stream.

    Naming happens before platform extraction, so stopping at the first network
    step keeps these assertions about names independent of platform resolvers.
    """
    monkeypatch.setattr(ytdlp, "get_settings", lambda: settings)
    pipeline = ytdlp.YtdlpLivePipeline("fixture")
    captured = {}

    async def stop_after_naming(*args, **kwargs):
        captured["path"] = str(Path(pipeline._output_path))
        raise StopNaming

    def reserve(path):
        captured["path"] = str(path)
        raise StopNaming

    monkeypatch.setattr(pipeline, "_is_chzzk_live_page", lambda url: False)
    monkeypatch.setattr(pipeline, "_extract_hls_url", stop_after_naming)
    monkeypatch.setattr(pipeline, "_reserve_capture_file", reserve)
    return pipeline, captured


@pytest.mark.parametrize(
    "page_url",
    [
        "https://chzzk.naver.com/live/fixture",
        "https://www.youtube.com/watch?v=fixture",
        "https://play.sooplive.co.kr/fixture",
        "https://www.twitch.tv/fixture",
        "https://kick.com/fixture",
        "https://www.tiktok.com/@fixture/live",
        "https://live.bilibili.com/1",
        "https://www.pandalive.co.kr/live/play/fixture",
        "https://www.popkontv.com/live/view?mcid=fixture&partnerCode=fixture",
        "https://ci.me/@fixture/live",
        "https://rplay.live/live/fixture",
        "https://www.twithcasting.com/fixture",
        "https://www.spoon.com/fixture",
        "https://www.berriz.io/fixture",
    ],
)
@pytest.mark.asyncio
async def test_every_platform_uses_one_time_stamp_in_the_name(monkeypatch, tmp_path, page_url):
    """A full template renders identical structure for every supported platform."""
    from app.core.config import Settings

    settings = Settings(_env_file=None)
    settings.live_filename_template = "[{name}] {title} {live_date_year}-{live_date_month}-{live_date_day} {live_date_hour}-{live_date_minute}"
    pipeline, captured = _started_pipeline(monkeypatch, tmp_path, settings)
    with pytest.raises(StopNaming):
        await pipeline.start_recording(
            stream_obj=page_url, output_dir=str(tmp_path),
            streamer_name="채널", title="방송 제목",
            live_started_at="2026-10-23T10:00:00+09:00",
        )
    assert Path(captured["path"]).name == "[채널] 방송 제목 2026-10-23 10-00.ts"


@pytest.mark.asyncio
async def test_unparsable_start_time_keeps_current_time_once(monkeypatch, tmp_path):
    """A bad start time falls back to now without adding a second stamp."""
    from app.core.config import Settings

    settings = Settings(_env_file=None)
    pipeline, captured = _started_pipeline(monkeypatch, tmp_path, settings)
    with pytest.raises(StopNaming):
        await pipeline.start_recording(
            stream_obj="https://chzzk.naver.com/live/fixture", output_dir=str(tmp_path),
            streamer_name="채널", title="방송 제목", live_started_at="not-a-time",
        )
    name = Path(captured["path"]).stem
    assert name.count(datetime.now().strftime("%Y")) == 1
    assert "not-a-time" not in name


@pytest.mark.asyncio
@pytest.mark.parametrize("template", ["[채널] 제목 20251023 1000", "12345"])
async def test_literal_or_numeric_template_is_a_valid_path(monkeypatch, tmp_path, template):
    """Numeric strings are valid file names; they are not integer file descriptors."""
    from app.core.config import Settings

    settings = Settings(_env_file=None)
    settings.live_filename_template = template
    pipeline, captured = _started_pipeline(monkeypatch, tmp_path, settings)
    with pytest.raises(StopNaming):
        await pipeline.start_recording(
            stream_obj="https://chzzk.naver.com/live/fixture", output_dir=str(tmp_path),
            streamer_name="채널", title="방송 제목",
        )
    assert Path(captured["path"]).name == template + ".ts"


@pytest.mark.parametrize("filename", ["12345.ts", "[채널] 제목 20251023 1000.ts", "방송.ts"])
def test_name_check_accepts_every_normal_name(filename, tmp_path):
    selected = YtdlpLivePipeline._reserve_capture_file(tmp_path / filename)
    assert selected.name == filename
    assert Path(str(selected) + ".part").is_file()


def test_restarted_session_uses_restart_time():
    from app.engine.channel import ChannelTask
    task = ChannelTask("fixture")
    first = task.new_session_stamp("2020-01-01T12:00:00")
    before = datetime.now()
    second = datetime.fromisoformat(task.new_session_stamp(first))
    assert before <= second <= datetime.now()
    assert first != second.isoformat()
