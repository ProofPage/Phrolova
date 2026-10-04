"""
test_api_notifications.py
알림 설정 API의 왕복(저장 → 재조회) 및 진단 엔드포인트 테스트.

설정 화면이 의존하는 계약이므로 필드 이름과 형태를 고정한다.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.services.notifications import KIND_LABELS


@pytest.fixture
def client():
    """lifespan 없이 라우터만 띄운다 (감시 루프를 돌리지 않기 위해)."""
    with TestClient(app) as c:
        yield c


class TestSettingsExposure:
    def test_settings_include_notification_fields(self, client):
        data = client.get("/api/settings").json()

        assert "discord_notify_events" in data
        assert "discord_mention_events" in data
        assert "discord_mention_target" in data
        assert "discord_notify_ttl" in data
        assert "discord_webhook_configured" in data

    def test_notification_kinds_are_listed(self, client):
        """설정 화면이 알림 종류 목록을 서버에서 받아 렌더링한다."""
        kinds = client.get("/api/settings").json()["notification_kinds"]

        assert len(kinds) == len(KIND_LABELS)
        values = {k["value"] for k in kinds}
        assert {"live_detected", "recording_started", "recording_failed"} <= values
        assert all(k["label"] for k in kinds)

    def test_webhook_url_is_not_exposed(self, client):
        """Webhook URL은 토큰과 동등한 비밀값이라 값 자체를 내려주면 안 된다."""
        url = "https://discord.com/api/webhooks/1234/tOkEnVaLuE"
        get_settings().discord_webhook_url = url

        data = client.get("/api/settings").json()

        assert data["discord_webhook_configured"] is True
        assert "discord_webhook_url" not in data
        # URL 자체도, 그 토큰 부분도 응답 어디에도 나타나면 안 된다.
        assert url not in str(data)
        assert "tOkEnVaLuE" not in str(data)


class TestNotificationSettingsRoundTrip:
    def test_save_and_reread(self, client):
        payload = {
            "discord_notify_events": ["live_detected", "recording_failed"],
            "discord_mention_events": ["recording_failed"],
            "discord_mention_target": "<@&123>",
            "discord_notify_ttl": 1800,
        }

        saved = client.put("/api/settings/discord", json=payload).json()["settings"]
        assert saved["discord_notify_events"] == ["live_detected", "recording_failed"]

        reread = client.get("/api/settings").json()
        assert reread["discord_notify_events"] == ["live_detected", "recording_failed"]
        assert reread["discord_mention_events"] == ["recording_failed"]
        assert reread["discord_mention_target"] == "<@&123>"
        assert reread["discord_notify_ttl"] == 1800

    def test_all_keyword_round_trips(self, client):
        client.put("/api/settings/discord", json={"discord_notify_events": ["all"]})
        assert client.get("/api/settings").json()["discord_notify_events"] == ["all"]

    def test_empty_selection_becomes_none(self, client):
        """전체 해제는 '아무것도 보내지 않음'으로 저장돼야 한다."""
        client.put("/api/settings/discord", json={"discord_notify_events": []})

        assert get_settings().discord_notify_events == "none"

    def test_partial_update_keeps_other_fields(self, client):
        client.put(
            "/api/settings/discord",
            json={"discord_mention_target": "@everyone", "discord_notify_ttl": 600},
        )
        client.put("/api/settings/discord", json={"discord_notify_ttl": 900})

        reread = client.get("/api/settings").json()
        assert reread["discord_mention_target"] == "@everyone"
        assert reread["discord_notify_ttl"] == 900

    def test_rejects_non_https_webhook(self, client):
        resp = client.put(
            "/api/settings/discord", json={"discord_webhook_url": "http://insecure"}
        )
        assert resp.status_code == 400

    def test_rejects_out_of_range_ttl(self, client):
        assert client.put(
            "/api/settings/discord", json={"discord_notify_ttl": 5}
        ).status_code == 422
        assert client.put(
            "/api/settings/discord", json={"discord_notify_ttl": 999999}
        ).status_code == 422


class TestNotificationDiagnostics:
    def test_status_endpoint_reports_transports(self, client):
        data = client.get("/api/settings/discord/status").json()

        assert data["available"] is True
        assert {"queued", "delivered", "dropped", "expired", "pending"} <= set(data)
        names = {t["name"] for t in data["transports"]}
        assert names == {"discord_bot", "webhook"}

    def test_test_notification_requires_a_transport(self, client):
        """Discord를 아예 설정하지 않았으면 안내와 함께 거절한다."""
        resp = client.post("/api/settings/discord/test")

        assert resp.status_code == 400
        assert "Webhook" in resp.json()["detail"]

    def test_test_notification_queues_when_configured(self, client):
        settings = get_settings()
        settings.discord_webhook_url = "https://discord.com/api/webhooks/x/y"
        settings.discord_notify_events = "all"

        resp = client.post("/api/settings/discord/test")

        assert resp.status_code == 200
        assert client.get("/api/settings/discord/status").json()["queued"] >= 1
