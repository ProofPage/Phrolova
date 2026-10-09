"""
Phrolova: Chzzk 라이브 엔진
치지직 채널의 라이브 상태를 확인하고 라이브 URL을 반환한다.
CHZZK 라이브 수신은 기존 Streamlink → FFmpeg 파이프라인으로 처리한다.
"""

from __future__ import annotations

import json
from typing import Optional

from app.core.http import get_http_client
from app.core.logger import logger as app_logger

logger = app_logger.getChild("chzzk")
from app.engine.auth import AuthManager
from app.engine.base import LiveStatus

# ── 치지직 API ──────────────────────────────────────────
CHZZK_API_BASE = "https://api.chzzk.naver.com"
CHZZK_LIVE_DETAIL = f"{CHZZK_API_BASE}/service/v3/channels/{{channel_id}}/live-detail"
CHZZK_LIVE_URL = "https://chzzk.naver.com/live/{channel_id}"


class ChzzkLiveEngine:
    """치지직 라이브 엔진.

    라이브 상태 확인(API) + 라이브 URL 반환.
    실제 스트림 다운로드는 YtdlpLivePipeline이 담당한다.
    """

    def __init__(self, auth: Optional[AuthManager] = None) -> None:
        self._auth = auth or AuthManager()

    async def check_live_status(self, channel_id: str) -> LiveStatus:
        """치지직 API를 통해 채널의 라이브 상태를 확인한다.

        Returns:
            라이브 상태 정보 딕셔너리 (status, title, thumbnail 등).
        """
        content = await self.get_live_detail(channel_id)
        status = content.get("status", "CLOSE")
        channel = content.get("channel") or {}

        raw_thumbnail = content.get("liveImageUrl", "")
        thumbnail_url = raw_thumbnail.replace("{type}", "480") if raw_thumbnail else ""
        raw_tags = content.get("tags")
        broadcast_tags = (
            raw_tags if isinstance(raw_tags, list) and all(isinstance(tag, str) for tag in raw_tags)
            else None
        )
        # 공식 같이보기는 일반 tags에 '같이보기'가 없어도 watchPartyNo로 구분된다.
        party_no = content.get("watchPartyNo")
        is_watchalong = None
        if isinstance(party_no, int) and not isinstance(party_no, bool):
            is_watchalong = party_no > 0 if party_no >= 0 else None
        elif isinstance(party_no, str) and party_no.isdecimal():
            is_watchalong = int(party_no) > 0
        elif "watchPartyNo" in content and party_no is None:
            is_watchalong = False
        party_tag = content.get("watchPartyTag")
        watchalong_tag = party_tag.strip() if isinstance(party_tag, str) and party_tag.strip() else None

        return {
            "channel_id": channel_id,
            "status": status,
            "is_live": status == "OPEN",
            "channel_name": channel.get("channelName", "Unknown"),
            "title": content.get("liveTitle", "No Title"),
            "category": content.get("liveCategoryValue", ""),
            "broadcast_tags": broadcast_tags,
            "is_watchalong": is_watchalong,
            "watchalong_tag": watchalong_tag,
            "live_started_at": content.get("openDate"),
            "viewer_count": content.get("concurrentUserCount", 0),
            "thumbnail_url": thumbnail_url,
            "profile_image_url": channel.get("channelImageUrl", ""),
        }

    async def get_live_detail(self, channel_id: str) -> dict:
        response = await get_http_client().get(
            CHZZK_LIVE_DETAIL.format(channel_id=channel_id),
            headers=self._auth.get_http_headers(),
        )
        response.raise_for_status()
        return response.json().get("content") or {}

    async def get_preview_url(self, channel_id: str) -> str:
        from app.engine.chzzk_time_machine import _media_path

        content = await self.get_live_detail(channel_id)
        if content.get("status") != "OPEN":
            raise ValueError("오프라인")
        playback = json.loads(content.get("livePlaybackJson") or "{}")
        # Standard live playback, never the recording time-machine playlist.
        return _media_path(playback.get("media") or [])

    def get_stream_url(self, channel_id: str) -> str:
        """치지직 라이브 URL을 반환한다.

        실제 스트림 추출은 yt-dlp가 처리한다.
        """
        return CHZZK_LIVE_URL.format(channel_id=channel_id)


# 하위 호환 별칭 (기존 import가 있다면 에러 방지)
StreamLinkEngine = ChzzkLiveEngine
