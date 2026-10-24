import http.cookiejar
import time

import pytest
import yt_dlp.cookies

from app.engine.platform_auth import DOMAINS, extract_platform_from_browser, parse_chzzk_cookie_text


def cookie(domain, value="secret", expires=None):
    return http.cookiejar.Cookie(
        0, "session", value, None, False, domain, True, domain.startswith("."),
        "/", True, True, expires, expires is None, None, None, {}, False,
    )


@pytest.mark.parametrize("platform", DOMAINS)
def test_browser_import_scopes_domains_and_excludes_expired(platform, monkeypatch):
    domain = DOMAINS[platform][0]
    jar = http.cookiejar.CookieJar()
    jar.set_cookie(cookie("." + domain))
    jar.set_cookie(cookie("evil" + domain, "unrelated"))
    jar.set_cookie(cookie("expired." + domain, "expired", int(time.time()) - 60))
    monkeypatch.setattr(yt_dlp.cookies, "extract_cookies_from_browser", lambda name: jar)
    text = extract_platform_from_browser(platform, "chrome")
    assert "secret" in text
    assert "unrelated" not in text
    assert "expired" not in text


def test_missing_chzzk_cookie_is_validation_error():
    with pytest.raises(ValueError):
        parse_chzzk_cookie_text("unrelated=value")


@pytest.mark.parametrize("value,expires,valid,expired", [
    ("secret", None, True, False),
    ("", None, False, False),
    ("secret", 1, False, True),
])
def test_file_status_does_not_claim_verified_login(tmp_path, value, expires, valid, expired):
    from app.engine.platform_auth import cookie_file_status

    jar = http.cookiejar.MozillaCookieJar()
    jar.set_cookie(cookie(".youtube.com", value, expires))
    path = tmp_path / "cookies.txt"
    jar.save(str(path), ignore_discard=True, ignore_expires=True)
    status = cookie_file_status(path, "youtube")
    assert status["configured"] is True
    assert status["valid"] is valid
    assert status["expired"] is expired
    assert status["login_verified"] is False
