"""
test_twitcasting.py
TwitCasting 로그인 쿠키 대여와 재생 차단 판별 테스트.

로그인한 사용자만 볼 수 있는 아카이브는 yt-dlp가 "m3u8을 못 찾았다, 버그를 제보하라"는
엉뚱한 오류로 끝난다. 페이지의 안내 문구로 진짜 원인을 가려내고,
로그인 쿠키는 원본이 아니라 사본으로만 빌려주는지 확인한다.
"""

import json
from pathlib import Path

import httpx
import pytest

from app.core.config import get_settings
from app.engine import twitcasting
from app.engine.twitcasting import (
    borrow_cookie_file,
    explain_unplayable,
    find_playback_block,
    twitcasting_cookie_file,
)

ARCHIVE_URL = "https://twitcasting.tv/c:s2s2rete/movie/841067169"

# yt-dlp 2026.06.09가 로그인 전용 아카이브에서 실제로 낸 오류 문구
M3U8_ERROR = (
    "ERROR: [TwitCasting] 841067169: Failed to get m3u8 playlist; please report this issue on  "
    "https://github.com/yt-dlp/yt-dlp/issues?q= , filling out the appropriate issue template. "
    "Confirm you are on the latest version using  yt-dlp -U"
)

# 2026-09-24 실제 로그인 전용 아카이브 페이지에서 잘라낸 플레이어 영역
LOGIN_ONLY_PAGE = """
<div class="tw-player partially-dark">
<div class="tw-player__body">
<div class="liveimage_wrapper">
<img
src="/c:s2s2rete/thumb/841067169"
class="liveimage"
alt=""
>
</div>
</div>
<div class="tw-player-empty-message">Login required to watch</div>
</div>
"""

PLAYABLE_PAGE = """
<div class="tw-player">
<div class="tw-player__body"></div>
</div>
"""

COOKIES = (
    "# Netscape HTTP Cookie File\n"
    ".twitcasting.tv\tTRUE\t/\tTRUE\t1790000000\ttc_ss\tsession-value\n"
)


@pytest.fixture
def cookie_file(tmp_path) -> Path:
    path = tmp_path / "twitcasting_cookies.txt"
    path.write_text(COOKIES, encoding="utf-8")
    get_settings().twitcasting_cookie_file = str(path)
    return path


@pytest.fixture
def serve_page(monkeypatch):
    """공용 HTTP 클라이언트를 가짜 응답을 주는 클라이언트로 바꾼다. 받은 요청 목록을 돌려준다."""
    requests: list[httpx.Request] = []

    def install(html: str = "", status: int = 200, error: Exception | None = None):
        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if error is not None:
                raise error
            return httpx.Response(status, text=html)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        monkeypatch.setattr(twitcasting, "get_http_client", lambda: client)
        return requests

    return install


class TestFindPlaybackBlock:
    def test_reads_login_notice(self):
        assert find_playback_block(LOGIN_ONLY_PAGE) == "Login required to watch"

    def test_playable_page_has_no_block(self):
        assert find_playback_block(PLAYABLE_PAGE) is None


class TestCookieFileSetting:
    def test_unset(self):
        get_settings().twitcasting_cookie_file = None
        assert twitcasting_cookie_file() is None

    def test_missing_file_is_ignored(self, tmp_path):
        get_settings().twitcasting_cookie_file = str(tmp_path / "gone.txt")
        assert twitcasting_cookie_file() is None

    def test_existing_file(self, cookie_file):
        assert twitcasting_cookie_file() == str(cookie_file)


class TestCookiePathStaysPrivate:
    @pytest.mark.asyncio
    async def test_settings_api_does_not_expose_it(self):
        """로그인 쿠키는 계정 세션이다. 경로조차 웹 UI로 내보내지 않는다."""
        from app.api.settings.general import get_current_settings

        get_settings().twitcasting_cookie_file = "/root/secret/twitcasting_cookies.txt"

        body = json.dumps(await get_current_settings(), ensure_ascii=False, default=str)

        assert "twitcasting_cookie" not in body
        assert "/root/secret" not in body


class TestBorrowCookieFile:
    def test_lends_a_copy_and_removes_it(self, cookie_file):
        with borrow_cookie_file(ARCHIVE_URL) as lent:
            assert lent is not None
            assert Path(lent) != cookie_file
            assert Path(lent).read_text(encoding="utf-8") == COOKIES
            # yt-dlp는 끝날 때 쿠키 파일을 다시 쓴다. 사본이 바뀌어도 원본은 그대로여야 한다.
            Path(lent).write_text("# rewritten by yt-dlp\n", encoding="utf-8")

        assert not Path(lent).exists()
        assert cookie_file.read_text(encoding="utf-8") == COOKIES

    def test_other_sites_get_nothing(self, cookie_file):
        with borrow_cookie_file("https://www.youtube.com/watch?v=abc") as lent:
            assert lent is None

    def test_nothing_configured(self):
        get_settings().twitcasting_cookie_file = None
        with borrow_cookie_file(ARCHIVE_URL) as lent:
            assert lent is None


class TestExplainUnplayable:
    @pytest.mark.asyncio
    async def test_login_only_archive(self, serve_page):
        serve_page(LOGIN_ONLY_PAGE)

        reason = await explain_unplayable(ARCHIVE_URL, M3U8_ERROR, has_cookies=False)

        assert reason is not None
        assert "로그인한 사용자만" in reason
        # 쿠키 기능은 설정한 서버에서만 드러낸다.
        assert "쿠키" not in reason

    @pytest.mark.asyncio
    async def test_login_only_with_cookies_points_at_the_cookie(self, serve_page):
        serve_page(LOGIN_ONLY_PAGE)

        reason = await explain_unplayable(ARCHIVE_URL, M3U8_ERROR, has_cookies=True)

        assert reason is not None
        assert "쿠키" in reason

    @pytest.mark.asyncio
    async def test_other_notice_is_passed_through(self, serve_page):
        serve_page('<div class="tw-player-empty-message">Unavailable</div>')

        reason = await explain_unplayable(ARCHIVE_URL, M3U8_ERROR, has_cookies=False)

        assert reason is not None
        assert "Unavailable" in reason

    @pytest.mark.asyncio
    async def test_password_protected_needs_no_page(self, serve_page):
        requests = serve_page(LOGIN_ONLY_PAGE)
        error = (
            "ERROR: [TwitCasting] 841067169: This video is protected by a password, "
            "use the --video-password option"
        )

        reason = await explain_unplayable(ARCHIVE_URL, error, has_cookies=False)

        assert reason is not None
        assert "비밀번호" in reason
        assert requests == []

    @pytest.mark.asyncio
    async def test_playable_page_is_not_blocked(self, serve_page):
        serve_page(PLAYABLE_PAGE)

        assert await explain_unplayable(ARCHIVE_URL, M3U8_ERROR, has_cookies=False) is None

    @pytest.mark.asyncio
    async def test_unrelated_error_skips_page_check(self, serve_page):
        """네트워크 오류 같은 일시적 실패는 재시도해야 하므로 판별하지 않는다."""
        requests = serve_page(LOGIN_ONLY_PAGE)

        reason = await explain_unplayable(
            ARCHIVE_URL, "ERROR: Unable to download webpage: timed out", has_cookies=True
        )

        assert reason is None
        assert requests == []

    @pytest.mark.asyncio
    async def test_page_fetch_failure_keeps_retrying(self, serve_page):
        serve_page(error=httpx.ConnectError("offline"))

        assert await explain_unplayable(ARCHIVE_URL, M3U8_ERROR, has_cookies=False) is None
