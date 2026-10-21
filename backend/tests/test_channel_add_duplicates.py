import asyncio

import pytest
from fastapi import HTTPException

from app.api import platforms, stream
from app.engine.conductor import Conductor
from app.services.recorder import RecorderService


@pytest.mark.asyncio
@pytest.mark.parametrize("platform,cid,url", [
    ("chzzk", "a" * 32, "https://chzzk.naver.com/live/" + "a" * 32),
    ("rplay", "6575bacd579cf110bca19354", "https://rplay.live/live/6575bacd579cf110bca19354"),
    ("twitch", "alice", "https://www.twitch.tv/alice"),
])
async def test_duplicate_add_rejected_without_changing_existing(monkeypatch, platform, cid, url):
    conductor = Conductor()
    service = RecorderService(conductor)
    monkeypatch.setattr("app.main.get_recorder_service", lambda: service)
    first = await platforms.add_platform_channel(platforms.AddPlatformChannelRequest(
        platform=platform, channel_id=cid, auto_record=False))
    key = first["composite_key"]
    task = conductor._channels[key]
    with pytest.raises(HTTPException) as caught:
        await platforms.add_platform_channel(platforms.AddPlatformChannelRequest(
            platform=platform, channel_id=url, auto_record=True))
    assert caught.value.status_code == 409
    assert caught.value.detail == "live.channelAlreadyRegistered"
    assert conductor.channel_count == 1
    assert conductor._channels[key] is task
    assert task.auto_record is False


@pytest.mark.asyncio
async def test_concurrent_cross_route_add_has_one_winner(monkeypatch):
    conductor = Conductor()
    service = RecorderService(conductor)
    monkeypatch.setattr("app.main.get_recorder_service", lambda: service)
    cid = "b" * 32

    async def add(index):
        try:
            if index % 2:
                return await stream.add_channel(stream.AddChannelRequest(channel_id=cid))
            return await platforms.add_platform_channel(platforms.AddPlatformChannelRequest(
                platform="chzzk", channel_id="https://chzzk.naver.com/live/" + cid))
        except HTTPException as error:
            return error.status_code

    results = await asyncio.gather(*(add(i) for i in range(16)))
    assert sum(isinstance(result, dict) for result in results) == 1
    assert results.count(409) == 15
    assert conductor.channel_count == 1
