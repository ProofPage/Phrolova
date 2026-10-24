"""Refresh imported PopkonTV sessions without requesting account passwords."""

import copy
import os
import re
import tempfile
import threading
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.request import Request

import httpx

from app.core.config import get_settings
from app.engine.platform_auth import platform_cookie_jar, read_cookie_jar
from app.engine.popkontv import (
    ORIGIN, _decode_account_cookie, _post, encode_account_cookie,
    popkontv_account, popkontv_headers, public_web_config, response_data,
)
from app.engine.recording_errors import RecordingError


_lock = threading.RLock()
_TOKEN_SECRETS = {
    "auth-tk": "SECRET_PSID12__SECRET_PSID12_SECRET_PSID12__SECRET_PSID12",
    "ref-tk": "SECRET_PSID6_SECRET_PSID6___SECRET_PSID6_SECRET_PSID6",
}


def _copy_cookies(target, source):
    for cookie in source:
        target.set_cookie(copy.copy(cookie))


def _rotate_cookies(jar, tokens):
    for name, value in tokens.items():
        for original in list(jar):
            if original.name == name and original.domain.lstrip(".").lower() in (
                "popkontv.com", "www.popkontv.com",
            ):
                cookie = copy.copy(original)
                cookie.value = encode_account_cookie(value, _TOKEN_SECRETS[name])
                cookie.expires = None
                cookie.discard = True
                jar.set_cookie(cookie)


def _persist_tokens(jar, tokens, source):
    if source is not None:
        temporary = None
        try:
            stored = read_cookie_jar(source, "popkontv", include_expired=True)
            _rotate_cookies(stored, tokens)
            fd, temporary = tempfile.mkstemp(prefix=".popkontv-session-", dir=source.parent)
            os.close(fd)
            stored.save(temporary, ignore_discard=True, ignore_expires=True)
            os.replace(temporary, source)
            temporary = None
        except (OSError, ValueError) as error:
            raise RecordingError(
                "popkontv_cookie_storage",
                "갱신된 팝콘티비 세션을 저장하지 못했습니다. 인증 쿠키 파일의 쓰기 권한을 확인하세요.",
            ) from error
        finally:
            if temporary is not None:
                os.unlink(temporary)
    _rotate_cookies(jar, tokens)


def _refresh_session(jar, expired_auth, referer, client=None, config=None):
    with _lock:
        filename = get_settings().popkontv_cookie_file
        source = Path(filename) if filename else None
        if source is not None:
            current = platform_cookie_jar("popkontv")
            current_auth, _ = popkontv_account(current)
            if current_auth and current_auth != expired_auth:
                _copy_cookies(jar, current)
                return
        auth, user = popkontv_account(jar)
        request = Request(ORIGIN + "/")
        jar.add_cookie_header(request)
        cookies = SimpleCookie()
        cookies.load(request.get_header("Cookie", ""))
        if not auth or not user or "ref-tk" not in cookies:
            raise RecordingError(
                "popkontv_authentication",
                "팝콘티비 세션을 갱신할 수 없습니다. 공식 사이트의 인증 쿠키를 다시 등록하세요.",
            )
        refresh = _decode_account_cookie(cookies["ref-tk"].value, _TOKEN_SECRETS["ref-tk"])
        if not isinstance(refresh, str) or not refresh or len(refresh) > 16384 or re.search(r"[\x00-\x20\x7f]", refresh):
            raise RecordingError("popkontv_cookie", "팝콘티비 세션 갱신 쿠키가 올바르지 않습니다.")
        if client is None:
            with httpx.Client(
                timeout=15, follow_redirects=False, headers=popkontv_headers(referer), cookies=jar,
            ) as owned:
                return _refresh_session(jar, expired_auth, referer, client=owned, config=config)
        config = config or public_web_config(client, referer, require_version=False)
        client_key = config["ClientKey"]
        payload = _post(
            client, "/member/v1/refresh",
            {"clientKey": client_key, "partnerCode": user["partnerCode"],
             "signId": user["signId"], "token": auth["Authorization"].removeprefix("Bearer "),
             "refreshToken": refresh},
            headers={"Authorization": "Basic " + client_key.removeprefix("Client "),
                     "ClientKey": client_key, "Content-Type": "application/json"},
        )
        data = response_data(payload)
        tokens = {"auth-tk": data.get("accessToken"), "ref-tk": data.get("refreshToken")}
        if any(not isinstance(value, str) or not value or len(value) > 16384
               or re.search(r"[\x00-\x20\x7f]", value) for value in tokens.values()):
            raise RecordingError("popkontv_response", "팝콘티비 세션 갱신 응답이 올바르지 않습니다.")
        _persist_tokens(jar, tokens, source)
        client.cookies.update(jar)


def authorized_popkontv_request(operation, jar, referer, *, client=None, config=None):
    auth, user = popkontv_account(jar)
    try:
        return operation(auth, user)
    except RecordingError as error:
        if error.code != "popkontv_session_expired" or not auth:
            raise
    _refresh_session(jar, auth, referer, client=client, config=config)
    return operation(*popkontv_account(jar))
