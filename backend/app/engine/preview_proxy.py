"""Bounded, opaque HLS assets: signed upstream URLs stay on the server."""

import asyncio
import re
import time
import uuid
from urllib.parse import urljoin, urlsplit, urlencode
import ipaddress
import httpx
from app.core.http import USER_AGENT
from app.engine.preview_transport import preview_ca_bundle


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
    def allowed(url, hosts):
        host = urlsplit(url).hostname or ""
        trusted = (
            "navercdn.com",
            "pstatic.net",
            "akamaized.net",
            "googlevideo.com",
            "youtube.com",
            "live-video.net",
            "ci.me",
            "sooplive.com",
            "sooplive.co.kr",
        )
        return PreviewProxy.valid(url) and (
            host in hosts
            or any(host == domain or host.endswith("." + domain) for domain in trusted)
        )

    def rewrite(self, node, body):
        def replace(uri):
            url = urljoin(node["url"], uri)
            if not self.allowed(url, node["hosts"]):
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
            if line.strip().startswith("#"):
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
        node = self.nodes.get(token)
        if not node or time.monotonic() - node["time"] > 120:
            raise KeyError("expired")
        node["time"] = time.monotonic()
        headers = {"User-Agent": USER_AGENT}
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
                verify=preview_ca_bundle(), timeout=15, follow_redirects=False
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
                            if not self.allowed(url, node["hosts"]):
                                raise ValueError("허용되지 않은 CDN 이동입니다.")
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
                        extra = {
                            k: response.headers[k]
                            for k in ("content-range", "accept-ranges")
                            if k in response.headers
                        }
                        return bytes(data), kind, response.status_code, extra
                raise ValueError("미리보기 CDN 이동 횟수를 초과했습니다.")


preview_proxy = PreviewProxy()
