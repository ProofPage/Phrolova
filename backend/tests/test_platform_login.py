"""Official wire formats, usable sessions and transactional password sign-in."""
import html
import json
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import platforms
from app.core.config import get_settings
from app.engine import platform_login as login
from app.engine.platform_auth import get_platform_cookies, read_cookie_jar
from app.engine.popkontv import popkontv_account

PASSWORD = "fixture-private-password +&한글"
USERS = {"cime": "viewer@example.invalid", "hearheart": "audio@example.invalid",
         "pandalive": "viewer", "popkontv": "viewer"}
SNAPSHOT = json.dumps({"data": {"email": "", "password": "", "mode": "email", "variant": "default"},
                       "memo": {"name": "auth.login-form", "errors": []}, "checksum": "signed-fixture"})


@pytest.fixture
def protocol(monkeypatch):
    calls = []
    state = {"failure": None}
    original_client = httpx.Client

    def handler(request):
        calls.append(request)
        host, path = request.url.host, request.url.path
        if request.method == "POST" and state["failure"] == "timeout":
            raise httpx.ReadTimeout("secret-connection-detail", request=request)
        if request.method == "POST" and state["failure"] == "limit":
            return httpx.Response(429, text=PASSWORD)
        if request.method == "POST" and state["failure"] == "malformed":
            return httpx.Response(200, text=PASSWORD)
        if host == "ci.me":
            if path == "/auth/login" and "code" not in request.url.params:
                return httpx.Response(200, text=json.dumps({
                    "destination": "https://mauth.marpple.com/kr/login?client_id=fixture-client",
                }, separators=(",", ":")))
            if path == "/auth/login":
                return httpx.Response(303, headers={"location": "/",
                    "set-cookie": "cime-session=fixture-cime-session; Secure; HttpOnly; Path=/"})
            if path == "/mypage" and "cime-session=fixture-cime-session" not in request.headers.get("cookie", ""):
                return httpx.Response(307, headers={"location": "/auth/login"})
            return httpx.Response(200, text="<html>account</html>")
        if host == "mauth.marpple.com":
            if path == "/kr/login":
                return httpx.Response(302, headers={"location": "/ko/login?client_id=fixture-client"})
            if path.endswith("/auth/signin"):
                assert json.loads(request.content) == {"email": USERS["cime"], "password": PASSWORD}
                assert request.headers["origin"] == "https://mauth.marpple.com"
                if state["failure"] == "challenge":
                    return httpx.Response(403, text=PASSWORD)
                return httpx.Response(200, json={}, headers={"set-cookie": "gateway=private-gateway; Secure; Path=/"})
            if path == "/ko/result":
                return httpx.Response(302, headers={"location": "http://ci.me/auth/login?code=one-use-code"})
            return httpx.Response(200, text='<input name="email"><input name="password">')
        if host == "api.pandalive.co.kr":
            body = parse_qs(request.content.decode(), keep_blank_values=True)
            if path.endswith("/login"):
                assert body == {"id": [USERS["pandalive"]], "pw": [PASSWORD], "idSave": ["N"], "recaptcha": [""]}
                assert json.loads(request.headers["x-device-info"])["t"] == "webPc"
                if state["failure"] == "challenge":
                    return httpx.Response(400, json={"result": False, "errorData": {"code": "recaptcha"}})
                return httpx.Response(200, json={"result": True},
                    headers={"set-cookie": "sessKey=fixture-panda-session; Domain=.pandalive.co.kr; Secure; HttpOnly; Path=/"})
            assert path.endswith("/login_info")
            assert "sessKey=fixture-panda-session" in request.headers["cookie"]
            return httpx.Response(200, json={"result": True, "loginInfo": {"userInfo": {"id": USERS["pandalive"]}}})
        if host == "hearheart.com":
            if path == "/":
                return httpx.Response(200, text=(
                    '<meta name="csrf-token" content="csrf-fixture">'
                    f'<div wire:snapshot="{html.escape(SNAPSHOT, quote=True)}"></div>'
                    '<script data-update-uri="https://hearheart.com/livewire-dd532633/update" data-csrf="csrf-fixture"></script>'
                ), headers={"set-cookie": "hearheart-session=guest; Secure; HttpOnly; Path=/"})
            if path.endswith("/update"):
                data = json.loads(request.content)
                assert data["_token"] == "csrf-fixture" and "x-livewire" in request.headers
                assert data["components"] == [{
                    "snapshot": SNAPSHOT,
                    "updates": {"email": USERS["hearheart"], "password": PASSWORD},
                    "calls": [{"path": "", "method": "login", "params": []}],
                }]
                if state["failure"] == "challenge":
                    return httpx.Response(419, text=PASSWORD)
                return httpx.Response(200, json={"components": [{"snapshot": SNAPSHOT, "effects": {}}]},
                    headers={"set-cookie": "hearheart-session=fixture-heart-session; Secure; HttpOnly; Path=/"})
            assert path == "/my/settings"
            assert "hearheart-session=fixture-heart-session" in request.headers["cookie"]
            return httpx.Response(200, text="<html>account settings</html>")
        assert host == "www.popkontv.com"
        if path == "/":
            data = {"props": {"pageProps": {"initialData": {"partnerCode": "P-00001"}}}}
            return httpx.Response(200, text='<script id="__NEXT_DATA__" type="application/json">' + json.dumps(data) + "</script>")
        assert path == "/api/proxy/member/v1/login"
        assert json.loads(request.content) == {"partnerCode": "P-00001", "signId": USERS["popkontv"], "signPwd": PASSWORD}
        assert request.headers["authorization"] == "Basic public-client"
        if state["failure"] == "challenge":
            return httpx.Response(200, json={"statusCd": "E4025", "data": {}})
        return httpx.Response(200, json={"statusCd": "S2000", "data": {
            "signId": USERS["popkontv"], "partnerCode": "P-00001", "isAdultCheck": "1",
            "token": "fixture-access-token", "refreshToken": "fixture-refresh-token",
        }})

    monkeypatch.setattr(login.httpx, "Client", lambda **kwargs: original_client(
        **kwargs, transport=httpx.MockTransport(handler)))
    monkeypatch.setattr("app.engine.popkontv.public_web_config",
                        lambda client, referer, **kwargs: {"ClientKey": "Client public-client"})
    return calls, state


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(platforms, "_COOKIE_SAVE_PATH", tmp_path / "cookies.txt")
    settings = get_settings()
    getter = lambda: settings
    getter.cache_clear = lambda: None
    monkeypatch.setattr(platforms, "get_settings", getter)
    app = FastAPI()
    app.include_router(platforms.router)
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("platform", USERS)
def test_verified_login_registers_only_platform_session(client, protocol, tmp_path, platform, caplog):
    calls, _ = protocol
    response = client.post(f"/api/platforms/{platform}/login",
        json={"username": " " + USERS[platform] + " ", "password": PASSWORD})
    assert response.status_code == 200, response.text
    assert response.json()["configured"] and response.json()["valid"]
    assert response.headers["cache-control"] == "no-store"
    saved = tmp_path / f"{platform}_cookies.txt"
    jar = read_cookie_jar(saved, platform)
    assert len(jar) and all(not cookie.is_expired() for cookie in jar)
    assert getattr(get_settings(), f"{platform}_cookie_file") == str(saved)
    assert PASSWORD not in saved.read_text() + (tmp_path / ".env").read_text() + response.text + caplog.text
    assert "private-gateway" not in saved.read_text()
    assert all(request.url.scheme == "https" for request in calls)
    assert all(PASSWORD not in str(request.url) for request in calls)
    if platform == "popkontv":
        auth, user = popkontv_account(jar)
        assert auth == {"Authorization": "Bearer fixture-access-token"}
        assert user == {"signId": "viewer", "partnerCode": "P-00001", "adult_verified": True}
    else:
        url = {"cime": "https://ci.me/", "pandalive": "https://api.pandalive.co.kr/v1/live/play",
               "hearheart": "https://hearheart.com/playlist/1/content/2"}[platform]
        assert get_platform_cookies(platform, url)
        assert get_platform_cookies(platform, "https://example.invalid/") == {}


@pytest.mark.parametrize("platform", USERS)
@pytest.mark.parametrize("failure,code", [("timeout", 502), ("limit", 502), ("malformed", 502), ("challenge", 409)])
def test_login_failure_preserves_prior_credentials(client, protocol, tmp_path, platform, failure, code):
    calls, state = protocol
    state["failure"] = failure
    path = tmp_path / f"{platform}_cookies.txt"
    path.write_text("previous-private-session")
    setattr(get_settings(), f"{platform}_cookie_file", str(path))
    response = client.post(f"/api/platforms/{platform}/login",
        json={"username": USERS[platform], "password": PASSWORD})
    assert response.status_code == code, response.text
    assert response.headers["cache-control"] == "no-store"
    assert path.read_text() == "previous-private-session"
    assert "private-" not in response.text and PASSWORD not in response.text
    assert getattr(get_settings(), f"{platform}_cookie_file") == str(path)
    assert not list(tmp_path.glob(".credential-*"))
    assert sum(request.method == "POST" for request in calls) == 1


@pytest.mark.parametrize("platform", USERS)
def test_login_storage_failure_restores_previous_session(client, protocol, tmp_path, monkeypatch, platform):
    path = tmp_path / f"{platform}_cookies.txt"
    path.write_text("previous-private-session")
    setattr(get_settings(), f"{platform}_cookie_file", str(path))
    def denied(*args, **kwargs):
        raise PermissionError(PASSWORD)
    monkeypatch.setattr(platforms, "_update_env_file", denied)
    response = client.post(f"/api/platforms/{platform}/login",
        json={"username": USERS[platform], "password": PASSWORD})
    assert response.status_code == 500 and PASSWORD not in response.text
    assert path.read_text() == "previous-private-session"
    assert getattr(get_settings(), f"{platform}_cookie_file") == str(path)


@pytest.mark.parametrize("body", [
    {}, [], {"username": "", "password": PASSWORD}, {"username": "viewer", "password": ""},
    {"username": ["viewer"], "password": PASSWORD}, {"username": "viewer", "password": [PASSWORD]},
    {"username": "viewer", "password": "x" * 4097}, {"username": "bad\nid", "password": PASSWORD},
    {"username": "x" * 321, "password": PASSWORD},
])
def test_invalid_input_never_contacts_provider_or_echoes_password(client, protocol, body):
    calls, _ = protocol
    response = client.post("/api/platforms/pandalive/login", json=body)
    assert response.status_code == 400 and PASSWORD not in response.text
    assert calls == []


def test_malformed_oversized_unsupported_and_busy_requests(client, protocol):
    calls, _ = protocol
    for payload in (b'{"password":"private-secret",', b"x" * (32 * 1024 + 1)):
        response = client.post("/api/platforms/cime/login", content=payload)
        assert response.status_code == 400 and "private-secret" not in response.text
    assert client.post("/api/platforms/chzzk/login", json={}).status_code == 400
    with login.LOGIN_LOCKS["cime"]:
        response = client.post("/api/platforms/cime/login", json={})
        assert response.status_code == 409 and response.json()["detail"]["code"] == "busy"
    assert calls == []


@pytest.mark.parametrize("target", [
    "https://mauth.marpple.com.evil.invalid/login", "https://evil.invalid/",
    "https://user:pass@mauth.marpple.com/login", "https://mauth.marpple.com:444/login",
    "http://mauth.marpple.com/login", "//evil.invalid/login",
])
def test_cime_rejects_untrusted_destinations_before_credentials(monkeypatch, target):
    original = httpx.Client
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, text=json.dumps({"destination": target}, separators=(",", ":")))
    monkeypatch.setattr(login.httpx, "Client", lambda **kwargs: original(
        **kwargs, transport=httpx.MockTransport(handler)))
    with pytest.raises(login.PlatformLoginError, match="settings.platformLoginChanged"):
        login.login_with_credentials("cime", USERS["cime"], PASSWORD)
    assert len(calls) == 1 and calls[0].method == "GET"
