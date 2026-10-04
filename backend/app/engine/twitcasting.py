"""
Rookery: TwitCasting 엔진
TwitCasting API v2로 라이브 상태를 확인하고,
라이브 URL을 반환한다. 스트림 다운로드는 YtdlpLivePipeline에서 처리한다.

로그인한 사용자만 볼 수 있는 영상을 위해 로그인 쿠키를 빌려주고,
yt-dlp가 알아보지 못하는 재생 차단의 진짜 이유를 페이지에서 찾아낸다.
"""

from __future__ import annotations

import base64
import os
import re
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

import httpx

from app.core.config import get_settings
from app.core.http import get_http_client
from app.core.logger import logger
from app.engine.base import LiveStatus

# ── TwitCasting API v2 ──────────────────────────────────────
TWITCASTING_API_BASE = "https://apiv2.twitcasting.tv"
TWITCASTING_LIVE_URL = "https://twitcasting.tv/{channel_id}"


class TwitcastingEngine:
    """TwitCasting 라이브 감지 + 스트림 추출 엔진.

    라이브 감지: TwitCasting API v2 `GET /users/{id}/current_live`
    스트림 추출: Streamlink twitcasting.tv 플러그인
    인증: Basic Auth (Client ID + Client Secret)
    """

    def _get_auth_header(self) -> dict[str, str]:
        """Basic Auth 헤더를 생성한다."""
        settings = get_settings()
        client_id = settings.twitcasting_client_id
        client_secret = settings.twitcasting_client_secret

        if not client_id or not client_secret:
            return {}

        credentials = f"{client_id}:{client_secret}"
        encoded = base64.b64encode(credentials.encode()).decode()
        return {"Authorization": f"Basic {encoded}"}

    async def check_live_status(self, channel_id: str) -> LiveStatus:
        """TwitCasting API v2로 채널의 라이브 상태를 확인한다.

        오프라인 시 404 응답이 반환되므로 예외 없이 처리한다.

        Args:
            channel_id: TwitCasting 사용자 ID (예: "someuser")

        Returns:
            LiveStatus 딕셔너리.
        """
        url = f"{TWITCASTING_API_BASE}/users/{channel_id}/current_live"
        headers = {
            "Accept": "application/json",
            **self._get_auth_header(),
        }

        try:
            resp = await get_http_client().get(url, headers=headers)
        except httpx.RequestError as e:
            logger.error(f"[TwitCasting:{channel_id}] API 요청 실패: {e}")
            return self._offline_status(channel_id)

        # 404 = 오프라인 (공식 동작)
        if resp.status_code == 404:
            return self._offline_status(channel_id)

        if resp.status_code != 200:
            logger.warning(f"[TwitCasting:{channel_id}] API 응답 {resp.status_code}")
            return self._offline_status(channel_id)

        try:
            data = resp.json()
        except Exception:
            return self._offline_status(channel_id)

        movie = data.get("movie") or {}
        broadcaster = data.get("broadcaster") or {}

        is_live = bool(movie.get("is_live", False))

        return LiveStatus(
            channel_id=channel_id,
            is_live=is_live,
            channel_name=broadcaster.get("screen_id") or broadcaster.get("name") or channel_id,
            title=movie.get("title", ""),
            category=movie.get("category") or "",
            viewer_count=movie.get("current_view_count", 0),
            thumbnail_url=movie.get("large_thumbnail", "") or "",
            profile_image_url=broadcaster.get("image") or "",
        )

    async def get_movie_list(
        self,
        channel_id: str,
        offset: int = 0,
        limit: int = 20,
    ) -> dict:
        """TwitCasting API v2로 채널의 과거 방송 목록을 조회한다.

        Args:
            channel_id: TwitCasting 사용자 ID
            offset: 페이지 오프셋 (0~1000)
            limit: 한 번에 가져올 개수 (1~50)

        Returns:
            {total_count, movies: [{id, title, duration, created_at,
             thumbnail_url, view_count, archive_url}]}
        """
        url = f"{TWITCASTING_API_BASE}/users/{channel_id}/movies"
        headers = {
            "Accept": "application/json",
            **self._get_auth_header(),
        }
        params = {"offset": offset, "limit": min(limit, 50)}

        try:
            resp = await get_http_client().get(url, headers=headers, params=params)
        except httpx.RequestError as e:
            logger.error(f"[TwitCasting:{channel_id}] 아카이브 목록 요청 실패: {e}")
            raise RuntimeError(f"API 요청 실패: {e}") from e

        if resp.status_code == 401:
            raise PermissionError("TwitCasting 인증 실패: Client ID/Secret을 확인하세요.")
        if resp.status_code == 404:
            raise ValueError(f"채널을 찾을 수 없습니다: {channel_id}")
        if resp.status_code != 200:
            raise RuntimeError(f"TwitCasting API 오류: HTTP {resp.status_code}")

        data = resp.json()
        total_count = data.get("total_count", 0)
        raw_movies = data.get("movies", [])

        movies = []
        for item in raw_movies:
            movie = item.get("movie") or {}
            broadcaster = item.get("broadcaster") or {}
            movie_id = movie.get("id")
            if not movie_id:
                continue  # ID 없는 항목 스킵 (비정상 응답 방어)
            movie_id = str(movie_id)
            movies.append({
                "id": movie_id,
                "title": movie.get("title", ""),
                "duration": movie.get("duration", 0),
                "created_at": movie.get("created", 0),
                "thumbnail_url": movie.get("large_thumbnail", "") or "",
                "view_count": movie.get("total_view_count", 0),
                "channel_name": broadcaster.get("screen_id") or broadcaster.get("name") or channel_id,
                "archive_url": f"https://twitcasting.tv/{channel_id}/movie/{movie_id}",
            })

        return {"total_count": total_count, "movies": movies}

    def get_stream_url(self, channel_id: str) -> str:
        """TwitCasting 라이브 URL을 반환한다.

        실제 스트림 추출은 yt-dlp가 처리한다.

        Args:
            channel_id: TwitCasting 사용자 ID

        Returns:
            TwitCasting 라이브 URL 문자열.
        """
        return TWITCASTING_LIVE_URL.format(channel_id=channel_id)

    @staticmethod
    def _offline_status(channel_id: str) -> LiveStatus:
        """오프라인 상태 딕셔너리를 반환한다."""
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


# ── 로그인 쿠키 · 재생 차단 판별 ─────────────────────────────

#: 로그인 전용 아카이브에서 yt-dlp가 내는 오류. 페이지에 영상 주소가 없으면 이렇게 끝난다.
_M3U8_MISSING = "Failed to get m3u8 playlist"
#: 비밀번호가 걸린 영상에서 yt-dlp가 내는 오류.
_PASSWORD_REQUIRED = "protected by a password"

_PLAYBACK_BLOCK_RE = re.compile(
    r'class="tw-player-empty-message"[^>]*>(.*?)</div>', re.DOTALL
)


def is_twitcasting_url(url: str) -> bool:
    """TwitCasting 페이지 URL인지 확인한다."""
    return "twitcasting.tv" in url


def twitcasting_cookie_file() -> Optional[str]:
    """.env에 지정한 로그인 쿠키 파일 경로. 지정하지 않았거나 파일이 없으면 None."""
    path = get_settings().twitcasting_cookie_file
    if not path:
        return None
    if not Path(path).is_file():
        # 경로를 잘못 적었는데 조용히 비로그인으로 받으면 원인을 찾기 어렵다.
        logger.warning(f"TwitCasting 쿠키 파일을 찾을 수 없습니다: {path}")
        return None
    return path


@contextmanager
def borrow_cookie_file(url: str) -> Iterator[Optional[str]]:
    """TwitCasting URL이면 로그인 쿠키 파일의 임시 사본 경로를 빌려준다.

    yt-dlp는 끝날 때 쿠키 파일을 다시 쓴다. 원본을 그대로 넘기면 동시에 도는
    다운로드와 녹화가 같은 파일을 번갈아 덮어써 쿠키가 깨질 수 있다.
    """
    source = twitcasting_cookie_file() if is_twitcasting_url(url) else None
    if source is None:
        yield None
        return

    # mkstemp는 소유자만 읽을 수 있는 권한으로 만든다. 사본도 계정 세션이다.
    fd, lent = tempfile.mkstemp(prefix="tc_cookie_", suffix=".txt")
    os.close(fd)
    try:
        shutil.copyfile(source, lent)
        yield lent
    finally:
        Path(lent).unlink(missing_ok=True)


def find_playback_block(html: str) -> Optional[str]:
    """영상 페이지에서 플레이어 대신 나온 안내 문구(예: "Login required to watch")를 찾는다."""
    match = _PLAYBACK_BLOCK_RE.search(html)
    if not match:
        return None
    text = " ".join(re.sub(r"<[^>]+>", " ", match.group(1)).split())
    return text or None


async def fetch_playback_block(url: str) -> Optional[str]:
    """페이지를 비로그인으로 받아 재생 차단 문구를 찾는다. 페이지를 못 받으면 None."""
    try:
        # 안내 문구의 언어를 고정해야 로그인 요구인지 알아볼 수 있다.
        resp = await get_http_client().get(
            url, headers={"Accept-Language": "en"}, follow_redirects=True
        )
    except httpx.HTTPError as e:
        logger.debug(f"[TwitCasting] 재생 차단 확인용 페이지 요청 실패: {e}")
        return None
    if resp.status_code != 200:
        return None
    return find_playback_block(resp.text)


async def explain_unplayable(url: str, error: str, has_cookies: bool) -> Optional[str]:
    """다시 시도해도 결과가 같은 실패면 사용자에게 보여줄 이유를, 아니면 None을 돌려준다.

    yt-dlp는 로그인 전용 아카이브를 알아보지 못하고 "m3u8을 못 찾았다, 버그를 제보하라"로
    끝난다. 그 오류일 때만 페이지를 직접 받아 진짜 이유를 확인한다. 네트워크 오류처럼
    재시도로 풀릴 수 있는 실패까지 포기하지 않도록 다른 오류는 판별하지 않는다.
    """
    if _PASSWORD_REQUIRED in error:
        return "비밀번호가 걸린 TwitCasting 영상이라 받을 수 없습니다."
    if _M3U8_MISSING not in error:
        return None

    block = await fetch_playback_block(url)
    if block is None:
        return None
    if "login" in block.lower():
        reason = "로그인한 사용자만 볼 수 있는 TwitCasting 영상이라 받을 수 없습니다."
        if has_cookies:
            reason += " TwitCasting 쿠키가 만료됐거나 이 영상을 볼 권한이 없는 계정인지 확인하세요."
        return reason
    return f"TwitCasting이 재생을 막은 영상이라 받을 수 없습니다: {block}"
