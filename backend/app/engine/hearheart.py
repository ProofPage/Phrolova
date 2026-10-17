"""HearHeart (hearheart.com) platform helper and metadata parser."""
from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

from app.core.config import USER_AGENT

HEARHEART_ORIGIN = "https://hearheart.com"
HEARHEART_DOMAINS = ("hearheart.com", "www.hearheart.com")


def canonical_hearheart_video_url(url: str) -> str:
    """Normalize hearheart URL to canonical playlist or play URL."""
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if host not in HEARHEART_DOMAINS:
        raise ValueError("올바른 히어하트 링크를 입력하세요.")
    
    path = parsed.path.rstrip("/")
    match = re.fullmatch(r"/playlist/(?P<playlist_id>\d+)(?:/play/(?P<content_id>\d+))?", path)
    if not match:
        raise ValueError("올바른 히어하트 플레이리스트 또는 재생 링크를 입력하세요.")
    
    clean_path = f"/playlist/{match.group('playlist_id')}"
    if match.group("content_id"):
        clean_path += f"/play/{match.group('content_id')}"
    return urlunsplit(("https", "hearheart.com", clean_path, "", ""))


def parse_hearheart_url(url: str) -> dict[str, str | None]:
    """Parse playlist_id and content_id from hearheart URL."""
    canonical = canonical_hearheart_video_url(url)
    parsed = urlsplit(canonical)
    match = re.fullmatch(r"/playlist/(?P<playlist_id>\d+)(?:/play/(?P<content_id>\d+))?", parsed.path)
    if not match:
        raise ValueError("올바른 히어하트 링크를 입력하세요.")
    return {
        "url": canonical,
        "playlist_id": match.group("playlist_id"),
        "content_id": match.group("content_id"),
    }


def hearheart_headers(referer: str | None = None) -> dict[str, str]:
    """Standard HTTP headers for hearheart requests."""
    return {
        "User-Agent": USER_AGENT,
        "Origin": HEARHEART_ORIGIN,
        "Referer": referer or HEARHEART_ORIGIN,
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    }
