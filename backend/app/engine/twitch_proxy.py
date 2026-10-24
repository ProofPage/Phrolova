"""Session-local adaptation of ReYohoho's Usher proxy protocol.

Protocol reference: reyohoho/twitch_quality_proxy, userscript/twitch.user.js.
Account-token forwarding is explicitly enabled by the Twitch proxy setting.
No userscript code, browser hooks or remote executable code is loaded.
"""
from __future__ import annotations

import re
from urllib.parse import unquote, urlencode, urlsplit

import requests
from requests.adapters import HTTPAdapter

from app.core.logger import get_platform_logger
from app.engine.preview_proxy import PreviewProxy
from app.engine.streamlink_support import QUERY_MEDIA_DOMAINS

PROXY_SERVERS = (
    "https://proxy4.rte.net.ru/",
    "https://proxy7.rte.net.ru/",
    "https://proxy5.rte.net.ru/",
    "https://proxy6.rte.net.ru/",
)
logger = get_platform_logger("twitch", "proxy")


def _valid_manifest(text: str, auth_token: str) -> bool:
    if not text.startswith("#EXTM3U") or "#EXT-X-STREAM-INF:" not in text:
        return False
    if auth_token and auth_token in unquote(text):
        return False
    urls = [
        line.strip() for line in text.splitlines()
        if line.strip() and not line.startswith("#")
    ]
    urls.extend(re.findall(r'\bURI="([^"]+)"', text))
    domains = QUERY_MEDIA_DOMAINS["twitch"]
    return bool(urls) and all(
        PreviewProxy.valid(url) and urlsplit(url).scheme == "https"
        and any((urlsplit(url).hostname or "") == domain
                or (urlsplit(url).hostname or "").endswith("." + domain) for domain in domains)
        for url in urls
    )


class TwitchProxyAdapter(HTTPAdapter):
    """Relay only live Usher GET requests, never API, CDN or cookie requests."""

    def __init__(self, auth_token: str = ""):
        super().__init__()
        self.auth_token = auth_token if re.fullmatch(r"[A-Za-z0-9_-]{1,512}", auth_token) else ""

    def send(self, request, **kwargs):
        parts = urlsplit(request.url)
        if (request.method != "GET" or parts.scheme != "https"
                or parts.hostname != "usher.ttvnw.net" or parts.port not in (None, 443)
                or parts.username or parts.password
                or not re.fullmatch(r"/api/v2/channel/hls/[A-Za-z0-9_]{1,25}\.m3u8", parts.path)):
            return super().send(request, **kwargs)

        # A separate session prevents account cookies, headers and query hooks
        # from being copied to the proxy. Redirects are never followed.
        with requests.Session() as transport:
            for proxy in PROXY_SERVERS:
                proxy_url = proxy + request.url
                if self.auth_token:
                    proxy_url += ("&" if parts.query else "?") + urlencode({"auth": self.auth_token})
                try:
                    with transport.get(
                        proxy_url, timeout=12, allow_redirects=False,
                        headers={"Accept": "application/vnd.apple.mpegurl"},
                    ) as response:
                        text = response.text
                        if response.status_code != 200 or not _valid_manifest(text, self.auth_token):
                            logger.warning("Twitch 프록시 응답을 사용할 수 없습니다: %s · HTTP %s",
                                           urlsplit(proxy).hostname, response.status_code)
                            continue
                        # Do not expose the authenticated proxy URL or accept
                        # proxy Set-Cookie headers in Streamlink's session.
                        result = requests.Response()
                        result.status_code = 200
                        result._content = text.encode("utf-8")
                        result.encoding = "utf-8"
                        result.url = request.url
                        result.request = request
                        result.headers["Content-Type"] = "application/vnd.apple.mpegurl"
                        logger.info("Twitch 프록시 재생목록 준비 완료: %s", urlsplit(proxy).hostname)
                        return result
                except requests.RequestException:
                    logger.warning("Twitch 프록시 연결 실패: %s", urlsplit(proxy).hostname)
                finally:
                    transport.cookies.clear()
        logger.warning("Twitch 프록시를 사용할 수 없어 직접 연결로 복구합니다.")
        return super().send(request, **kwargs)


def configure_twitch_proxy(session, auth_token: str = "") -> None:
    from app.core.config import get_settings
    if get_settings().twitch_proxy_enabled:
        session.http.mount("https://usher.ttvnw.net/", TwitchProxyAdapter(auth_token))
