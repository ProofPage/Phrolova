"""CIME public router adapter, adapted from recordWEB's observed HLS schema.

Network metadata and playlist selection are independent of recording processes.
Only real manifest dimensions become quality options; cookies are borrowed only
after a permission response and remain scoped to the requested host.
"""
from __future__ import annotations

import html
import json
import re
import time
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit

import httpx

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
    if (quality.lower() == 'best' or height and int(height[1]) > 1080) and playback.get("canWatchUhd"):
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


class CimeLiveEngine:
    """Resolve CIME live metadata without starting or stopping recording."""

    def __init__(self) -> None:
        self._metadata_cache: dict[str, tuple[float, dict, dict, bool]] = {}

    async def _request(self, url: str, *, referer: str = CIME_ORIGIN + "/") -> tuple[httpx.Response, dict[str, str]]:
        from app.engine.platform_auth import (get_platform_cookies, platform_cookie_jar, platform_cookie_status,
                                               PlatformAuthenticationError)
        headers = cime_headers(referer)
        # Explicitly isolated sessions prevent a shared HTTP client's cookie jar
        # from turning the first public request into an authenticated request.
        async with httpx.AsyncClient(timeout=12.0, headers=headers, follow_redirects=True) as client:
            response = await client.get(url)
        cookies: dict[str, str] = {}
        denied = response.status_code in (401, 403)
        if not denied and response.status_code < 400 and "json" in response.headers.get("content-type", ""):
            try:
                body = extract_cime_body_data(response.json())
                denied = permission_required(body, extract_cime_live(body))
            except ValueError:
                pass
        if denied:
            cookies = get_platform_cookies("cime", url)
            if not cookies:
                raise PlatformAuthenticationError("cime", expired=platform_cookie_status('cime')['expired'])
            async with httpx.AsyncClient(timeout=12.0, headers=headers, cookies=platform_cookie_jar("cime"),
                                         follow_redirects=True) as client:
                response = await client.get(url)
            if response.status_code in (401, 403):
                raise PlatformAuthenticationError("cime", permission_denied=True)
        if response.status_code >= 400 and response.status_code != 404:
            raise RuntimeError(f"씨미 정보를 가져오지 못했습니다. (HTTP {response.status_code})")
        return response, cookies

    async def _live_data(self, channel_id: str) -> tuple[dict, dict, bool]:
        slug = normalize_cime_channel_id(channel_id)
        cached = self._metadata_cache.get(slug)
        if cached and time.monotonic() - cached[0] < 8.0:
            return cached[1], cached[2], cached[3]
        for path in (f"/json/@{slug}/live", f"/json/@{slug}", f"/@{slug}/live"):
            response, cookies = await self._request(CIME_ORIGIN + path)
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

    async def _master(self, channel_id: str, quality: str = "best") -> tuple[str, bool]:
        _, live, authenticated = await self._live_data(channel_id)
        url = playback_url(live, quality=quality)
        if str(live.get("state") or "").upper() not in {"ACTIVE", "OPEN", "LIVE"} or not url:
            raise ValueError("씨미 채널이 오프라인입니다.")
        return url, authenticated

    async def get_preview_url(self, channel_id: str) -> str:
        url, _ = await self._master(channel_id)
        # Preserve original master, including separate audio groups. Hls.js
        # selects a measured 1080p level using the shared preview policy.
        return url

    async def get_qualities(self, channel_id: str) -> list[dict]:
        url, _ = await self._master(channel_id)
        response, _ = await self._request(url, referer=self.get_stream_url(channel_id))
        if response.status_code == 404:
            raise ValueError("씨미 스트림을 찾을 수 없습니다.")
        return cime_quality_options(parse_cime_variants(str(response.url), response.text))

    async def resolve_stream_spec(self, channel_id: str, quality: str = "best") -> dict:
        from app.engine.platform_auth import get_platform_cookies
        master, authenticated = await self._master(channel_id, quality)
        response, cookies = await self._request(master, referer=self.get_stream_url(channel_id))
        if response.status_code == 404 or "#EXTM3U" not in response.text:
            raise ValueError("씨미 재생 목록을 찾을 수 없습니다.")
        if "#EXT-X-ENDLIST" in response.text and "#EXT-X-STREAM-INF" not in response.text:
            raise ValueError("씨미 방송이 종료되었습니다.")
        variants = parse_cime_variants(str(response.url), response.text)
        selected = select_cime_variant(variants, quality)
        external_audio = bool(selected and selected.get("external_audio"))
        url = str(response.url) if external_audio or not selected else selected["url"]
        # Credentials sent to ci.me are never copied to an unrelated CDN.
        stream_cookies = get_platform_cookies("cime", url) if authenticated or cookies else {}
        headers = cime_headers(self.get_stream_url(channel_id))
        cookie_header = "; ".join(f"{k}={v}" for k, v in stream_cookies.items()) or None
        return {"url": url, "headers": headers, "cookies": cookie_header,
                "video_index": selected["video_index"] if external_audio else None,
                "width": selected["width"] if selected else None,
                "height": selected["height"] if selected else None,
                "fps": selected["fps"] if selected else None}

    async def resolve_stream(self, channel_id: str, quality: str = "best") -> tuple[str, dict[str, str], str | None]:
        spec = await self.resolve_stream_spec(channel_id, quality)
        return spec["url"], spec["headers"], spec["cookies"]
