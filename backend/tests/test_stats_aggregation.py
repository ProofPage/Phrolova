import pytest
from unittest.mock import Mock
from fastapi.testclient import TestClient
from app.main import app

def test_stats_channel_aggregation_and_deduplication(monkeypatch):
    mock_service = Mock()
    mock_conductor = Mock()
    
    # 1) 세션 이력: 구버전 @https://... 키로 기록된 항목
    mock_conductor.get_live_history.return_value = [
        {
            "channel_id": "@https://www.youtube.com/live/BQJSlMSIrPk",
            "composite_key": "youtube:@https://www.youtube.com/live/BQJSlMSIrPk",
            "platform": "youtube",
            "channel_name": "말왕TV",
            "duration_seconds": 120,
            "file_size_bytes": 126800000,
        }
    ]
    
    # 2) 라이브 감지 기록: 동일한 채널의 감지 수
    mock_conductor.get_live_detections.return_value = {
        "youtube:@https://www.youtube.com/live/BQJSlMSIrPk": 1,
        "youtube:BQJSlMSIrPk": 0,
    }
    
    mock_conductor.get_all_status.return_value = [
        {
            "composite_key": "youtube:BQJSlMSIrPk",
            "channel_id": "BQJSlMSIrPk",
            "channel_name": "말왕TV",
            "platform": "youtube",
        }
    ]
    
    mock_service._conductor = mock_conductor
    mock_service._vod_engine = None
    monkeypatch.setattr("app.main.get_recorder_service", lambda: mock_service)
    
    client = TestClient(app)
    res = client.get("/api/stats")
    assert res.status_code == 200
    data = res.json()
    
    by_channel = data["live"]["by_channel"]
    # 반드시 1개로 병합되어야 함 (중복 없음)
    assert len(by_channel) == 1
    item = by_channel[0]
    assert item["channel_id"] == "BQJSlMSIrPk"
    assert item["channel_name"] == "말왕TV"
    assert item["session_count"] == 1
    assert item["live_detected_count"] == 1
    assert item["total_size_bytes"] == 126800000
