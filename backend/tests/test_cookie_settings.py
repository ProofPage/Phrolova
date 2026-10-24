"""Cookie-file settings use isolated credentials, storage and authenticated APIs."""

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.core.config import Settings, get_settings
from app.engine.auth import AuthManager


def cookies(domain=".naver.com", expiry="0", names=("NID_AUT", "NID_SES")):
    return "# Netscape HTTP Cookie File\n" + "".join(
        f"{domain}\tTRUE\t/\tTRUE\t{expiry}\t{name}\tfixture-{name}\n" for name in names
    )


@pytest.fixture
def cookie_client(api_client, monkeypatch, tmp_path):
    import app.main
    from app.api import platforms

    api_client.app.include_router(platforms.router)
    # Match main.lifespan: the live and VOD services share one AuthManager.
    service = app.main.get_recorder_service()
    service._auth = service._conductor._auth
    service._vod_engine._auth = service._auth
    settings = get_settings()
    settings.youtube_cookie_file = None
    getter = lambda: settings
    getter.cache_clear = lambda: None
    monkeypatch.setattr(platforms, "get_settings", getter)
    monkeypatch.setattr(
        platforms, "_COOKIE_SAVE_PATH", tmp_path / "platform_cookies.txt"
    )
    return api_client


def upload(client, platform, content):
    return client.post(
        f"/api/platforms/{platform}/cookie", files={"file": ("쿠키 파일.txt", content)}
    )


def test_chzzk_upload_uses_existing_live_and_vod_auth_and_persists(
    cookie_client, tmp_path
):
    import app.main

    payload = (
        cookies().replace(".naver.com", "#HttpOnly_.naver.com")
        + cookies(".example.com", names=("tracking",)).split("\n", 1)[1]
    )
    response = upload(cookie_client, "chzzk", payload)
    assert response.status_code == 200 and response.json()["configured"]
    assert response.json()["valid"] is None  # Registration is not a remote login check.
    auth = app.main.get_recorder_service()._conductor._auth
    assert auth.get_cookies().to_dict() == {
        "NID_AUT": "fixture-NID_AUT",
        "NID_SES": "fixture-NID_SES",
    }
    assert "fixture-NID_AUT" in auth.get_ytdlp_cookies()
    saved = Settings(_env_file=tmp_path / ".env")
    assert saved.nid_aut == "fixture-NID_AUT" and saved.nid_ses == "fixture-NID_SES"
    assert (
        "fixture-" not in response.text
        and "tracking" not in (tmp_path / ".env").read_text()
    )


@pytest.mark.parametrize(
    "payload",
    [
        b"not a cookie file",
        b"\xff\xfe",
        b"x" * (1024 * 1024 + 1),
        cookies(".example.com"),
        cookies(".naver.com.evil.test"),
        cookies(".chzzk.naver.com"),
        cookies(expiry="1"),
        cookies(names=("NID_AUT",)),
        cookies(names=("other-cookie",)),
    ],
    ids=[
        "invalid-format",
        "invalid-encoding",
        "oversized",
        "other-domain",
        "spoofed-domain",
        "narrow-domain",
        "expired",
        "missing-session",
        "unrelated-cookie",
    ],
)
def test_chzzk_invalid_upload_preserves_existing_credentials(cookie_client, payload):
    AuthManager().update_cookies("existing-aut", "existing-ses")
    response = upload(cookie_client, "chzzk", payload)
    assert response.status_code == 400
    assert (
        get_settings().nid_aut == "existing-aut"
        and get_settings().nid_ses == "existing-ses"
    )
    assert "existing-aut" not in response.text and "fixture-" not in response.text


def test_legacy_chzzk_credentials_can_be_checked_and_removed(
    cookie_client, monkeypatch, tmp_path
):
    from app.api.settings import auth as auth_api

    AuthManager().update_cookies("legacy-aut", "legacy-ses")
    assert cookie_client.get("/api/platforms/chzzk/cookie").json()["configured"]
    check = AsyncMock(
        return_value={"valid": True, "user_status": {"nickname": "private-name"}}
    )
    monkeypatch.setattr(auth_api, "test_cookies", check)
    response = cookie_client.post("/api/platforms/chzzk/cookie/check")
    assert response.json()["valid"] is True and "private-name" not in response.text
    assert (
        cookie_client.delete("/api/platforms/chzzk/cookie").json()["configured"]
        is False
    )
    assert not AuthManager().is_authenticated
    assert not Settings(_env_file=tmp_path / ".env").nid_aut
    assert (
        cookie_client.post("/api/platforms/chzzk/cookie/check").json()["configured"]
        is False
    )
    assert check.await_count == 1


def test_chzzk_invalid_remote_login_and_network_error(cookie_client, monkeypatch):
    from app.api.settings import auth as auth_api

    AuthManager().update_cookies("legacy-aut", "legacy-ses")
    check = AsyncMock(return_value={"valid": False})
    monkeypatch.setattr(auth_api, "test_cookies", check)
    assert (
        cookie_client.post("/api/platforms/chzzk/cookie/check").json()["expired"]
        is False
    )
    check.side_effect = HTTPException(500, "Cookie: legacy-aut")
    response = cookie_client.post("/api/platforms/chzzk/cookie/check")
    assert response.status_code == 502 and "legacy-aut" not in response.text


@pytest.mark.parametrize("user", [{}, {"loggedIn": False}])
def test_chzzk_anonymous_success_response_is_not_valid_login(
    cookie_client, monkeypatch, user
):
    from app.api.settings import auth as auth_api

    AuthManager().update_cookies("legacy-aut", "legacy-ses")
    monkeypatch.setattr(
        auth_api,
        "test_cookies",
        AsyncMock(return_value={"valid": True, "user_status": user}),
    )
    assert (
        cookie_client.post("/api/platforms/chzzk/cookie/check").json()["valid"] is False
    )


def test_youtube_shared_status_upload_refresh_delete(cookie_client, tmp_path):
    assert (
        cookie_client.get("/api/platforms/youtube/cookie").json()["configured"] is False
    )
    response = upload(cookie_client, "youtube", cookies(".youtube.com", names=("SID",)))
    assert response.status_code == 200 and response.json()["valid"] is True
    assert "fixture-SID" not in response.text
    status = cookie_client.get("/api/platforms/youtube/cookie").json()
    assert status["configured"] and status["valid"] and not status["expired"]
    saved = Settings(_env_file=tmp_path / ".env")
    assert saved.youtube_cookie_file == str(tmp_path / "youtube_cookies.txt")
    assert (
        cookie_client.delete("/api/platforms/youtube/cookie").json()["configured"]
        is False
    )
    assert not (tmp_path / "youtube_cookies.txt").exists()


@pytest.mark.parametrize(
    "content, expired",
    [(cookies(".youtube.com", "1", ("SID",)), True), ("invalid", False)],
)
def test_youtube_expired_or_unreadable_status(
    cookie_client, tmp_path, content, expired
):
    source = tmp_path / "legacy-cookies.txt"
    source.write_text(content, encoding="utf-8")
    get_settings().youtube_cookie_file = str(source)
    status = cookie_client.get("/api/platforms/youtube/cookie").json()
    assert status["configured"] and not status["valid"] and status["expired"] is expired


def test_old_chzzk_cookie_api_remains_compatible(cookie_client):
    assert (
        cookie_client.put(
            "/api/settings/cookies",
            json={"nid_aut": "fixture-aut", "nid_ses": "fixture-ses"},
        ).status_code
        == 200
    )
    assert cookie_client.get("/api/platforms/chzzk/cookie").json()["configured"] is True
