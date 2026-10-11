"""New defaults preserve explicit settings and use the real engine entry points."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.config import Settings


@pytest.fixture
def defaults(monkeypatch):
    for key in (
        "CHZZK_STREAM_MODE",
        "CHZZK_TIME_MACHINE_ENABLED",
        "VOD_MAX_CONCURRENT",
        "LIVE_FORMAT",
    ):
        monkeypatch.delenv(key, raising=False)
    return Settings(_env_file=None)


def test_new_install_defaults(defaults):
    assert defaults.effective_chzzk_stream_mode == "force-timemachine"
    assert defaults.vod_max_concurrent == 5
    assert defaults.live_format == "mkv"


@pytest.mark.parametrize(
    "mode", ["standard", "request-timemachine", "force-timemachine"]
)
def test_explicit_stream_mode_preserved(defaults, mode):
    defaults.chzzk_stream_mode = mode
    defaults.chzzk_time_machine_enabled = True
    assert defaults.effective_chzzk_stream_mode == mode


@pytest.mark.parametrize(
    "enabled, expected", [(True, "force-timemachine"), (False, "standard")]
)
def test_legacy_stream_mode_preserved(defaults, enabled, expected):
    defaults.chzzk_time_machine_enabled = enabled
    assert defaults.effective_chzzk_stream_mode == expected


def test_explicit_env_values_and_restart(defaults, tmp_path):
    source = tmp_path / ".env"
    source.write_text(
        "CHZZK_STREAM_MODE=standard\nVOD_MAX_CONCURRENT=2\n", encoding="utf-8"
    )
    assert Settings(_env_file=source).effective_chzzk_stream_mode == "standard"
    assert Settings(_env_file=source).vod_max_concurrent == 2
    source.write_text(
        "CHZZK_STREAM_MODE=force-timemachine\nVOD_MAX_CONCURRENT=5\n", encoding="utf-8"
    )
    assert Settings(_env_file=source).effective_chzzk_stream_mode == "force-timemachine"
    assert Settings(_env_file=source).vod_max_concurrent == 5


@pytest.mark.asyncio
async def test_vod_engine_applies_five_download_slots(defaults, monkeypatch):
    from app.engine import vod

    monkeypatch.setattr(vod, "get_settings", lambda: defaults)
    engine = vod.VodEngine()
    assert engine._max_concurrent == 5
    for _ in range(5):
        await engine._semaphore.acquire()
    assert engine._semaphore.locked()
    for _ in range(5):
        engine._semaphore.release()
    await engine.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("available", [True, False])
async def test_default_chzzk_requires_time_machine(
    defaults, monkeypatch, tmp_path, available
):
    from app.engine.pipeline import ytdlp

    monkeypatch.setattr(ytdlp, "get_settings", lambda: defaults)
    stream = SimpleNamespace(
        url="https://fixture.test/time.m3u8", headers={}, live_start_index=0
    )
    resolve = (
        AsyncMock(return_value=stream)
        if available
        else AsyncMock(side_effect=RuntimeError("타임머신 제공 안 됨"))
    )
    standard = AsyncMock()
    monkeypatch.setattr(ytdlp, "resolve_time_machine_stream", resolve)
    monkeypatch.setattr(ytdlp, "resolve_live_cdn_stream", standard)
    pipeline = ytdlp.YtdlpLivePipeline("a" * 32)
    monkeypatch.setattr(pipeline, "_begin_receiver", AsyncMock())
    arguments = dict(
        stream_obj="https://chzzk.naver.com/live/" + "a" * 32,
        output_dir=str(tmp_path),
        filename="테스트.ts",
    )
    if available:
        await pipeline.start_recording(**arguments)
        assert pipeline._resume_args[0] == stream.url
        assert pipeline._resume_args[4] is True
    else:
        with pytest.raises(RuntimeError, match="강제 녹화"):
            await pipeline.start_recording(**arguments)
        assert not list(tmp_path.glob("*.part"))
    resolve.assert_awaited_once()
    standard.assert_not_awaited()
