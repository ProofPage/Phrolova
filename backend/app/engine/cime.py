"""CIME public router adapter, adapted from recordWEB's observed HLS schema.

Network metadata and playlist selection are independent of recording processes.
Only real manifest dimensions become quality options; cookies are borrowed only
after a permission response and remain scoped to the requested host.
"""
from __future__ import annotations

import asyncio
import html
import json
import math
import re
import threading
import time
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit

import httpx
from requests.auth import AuthBase
from requests.cookies import create_cookie

from app.core.http import USER_AGENT
from app.core.logger import logger as app_logger
from app.engine.base import LiveStatus

logger = app_logger.getChild("cime")
CIME_ORIGIN = "https://ci.me"
_SLUG = r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}"
_ATTRS = re.compile(r'([A-Z0-9-]+)=("[^"\r\n]*"|[^,\r\n]+)', re.I)


def normalize_cime_channel_id(value: str) -> str:
    raw = str(value or "").strip()
    if "://" in raw:
        try:
            parts = urlsplit(raw)
            if (parts.scheme not in ("https", "http")
                    or (parts.hostname or "").lower() not in ("ci.me", "www.ci.me")
                    or parts.username is not None or parts.password is not None
                    or parts.port not in (None, 80 if parts.scheme == "http" else 443)):
                raise ValueError
            match = re.fullmatch(rf"/@({_SLUG})(?:/live)?/?", unquote(parts.path))
            if not match:
                raise ValueError
            raw = match.group(1)
        except ValueError:
            raise ValueError("올바른 씨미 채널 ID 또는 채널 링크를 입력하세요.") from None
    else:
        raw = raw.removeprefix("@")
    if not re.fullmatch(_SLUG, raw):
        raise ValueError("올바른 씨미 채널 ID 또는 채널 링크를 입력하세요.")
    return raw


def parse_cime_video_url(value: str) -> dict[str, str] | None:
    """Accept verified watch pages, never arbitrary URLs containing ci.me."""
    try:
        parts = urlsplit(str(value or "").strip())
        if (parts.scheme not in ("https", "http")
                or (parts.hostname or "").lower() not in ("ci.me", "www.ci.me")
                or parts.username is not None or parts.password is not None
                or parts.port not in (None, 80 if parts.scheme == "http" else 443)):
            return None
        path = unquote(parts.path).rstrip("/")
        match = re.fullmatch(rf"/@({_SLUG})/vods/(\d+)", path)
        if match:
            slug, video_id = match.groups()
            return {"kind": "vod", "slug": slug, "id": video_id,
                    "url": f"{CIME_ORIGIN}/@{slug}/vods/{video_id}"}
        match = re.fullmatch(r"/clips/(\d+)", path)
        if match:
            return {"kind": "clip", "slug": "", "id": match.group(1),
                    "url": f"{CIME_ORIGIN}/clips/{match.group(1)}"}
    except ValueError:
        pass
    return None


def is_cime_video_url(value: str) -> bool:
    return parse_cime_video_url(value) is not None


def _walk_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _walk_dicts(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_dicts(item)


def extract_cime_body_data(value: str | dict) -> dict:
    if isinstance(value, dict):
        for item in _walk_dicts(value):
            if isinstance(item.get("bodyData"), dict):
                return item["bodyData"]
        return {}
    text = html.unescape(str(value or "")).replace(r"\/", "/").replace(r"\u0026", "&")
    try:
        return extract_cime_body_data(json.loads(text))
    except (ValueError, TypeError):
        pass
    # The fallback parses complete JSON objects, avoiding regex extraction of
    # playback URLs from unrelated recommendations or Javascript bundles.
    decoder = json.JSONDecoder()
    for match in re.finditer(r'\{\s*"bodyData"\s*:', text):
        try:
            item, _ = decoder.raw_decode(text[match.start():])
            return extract_cime_body_data(item)
        except ValueError:
            continue
    return {}


def extract_cime_live(body: dict) -> dict:
    live = body.get("live")
    if isinstance(live, dict):
        return live
    home = body.get("homeData")
    if isinstance(home, dict) and isinstance(home.get("live"), dict):
        return home["live"]
    return {}


def cime_headers(referer: str = CIME_ORIGIN + "/") -> dict[str, str]:
    return {"User-Agent": USER_AGENT, "Referer": referer, "Origin": CIME_ORIGIN,
            "Accept": "application/json, application/vnd.apple.mpegurl, */*"}


def _cime_signed_cookies(resource_id: str, *, kind: str, referer: str) -> tuple[dict[str, str], float]:
    from app.engine.platform_auth import PlatformAuthenticationError, platform_cookie_jar, platform_cookie_status
    headers = cime_headers(referer)
    kind = kind.upper()
    payload = {"type": kind, "channelId" if kind == "UHD" else "videoId": str(resource_id)}
    with httpx.Client(timeout=10.0, headers=headers, cookies=platform_cookie_jar("cime"), follow_redirects=False) as client:
        response = client.post(f"{CIME_ORIGIN}/api/app/streams/sign-cookie", json=payload)
    if response.status_code in (401, 403):
        status = platform_cookie_status("cime")
        raise PlatformAuthenticationError("cime", expired=status["expired"], permission_denied=status["valid"])
    response.raise_for_status()
    cookies = {name: value for name, value in response.cookies.items() if name.startswith("CloudFront-")}
    if any(any(c in value for c in "\r\n;") for value in cookies.values()):
        raise ValueError("씨미 재생 인증 정보 형식이 올바르지 않습니다.")
    refresh_after = 0.0
    if kind == "UHD":
        body = response.json()
        data = body.get("data") or {}
        if body.get("code") != 200 or not all(
            cookies.get(name) for name in ("CloudFront-Policy", "CloudFront-Signature", "CloudFront-Key-Pair-Id")
        ):
            raise ValueError("씨미 UHD 재생 인증 정보를 받지 못했습니다.")
        refresh_after, ttl = float(data["refreshAfterSec"]), float(data["ttlSec"])
        if not 0 < refresh_after <= ttl or not math.isfinite(ttl):
            raise ValueError("씨미 UHD 재생 인증 유효 시간이 올바르지 않습니다.")
    return cookies, refresh_after


def get_cime_sign_cookie_header(video_id: str, *, kind: str = "VIDEO", referer: str = CIME_ORIGIN + "/") -> str | None:
    """Request CloudFront signed cookies required for CIME VOD and clip playback."""
    try:
        cookies, _ = _cime_signed_cookies(video_id, kind=kind, referer=referer)
        return "; ".join(f"{name}={value}" for name, value in cookies.items()) or None
    except Exception as e:
        from app.engine.platform_auth import redact_media_error
        logger.debug("[CIME] sign-cookie 발급 실패: %s", redact_media_error(e))
        return None


class CimeUhdAuth(AuthBase):
    """Renew official UHD grants without sending account cookies to the media host."""

    def __init__(self, channel_id: str, referer: str) -> None:
        self.channel_id = channel_id
        self.referer = referer
        self._cookies: dict[str, str] = {}
        self._refresh_at = 0.0
        self._lock = threading.Lock()

    @staticmethod
    def _channel_id(url: str) -> str | None:
        try:
            parts = urlsplit(url)
            match = re.match(r"/uhd/([0-9]+)/", parts.path)
            if (parts.scheme == "https" and parts.hostname == "view.ci.me" and parts.port in (None, 443)
                    and not parts.username and not parts.password and not any(c in url for c in "\r\n\\")
                    and match):
                return match[1]
        except ValueError:
            pass
        return None

    @classmethod
    def for_url(cls, url: str, referer: str) -> CimeUhdAuth | None:
        channel_id = cls._channel_id(url)
        return cls(channel_id, referer) if channel_id else None

    def matches(self, url: str) -> bool:
        return self._channel_id(url) == self.channel_id

    def cookie_values(self, url: str) -> dict[str, str]:
        if not self.matches(url):
            return {}
        with self._lock:
            if not self._cookies or time.monotonic() >= self._refresh_at:
                cookies, refresh_after = _cime_signed_cookies(self.channel_id, kind="UHD", referer=self.referer)
                self._cookies = cookies
                self._refresh_at = time.monotonic() + refresh_after
            return dict(self._cookies)

    def cookie_jar(self, url: str) -> httpx.Cookies:
        jar = httpx.Cookies()
        for name, value in self.cookie_values(url).items():
            jar.jar.set_cookie(create_cookie(name, value, domain="view.ci.me",
                                            path=f"/uhd/{self.channel_id}/", secure=True))
        return jar

    def __call__(self, request):
        if self.matches(request.url):
            request.headers["Cookie"] = "; ".join(
                f"{name}={value}" for name, value in self.cookie_values(request.url).items()
            )
        return request


def _http_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value or any(c in value for c in "\r\n"):
        return None
    try:
        parts = urlsplit(value)
        if parts.scheme in ("http", "https") and parts.hostname and parts.username is None:
            return value
    except ValueError:
        pass
    return None


def playback_url(item: dict, *, quality: str = "best") -> str | None:
    playback = item.get("playback") if isinstance(item.get("playback"), dict) else {}
    height = re.match(r'(\d+)p', quality.lower())
    if quality.lower() == 'best' or (height and int(height[1]) > 1080):
        uhd = _http_url(playback.get("urlUhd"))
        if uhd:
            return uhd
    return _http_url(item.get("playbackUrl")) or _http_url(playback.get("url"))


def permission_required(body: dict, item: dict | None = None) -> bool:
    if body.get("isAdultRestricted") is True or body.get("statusCode") in (401, 403):
        return True
    item = item or {}
    # A non-null access descriptor alone is not denial: an entitled account
    # may receive it together with a usable playback URL.
    return bool(item.get("viewAccess")) and not playback_url(item)


def parse_cime_variants(master_url: str, playlist: str) -> list[dict[str, Any]]:
    """Read complete attributes and associate each with its immediate URI."""
    result: list[dict[str, Any]] = []
    pending: dict[str, str] | None = None
    audio_groups = set()
    for line in str(playlist or "").splitlines():
        line = line.strip()
        if line.startswith("#EXT-X-MEDIA:"):
            attrs = {k.upper(): v.strip('"') for k, v in _ATTRS.findall(line.split(":", 1)[1])}
            if attrs.get("TYPE") == "AUDIO" and attrs.get("URI"):
                audio_groups.add(attrs.get("GROUP-ID"))
        if line.startswith("#EXT-X-STREAM-INF:"):
            pending = {k.upper(): v.strip('"') for k, v in _ATTRS.findall(line.split(":", 1)[1])}
            continue
        if not line or line.startswith("#"):
            continue
        if pending is None:
            continue
        resolution = re.fullmatch(r"(\d+)[xX](\d+)", pending.get("RESOLUTION", ""))
        width, height = (int(n) for n in resolution.groups()) if resolution else (0, 0)
        try:
            bandwidth = int(pending.get("AVERAGE-BANDWIDTH") or pending.get("BANDWIDTH") or 0)
            fps = float(pending.get("FRAME-RATE") or 0)
        except ValueError:
            bandwidth, fps = 0, 0.0
        url = _http_url(urljoin(master_url, line))
        if url:
            result.append({"url": url, "width": width, "height": height,
                           "bandwidth": bandwidth, "fps": fps,
                           "audio_group": pending.get("AUDIO"), "video_index": len(result)})
        pending = None
    for item in result:
        item["external_audio"] = item.get("audio_group") in audio_groups
    return result


def select_cime_variant(variants: list[dict], quality: str = "best") -> dict | None:
    if not variants:
        return None
    order = lambda v: (v.get("height") or 0, v.get("width") or 0,
                       v.get("fps") or 0, v.get("bandwidth") or 0)
    quality = str(quality or "best").lower()
    if quality == "worst":
        return min(variants, key=order)
    target = re.fullmatch(r"(\d+)p(\d+(?:\.\d+)?)?", quality)
    if target:
        height = int(target.group(1))
        fps = float(target.group(2)) if target.group(2) else None
        exact = [v for v in variants if v.get("height") == height and
                 (fps is None or abs((v.get("fps") or 0) - fps) < 0.2)]
        if exact:
            return max(exact, key=order)
        lower = [v for v in variants if 0 < (v.get("height") or 0) <= height]
        return max(lower, key=order) if lower else min(variants, key=order)
    return max(variants, key=order)


def cime_quality_options(variants: list[dict]) -> list[dict]:
    options = []
    seen = set()
    for variant in sorted(variants, key=lambda v: (v["height"], v["fps"], v["bandwidth"]), reverse=True):
        height, fps = variant["height"], variant["fps"]
        if height <= 0:
            continue
        suffix = f"{fps:g}" if fps > 0 else ""
        value = f"{height}p{suffix}"
        if value in seen:
            continue
        seen.add(value)
        options.append({"value": value, "label": value, "width": variant["width"],
                        "height": height, "fps": fps or None, "bitrate": variant["bandwidth"] or None})
    return options


def cime_init_dimensions(data: bytes) -> tuple[int, int]:
    """Read the video track's actual 16.16 dimensions from a bounded fMP4 init."""
    from app.engine.native_clock import boxes

    for kind, movie in boxes(data):
        if kind != b"moov":
            continue
        for kind, track in boxes(movie):
            if kind != b"trak":
                continue
            parts = dict(boxes(track))
            media = dict(boxes(parts.get(b"mdia", b"")))
            header = parts.get(b"tkhd", b"")
            if media.get(b"hdlr", b"")[8:12] != b"vide" or not header:
                continue
            required = {0: 84, 1: 96}.get(header[0])
            if required is None or len(header) < required:
                continue
            width = int.from_bytes(header[-8:-4], "big") >> 16
            height = int.from_bytes(header[-4:], "big") >> 16
            if width > 0 and height > 0:
                return width, height
    raise ValueError("씨미 스트림의 실제 해상도를 확인하지 못했습니다.")


class CimeLiveEngine:
    """Resolve CIME live metadata without starting or stopping recording."""

    def __init__(self) -> None:
        self._metadata_cache: dict[str, tuple[float, dict, dict, bool]] = {}
        self._uhd_auth: dict[str, CimeUhdAuth] = {}

    async def _request(self, url: str, *, referer: str = CIME_ORIGIN + "/", authenticated: bool = False,
                       uhd_auth: CimeUhdAuth | None = None, max_bytes: int | None = None) -> tuple[httpx.Response, dict[str, str]]:
        from app.engine.platform_auth import (get_platform_cookies, platform_cookie_jar, platform_cookie_status,
                                               PlatformAuthenticationError)
        headers = cime_headers(referer)
        cookies = get_platform_cookies("cime", url) if authenticated else {}
        jar = platform_cookie_jar("cime") if authenticated else None
        if uhd_auth is not None:
            if not uhd_auth.matches(url):
                raise ValueError("씨미 UHD 재생 주소의 범위가 올바르지 않습니다.")
            jar = await asyncio.to_thread(uhd_auth.cookie_jar, url)
            cookies = dict(jar.items())

        async def fetch(cookie_jar):
            async with httpx.AsyncClient(timeout=12.0, headers=headers, cookies=cookie_jar,
                                         follow_redirects=True) as client:
                if max_bytes is None:
                    return await client.get(url)
                async with client.stream("GET", url) as response:
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(data) + len(chunk) > max_bytes:
                            raise ValueError("씨미 스트림 초기화 정보가 너무 큽니다.")
                        data.extend(chunk)
                    decoded_headers = response.headers.copy()
                    decoded_headers.pop("content-encoding", None)
                    decoded_headers.pop("content-length", None)
                    return httpx.Response(response.status_code, headers=decoded_headers,
                                          content=bytes(data), request=response.request)

        # Explicitly isolated sessions prevent a shared HTTP client's cookie jar
        # from turning the first public request into an authenticated request.
        response = await fetch(jar)
        denied = response.status_code in (401, 403)
        if not denied and response.status_code < 400 and "json" in response.headers.get("content-type", ""):
            try:
                body = extract_cime_body_data(response.json())
                denied = permission_required(body, extract_cime_live(body))
            except ValueError:
                pass
        if denied:
            if uhd_auth is not None or authenticated:
                raise PlatformAuthenticationError("cime", permission_denied=True)
            cookies = get_platform_cookies("cime", url)
            if not cookies:
                raise PlatformAuthenticationError("cime", expired=platform_cookie_status('cime')['expired'])
            response = await fetch(platform_cookie_jar("cime"))
            if response.status_code in (401, 403):
                raise PlatformAuthenticationError("cime", permission_denied=True)
        if response.status_code >= 400 and response.status_code != 404:
            raise RuntimeError(f"씨미 정보를 가져오지 못했습니다. (HTTP {response.status_code})")
        return response, cookies

    async def _live_data(self, channel_id: str, *, authenticated: bool = False) -> tuple[dict, dict, bool]:
        slug = normalize_cime_channel_id(channel_id)
        cached = self._metadata_cache.get(slug)
        if cached and time.monotonic() - cached[0] < 8.0 and (not authenticated or cached[3]):
            return cached[1], cached[2], cached[3]
        for path in (f"/json/@{slug}/live", f"/json/@{slug}", f"/@{slug}/live"):
            response, cookies = await self._request(CIME_ORIGIN + path, authenticated=authenticated)
            if response.status_code == 404:
                continue
            body = extract_cime_body_data(response.text)
            live = extract_cime_live(body)
            if body:
                from app.engine.platform_auth import PlatformAuthenticationError
                if permission_required(body, live):
                    raise PlatformAuthenticationError("cime", permission_denied=bool(cookies))
                # An explicit live:null is a valid offline response, not an
                # instruction to search recommendations for another broadcast.
                if live or "live" in body or "homeData" in body:
                    self._metadata_cache[slug] = (time.monotonic(), body, live, bool(cookies))
                    return body, live, bool(cookies)
        raise RuntimeError('씨미 채널 정보를 가져오지 못했습니다.')

    async def _playback_data(self, channel_id: str) -> tuple[dict, dict, bool]:
        from app.engine.platform_auth import get_platform_cookies
        body, live, authenticated = await self._live_data(channel_id)
        playback = live.get("playback") or {}
        if (playback.get("uhdActive") is True and playback.get("canWatchUhd") is False
                and not authenticated and get_platform_cookies("cime", CIME_ORIGIN + "/")):
            return await self._live_data(channel_id, authenticated=True)
        return body, live, authenticated

    def get_stream_url(self, channel_id: str) -> str:
        return f"{CIME_ORIGIN}/@{normalize_cime_channel_id(channel_id)}/live"

    async def check_live_status(self, channel_id: str) -> LiveStatus:
        slug = normalize_cime_channel_id(channel_id)
        body, live, _ = await self._live_data(slug)
        home = body.get("homeData") if isinstance(body.get("homeData"), dict) else {}
        channel = live.get("channel") or body.get("channel") or home.get("channel") or {}
        if not isinstance(channel, dict): channel = {}
        category = live.get("category") if isinstance(live.get("category"), dict) else {}
        state = str(live.get("state") or "").upper()
        is_live = state in {"ACTIVE", "OPEN", "LIVE"} and bool(playback_url(live))
        try:
            viewers = max(0, int(live.get("curViewerCnt") or 0))
        except (TypeError, ValueError):
            viewers = 0
        tags = [str(t.get("displayName") or t.get("name")) for t in live.get("tags") or []
                if isinstance(t, dict) and (t.get("displayName") or t.get("name"))]
        return LiveStatus(channel_id=slug, is_live=is_live,
                          channel_name=str(channel.get("name") or slug),
                          title=str(live.get("title") or ""), category=str(category.get("name") or ""),
                          viewer_count=viewers, thumbnail_url=_http_url(live.get("imageUrl")) or "",
                          profile_image_url=_http_url(channel.get("imageUrl")) or "", broadcast_tags=tags,
                          live_started_at=live.get('openedAt'))

    async def _master(self, channel_id: str, quality: str = "best") -> tuple[str, bool, dict]:
        from app.engine.platform_auth import PlatformAuthenticationError, platform_cookie_status
        height = re.match(r"(\d+)p", quality.lower())
        wants_uhd = quality.lower() == "best" or bool(height and int(height[1]) > 1080)
        _, live, authenticated = await (self._playback_data(channel_id) if wants_uhd else self._live_data(channel_id))
        url = playback_url(live, quality=quality)
        if str(live.get("state") or "").upper() not in {"ACTIVE", "OPEN", "LIVE"} or not url:
            raise ValueError("씨미 채널이 오프라인입니다.")
        playback = live.get("playback") or {}
        if (height and int(height[1]) > 1080 and playback.get("uhdActive") is True
                and (playback.get("canWatchUhd") is False or not _http_url(playback.get("urlUhd")))):
            raise PlatformAuthenticationError("cime", expired=platform_cookie_status("cime")["expired"],
                                              permission_denied=authenticated)
        return url, authenticated, live

    async def get_preview_url(self, channel_id: str) -> str:
        url, _, _ = await self._master(channel_id, "1080p")
        # Preserve original master, including separate audio groups. Hls.js
        # selects a measured 1080p level using the shared preview policy.
        return url

    async def _playlist(self, channel_id: str, quality: str) -> tuple[httpx.Response, list[dict], dict, bool]:
        master, authenticated, live = await self._master(channel_id, quality)
        referer = self.get_stream_url(channel_id)
        uhd_auth = CimeUhdAuth.for_url(master, referer)
        if uhd_auth is not None:
            uhd_auth = self._uhd_auth.setdefault(uhd_auth.channel_id, uhd_auth)
        response, cookies = await self._request(master, referer=referer, uhd_auth=uhd_auth)
        if response.status_code == 404 or "#EXTM3U" not in response.text:
            raise ValueError("씨미 재생 목록을 찾을 수 없습니다.")
        if "#EXT-X-ENDLIST" in response.text and "#EXT-X-STREAM-INF" not in response.text:
            raise ValueError("씨미 방송이 종료되었습니다.")
        variants = parse_cime_variants(str(response.url), response.text)
        if not variants:
            for line in response.text.splitlines():
                if not line.startswith("#EXT-X-MAP:"):
                    continue
                attrs = {key.upper(): value.strip('"') for key, value in _ATTRS.findall(line.split(":", 1)[1])}
                initial = _http_url(urljoin(str(response.url), attrs.get("URI", "")))
                if not initial or "URI" not in attrs:
                    raise ValueError("씨미 스트림 초기화 주소가 올바르지 않습니다.")
                init_response, _ = await self._request(initial, referer=referer, uhd_auth=uhd_auth, max_bytes=1024 * 1024)
                if init_response.status_code != 200:
                    raise ValueError("씨미 스트림 초기화 정보를 가져오지 못했습니다.")
                width, height = cime_init_dimensions(init_response.content)
                fps = float((live.get("playback") or {}).get("uhdFps") or 0)
                variants = [{"url": str(response.url), "width": width, "height": height, "fps": fps,
                             "bandwidth": 0, "external_audio": False, "video_index": 0}]
                break
        return response, variants, cookies, authenticated

    async def get_qualities(self, channel_id: str) -> list[dict]:
        response, variants, _, _ = await self._playlist(channel_id, "worst")
        _, live, _ = await self._playback_data(channel_id)
        playback = live.get("playback") if isinstance(live.get("playback"), dict) else {}
        uhd_url = _http_url(playback.get("urlUhd"))
        if uhd_url and uhd_url != str(response.url):
            try:
                _, uhd_variants, _, _ = await self._playlist(channel_id, "best")
                variants.extend(uhd_variants)
            except (httpx.HTTPError, ValueError, RuntimeError) as error:
                from app.engine.platform_auth import redact_media_error
                logger.warning("씨미 UHD 화질 확인 실패: %s", redact_media_error(error))
        return cime_quality_options(variants)

    async def resolve_stream_spec(self, channel_id: str, quality: str = "best") -> dict:
        from app.engine.platform_auth import get_platform_cookies
        response, variants, cookies, authenticated = await self._playlist(channel_id, quality)
        selected = select_cime_variant(variants, quality)
        external_audio = bool(selected and selected.get("external_audio"))
        url = str(response.url) if external_audio or not selected else selected["url"]
        # Credentials sent to ci.me are never copied to an unrelated CDN.
        stream_cookies = (cookies if CimeUhdAuth.for_url(url, self.get_stream_url(channel_id)) else
                          get_platform_cookies("cime", url) if authenticated or cookies else {})
        headers = cime_headers(self.get_stream_url(channel_id))
        cookie_header = "; ".join(f"{k}={v}" for k, v in stream_cookies.items()) or None
        return {"url": url, "headers": headers, "cookies": cookie_header,
                "preview_url": selected['url'] if selected else str(response.url),
                "video_index": selected["video_index"] if external_audio else None,
                "width": selected["width"] if selected else None,
                "height": selected["height"] if selected else None,
                "fps": selected["fps"] if selected else None}

    async def resolve_stream(self, channel_id: str, quality: str = "best") -> tuple[str, dict[str, str], str | None]:
        spec = await self.resolve_stream_spec(channel_id, quality)
        return spec["url"], spec["headers"], spec["cookies"]
