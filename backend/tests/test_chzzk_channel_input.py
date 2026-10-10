"""Keep the existing registration API's ID/link and recording option contract."""
from unittest.mock import Mock
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.engine.base import Platform

CHANNEL_ID = '19e3b97ca1bca954d1ac84cf6862e0dc'

@pytest.mark.parametrize('value', [
    CHANNEL_ID, f' {CHANNEL_ID} ',
    f'https://chzzk.naver.com/{CHANNEL_ID}',
    f'https://chzzk.naver.com/live/{CHANNEL_ID}',
    f'https://chzzk.naver.com/{CHANNEL_ID}?source=share',
])
def test_channel_registration_id_and_url_preserve_recording_options(monkeypatch, value):
    service = Mock()
    service.add_platform_channel.return_value = {'channel_id': CHANNEL_ID}
    monkeypatch.setattr('app.main.get_recorder_service', lambda: service)
    response = TestClient(app).post('/api/stream/channels', json={
        'channel_id': value, 'auto_record': False,
        'download_condition': 'watchalong', 'watchalong_tags': '같이보기',
    })
    assert response.status_code == 200
    service.add_platform_channel.assert_called_once_with(
        CHANNEL_ID, platform=Platform.CHZZK, auto_record=False,
        download_condition='watchalong', watchalong_tags='같이보기',
    )
