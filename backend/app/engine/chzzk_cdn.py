"""Per-download CHZZK VOD CDN routing; no global yt-dlp patches or fallback."""
from __future__ import annotations

from urllib.parse import parse_qsl, urlsplit, urlunsplit

import yt_dlp
from yt_dlp.networking import Request

DEFAULT_HOST = "ex-nlive-slitvod-streaming.navercdn.com"
AKAMAI_HOST = "light-slit.akamaized.net"


def is_chzzk_media_url(url: str) -> bool:
    try:
        return (urlsplit(url).hostname or "").lower() == "chzzk.naver.com"
    except ValueError:
        return False


def is_chzzk_vod_url(url: str) -> bool:
    # Live/timemachine/clip routes remain outside this VOD-only option.
    try:
        path = urlsplit(url).path.rstrip("/")
        return is_chzzk_media_url(url) and path.startswith("/video/") and path[7:].isdigit()
    except ValueError:
        return False


def akamai_url(url: str) -> str:
    """Map only the known VOD origin. Preserve escaped path/query bytes.

    Other CDNs, userinfo, custom ports and recognizable host-bound signatures
    are not interchangeable and are left unchanged. Availability is not assumed:
    errors from the selected origin propagate through the existing retry policy.
    """
    try:
        parts = urlsplit(url)
        if (parts.scheme not in ("http", "https")
                or (parts.hostname or "").lower() != DEFAULT_HOST
                or parts.username is not None or parts.password is not None
                or parts.port not in (None, 80 if parts.scheme == "http" else 443)
                or not parts.path.startswith("/")):
            return url
        keys = {key.lower() for key, _ in parse_qsl(parts.query)}
        if keys.intersection({"signature", "policy", "key-pair-id"}) or any(
            key.startswith("x-amz-") or key.startswith("x-goog-") for key in keys
        ):
            return url
    except ValueError:
        return url
    return urlunsplit(("https", AKAMAI_HOST, parts.path, parts.query, parts.fragment))


class ChzzkCdnYoutubeDL(yt_dlp.YoutubeDL):
    """Route manifest, fragment, initialization, byte-range and HLS key requests.

    Relative URLs are resolved by yt-dlp as usual. Absolute origins embedded in
    MPD/M3U8 still pass through urlopen, unlike rewriting only format metadata.
    Cookie jars remain scoped to their original domains.
    """

    def __init__(self, *args, cdn: str = "default", **kwargs):
        if cdn not in ("default", "akamai"):
            raise ValueError("지원하지 않는 CDN입니다.")
        self.cdn = cdn
        self.cdn_applied = False
        self.cdn_unsupported = False
        super().__init__(*args, **kwargs)

    def urlopen(self, request):
        if self.cdn == "default":
            return super().urlopen(request)
        if isinstance(request, str):
            request = Request(request)
        if isinstance(request, Request):
            original = request.url
            mapped = akamai_url(original)
            if mapped != original and request.method in ("GET", "HEAD"):
                request = request.copy()
                request.url = mapped
                # Host-bound credentials must never be carried to another CDN.
                for name in ("Host", "Cookie", "Authorization", "Proxy-Authorization", "X-CSRF-Token"):
                    request.headers.pop(name, None)
                self.cdn_applied = True
            else:
                try:
                    host = (urlsplit(original).hostname or "").lower()
                except ValueError:
                    host = ""
                if host == DEFAULT_HOST:
                    self.cdn_unsupported = True
                elif host == AKAMAI_HOST:
                    self.cdn_applied = True
        return super().urlopen(request)

    def process_info(self, info_dict):
        # Native HLS can delegate unsupported playlists to FFmpeg, whose HTTP
        # requests bypass urlopen. Detect that case before starting media output.
        if self.cdn == "akamai":
            from yt_dlp.downloader.hls import HlsFD
            for fmt in info_dict.get("requested_formats") or [info_dict]:
                if fmt.get("protocol") not in ("m3u8", "m3u8_native"):
                    continue
                url = fmt.get("url", "")
                if (urlsplit(url).hostname or "").lower() not in (DEFAULT_HOST, AKAMAI_HOST):
                    continue
                manifest = fmt.get("hls_media_playlist_data")
                if not manifest:
                    with self.urlopen(Request(url, headers=fmt.get("http_headers", {}))) as response:
                        manifest = response.read().decode("utf-8-sig")
                if not HlsFD.can_download(manifest, fmt):
                    raise yt_dlp.utils.DownloadError(
                        "Akamai 선택은 이 HLS 형식을 지원하지 않습니다. 기본 CDN으로 새 작업을 시작하세요."
                    )
                # Reuse this request; the native downloader accepts cached data.
                fmt["hls_media_playlist_data"] = manifest
        return super().process_info(info_dict)
