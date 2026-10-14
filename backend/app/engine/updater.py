"""
Phrolova: Updater (자동 업데이트 알림 모듈)
GitHub API를 통해 주기적으로 최신 릴리즈를 확인하고, 
신규 버전 발견 시 Discord를 통해 알림을 전송한다.
"""

import asyncio
import httpx
from datetime import datetime
from typing import Optional

from app.core.logger import logger as app_logger
logger = app_logger.getChild("update")
from app.version import __version__
from app.services.notifications import NotificationKind, NotificationService

# GitHub 리포지토리 정보
GITHUB_REPO = "ProofPage/Phrolova"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

class UpdaterService:
    """업데이트를 주기적으로 체크하는 백그라운드 서비스"""
    
    _CHECK_INTERVAL = 86400  # 24시간마다 체크
    
    def __init__(self, notifier: Optional[NotificationService] = None):
        self._notifier = notifier
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._cached_update_info: Optional[dict] = None
        self._last_checked_at: Optional[datetime] = None
        self._last_check_error: Optional[dict] = None
        
        # 최신 버전을 이미 알렸는지 추적 (중복 알림 방지)
        self._notified_versions: set[str] = set()

    def _parse_version(self, version_str: str) -> tuple:
        """v1.1.1 형태의 문자열을 (1, 1, 1) 튜플로 변환한다."""
        v = version_str.lower().strip().lstrip('v')
        try:
            return tuple(int(x) for x in v.split('.'))
        except ValueError:
            return (0, 0, 0)

    def _is_newer(self, current: str, latest: str) -> bool:
        """latest 버전이 current 보다 높은지 비교한다."""
        return self._parse_version(latest) > self._parse_version(current)

    async def check_update_now(self) -> dict:
        """GitHub API를 즉시 호출하여 업데이트 상태를 반환한다."""
        logger.info("GitHub에서 최신 릴리즈를 확인합니다...")
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                response = await client.get(
                    GITHUB_API_URL, 
                    headers={"Accept": "application/vnd.github+json", "User-Agent": "Phrolova-Update-Check"}
                )
                
            if response.status_code == 200:
                data = response.json()
                if not isinstance(data, dict) or not isinstance(data.get("tag_name"), str) or not data["tag_name"].strip():
                    raise ValueError("GitHub 릴리즈 응답에 tag_name이 없습니다.")
                latest_version = data.get("tag_name", "").lstrip('v')
                release_notes = data.get("body", "")
                published_at = data.get("published_at", "")
                html_url = data.get("html_url", "")
                
                has_update = self._is_newer(__version__, latest_version)
                
                self._cached_update_info = {
                    "current_version": __version__,
                    "latest_version": latest_version,
                    "has_update": has_update,
                    "release_notes": release_notes,
                    "published_at": published_at,
                    "download_url": html_url,
                    "checked_at": datetime.now().isoformat()
                }
                self._last_checked_at = datetime.now()
                self._last_check_error = None
                logger.info("업데이트 확인 완료 · 현재=%s · 최신=%s · 새 버전=%s", __version__, latest_version, has_update)
                
                # 새 버전 발견 & 알림 보낸 적 없으면 알림 발송
                if has_update and latest_version not in self._notified_versions:
                    self._notify_update(latest_version, release_notes, html_url)
                    self._notified_versions.add(latest_version)
                    
                return self._cached_update_info
            elif response.status_code == 404:
                self._check_failed("release_unavailable", "저장소 또는 최신 공개 릴리즈에 접근할 수 없습니다. 저장소 공개 여부·접근 권한·릴리즈 게시 상태를 확인하세요.", status=404)
            elif response.status_code == 429 or (response.status_code == 403 and response.headers.get("x-ratelimit-remaining") == "0"):
                self._check_failed("rate_limit", "GitHub API 요청 한도에 도달했습니다. 잠시 후 다시 확인하세요.", status=response.status_code)
            else:
                self._check_failed("http_error", "GitHub API 요청에 실패했습니다. 접근 권한과 GitHub 서비스 상태를 확인하세요.", status=response.status_code)
                
        except httpx.TimeoutException as e:
            self._check_failed("timeout", f"GitHub 응답 대기 시간(10초)을 초과했습니다. 네트워크를 확인하세요. {type(e).__name__}")
        except httpx.RequestError as e:
            self._check_failed("network", f"GitHub 연결 실패 · {type(e).__name__}: {e}")
        except Exception as e:
            self._check_failed("invalid_response", f"업데이트 응답 처리 실패 · {type(e).__name__}: {e}")
            
        # 오류 발생 시 기존 캐시 반환 또는 기본값
        if self._cached_update_info:
            return {**self._cached_update_info, "check_error": self._last_check_error}
            
        return {
            "current_version": __version__,
            "latest_version": __version__,
            "has_update": False,
            "release_notes": "",
            "published_at": "",
            "download_url": f"https://github.com/{GITHUB_REPO}/releases",
            "checked_at": datetime.now().isoformat() if self._last_checked_at else None,
            "check_error": self._last_check_error,
        }

    def _check_failed(self, code: str, message: str, *, status: int | None = None) -> None:
        self._last_check_error = {"code": code, "status": status}
        logger.warning("업데이트 확인 실패 · 저장소=%s · 코드=%s · HTTP=%s · %s", GITHUB_REPO, code, status or "응답 없음", message)

    def _notify_update(self, latest_version: str, release_notes: str, html_url: str) -> None:
        """신규 업데이트 알림을 큐에 넣는다."""
        if not self._notifier:
            return

        # 릴리즈 노트가 길면 500자로 자름
        truncated_notes = release_notes[:500] + ("..." if len(release_notes) > 500 else "")

        self._notifier.notify(
            kind=NotificationKind.UPDATE_AVAILABLE,
            title=f"🚀 신규 버전 업데이트 (v{latest_version})",
            description=(
                f"**Phrolova**의 새로운 버전이 출시되었습니다!\n"
                f"현재 버전: `v{__version__}` → 최신 버전: `v{latest_version}`\n\n"
                f"대시보드의 설정 메뉴나 아래 링크에서 업데이트 하세요.\n"
                f"[GitHub 릴리즈 페이지 이동]({html_url})"
            ),
            color="green",
            fields={"주요 변경 사항": truncated_notes if truncated_notes else "내용 없음"},
        )
        logger.info(f"v{latest_version} 업데이트 알림을 큐에 넣었습니다.")

    async def _update_loop(self):
        """주기적으로 업데이트를 확인하는 백그라운드 루프"""
        # 앱 시작 직후에는 5초 정도 대기 후 첫 체크 (다른 초기화 완료 대기)
        await asyncio.sleep(5)
        
        while self._running:
            try:
                await self.check_update_now()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"업데이트 확인 루프 오류: {e}")
                
            # 24시간 대기
            try:
                await asyncio.sleep(self._CHECK_INTERVAL)
            except asyncio.CancelledError:
                break

    def get_cached_info(self) -> dict:
        """가장 최근에 확인된 업데이트 정보를 반환한다. 없으면 즉시 동기 검사 불가하므로 기본값 반환."""
        if self._cached_update_info:
            return {**self._cached_update_info, "check_error": self._last_check_error}
            
        return {
            "current_version": __version__,
            "latest_version": __version__,
            "has_update": False,
            "release_notes": "",
            "published_at": "",
            "download_url": f"https://github.com/{GITHUB_REPO}/releases",
            "checked_at": None,
            "check_error": self._last_check_error,
        }

    async def start(self):
        """업데이트 체크 백그라운드 작업을 시작한다."""
        if self._running:
            return
            
        self._running = True
        self._task = asyncio.create_task(self._update_loop())
        logger.info("자동 업데이트 체커 시작됨.")

    async def stop(self):
        """업데이트 체크 백그라운드 작업을 중지한다."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("자동 업데이트 체커 종료됨.")
