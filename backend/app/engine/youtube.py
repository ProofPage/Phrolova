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
        self._channel_info_cache = {}

    async def _resolve_channel_profile(self, channel_id: str) -> tuple[str, str]:
        """오프라인 상태일 때도 채널 페이지에서 채널명과 프로필 이미지를 1초 내로 빠르게 가져온다."""
        cached = self._channel_info_cache.get(channel_id)
        if cached:
            return cached
        raw = channel_id.strip().lstrip("@")
        home_url = f"https://www.youtube.com/channel/{raw}" if raw.startswith("UC") and len(raw) == 24 else f"https://www.youtube.com/@{raw}"
        headers = {"Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7", "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        name, avatar = channel_id, ""
        try:
            resp = await get_http_client().get(home_url, headers=headers, follow_redirects=True, timeout=5)
            if resp.status_code == 200:
                html = resp.text
                name_m = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', html)
                if not name_m:
                    name_m = re.search(r'<meta\s+name="title"\s+content="([^"]+)"', html)
                if name_m:
                    extracted = name_m.group(1).removesuffix(" - YouTube").strip()
                    if extracted and not extracted.startswith("http"):
                        name = extracted
                image_m = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html)
                if image_m:
                    avatar = image_m.group(1)
                self._channel_info_cache[channel_id] = (name, avatar)
        except Exception:
            pass
        return name, avatar

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

                # 등록된 채널 ID(UC...)가 있는데 추천 피드의 다른 채널 영상이 잡힌 경우 방어
                found_cid = details.get("channelId")
                if is_live and raw.startswith("UC") and len(raw) == 24 and found_cid and found_cid != raw:
                    is_live = False
        except httpx.RequestError as e:
            logger.error(f"[YouTube:{channel_id}] HTML 스크래핑 요청 실패: {e}")

        # HTML에서 채널 프로필 및 채널명 추출 (오프라인이어도 표시 가능)
        channel_name = channel_id
        profile_image_url = ""
        if html:
            name_match = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', html)
            if not name_match:
                name_match = re.search(r'<meta\s+name="title"\s+content="([^"]+)"', html)
            if name_match:
                extracted_name = name_match.group(1).removesuffix(" - YouTube").strip()
                if extracted_name and not extracted_name.startswith("http"):
                    channel_name = extracted_name

            image_match = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html)
            if image_match:
                profile_image_url = image_match.group(1)

        if not is_live and (channel_name == channel_id or not profile_image_url):
            fallback_name, fallback_avatar = await self._resolve_channel_profile(channel_id)
            if channel_name == channel_id:
                channel_name = fallback_name
            if not profile_image_url:
                profile_image_url = fallback_avatar

        # 2차 체크: HTML로 명확히 감지되지 않고, 방송 중일 가능성이 있을 때만 yt-dlp 덤프 백업 적용
        # (HTML 응답이 정상이고 라이브가 명백히 아닌 경우 yt-dlp를 생략하여 10~15초 지연 방지)
        needs_ytdlp_fallback = not html or (
            "LIVE_STREAM_OFFLINE" not in html
            and "isLive" not in html
            and "liveBroadcastDetails" not in html
            and any(kw in html for kw in ("ytInitialPlayerResponse", "liveStreamability"))
        )

        if not is_live and needs_ytdlp_fallback:
            is_live, yt_info = await self._check_via_ytdlp(url, channel_id)
            if is_live and yt_info:
                video_id = yt_info.get("id", "")
                if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
                    self._live_urls[channel_id] = (
                        f"https://www.youtube.com/watch?v={video_id}"
                    )
                title = yt_info.get("title", "YouTube Live")
                channel_name = yt_info.get("uploader", channel_name)
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
                    profile_image_url=profile_image_url or thumbnail_url,
                )

        if not is_live:
            status = self._offline_status(channel_id, channel_name=channel_name, profile_image_url=profile_image_url)
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
        player_title = (player.get("videoDetails") or {}).get("title")
        if player_title:
            title = player_title
        else:
            title_match = re.search(r"<title>(.*?) - YouTube</title>", html)
            if title_match:
                title = title_match.group(1)

        import html as _html
        title = _html.unescape(title)

        # 대기 중/오프라인 안내 문구가 포함되어 있다면 오프라인 처리
        if "대기 중" in title or "대기중" in title or "비공개" in title or "사용할 수 없음" in title:
            # 실제로 방송을 송출하기 전 예약 대기 상태인 경우
            return self._offline_status(channel_id)

        # 방송 종료 후 비공개 또는 재생 불가로 전환된 경우
        # (전체 HTML 대신 playabilityStatus 또는 player 에러 상태를 우선하고, 문자열 검사는 안전한 한국어 문구 및 정밀 검사 사용)
        play_status = player.get("playabilityStatus", {}).get("status")
        if play_status in ("UNPLAYABLE", "LOGIN_REQUIRED", "ERROR"):
            reason = str(player.get("playabilityStatus", {}).get("reason") or "")
            if any(marker in reason for marker in ("비공개", "사용할 수 없는", "삭제된", "private", "unavailable")):
                self._metadata_errors.pop(url, None)
                return self._offline_status(channel_id)

        if any(marker in html for marker in ("비공개 동영상입니다", "사용할 수 없는 동영상입니다", "동영상이 삭제되었습니다", "This video is private")):
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
                "the channel is not currently live", "does not have a live stream",
                "not currently live", "this live event will begin", "premieres in",
                "is offline", "offline",
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

    async def get_qualities(self, channel_id: str) -> list[dict]:
        """현재 유튜브 라이브 스트림에서 제공하는 실제 해상도/화질 목록을 반환한다."""
        from app.engine.platform_auth import platform_cookie_jar
        from app.core.http import get_http_client
        url = self.get_stream_url(channel_id)
        headers = {
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        }
        try:
            resp = await get_http_client().get(
                url, headers=headers, follow_redirects=True, cookies=platform_cookie_jar("youtube")
            )
            if resp.status_code != 200:
                return []
            html = resp.text
            match = re.search(r"(?:var\s+)?ytInitialPlayerResponse\s*=\s*", html)
            if not match:
                return []
            player = json.JSONDecoder().raw_decode(html[match.end():])[0]
            streaming_data = player.get("streamingData") or {}
            adaptive = streaming_data.get("adaptiveFormats") or []
            video_formats = [f for f in adaptive if str(f.get("mimeType", "")).startswith("video/")]
            seen = set()
            options = []
            for vf in sorted(
                video_formats,
                key=lambda f: (f.get("height") or 0, f.get("fps") or 0, f.get("bitrate") or 0),
                reverse=True,
            ):
                height = vf.get("height")
                fps = vf.get("fps")
                width = vf.get("width")
                if not height:
                    continue
                val = f"{height}p{fps}" if fps and fps > 30 else f"{height}p"
                if val in seen:
                    continue
                seen.add(val)
                options.append({
                    "value": val,
                    "label": val,
                    "width": width,
                    "height": height,
                    "fps": fps or None,
                    "bitrate": vf.get("bitrate") or None,
                })
            return options
        except Exception as error:
            logger.debug(f"[YouTube:{channel_id}] 화질 목록 조회 실패: {error}")
            return []

    @staticmethod
    def _offline_status(channel_id: str, channel_name: str | None = None, profile_image_url: str = "") -> LiveStatus:
        return LiveStatus(
            channel_id=channel_id,
            is_live=False,
            channel_name=channel_name or channel_id,
            title="",
            category="",
            viewer_count=0,
            thumbnail_url="",
            profile_image_url=profile_image_url,
        )
