"""Official password sign-in flows. Passwords are used once, never persisted."""
from __future__ import annotations

import json
import re
import threading
import time
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

import httpx

from app.core.http import USER_AGENT
from app.engine.platform_auth import scoped_cookie_jar
from app.engine.recording_errors import RecordingError

LOGIN_URLS = {
    "cime": "https://ci.me/auth/login",
    "pandalive": "https://www.pandalive.co.kr/",
    "popkontv": "https://www.popkontv.com/",
    "hearheart": "https://hearheart.com/",
    "animaru": "https://animaru1.com/api/auth/login",
    "anilife": "https://anilife01.tv/api/auth/login",
}
LOGIN_LOCKS = {platform: threading.Lock() for platform in LOGIN_URLS}
ERROR_KEYS = {
    "invalid": "settings.platformLoginInvalid",
    "challenge": "settings.platformLoginChallenge",
    "unavailable": "settings.platformLoginUnavailable",
    "changed": "settings.platformLoginChanged",
    "busy": "settings.platformLoginBusy",
}


class PlatformLoginError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(ERROR_KEYS[code])


class _LoginPage(HTMLParser):
    def __init__(self, text: str):
        super().__init__()
        self.csrf = ""
        self.update_url = ""
        self.login_snapshot = ""
        self.next_data = None
        self._next_script = False
        self._script_text = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script":
            self._next_script = attrs.get("id") == "__NEXT_DATA__"
            self._script_text = []
            if attrs.get("data-update-uri"):
                self.update_url = attrs["data-update-uri"]
                self.csrf = attrs.get("data-csrf", "")
        if tag == "meta" and attrs.get("name") == "csrf-token":
            self.csrf = attrs.get("content", "")
        snapshot = attrs.get("wire:snapshot")
        if snapshot:
            data = json.loads(snapshot)
            if data.get("memo", {}).get("name") == "auth.login-form":
                self.login_snapshot = snapshot

    def handle_data(self, data):
        if self._next_script:
            self._script_text.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._next_script:
            self.next_data = json.loads("".join(self._script_text))
            self._next_script = False


def _check_response(response):
    if response.status_code == 429 or response.status_code >= 500:
        raise PlatformLoginError("unavailable")
    if response.status_code in (403, 419):
        raise PlatformLoginError("challenge")
    if response.status_code in (400, 401, 422):
        raise PlatformLoginError("invalid")
    if not 200 <= response.status_code < 300 or len(response.content) > 4 * 1024 * 1024:
        raise PlatformLoginError("changed")


def _json(response):
    _check_response(response)
    data = response.json()
    if not isinstance(data, dict):
        raise PlatformLoginError("changed")
    return data


def _secure_url(url, hosts):
    parts = urlsplit(url)
    # The official CIME gateway still supplies an http callback. Upgrade before
    # sending even a GET: its one-use authorization code must stay on HTTPS.
    if parts.scheme == "http" and parts.hostname == "ci.me" and parts.port in (None, 80):
        parts = parts._replace(scheme="https", netloc="ci.me")
    if (parts.scheme != "https" or parts.hostname not in hosts
            or parts.port not in (None, 443) or parts.username is not None
            or parts.password is not None or parts.fragment):
        raise PlatformLoginError("changed")
    return urlunsplit(parts)


def _page(client, url, hosts):
    """Follow only observed HTTP/JSON destinations; never execute page scripts."""
    for _ in range(10):
        url = _secure_url(url, hosts)
        response = client.get(url)
        if response.is_redirect:
            url = urljoin(url, response.headers["location"])
            continue
        _check_response(response)
        destination = re.search(r'"destination":"([^"\r\n]+)"', response.text)
        if destination:
            url = urljoin(url, json.loads('"' + destination[1] + '"'))
            continue
        return response
    raise PlatformLoginError("changed")


def _cime(client, username, password):
    hosts = ("ci.me", "mauth.marpple.com")
    page = _page(client, LOGIN_URLS["cime"], hosts)
    parts = urlsplit(str(page.url))
    if parts.hostname != "mauth.marpple.com" or not re.fullmatch(r"/(?:ko|kr)/login", parts.path):
        raise PlatformLoginError("changed")
    client_id = parse_qs(parts.query).get("client_id", [""])[0]
    if not re.fullmatch(r"[A-Za-z0-9-]{1,100}", client_id):
        raise PlatformLoginError("changed")
    language = parts.path.split("/")[1]
    _json(client.post(
        f"https://mauth.marpple.com/{language}/api/v1/auth/signin",
        json={"email": username, "password": password},
        headers={"Origin": "https://mauth.marpple.com", "Referer": str(page.url)},
    ))
    _page(client, f"https://mauth.marpple.com/{language}/result?" + urlencode({"client_id": client_id}), hosts)
    # A gateway login alone is not a usable CIME session.
    profile = client.get("https://ci.me/mypage")
    if profile.is_redirect or profile.status_code in (401, 403):
        raise PlatformLoginError("challenge")
    _check_response(profile)


def _pandalive(client, username, password):
    headers = {
        "Origin": "https://www.pandalive.co.kr",
        "Referer": LOGIN_URLS["pandalive"],
        "X-Device-Info": json.dumps({"t": "webPc", "v": "1.0", "ui": 0}),
    }
    response = client.post(
        "https://api.pandalive.co.kr/v1/member/login",
        data={"id": username, "pw": password, "idSave": "N", "recaptcha": ""},
        headers=headers,
    )
    # The official API also uses HTTP 400 for structured CAPTCHA/login errors.
    data = response.json() if response.status_code == 400 else _json(response)
    if not isinstance(data, dict):
        raise PlatformLoginError("changed")
    if data.get("result") is not True:
        code = (data.get("errorData") or {}).get("code")
        raise PlatformLoginError("challenge" if code and code not in ("wrongId", "noid", "wrongPw", "nopw") else "invalid")
    # Confirm the issued cookies, not just the successful password response.
    data = _json(client.post(
        "https://api.pandalive.co.kr/v1/member/login_info", data={}, headers=headers,
    ))
    user = (data.get("loginInfo") or {}).get("userInfo") or {}
    if data.get("result") is not True or str(user.get("id", "")).casefold() != username.casefold():
        raise PlatformLoginError("changed")


def _popkontv(client, username, password):
    from requests.cookies import create_cookie
    from app.engine.popkontv import (
        ORIGIN, PARTNER_RE, _post, encode_account_cookie, popkontv_account,
        public_web_config, response_data,
    )
    from app.engine.popkontv_session import _TOKEN_SECRETS

    response = client.get(LOGIN_URLS["popkontv"])
    _check_response(response)
    page = _LoginPage(response.text)
    partner = page.next_data["props"]["pageProps"]["initialData"]["partnerCode"]
    if not isinstance(partner, str) or not re.fullmatch(PARTNER_RE, partner):
        raise PlatformLoginError("changed")
    config = public_web_config(client, ORIGIN + "/", require_version=False, page_html=response.text)
    payload = _post(
        client, "/member/v1/login",
        {"partnerCode": partner, "signId": username, "signPwd": password},
        headers={"Origin": ORIGIN, "Referer": ORIGIN + "/",
                 "ClientKey": config["ClientKey"],
                 "Authorization": "Basic " + config["ClientKey"].removeprefix("Client ")},
    )
    if payload.get("statusCd") not in ("S2000", "E4170", "E4171"):
        raise PlatformLoginError("challenge" if payload.get("statusCd") == "E4025" else "invalid")
    data = response_data(payload, success=("S2000", "E4170", "E4171"))
    if str(data.get("isBlockMember", 0)) == "1" or str(data.get("isLoginBlock", 0)) == "1":
        raise PlatformLoginError("challenge")
    if str(data.get("signId", "")).casefold() != username.casefold() or data.get("partnerCode") != partner:
        raise PlatformLoginError("changed")
    user = {key: data.get(key) for key in ("signId", "partnerCode", "isAdultCheck")}
    values = {"user": (user, "SECRET_PSID1"),
              "auth-tk": (data.get("token"), _TOKEN_SECRETS["auth-tk"]),
              "ref-tk": (data.get("refreshToken"), _TOKEN_SECRETS["ref-tk"])}
    for name, (value, secret) in values.items():
        if name != "user" and (not isinstance(value, str) or not value
                or len(value) > 16384 or re.search(r"[\x00-\x20\x7f]", value)):
            raise PlatformLoginError("changed")
        client.cookies.jar.set_cookie(create_cookie(
            name, encode_account_cookie(value, secret), domain="www.popkontv.com",
            path="/", secure=True, rest={"HttpOnly": None},
        ))
    popkontv_account(client.cookies.jar)


def _hearheart(client, username, password):
    response = client.get(LOGIN_URLS["hearheart"])
    _check_response(response)
    page = _LoginPage(response.text)
    if not page.csrf or not page.login_snapshot or not page.update_url:
        raise PlatformLoginError("changed")
    update = _secure_url(urljoin(str(response.url), page.update_url), ("hearheart.com",))
    data = _json(client.post(
        update,
        json={"_token": page.csrf, "components": [{
            "snapshot": page.login_snapshot,
            "updates": {"email": username, "password": password},
            "calls": [{"path": "", "method": "login", "params": []}],
        }]},
        headers={"X-Livewire": "", "Origin": "https://hearheart.com", "Referer": str(response.url)},
    ))
    components = data.get("components")
    if not isinstance(components, list) or len(components) != 1:
        raise PlatformLoginError("changed")
    snapshot = json.loads(components[0]["snapshot"])
    if snapshot.get("memo", {}).get("errors"):
        raise PlatformLoginError("invalid")
    profile = client.get("https://hearheart.com/my/settings")
    if profile.is_redirect or profile.status_code in (401, 403):
        raise PlatformLoginError("invalid")
    _check_response(profile)


def _animaru(client, username, password):
    host = "animaru1.com"
    origin = f"https://{host}"
    url = f"{origin}/api/auth/login"
    response = client.post(
        url,
        json={"username": username, "password": password},
        headers={"Origin": origin, "Referer": f"{origin}/"},
    )
    if response.status_code == 400:
        try:
            data = response.json()
            err = str(data.get("error", ""))
            if any(k in err for k in ("없는 회원", "비밀번호", "일치하지", "아이디", "가입")):
                raise PlatformLoginError("invalid")
        except (ValueError, TypeError):
            pass
        raise PlatformLoginError("invalid")
    _check_response(response)
    data = response.json()
    if not isinstance(data, dict) or data.get("ok") is not True or not data.get("member"):
        raise PlatformLoginError("invalid")


def _anilife(client, username, password):
    from app.engine.tls_compat import enable_tls_compat
    host = "anilife01.tv"
    origin = f"https://{host}"
    url = f"{origin}/api/auth/login"
    try:
        enable_tls_compat(client, host)
    except Exception:
        pass
    response = client.post(
        url,
        json={"username": username, "password": password},
        headers={"Origin": origin, "Referer": f"{origin}/"},
    )
    if response.status_code in (400, 401):
        try:
            data = response.json()
            err = str(data.get("error", ""))
            code = str(data.get("code", ""))
            if code == "INVALID_CREDENTIALS" or any(k in err for k in ("아이디", "비밀번호", "올바르지", "없는", "가입")):
                raise PlatformLoginError("invalid")
        except (ValueError, TypeError):
            pass
        raise PlatformLoginError("invalid")
    _check_response(response)
    data = response.json()
    if not isinstance(data, dict) or not data.get("member"):
        raise PlatformLoginError("invalid")


def login_with_credentials(platform: str, username: str, password: str):
    if platform not in LOGIN_URLS:
        raise PlatformLoginError("changed")
    if (not isinstance(username, str) or not isinstance(password, str)
            or not username.strip() or len(username) > 320 or not password
            or len(password) > 4096 or re.search(r"[\x00-\x1f\x7f]", username)
            or re.search(r"[\x00\r\n]", password)):
        raise PlatformLoginError("invalid")
    username = username.strip()
    try:
        with httpx.Client(
            timeout=20, follow_redirects=False,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json, text/html"},
        ) as client:
            {"cime": _cime, "pandalive": _pandalive, "popkontv": _popkontv,
             "hearheart": _hearheart, "animaru": _animaru, "anilife": _anilife}[platform](client, username, password)
            jar = scoped_cookie_jar(client.cookies.jar, platform)
            for cookie in list(jar):
                if cookie.is_expired(time.time() + 30):
                    jar.clear(cookie.domain, cookie.path, cookie.name)
                elif any(c in (cookie.name + cookie.value + cookie.domain + cookie.path) for c in "\t\r\n\x00"):
                    raise PlatformLoginError("changed")
            if not len(jar):
                raise PlatformLoginError("changed")
            return jar
    except PlatformLoginError:
        raise
    except httpx.HTTPError:
        raise PlatformLoginError("unavailable") from None
    except RecordingError as error:
        raise PlatformLoginError(
            "unavailable" if error.code in ("popkontv_connection", "popkontv_rate_limit") else "changed"
        ) from None
    except (ValueError, KeyError, TypeError, AttributeError):
        raise PlatformLoginError("changed") from None
