import asyncio
import pytest
from app.engine.conductor import Conductor, ChannelTask
from app.engine.base import Platform
from app.engine.recording_errors import RecordingError


@pytest.mark.asyncio
async def test_auth_error_treated_as_ended():
    c = Conductor()
    task = ChannelTask(
        platform=Platform.RPLAY,
        channel_id="6a39e7194ca42a1e782e96f4",
        channel_name="치지",
        title="test",
        auto_record=True,
    )
    task.is_live = True
    c._channels["rplay:6a39e7194ca42a1e782e96f4"] = task

    class MockEngine:
        async def check_live_status(self, cid):
            raise RecordingError("rplay_authentication", "권한이 없습니다.")

    c._extra_engines[Platform.RPLAY] = MockEngine()
    c._running = True

    async def run_one():
        try:
            await MockEngine().check_live_status("6a39e7194ca42a1e782e96f4")
        except Exception as e:
            code = getattr(e, "code", None)
            err_text = str(e).lower()
            is_ended = (
                code in ("rplay_authentication", "rplay_access", "rplay_not_found", "not_available")
                or any(m in err_text for m in ("비공개", "삭제", "private", "unavailable"))
            )
            if is_ended and task.is_live:
                task.is_live = False
                task.monitor_error = None
                task.monitor_status = "watching"
                await c._handle_live_ended("rplay:6a39e7194ca42a1e782e96f4", task)

    await run_one()
    assert task.is_live is False
    assert task.monitor_status == "watching"
    assert task.monitor_error is None
