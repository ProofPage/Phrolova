"""Official refresh-token flow, credential persistence and password isolation."""

import copy
import http.cookiejar
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import httpx
import pytest
import yt_dlp
from yt_dlp.networking.exceptions import HTTPError
from yt_dlp.utils import ExtractorError

from app.core.config import get_settings
from app.engine.base import Platform
from app.engine import popkontv as pop
from app.engine import popkontv_session as sessions
from app.engine.platform_auth import platform_cookie_jar, read_cookie_jar
from app.engine.popkontv_extractor import PopkonTVIE
from app.engine.recording_errors import RecordingError
from tests.test_popkontv import CHANNEL, MEDIA, META, account_jar, encrypt_cookie
from tests.test_popkontv_playback import media_parser as _media_parser

media_parser = _media_parser
REFRESH_SECRET = "SECRET_PSID6_SECRET_PSID6___SECRET_PSID6_SECRET_PSID6"


@pytest.fixture
def credentials(tmp_path):
    jar = http.cookiejar.MozillaCookieJar()
    for cookie in account_jar():
        jar.set_cookie(copy.copy(cookie))
    template = copy.copy(next(cookie for cookie in jar if cookie.name == "auth-tk"))
    template.name = "ref-tk"
    template.value = encrypt_cookie("fixture-refresh", REFRESH_SECRET)
    jar.set_cookie(template)
    source = tmp_path / "popkontv.txt"
    jar.save(str(source), ignore_discard=True, ignore_expires=True)
    get_settings().popkontv_cookie_file = str(source)
    return source


@pytest.fixture
def refresh_api(monkeypatch):
    requests = []
    original = httpx.Client

    def route(request):
        requests.append(request)
        if request.url.path.endswith("/mcinfo"):
            return httpx.Response(200, json={"statusCd": "S2000", "data": META})
        if request.url.path.endswith("/member/v1/refresh"):
            body = json.loads(request.content)
            assert body == {
                "clientKey": "Client public-fixture", "partnerCode": "P-00001",
                "signId": "viewer", "token": "fixture-token", "refreshToken": "fixture-refresh",
            }
            assert request.headers["Authorization"] == "Basic public-fixture"
            return httpx.Response(200, json={
                "statusCd": "S2000",
                "data": {"accessToken": "new-access", "refreshToken": "new-refresh"},
            })
        if request.headers.get("Authorization") == "Bearer fixture-token":
            return httpx.Response(401, json={})
        assert request.headers.get("Authorization") == "Bearer new-access"
        return httpx.Response(200, json={"statusCd": "L0000", "data": {"castHlsUrl": MEDIA}})

    monkeypatch.setattr(httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(route), **kw))
    config = lambda *a, **kw: {"ClientKey": "Client public-fixture", "version": "4.6.2"}
    monkeypatch.setattr(pop, "public_web_config", config)
    monkeypatch.setattr(sessions, "public_web_config", config)
    return requests


@pytest.mark.asyncio
async def test_expired_live_session_refreshes_once_and_persists_rotated_tokens(
    monkeypatch, credentials, refresh_api, media_parser
):
    monkeypatch.setattr(pop, "platform_cookie_jar", platform_cookie_jar)
    result = await pop.PopkonTVLiveEngine().resolve_stream(CHANNEL)
    assert result[0] == MEDIA.replace("index", "720")
    assert sum(r.url.path.endswith("/member/v1/refresh") for r in refresh_api) == 1
    assert not any(r.url.path.endswith("/login") for r in refresh_api)
    restored = platform_cookie_jar("popkontv")
    assert pop.popkontv_account(restored)[0] == {"Authorization": "Bearer new-access"}
    cookie = next(c for c in restored if c.name == "ref-tk")
    assert pop._decode_account_cookie(cookie.value, REFRESH_SECRET) == "new-refresh"
    assert b"new-access" not in credentials.read_bytes()
    assert b"new-refresh" not in credentials.read_bytes()
    assert len(media_parser) == 1


def test_parallel_expiry_uses_one_refresh(credentials, refresh_api):
    jars = [read_cookie_jar(credentials, "popkontv") for _ in range(2)]
    barrier = threading.Barrier(2)

    def operation(auth, user):
        if auth["Authorization"] == "Bearer fixture-token":
            barrier.wait(timeout=5)
            raise RecordingError("popkontv_session_expired", "expired")
        return auth["Authorization"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(
            lambda jar: sessions.authorized_popkontv_request(operation, jar, pop.ORIGIN + "/"),
            jars,
        ))
    assert results == ["Bearer new-access"] * 2
    assert sum(r.url.path.endswith("/member/v1/refresh") for r in refresh_api) == 1


def test_vod_session_refreshes_without_relogin(credentials, refresh_api, monkeypatch):
    jar = platform_cookie_jar("popkontv")
    with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
        for cookie in jar:
            ydl.cookiejar.set_cookie(copy.copy(cookie))
        ie = PopkonTVIE(ydl)
        seen = []

        def download(url, video_id, **kwargs):
            seen.append(kwargs["headers"])
            if kwargs["headers"]["Authorization"] == "Bearer fixture-token":
                raise ExtractorError(
                    "expired",
                    cause=HTTPError(SimpleNamespace(status=401, reason="Unauthorized")),
                )
            assert kwargs["headers"]["Authorization"] == "Bearer new-access"
            return {"statusCd": "S2000", "data": {
                "pk_code": "23501", "groupCode": "10", "locType": "0",
                "vodAddress": "https://vod2.popkontv.hscdn.com/video.mp4",
            }}

        monkeypatch.setattr(ie, "_download_json", download)
        item = ie._metadata({"id": "23501", "kind": "vod", "url": pop.ORIGIN + "/vod/23501"})
    assert item["pk_code"] == "23501" and len(seen) == 2
    assert not any(r.url.path.endswith("/login") for r in refresh_api)


def test_permission_denial_does_not_refresh(credentials, refresh_api):
    def denied(auth, user):
        raise RecordingError("popkontv_access", "permission denied")

    with pytest.raises(RecordingError, match="permission denied"):
        sessions.authorized_popkontv_request(denied, platform_cookie_jar("popkontv"), pop.ORIGIN + "/")
    assert refresh_api == []


def test_failed_persistence_does_not_replace_imported_file(credentials, monkeypatch):
    before = credentials.read_bytes()
    monkeypatch.setattr(sessions.os, "replace", lambda *a: (_ for _ in ()).throw(PermissionError("denied")))
    with pytest.raises(RecordingError, match="저장"):
        sessions._persist_tokens(
            platform_cookie_jar("popkontv"),
            {"auth-tk": "new-access", "ref-tk": "new-refresh"}, credentials,
        )
    assert credentials.read_bytes() == before
    assert list(credentials.parent.glob(".popkontv-session-*")) == []


def test_channel_password_is_write_only_and_memory_only(api_client):
    from app.api.platforms import router
    from app.main import get_recorder_service

    api_client.app.include_router(router)
    secret = "ROOM_SECRET_1234"
    response = api_client.post("/api/platforms/channels", json={
        "platform": "popkontv", "channel_id": CHANNEL, "auto_record": False,
        "popkontv_password": secret,
    })
    assert response.status_code == 200, response.text
    assert secret not in response.text
    engine = get_recorder_service()._conductor._get_engine(Platform.POPKONTV)
    assert engine._room_passwords[CHANNEL].get_secret_value() == secret
    assert secret not in repr(engine._room_passwords)
    assert secret not in api_client.get("/api/platforms/channels").text
    response = api_client.put(f"/api/platforms/channels/popkontv/{CHANNEL}/download-options", json={
        "auto_record": False, "popkontv_password": "",
    })
    assert response.status_code == 200 and CHANNEL not in engine._room_passwords
    oversized = secret * 20
    response = api_client.put(f"/api/platforms/channels/popkontv/{CHANNEL}/download-options", json={
        "auto_record": False, "popkontv_password": oversized,
    })
    assert response.status_code == 400 and oversized not in response.text
