"""
Rookery: 인증 관리 모듈 (Auth Manager)
치지직 쿠키(NID_AUT, NID_SES)를 관리하고 HTTP 헤더를 생성한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.core.config import get_settings
from app.core.http import USER_AGENT
from app.core.logger import logger


@dataclass(frozen=True)
class ChzzkCookies:
    """치지직 인증 쿠키 데이터."""

    nid_aut: str
    nid_ses: str

    def to_cookie_string(self) -> str:
        """HTTP Cookie 헤더용 문자열 반환."""
        return f"NID_AUT={self.nid_aut}; NID_SES={self.nid_ses}"

    def to_dict(self) -> dict[str, str]:
        """딕셔너리 형태로 반환."""
        return {"NID_AUT": self.nid_aut, "NID_SES": self.nid_ses}


class AuthManager:
    """치지직 인증 관리자.

    쿠키를 로드하고, Streamlink/yt-dlp/httpx에서 사용할 수 있는
    HTTP 헤더 또는 옵션을 생성한다.
    """

    #: 비로그인 경고를 인스턴스마다 반복 출력하지 않기 위한 클래스 단위 플래그.
    _warned_anonymous = False

    def __init__(
        self,
        nid_aut: Optional[str] = None,
        nid_ses: Optional[str] = None,
    ) -> None:
        settings = get_settings()
        self._nid_aut = nid_aut or settings.nid_aut
        self._nid_ses = nid_ses or settings.nid_ses

    @property
    def is_authenticated(self) -> bool:
        """인증 쿠키가 설정되어 있는지 확인."""
        return bool(self._nid_aut and self._nid_ses)

    def get_cookies(self) -> Optional[ChzzkCookies]:
        """쿠키 객체를 반환. 미설정 시 None."""
        if not self.is_authenticated:
            # 감시 루프가 채널마다 30초 간격으로 호출하므로 한 번만 알린다.
            if not AuthManager._warned_anonymous:
                AuthManager._warned_anonymous = True
                logger.warning(
                    "인증 쿠키가 설정되지 않았습니다. 비로그인 모드로 동작합니다."
                )
            return None
        return ChzzkCookies(nid_aut=self._nid_aut, nid_ses=self._nid_ses)  # type: ignore[arg-type]

    def get_http_headers(self) -> dict[str, str]:
        """httpx/yt-dlp용 HTTP 헤더 딕셔너리 반환."""
        headers: dict[str, str] = {"User-Agent": USER_AGENT}
        cookies = self.get_cookies()
        if cookies:
            headers["Cookie"] = cookies.to_cookie_string()
        return headers

    def get_ytdlp_cookies(self) -> Optional[str]:
        """yt-dlp용 쿠키 파일 경로 또는 쿠키 문자열 반환.

        NOTE: yt-dlp는 Netscape 쿠키 파일 형식을 지원하지만,
        여기서는 간단히 헤더 인젝션 방식을 사용한다.
        """
        cookies = self.get_cookies()
        if cookies:
            return cookies.to_cookie_string()
        return None

    def update_cookies(self, nid_aut: str, nid_ses: str) -> None:
        """런타임 및 파일에 쿠키를 갱신한다."""
        self._nid_aut = nid_aut
        self._nid_ses = nid_ses

        # Settings 싱글턴도 즉시 업데이트 (lru_cache 캐싱으로 재로딩 불가)
        # 이를 통해 이후 AuthManager() 생성 시 올바른 쿠키를 가져올 수 있음
        settings = get_settings()
        settings.nid_aut = nid_aut
        settings.nid_ses = nid_ses

        # .env 파일에 저장
        self._persist_env({"NID_AUT": nid_aut, "NID_SES": nid_ses})
        logger.info("인증 쿠키가 업데이트되고 .env 파일에 저장되었습니다.")


    def _persist_env(self, updates: dict[str, str]) -> None:
        """.env 파일의 특정 키 값을 업데이트한다."""
        from app.core.utils import update_env_file
        update_env_file(updates)
