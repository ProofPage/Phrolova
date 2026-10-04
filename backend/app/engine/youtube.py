"""
Rookery: YouTube 라이브 엔진
유튜브 채널의 라이브 상태를 HTML 스크래핑 및 yt-dlp 메타데이터 분석을 통해 감지하고 라이브 URL을 반환한다.
스트림 다운로드는 YtdlpLivePipeline에서 처리한다.
"""

from __future__ import annotations

import re
import asyncio
import httpx
from app.core.logger import logger
from app.core.config import get_settings
from app.core.http import get_http_client
from app.engine.base import LiveStatus


class YoutubeLiveEngine:
    """YouTube 라이브 감지 및 스트림 URL 매핑 엔진."""

    async def check_live_status(self, channel_id: str) -> LiveStatus:
        """유튜브 라이브 채널의 생방송 여부를 확인한다."""
        if channel_id.startswith("UC"):
            url = f"https://www.youtube.com/channel/{channel_id}/live"
        else:
            handle = channel_id if channel_id.startswith("@") else f"@{channel_id}"
            url = f"https://www.youtube.com/{handle}/live"

        headers = {"Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7"}

        # 1차 체크: 가벼운 HTML 스크래핑으로 감지
        is_live = False
        html = ""
        redirected_url = url

        try:
            resp = await get_http_client().get(url, headers=headers, follow_redirects=True)
            if resp.status_code == 200:
                html = resp.text
                redirected_url = str(resp.url)
                # "isLive":true 또는 "isLiveStreaming":true 확인
                # 혹은 리다이렉트된 주소가 watch?v= 인 경우
                if (
                    '"isLive":true' in html
                    or '"isLiveStreaming":true' in html
                    or ("watch?v=" in redirected_url)
                ):
                    is_live = True
        except httpx.RequestError as e:
            logger.error(f"[YouTube:{channel_id}] HTML 스크래핑 요청 실패: {e}")

        # 2차 체크: HTML로 명확히 감지되지 않았지만 차단 등으로 인한 이슈일 수 있어 yt-dlp 덤프 백업 적용
        if not is_live:
            is_live, yt_info = await self._check_via_ytdlp(url)
            if is_live and yt_info:
                title = yt_info.get("title", "YouTube Live")
                channel_name = yt_info.get("uploader", channel_id)
                viewer_count = yt_info.get("concurrent_viewers", 0) or 0
                thumbnail_url = yt_info.get("thumbnail", "")

                return LiveStatus(
                    channel_id=channel_id,
                    is_live=True,
                    channel_name=channel_name,
                    title=title,
                    category="YouTube Live",
                    viewer_count=viewer_count,
                    thumbnail_url=thumbnail_url,
                    profile_image_url="",
                )

        if not is_live:
            return self._offline_status(channel_id)

        # HTML 기반으로 1차 통과한 경우 메타데이터 파싱
        title = "YouTube Live"
        title_match = re.search(r'<title>(.*?) - YouTube</title>', html)
        if title_match:
            title = title_match.group(1)
            # 대기 중/오프라인 안내 문구가 포함되어 있다면 오프라인 처리
            if "대기 중" in title or "대기중" in title:
                # 실제로 방송을 송출하기 전 예약 대기 상태인 경우
                return self._offline_status(channel_id)

        channel_name = channel_id
        author_match = re.search(r'"author":"([^"]+)"', html)
        if author_match:
            channel_name = author_match.group(1)

        viewer_count = 0
        viewer_match = re.search(
            r'"viewCount":\{\"videoViewCountRenderer\":\{\"viewCount\":\{\"simpleText\":\"(?:시청자\s*)?([0-9,]+)명?\"\}',
            html
        )
        if viewer_match:
            try:
                viewer_count = int(viewer_match.group(1).replace(",", ""))
            except ValueError:
                pass

        thumbnail_url = ""
        thumb_match = re.search(r'<link rel="image_src" href="([^"]+)"', html)
        if thumb_match:
            thumbnail_url = thumb_match.group(1)

        return LiveStatus(
            channel_id=channel_id,
            is_live=True,
            channel_name=channel_name,
            title=title,
            category="YouTube Live",
            viewer_count=viewer_count,
            thumbnail_url=thumbnail_url,
            profile_image_url="",
        )

    async def _check_via_ytdlp(self, url: str) -> tuple[bool, dict | None]:
        """yt-dlp 메타데이터 조회를 통해 라이브 여부를 검증한다."""
        import json as _json
        
        ytdlp_path = get_settings().resolve_ytdlp_path()
        # --simulate -j 옵션으로 스트림 다운로드 없이 JSON 메타데이터만 조회
        cmd = [ytdlp_path, url, "--simulate", "-j", "--no-warnings"]
        
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode == 0:
                info = _json.loads(stdout.decode())
                # yt-dlp 응답의 is_live 플래그 검증
                if info.get("is_live") is True:
                    return True, info
        except Exception as e:
            logger.debug(f"[YouTube] yt-dlp 메타데이터 조회 중 예외 발생: {e}")
            
        return False, None

    def get_stream_url(self, channel_id: str) -> str:
        """라이브 스트림 다운로드 주소를 반환한다."""
        if channel_id.startswith("UC"):
            return f"https://www.youtube.com/channel/{channel_id}/live"
        else:
            handle = channel_id if channel_id.startswith("@") else f"@{channel_id}"
            return f"https://www.youtube.com/{handle}/live"

    @staticmethod
    def _offline_status(channel_id: str) -> LiveStatus:
        return LiveStatus(
            channel_id=channel_id,
            is_live=False,
            channel_name=channel_id,
            title="",
            category="",
            viewer_count=0,
            thumbnail_url="",
            profile_image_url="",
        )
