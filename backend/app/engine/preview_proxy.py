"""Bounded, opaque HLS assets: signed upstream URLs stay on the server."""

import asyncio
import logging
import re
import time
import uuid
from urllib.parse import urljoin, urlsplit, urlencode
import ipaddress
import httpx
from app.core.http import USER_AGENT
from app.engine.platform_auth import platform_cookie_jar
from app.engine.preview_transport import preview_ca_bundle, SafeMediaLogFilter

# HTTPX emits the complete upstream URL at INFO level. Apply the same
# redaction as the Streamlink preview transport before handlers receive it.
_http_logger = logging.getLogger("httpx")
if not any(isinstance(item, SafeMediaLogFilter) for item in _http_logger.filters):
    _http_logger.addFilter(SafeMediaLogFilter())


def trim_live_playlist(body: str, max_segments: int = 6) -> str:
    """Trim large live or low-latency time-shift media playlists for preview efficiency.
    Retains the latest segments, adjusts EXT-X-MEDIA-SEQUENCE, and strips sub-second
    part/preload hints so low-latency polling does not starve the proxy semaphore."""
    if '#EXTINF:' not in body:
        return body

    lines = body.splitlines()
    header_lines: list[str] = []
    segments: list[list[str]] = []
    current_segment: list[str] = []
    in_segments = False
    media_sequence = 0
    seq_index = -1

    for line in lines:
        stripped = line.strip()
        if stripped.startswith('#EXT-X-MEDIA-SEQUENCE:'):
            try:
                media_sequence = int(stripped.split(':', 1)[1])
            except ValueError:
                pass
            seq_index = len(header_lines)
            header_lines.append(line)
            continue
        if stripped.startswith(('#EXT-X-SERVER-CONTROL:', '#EXT-X-PART-INF:', '#EXT-X-PART:')):
            continue
        if stripped.startswith(('#EXT-X-PRELOAD-HINT:', '#EXT-X-RENDITION-REPORT:')):
            continue

        if stripped.startswith('#EXTINF:'):
            in_segments = True
            if current_segment:
                segments.append(current_segment)
                current_segment = []
            current_segment.append(line)
        elif in_segments:
            if stripped and not stripped.startswith('#'):
                current_segment.append(line)
                segments.append(current_segment)
                current_segment = []
            elif stripped.startswith('#EXT-X-DISCONTINUITY'):
                current_segment.append(line)
            elif stripped.startswith('#EXT-X-KEY:') or stripped.startswith('#EXT-X-MAP:'):
                current_segment.append(line)
            elif stripped:
                current_segment.append(line)
        else:
            header_lines.append(line)

    if current_segment:
        segments.append(current_segment)

    if len(segments) <= max_segments:
        # Keep intact except stripped part/preload hints
        result_lines = list(header_lines)
        for seg in segments:
            result_lines.extend(seg)
        return '\n'.join(result_lines) + '\n'

    dropped = len(segments) - max_segments
    kept_segments = segments[-max_segments:]
    new_sequence = media_sequence + dropped

    if seq_index >= 0:
        header_lines[seq_index] = f'#EXT-X-MEDIA-SEQUENCE:{new_sequence}'
    else:
        # Insert after #EXTM3U
        insert_at = 1 if header_lines and header_lines[0].startswith('#EXTM3U') else 0
        header_lines.insert(insert_at, f'#EXT-X-MEDIA-SEQUENCE:{new_sequence}')

    result_lines = list(header_lines)
    for seg in kept_segments:
        result_lines.extend(seg)
    return '\n'.join(result_lines) + '\n'


class PreviewProxy:
    def __init__(self):
        self.nodes = {}
        self.limit = asyncio.Semaphore(4)

    @staticmethod
    def valid(url):
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        try:
            if not ipaddress.ip_address(host).is_global:
                return False
        except ValueError:
            if "." not in host or host.endswith((".local", ".localhost")):
                return False
        return (
            parsed.scheme == "https"
            and host
            and not parsed.username
            and not parsed.password
        )

    def register(self, key, platform, url, hosts=None):
        if not self.valid(url):
            raise ValueError("미리보기 주소가 올바르지 않습니다.")
        now = time.monotonic()
        for token, node in list(self.nodes.items()):
            if now - node["time"] > 120:
                self.nodes.pop(token, None)
        while len(self.nodes) >= 2048:
            self.nodes.pop(next(iter(self.nodes)))
        hosts = hosts or {urlsplit(url).hostname}
        for token, node in self.nodes.items():
            if node["key"] == key and node["url"] == url:
                node["time"] = now
                return token
        token = uuid.uuid4().hex
        self.nodes[token] = dict(
            key=key, platform=platform, url=url, hosts=hosts, time=now
        )
        return token

    @staticmethod
    def allowed(url, hosts, platform=None):
        host = urlsplit(url).hostname or ""
        trusted = (
            "navercdn.com",
            "pstatic.net",
            "akamaized.net",
            "googlevideo.com",
            "youtube.com",
            "live-video.net",
            "ci.me",
        )
        # Twitch 재생 목록과 영상 조각은 서로 다른 ttvnw.net 호스트를 쓴다.
        # 다른 플랫폼의 미리보기까지 이 CDN을 허용하지 않도록 범위를 제한한다.
        if platform == "twitch":
            trusted += ("ttvnw.net",)
        if platform == "pandalive":
            trusted = ("pandalive.co.kr", "live-video.net")
        if platform == "rplay":
            from app.engine.rplay_live import media_allowed
            return PreviewProxy.valid(url) and media_allowed(url)
        if platform == "popkontv":
            trusted = ("live-popkontv.hscdn.com", "vod2.popkontv.hscdn.com")
        if platform == "bilibili":
            trusted += ("bilivideo.com", "bilivideo.cn", "biliapi.net")
        if platform == "tiktok":
            trusted += ("tiktokcdn.com", "byteoversea.com", "ibytedtos.com", "tiktokv.com")
        return PreviewProxy.valid(url) and (
            host in hosts
            or any(host == domain or host.endswith("." + domain) for domain in trusted)
        )

    def rewrite(self, node, body):
        body = trim_live_playlist(body)

        def replace(uri):
            url = urljoin(node["url"], uri)
            if not self.allowed(url, node["hosts"], node["platform"]):
                raise ValueError("미리보기 CDN 주소가 허용되지 않습니다.")
            token = self.register(node["key"], node["platform"], url, node["hosts"])
            suffix = urlsplit(url).path.rsplit(".", 1)[-1].lower()
            extension = (
                suffix
                if suffix in ("m3u8", "ts", "m4s", "mp4", "aac", "key")
                else "bin"
            )
            return f"/api/stream/preview-media/{token}/asset.{extension}"

        lines = []
        for line in body.splitlines():
            if node["platform"] == "twitch":
                if (line.startswith("#EXT-X-DATERANGE:")
                        and ('X-TV-TWITCH-TRIGGER-URL="' in line
                             or 'twitch-stitched-ad' in line
                             or 'twitch-ad' in line
                             or 'stitched-ad' in line
                             or 'SCTE35' in line)):
                    # TTV-AB 23.0.2: 불필요한 광고 트리거 및 광고 메타데이터 태그를 필터링하여 플레이어 정체 방지
                    continue
                if line.startswith("#EXT-X-CUE-OUT"):
                    continue
            if line.startswith("#EXT-X-PREFETCH:"):
                # AWS IVS 등의 저지연 HLS도 미리 읽을 영상 주소를 프록시로 전달한다.
                line = "#EXT-X-PREFETCH:" + replace(line.split(":", 1)[1].strip())
            elif node["platform"] == "twitch" and line.startswith("#EXT-X-TWITCH-PREFETCH:"):
                # Twitch 전용 태그에도 서명된 영상 주소가 들어가므로 브라우저에 노출하지 않는다.
                line = "#EXT-X-TWITCH-PREFETCH:" + replace(line.split(":", 1)[1].strip())
            elif line.strip().startswith("#"):
                line = re.sub(
                    r'URI="([^"]+)"',
                    lambda match: 'URI="' + replace(match[1]) + '"',
                    line,
                )
            elif line.strip():
                line = replace(line.strip())
            lines.append(line)
        return "\n".join(lines) + "\n"

    async def fetch(self, token, query=None, range_header=None):
        try:
            return await self._fetch(token, query, range_header)
        except httpx.HTTPStatusError as error:
            node = self.nodes.get(token)
            if error.response.status_code not in (401, 403, 500, 502, 503, 504) or not node or not node.get("resolver"):
                raise
        # Only the registered root playlist can obtain a fresh authorized URL.
        # Segment URLs are never guessed or retried under different credentials.
        async with node["renewal_lock"]:
            url = await node["resolver"]()
            if not self.allowed(url, node["hosts"], node["platform"]):
                raise ValueError("갱신된 미리보기 주소가 허용되지 않습니다.")
            node["url"] = url
        return await self._fetch(token, query, range_header)

    async def _fetch(self, token, query=None, range_header=None):
        node = self.nodes.get(token)
        if not node or time.monotonic() - node["time"] > 120:
            raise KeyError("expired")
        node["time"] = time.monotonic()
        headers = {"User-Agent": USER_AGENT}
        # Browser requests remain same-origin; platform headers and domain-scoped
        # cookies are sent only by the verified server-side media transport.
        origins = {"chzzk": "https://chzzk.naver.com", "cime": "https://ci.me", "kick": "https://kick.com", "twitch": "https://www.twitch.tv", "bilibili": "https://live.bilibili.com", "pandalive": "https://www.pandalive.co.kr", "popkontv": "https://www.popkontv.com", "rplay": "https://rplay.live"}
        origin = origins.get(node["platform"])
        if origin:
            headers.update({"Origin": origin, "Referer": origin + "/"})
        if node["platform"] == "popkontv":
            from app.engine.popkontv import popkontv_live_url
            headers["Referer"] = popkontv_live_url(node["key"].split(":",1)[1])
        if node["platform"] == "rplay":
            from app.engine.rplay_live import live_headers
            headers.update(live_headers(node["key"].split(":",1)[1]))
        if node["platform"] == "pandalive":
            from app.engine.pandalive import pandalive_headers
            headers.update(pandalive_headers(node["key"].split(":",1)[1]))
        if node["platform"] == "bilibili":
            from app.engine.bilibili import bilibili_headers
            headers.update(bilibili_headers(node["key"].split(":",1)[1]))
        if node["platform"] == "tiktok":
            from app.engine.tiktok import tiktok_headers
            headers.update(tiktok_headers(node["key"].split(":",1)[1]))
        if range_header and re.fullmatch(r"bytes=\d+-\d*", range_header):
            headers["Range"] = range_header
        params = {
            k: v
            for k, v in (query or {}).items()
            if k in ("_HLS_msn", "_HLS_part", "_HLS_skip")
            and re.fullmatch(r"\d+|YES|v2", v)
        }
        async with self.limit:
            async with httpx.AsyncClient(
                verify=preview_ca_bundle(), timeout=15, follow_redirects=False,
                cookies=platform_cookie_jar(node["platform"]) if node["platform"] in ("cime", "kick", "twitch", "bilibili", "pandalive", "popkontv", "youtube") else None
            ) as client:
                url = node["url"]
                for _ in range(4):
                    upstream = url + (
                        ("&" if "?" in url else "?") + urlencode(params)
                        if params
                        else ""
                    )
                    async with client.stream(
                        "GET", upstream, headers=headers
                    ) as response:
                        if response.is_redirect:
                            url = urljoin(url, response.headers.get("location", ""))
                            if not self.allowed(url, node["hosts"], node["platform"]):
                                raise ValueError("허용되지 않은 CDN 이동입니다.")
                            continue
                        if response.status_code in (429, 500, 502, 503, 504):
                            if node.get("_last_manifest") and bytes(node["_last_manifest"]).lstrip().startswith(b"#EXTM3U"):
                                return bytes(node["_last_manifest"]), "application/vnd.apple.mpegurl", 200, {}
                            await asyncio.sleep(0.5)
                            continue
                        response.raise_for_status()
                        data = bytearray()
                        async for chunk in response.aiter_bytes():
                            data.extend(chunk)
                            if len(data) > 32 * 1024 * 1024:
                                raise ValueError("미리보기 데이터 제한을 초과했습니다.")
                        kind = response.headers.get(
                            "content-type", "application/octet-stream"
                        )
                        if bytes(data).lstrip().startswith(b"#EXTM3U"):
                            if len(data) > 2 * 1024 * 1024:
                                raise ValueError("재생 목록 제한을 초과했습니다.")
                            data = self.rewrite(
                                {**node, "url": url}, data.decode("utf-8-sig")
                            ).encode()
                            kind = "application/vnd.apple.mpegurl"
                            node["_last_manifest"] = bytes(data)
                        extra = {
                            k: response.headers[k]
                            for k in ("content-range", "accept-ranges")
                            if k in response.headers
                        }
                        return bytes(data), kind, response.status_code, extra
                raise ValueError("미리보기 CDN 이동 횟수를 초과했습니다.")

    async def fetch_stream(self, token):
        node = self.nodes.get(token)
        if not node:
            raise KeyError("expired")
        node["time"] = time.monotonic()
        headers = {"User-Agent": USER_AGENT}
        if node["platform"] == "tiktok":
            from app.engine.tiktok import tiktok_headers
            headers.update(tiktok_headers(node["key"].split(":", 1)[1]))
        elif node["platform"] == "bilibili":
            from app.engine.bilibili import bilibili_headers
            headers.update(bilibili_headers(node["key"].split(":", 1)[1]))

        async with httpx.AsyncClient(
            verify=preview_ca_bundle(), timeout=httpx.Timeout(connect=15.0, read=None, write=15.0, pool=15.0),
            follow_redirects=True,
            cookies=platform_cookie_jar(node["platform"]) if node["platform"] in ("cime", "kick", "twitch", "bilibili", "pandalive", "popkontv", "youtube") else None
        ) as client:
            async with client.stream("GET", node["url"], headers=headers) as upstream:
                upstream.raise_for_status()
                async for chunk in upstream.aiter_bytes(64 * 1024):
                    node["time"] = time.monotonic()
                    yield chunk


preview_proxy = PreviewProxy()
