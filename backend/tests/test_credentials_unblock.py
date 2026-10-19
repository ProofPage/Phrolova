import asyncio
import pytest
from app.engine.conductor import Conductor, ChannelTask
from app.engine.base import Platform


def test_credentials_unblock():
    c = Conductor()
    cid1 = "68b551a74efe8779413a195f"
    task1 = ChannelTask(
        platform=Platform.RPLAY,
        channel_id=cid1,
        channel_name="test_rplay",
        title="test",
        auto_record=True,
    )
    task1.retry_blocked = True
    task1.retry_count = 3
    task1.last_error = "인증 실패"
    c._channels[f"rplay:{cid1}"] = task1
    c._scan_events[f"rplay:{cid1}"] = asyncio.Event()

    task2 = ChannelTask(
        platform=Platform.YOUTUBE,
        channel_id="@test_yt",
        channel_name="test_yt",
        title="test",
        auto_record=True,
    )
    task2.retry_blocked = True
    c._channels["youtube:@test_yt"] = task2
    c._scan_events["youtube:@test_yt"] = asyncio.Event()

    # RPLAY credentials updated -> unblock only RPLAY channels
    c.on_credentials_updated("rplay")

    assert task1.retry_blocked is False
    assert task1.retry_count == 0
    assert task1.last_error is None
    assert c._scan_events[f"rplay:{cid1}"].is_set()

    # YouTube task should remain blocked
    assert task2.retry_blocked is True
    assert not c._scan_events["youtube:@test_yt"].is_set()

    # All credentials updated -> unblock YouTube as well
    c.on_credentials_updated()
    assert task2.retry_blocked is False
    assert c._scan_events["youtube:@test_yt"].is_set()
