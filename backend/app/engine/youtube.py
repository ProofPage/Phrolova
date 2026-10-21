"""
Phrolova: YouTube 라이브 엔진
유튜브 채널의 라이브 상태를 HTML 스크래핑 및 yt-dlp 메타데이터 분석을 통해 감지하고 라이브 URL을 반환한다.
스트림 다운로드는 YtdlpLivePipeline에서 처리한다.
"""

from __future__ import annotations

import json
import re
import asyncio
import httpx
from app.core.logger import logger as app_logger

logger = app_logger.getChild("youtube")
from app.core.config import get_settings
from app.core.http import get_http_client
from app.engine.base import LiveStatus
from app.engine.youtube_support import runtime_cli_options, with_youtube_cookie_fallback, youtube_extractor_command


class YoutubeLiveEngine:
    """YouTube 라이브 감지 및 스트림 URL 매핑 엔진."""

    def __init__(self):
        self._live_urls = {}
        self._metadata_errors = {}

    async def check_live_status(self, channel_id: str) -> LiveStatus:
        """유튜브 라이브 채널의 생방송 여부를 확인한다."""
        raw = channel_id.strip()
        if raw.startswith("@http"):
            raw = raw[1:]
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", raw):
            url = f"https://www.youtube.com/watch?v={raw}"
        elif "://" in raw or "youtube.com" in raw or "youtu.be" in raw:
            url = raw if "://" in raw else f"https://{raw}"
        elif raw.startswith("UC"):
            url = f"https://www.youtube.com/channel/{raw}/live"
        else:
            url = f"https://www.youtube.com/@{raw.lstrip('@')}/live"

        self._metadata_errors.pop(url, None)
        from app.engine.platform_auth import platform_cookie_jar
        headers = {"Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7", "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

        # 1차 체크: 가벼운 HTML 스크래핑으로 감지
        is_live = False
        html = ""
        player = {}

        try:
            resp = await get_http_client().get(
                url, headers=headers, follow_redirects=True, cookies=platform_cookie_jar("youtube")
            )
            if resp.status_code == 200:
                html = resp.text
                # Only the selected player's JSON describes this channel's live.
                # Recommended live videos elsewhere in the page are unrelated.
                match = re.search(r"(?:var\s+)?ytInitialPlayerResponse\s*=\s*", html)
                if match:
                    try:
                        player = json.JSONDecoder().raw_decode(html[match.end() :])[0]
                    except (ValueError, TypeError):
                        player = {}
                details = player.get("videoDetails") or {}
                live = (
                    player.get("microformat", {})
                    .get("playerMicroformatRenderer", {})
                    .get("liveBroadcastDetails", {})
                )
                is_live = (
                    details.get("isLive") is True or live.get("isLiveNow") is True
                ) and player.get("playabilityStatus", {}).get("status") == "OK"
        except httpx.RequestError as e:
            logger.error(f"[YouTube:{channel_id}] HTML 스크래핑 요청 실패: {e}")

        # 2차 체크: HTML로 명확히 감지되지 않았지만 차단 등으로 인한 이슈일 수 있어 yt-dlp 덤프 백업 적용
        if not is_live:
            is_live, yt_info = await self._check_via_ytdlp(url, channel_id)
            if is_live and yt_info:
                video_id = yt_info.get("id", "")
                if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
                    self._live_urls[channel_id] = (
                        f"https://www.youtube.com/watch?v={video_id}"
                    )
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
                    profile_image_url=thumbnail_url,
                )

        if not is_live:
            status = self._offline_status(channel_id)
            if url in self._metadata_errors:
                failure, detail = self._metadata_errors[url]
                status.update(
                    status_error=str(failure),
                    error_detail=detail,
                    status_error_retryable=failure.retryable,
                )
            else:
                self._live_urls.pop(channel_id, None)
            return status

        video_id = (player.get("videoDetails") or {}).get("videoId", "")
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            self._live_urls[channel_id] = f"https://www.youtube.com/watch?v={video_id}"

        # HTML 기반으로 1차 통과한 경우 메타데이터 파싱
        title = "YouTube Live"
        title_match = re.search(r"<title>(.*?) - YouTube</title>", html)
        if title_match:
            title = title_match.group(1)
            # 대기 중/오프라인 안내 문구가 포함되어 있다면 오프라인 처리
            if "대기 중" in title or "대기중" in title or "비공개" in title or "사용할 수 없음" in title:
                # 실제로 방송을 송출하기 전 예약 대기 상태인 경우
                return self._offline_status(channel_id)

        # 방송 종료 후 비공개 또는 재생 불가로 전환된 경우
        if any(marker in html for marker in ("비공개 동영상입니다", "사용할 수 없는 동영상입니다", "동영상이 삭제되었습니다", "This video is private", "Video unavailable")):
            self._metadata_errors.pop(url, None)
            return self._offline_status(channel_id)

        channel_name = channel_id
        owner_match = re.search(r'"videoOwnerRenderer":\{.*?"title":\{"runs":\[\{"text":"([^"]+)"', html)
        if owner_match:
            channel_name = owner_match.group(1)
        else:
            author_match = re.search(r'"author":"([^"]+)"', html)
            if author_match:
                channel_name = author_match.group(1)

        viewer_count = 0
        # 최신 유튜브 runs 형식 및 레거시 simpleText 형식 모두 지원
        viewer_match = re.search(
            r'"videoViewCountRenderer":\{"viewCount":\{"runs":\[.*?"text":"([0-9,]+)"',
            html,
        )
        if not viewer_match:
            viewer_match = re.search(
                r'"viewCount":\{\"videoViewCountRenderer\":\{\"viewCount\":\{\"simpleText\":\"(?:시청자\s*)?([0-9,]+)명?\"\}',
                html,
            )
        if not viewer_match:
            viewer_match = re.search(
                r'"(?:shortViewCount|viewCount)":\{.*?"(?:simpleText|text)":"(?:시청자\s*)?([0-9,]+)명?',
                html,
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

        profile_image_url = ""
        avatar_match = re.search(r'"videoOwnerRenderer":\{.*?"thumbnail":\{"thumbnails":\[\{"url":"([^"]+)"', html)
        if not avatar_match:
            avatar_match = re.search(r'"avatar":\{"avatarViewModel":\{"image":\{"sources":\[\{"url":"([^"]+)"', html)
        if avatar_match:
            profile_image_url = avatar_match.group(1)

        return LiveStatus(
            channel_id=channel_id,
            is_live=True,
            channel_name=channel_name,
            title=title,
            category="YouTube Live",
            viewer_count=viewer_count,
            thumbnail_url=thumbnail_url,
            profile_image_url=profile_image_url or thumbnail_url,
        )

    async def _check_via_ytdlp(self, url: str, channel_id: str | None = None) -> tuple[bool, dict | None]:
        """yt-dlp 메타데이터 조회를 통해 라이브 여부를 검증한다."""
        import json as _json

        # --simulate -j 옵션으로 스트림 다운로드 없이 JSON 메타데이터만 조회
        cmd = [
            *youtube_extractor_command(),
            url,
            "--simulate",
            "-j",
            "--no-warnings",
            "--ignore-config",
            "--no-playlist",
            "--socket-timeout", "10",
            "--extractor-retries", "1",
            "--sleep-requests", "1",
            *runtime_cli_options(),
        ]

        async def query(cookie_file):
            proc = None
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    *(["--cookies", cookie_file] if cookie_file else []),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
                if proc.returncode:
                    raise RuntimeError(stderr.decode(errors="replace")[-4000:])
                info = _json.loads(stdout.decode())
                return (info.get("is_live") is True, info)
            finally:
                if proc is not None and proc.returncode is None:
                    proc.kill()
                    await proc.communicate()

        try:
            return await with_youtube_cookie_fallback(query)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            from app.engine.platform_auth import redact_media_error
            from app.engine.recording_errors import classify_recording_error

            err_text = str(error).lower()
            # 방송 종료 후 비공개, 삭제, 사용할 수 없는 영상 등은 모니터링 장애가 아닌 방송 종료(오프라인)로 처리
            if any(m in err_text for m in (
                "video unavailable", "this video is private", "private video",
                "live stream recording is not available", "removed by the uploader",
                "this video has been removed", "is not a live stream", "video is unavailable",
                "비공개", "사용할 수 없는", "삭제된"
            )):
                self._metadata_errors.pop(url, None)
                if channel_id:
                    self._live_urls.pop(channel_id, None)
                return False, None

            self._metadata_errors[url] = (
                classify_recording_error(error),
                redact_media_error(error),
            )
            logger.debug(f"유튜브 방송 정보 조회 실패: {redact_media_error(error)}")

        return False, None

    def get_stream_url(self, channel_id: str) -> str:
        """라이브 스트림 다운로드 주소를 반환한다."""
        if channel_id in self._live_urls:
            return self._live_urls[channel_id]
        raw = channel_id.strip()
        if raw.startswith("@http"):
            raw = raw[1:]
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", raw):
            return f"https://www.youtube.com/watch?v={raw}"
        if "://" in raw or "youtube.com" in raw or "youtu.be" in raw:
            return raw if "://" in raw else f"https://{raw}"
        if raw.startswith("UC"):
            return f"https://www.youtube.com/channel/{raw}/live"
        else:
            return f"https://www.youtube.com/@{raw.lstrip('@')}/live"

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
