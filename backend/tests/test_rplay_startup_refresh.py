import hashlib
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.engine import rplay_live
from app.engine.base import Platform
from app.engine.channel import ChannelTask
from app.engine.conductor import Conductor
from app.engine.pipeline import YtdlpLivePipeline
from app.engine.recording_errors import RecordingError

CID = "64e6e0e34f13627b4b3ea17d"


@pytest.mark.asyncio
async def test_startup_refresh_does_not_reuse_cached_live_state_or_dead_playlist(monkeypatch):
    monkeypatch.setattr(rplay_live, "account_session", lambda: None)
    engine = rplay_live.RplayLiveEngine()
    cache_key = (CID, hashlib.sha256(b"").hexdigest())
    engine._cache[cache_key] = (time.monotonic(), {"streamState": "live"})
    engine._stream_cache[cache_key] = (time.monotonic(), [
        {"value": "720p", "url": "https://livestream.rplay.live/stale.m3u8"}])
    engine._api = AsyncMock(return_value={
        "creatorOid": CID, "creatorMetadata": {"_id": CID}, "streamState": "offline"})
    with pytest.raises(RecordingError) as caught:
        await engine.resolve_stream(CID, force_refresh=True)
    assert caught.value.code == "broadcast_ended" and not caught.value.retryable
    engine._api.assert_awaited_once()
    assert cache_key not in engine._stream_cache


@pytest.mark.asyncio
@pytest.mark.parametrize("platform,cid", [(Platform.RPLAY, CID), (Platform.TWITCH, "alice")])
async def test_confirmed_end_at_start_is_not_logged_or_notified_as_capture_failure(monkeypatch, platform, cid):
    conductor = Conductor()
    key = platform.value + ":" + cid
    task = ChannelTask(cid, platform=platform, auto_record=True, is_live=True)
    conductor._channels[key] = task
    engine = SimpleNamespace(
        get_stream_url=lambda _: ("https://rplay.live/live/" + cid
                                  if platform == Platform.RPLAY else "https://www.twitch.tv/" + cid),
        resolve_stream=AsyncMock(side_effect=RecordingError("broadcast_ended", "방송 종료 확인")))
    monkeypatch.setattr(conductor, "_get_engine", lambda _: engine)
    monkeypatch.setattr(conductor, "_notify", Mock())
    failure = Mock()
    monkeypatch.setattr(conductor, "_record_failure", failure)
    async def start(pipe, **kwargs):
        await kwargs["source_resolver"]("best")
    monkeypatch.setattr(YtdlpLivePipeline, "start_recording", start)
    await conductor._start_recording(key)
    engine.resolve_stream.assert_awaited_once_with(
        cid, "best", **({"force_refresh": True} if platform == Platform.RPLAY else {}))
    failure.assert_not_called()
    conductor._notify.assert_not_called()
    assert task.broadcast_status == "offline" and task.pipeline is None
    assert task.retry_at is None and not task.retry_blocked
