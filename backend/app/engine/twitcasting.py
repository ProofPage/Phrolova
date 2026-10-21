"""
Phrolova: TwitCasting (트윗캐스팅) 라이브 엔진
공개 streamserver API 및 Streamlink/HLS 연동을 통해 실시간 라이브를 감지하고 스트림을 매핑한다.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Optional

import httpx

from app.core.logger import get_platform_logger
from app.engine.base import LiveStatus, Platform
from app.engine.recording_errors import RecordingError

log = get_platform_logger("twitcasting", "live")

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
HOSTS = ("twitcasting.tv", "www.twitcasting.tv")


def normalize_twitcasting_channel_id(value: str) -> str:
    """트윗캐스팅 URL 또는 채널 ID를 정규화한다."""
    raw = value.strip()
    if "://" in raw or "twitcasting.tv" in raw:
        if not raw.startswith("http"):
            raw = "https://" + raw
        parsed = urllib.parse.urlsplit(raw)
        host = (parsed.hostname or "").lower()
        if host not in HOSTS:
            raise ValueError("올바른 트윗캐스팅 채널 ID 또는 라이브 링크를 입력하세요.")
        path = parsed.path.strip("/")
        # /channel_id or /channel_id/live or /channel_id/show
        parts = [p for p in path.split("/") if p and p not in ("live", "show", "broadcaster")]
        if not parts:
            raise ValueError("트윗캐스팅 채널 ID를 찾을 수 없습니다.")
        raw = parts[0]
    
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,60}", raw):
        raise ValueError("올바른 트윗캐스팅 채널 ID 또는 라이브 링크를 입력하세요.")
    return raw.lower()


class TwitcastingLiveEngine:
    """트윗캐스팅 라이브 상태 감지 및 스트림 추출 엔진."""

    platform = Platform.TWITCASTING if hasattr(Platform, "TWITCASTING") else "twitcasting"

    def __init__(self):
        self._cache = {}

    def get_stream_url(self, channel_id: str) -> str:
        cid = normalize_twitcasting_channel_id(channel_id)
        return f"https://twitcasting.tv/{cid}"

    async def check_live_status(self, channel_id: str) -> LiveStatus:
        """streamserver.php API를 통해 라이브 방송 상태를 확인한다."""
        cid = normalize_twitcasting_channel_id(channel_id)
        api_url = f"https://twitcasting.tv/streamserver.php?target={cid}&mode=client"
        
        from app.engine.platform_auth import get_platform_cookies
        cookies = get_platform_cookies("twitcasting", api_url)
        headers = {
            "User-Agent": USER_AGENT,
            "Referer": f"https://twitcasting.tv/{cid}",
            "Accept": "application/json, text/plain, */*",
        }

        is_live = False
        movie_id = None
        title = ""
        channel_name = cid
        thumbnail_url = ""

        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                resp = await client.get(api_url, headers=headers, cookies=cookies)
            if resp.status_code == 200:
                data = resp.json()
                movie = data.get("movie") or {}
                movie_id = movie.get("id")
                is_live = bool(movie.get("live"))
        except Exception as e:
            log.debug(f"[{cid}] 트윗캐스팅 streamserver 조회 실패: {e}")

        if not is_live:
            return LiveStatus(
                channel_id=cid,
                is_live=False,
                channel_name=channel_name,
                title="",
                category="TwitCasting",
                viewer_count=0,
                thumbnail_url="",
                profile_image_url="",
            )

        # 라이브 중일 때 추가 메타데이터(제목, 스트리머명) 파싱
        try:
            page_url = f"https://twitcasting.tv/{cid}"
            async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
                page_resp = await client.get(page_url, headers=headers, cookies=cookies)
            if page_resp.status_code == 200:
                html = page_resp.text
                title_match = re.search(r"<title>(.*?)</title>", html)
                if title_match:
                    raw_title = title_match.group(1).strip()
                    # e.g. "ツイキャス公式 (@twitcasting_jp) 's Live - Twitcast"
                    name_match = re.match(r"(.*?)\s*\(@[A-Za-z0-9_.-]+\)", raw_title)
                    if name_match:
                        channel_name = name_match.group(1).strip()
                    title = raw_title
                
                # 방송 제목 탐색 (h2.tw-player-page-title 등)
                h2_match = re.search(r'<h2[^>]*class="[^"]*tw-player-page-title[^"]*"[^>]*>(.*?)</h2>', html, re.DOTALL)
                if h2_match:
                    title = re.sub(r"<[^>]+>", "", h2_match.group(1)).strip() or title
        except Exception:
            pass

        return LiveStatus(
            channel_id=cid,
            is_live=True,
            channel_name=channel_name or cid,
            title=title or f"{channel_name} 라이브 방송",
            category="TwitCasting",
            viewer_count=0,
            thumbnail_url=thumbnail_url,
            profile_image_url=thumbnail_url,
        )

    async def get_qualities(self, channel_id: str) -> list[dict]:
        """스트림 화질 목록을 반환한다."""
        return [
            {"value": "best", "label": "최고 화질 (Source)", "height": 1080},
            {"value": "high", "label": "고화질 (High)", "height": 720},
            {"value": "medium", "label": "중간 화질 (Medium)", "height": 480},
            {"value": "worst", "label": "낮은 화질 (Low)", "height": 360},
        ]

    async def resolve_stream(self, channel_id: str, quality: str = "best") -> tuple[str, dict[str, str], Optional[str]]:
        """라이브 스트림 URL과 헤더를 반환한다."""
        cid = normalize_twitcasting_channel_id(channel_id)
        live_url = f"https://twitcasting.tv/{cid}"
        from app.engine.platform_auth import get_platform_cookies
        cookies = get_platform_cookies("twitcasting", live_url)
        headers = {
            "User-Agent": USER_AGENT,
            "Referer": live_url,
        }
        return live_url, headers, None

    async def get_preview_url(self, channel_id: str) -> str:
        cid = normalize_twitcasting_channel_id(channel_id)
        return f"https://twitcasting.tv/{cid}"
