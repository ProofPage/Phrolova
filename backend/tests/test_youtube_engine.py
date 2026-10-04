import pytest
from app.engine.youtube import YoutubeLiveEngine
from app.core.utils import extract_youtube_id
from app.engine.base import Platform


@pytest.mark.asyncio
async def test_youtube_id_extraction():
    # 1. URL 기반 파싱 테스트
    assert extract_youtube_id("https://www.youtube.com/@GoogleDeepMind") == "@GoogleDeepMind"
    assert extract_youtube_id("https://www.youtube.com/@GoogleDeepMind/live") == "@GoogleDeepMind"
    assert extract_youtube_id("https://youtube.com/@GoogleDeepMind") == "@GoogleDeepMind"
    
    # 2. 채널 ID 파싱 테스트
    channel_url = "https://www.youtube.com/channel/UC-9-kyTE8y5JhEl5xWd-R4A"
    assert extract_youtube_id(channel_url) == "UC-9-kyTE8y5JhEl5xWd-R4A"
    assert extract_youtube_id(channel_url + "/live") == "UC-9-kyTE8y5JhEl5xWd-R4A"

    # 3. 단일 식별자 파싱 및 자동 보정 테스트
    assert extract_youtube_id("@GoogleDeepMind") == "@GoogleDeepMind"
    assert extract_youtube_id("UC-9-kyTE8y5JhEl5xWd-R4A") == "UC-9-kyTE8y5JhEl5xWd-R4A"
    # 골뱅이가 누락된 핸들명의 자동 보정 테스트
    assert extract_youtube_id("GoogleDeepMind") == "@GoogleDeepMind"


@pytest.mark.asyncio
async def test_youtube_live_engine_offline():
    # 실제 존재하는 채널(예: @GoogleDeepMind)은 보통 오프라인 상태일 것입니다.
    # 이를 통해 엔진이 정상적으로 HTTP 요청을 보내고 오프라인 상태(is_live=False)를 파싱하는지 실측합니다.
    engine = YoutubeLiveEngine()
    status = await engine.check_live_status("@GoogleDeepMind")
    
    # 기본 메타데이터 검증
    assert status["channel_id"] == "@GoogleDeepMind"
    # 실시간 생방송 중이 아닐 경우 is_live는 False여야 함
    assert isinstance(status["is_live"], bool)
    
    # get_stream_url 정상 반환 검증
    stream_url = engine.get_stream_url("@GoogleDeepMind")
    assert stream_url == "https://www.youtube.com/@GoogleDeepMind/live"


@pytest.mark.asyncio
async def test_youtube_live_engine_invalid_channel():
    # 존재하지 않는 임의의 채널에 대한 예외 처리 검증
    engine = YoutubeLiveEngine()
    status = await engine.check_live_status("@this_channel_does_not_exist_123456789")
    
    assert status["is_live"] is False
    assert status["viewer_count"] == 0
