import pytest
from app.engine.twitcasting import normalize_twitcasting_channel_id, TwitcastingLiveEngine

def test_normalize_twitcasting_channel_id():
    assert normalize_twitcasting_channel_id("twitcasting_jp") == "twitcasting_jp"
    assert normalize_twitcasting_channel_id("https://twitcasting.tv/twitcasting_jp") == "twitcasting_jp"
    assert normalize_twitcasting_channel_id("https://twitcasting.tv/twitcasting_jp/live") == "twitcasting_jp"
    assert normalize_twitcasting_channel_id("https://twitcasting.tv/twitcasting_jp/show") == "twitcasting_jp"
    assert normalize_twitcasting_channel_id("https://www.twitcasting.tv/TWITCASTING_JP") == "twitcasting_jp"

@pytest.mark.asyncio
async def test_twitcasting_engine_offline():
    engine = TwitcastingLiveEngine()
    status = await engine.check_live_status("twitcasting_jp")
    assert status["channel_id"] == "twitcasting_jp"
    assert "is_live" in status
    assert status["category"] == "TwitCasting"
    stream_url = engine.get_stream_url("twitcasting_jp")
    assert stream_url == "https://twitcasting.tv/twitcasting_jp"
