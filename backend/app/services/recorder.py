"""
Rookery: RecorderService
Conductor와 VodEngine을 감싸는 비즈니스 로직 레이어.
API 라우터에서 직접 엔진을 호출하지 않고 이 서비스를 통해 접근한다.
"""

from __future__ import annotations

from typing import Optional

from app.core.logger import logger
from app.engine.auth import AuthManager
from app.engine.base import Platform
from app.engine.conductor import Conductor
from app.engine.vod import VodEngine
from app.services.notifications import NotificationService


class RecorderService:
    """녹화 및 VOD 다운로드를 총괄하는 서비스 레이어.

    Conductor(라이브 녹화)와 VodEngine(다시보기)을 통합 관리한다.
    FastAPI의 lifespan에서 초기화되어 앱 전역에서 공유된다.
    """

    def __init__(
        self,
        conductor: Conductor,
        auth: Optional[AuthManager] = None,
        notifier: Optional[NotificationService] = None,
    ) -> None:
        self._conductor = conductor
        self._auth = auth or AuthManager()
        self._notifier = notifier
        self._vod_engine = VodEngine(auth=self._auth, notifier=notifier)

    # ── 채널 관리 ────────────────────────────────────────

    def add_channel(self, channel_id: str, auto_record: bool = True) -> dict:
        """Chzzk 감시 채널을 추가한다 (하위 호환용)."""
        return self.add_platform_channel(
            channel_id=channel_id,
            platform=Platform.CHZZK,
            auto_record=auto_record,
        )

    def add_platform_channel(
        self,
        channel_id: str,
        platform: Platform = Platform.CHZZK,
        auto_record: bool = True,
        download_condition: Optional[str] = None,
        watchalong_tags: Optional[str] = None,
    ) -> dict:
        """멀티 플랫폼 감시 채널을 추가한다."""
        self._conductor.add_channel(
            channel_id, auto_record=auto_record, platform=platform,
            download_condition=download_condition, watchalong_tags=watchalong_tags,
        )
        composite_key = self._conductor.make_composite_key(platform, channel_id)
        return {
            "composite_key": composite_key,
            "platform": platform.value,
            "channel_id": channel_id,
            "auto_record": auto_record,
            "download_condition": download_condition,
            "watchalong_tags": watchalong_tags,
            "message": f"채널 '{composite_key}' 등록 완료.",
        }

    async def remove_channel(self, channel_id: str) -> dict:
        """Chzzk 감시 채널을 제거한다 (하위 호환용)."""
        composite_key = self._conductor.make_composite_key(Platform.CHZZK, channel_id)
        return await self.remove_platform_channel(composite_key)

    async def remove_platform_channel(self, composite_key: str) -> dict:
        """플랫폼 채널을 감시 목록에서 제거한다."""
        await self._conductor.remove_channel(composite_key)
        return {
            "composite_key": composite_key,
            "message": f"채널 '{composite_key}' 제거 완료.",
        }

    async def get_live_preview_url(self, composite_key: str) -> str:
        return await self._conductor.get_live_preview_url(composite_key)

    def get_channels(self) -> list[dict]:
        """모든 채널 상태를 반환한다."""
        return self._conductor.get_all_status()

    async def toggle_auto_record(self, composite_key: str) -> dict:
        """채널의 자동 녹화 설정을 토글한다."""
        new_value = await self._conductor.toggle_auto_record(composite_key)
        logger.info(f"[Service] 자동 녹화 토글: {composite_key} → {'ON' if new_value else 'OFF'}")
        return {
            "composite_key": composite_key,
            "auto_record": new_value,
            "message": f"자동 녹화 {'ON' if new_value else 'OFF'}",
        }

    def scan_now(self, composite_key: Optional[str] = None) -> None:
        """채널 폴링 주기를 무시하고 즉시 스캔을 트리거한다."""
        self._conductor.trigger_scan_now(composite_key)

    def set_download_options(self, composite_key: str, auto_record: bool, condition: Optional[str], tags: Optional[str]) -> None:
        self._conductor.set_download_options(composite_key, auto_record, condition, tags)

    def set_channel_tags(self, composite_key: str, tags: list[str]) -> None:
        """특정 채널의 태그를 변경한다."""
        self._conductor.set_channel_tags(composite_key, tags)

    def remove_tag_from_all_channels(self, tag_name: str) -> bool:
        """모든 채널에서 특정 태그를 일괄 제거한다."""
        return self._conductor.remove_tag_from_all_channels(tag_name)



    # ── 라이브 녹화 ──────────────────────────────────────

    async def start_recording(self, channel_id: str) -> dict:
        """수동 녹화를 시작한다."""
        logger.info(f"[Service] 녹화 시작 요청: {channel_id}")
        return await self._conductor.start_manual_recording(channel_id)

    async def stop_recording(self, channel_id: str) -> dict:
        """녹화를 중지한다."""
        logger.info(f"[Service] 녹화 중지 요청: {channel_id}")
        return await self._conductor.stop_manual_recording(channel_id)

    async def stop_all_recordings(self) -> dict:
        """모든 채널의 녹화를 중지한다."""
        logger.info("[Service] 모든 녹화 중지 요청")
        return await self._conductor.stop_all_recordings()

    async def start_channel(self, composite_key: str) -> dict:
        """녹화 시작 + 자동 녹화 ON. Discord /start 전용."""
        logger.info(f"[Service] 채널 시작 요청: {composite_key}")
        self._conductor.set_auto_record(composite_key, True)
        return await self._conductor.start_manual_recording(composite_key)

    async def stop_channel(self, composite_key: str) -> dict:
        """녹화 중지 + 자동 녹화 OFF. Discord /stop 전용."""
        logger.info(f"[Service] 채널 중지 요청: {composite_key}")
        result = await self._conductor.stop_manual_recording(composite_key)
        self._conductor.set_auto_record(composite_key, False)
        return result

    # ── Conductor 제어 ───────────────────────────────────

    async def start_monitoring(self) -> dict:
        """모든 채널 감시를 시작한다."""
        await self._conductor.start()
        return {
            "message": "Conductor 시작.",
            "channels": self._conductor.channel_count,
        }

    async def stop_monitoring(self) -> dict:
        """모든 감시 및 녹화를 중지한다."""
        await self._conductor.stop()
        return {"message": "Conductor 종료."}

    # ── VOD 다운로드 ─────────────────────────────────────

    async def get_vod_info(self, url: str) -> dict:
        """VOD 메타데이터를 조회한다."""
        return await self._vod_engine.get_video_info(url)

    async def capture_space(self, username: str) -> dict:
        """Twitter Spaces m3u8 URL을 즉시 1회 조회한다."""
        return await self._conductor.capture_space(username)

    async def download_space(self, space_url: str) -> dict:
        """Space URL로 직접 다운로드한다 (채널 등록 불필요)."""
        return await self._conductor.download_space(space_url)

    async def download_vod(
        self,
        url: str,
        quality: str = "best",
        output_dir: Optional[str] = None,
        cdn: str = "default",
    ) -> str:
        """VOD 다운로드를 시작한다. task_id를 반환한다."""
        logger.info(f"[Service] VOD 다운로드 요청: {url}")
        task_id = await self._vod_engine.download(
            url=url,
            quality=quality,
            output_dir=output_dir,
            cdn=cdn,
        )
        return task_id

    async def download_vod_batch(
        self, url: str, quality: str = "best", output_dir: Optional[str] = None, cdn: str = "default",
    ) -> dict:
        """Return immediately; channel enumeration continues in the background."""
        url = url.strip()
        if url.startswith("@"):
            url = "https://www.youtube.com/" + url
        if self._vod_engine.is_youtube_channel_url(url):
            job = self._vod_engine.channel_imports.start(url, output_dir, quality)
            return {"task_id": None, "task_ids": [], "added_count": 0,
                    "import_id": job["id"], "message": "채널 영상 수집을 시작했습니다."}
        task_id = await self.download_vod(url, quality, output_dir, cdn=cdn)
        return {"task_id": task_id, "task_ids": [task_id], "added_count": 1,
                "message": "다운로드 목록에 추가했습니다."}

    def list_vod_imports(self) -> list[dict]:
        return self._vod_engine.channel_imports.list()

    def cancel_vod_import(self, import_id: str) -> dict:
        return self._vod_engine.channel_imports.cancel(import_id)

    def list_vod_tasks(self) -> list[dict]:
        """모든 VOD 다운로드 작업 목록을 반환한다."""
        return self._vod_engine.list_all_tasks()

    def get_vod_task_status(self, task_id: str) -> dict:
        """특정 VOD 다운로드 작업의 상태를 반환한다."""
        return self._vod_engine.get_task_status(task_id)

    def cancel_vod(self, task_id: str) -> dict:
        """VOD 다운로드를 취소한다."""
        logger.info(f"[Service] VOD 다운로드 취소 요청: {task_id}")
        return self._vod_engine.cancel_download(task_id)

    def pause_vod(self, task_id: str) -> dict:
        """VOD 다운로드를 일시정지한다."""
        logger.info(f"[Service] VOD 다운로드 일시정지 요청: {task_id}")
        return self._vod_engine.pause_download(task_id)

    def resume_vod(self, task_id: str) -> dict:
        """VOD 다운로드를 재개한다."""
        logger.info(f"[Service] VOD 다운로드 재개 요청: {task_id}")
        return self._vod_engine.resume_download(task_id)

    async def retry_vod(self, task_id: str, cdn: str = "default") -> str:
        """VOD 다운로드를 재시도한다. 새 task_id를 반환한다."""
        logger.info(f"[Service] VOD 다운로드 재시도 요청: {task_id}")
        return await self._vod_engine.retry_download(task_id, cdn=cdn)

    def reorder_vod_tasks(self, task_ids: list[str]) -> dict:
        """VOD 다운로드 작업 순서를 재정렬한다."""
        logger.info(f"[Service] VOD 작업 순서 재정렬 요청: {len(task_ids)}개")
        return self._vod_engine.reorder_tasks(task_ids)

    def clear_completed_vod_tasks(self) -> dict:
        """대기 및 종료된 VOD 작업들을 일괄 삭제한다."""
        logger.info("[Service] VOD 작업 정리 요청")
        return self._vod_engine.clear_completed_tasks()

    def open_vod_file_location(self, task_id: str) -> dict:
        """VOD 다운로드 파일 위치를 탐색기로 연다."""
        logger.info(f"[Service] VOD 파일 위치 열기 요청: {task_id}")
        return self._vod_engine.open_file_location(task_id)

    # ── 인증 ─────────────────────────────────────────────

    def update_cookies(self, nid_aut: str, nid_ses: str) -> dict:
        """인증 쿠키를 업데이트한다."""
        self._auth.update_cookies(nid_aut, nid_ses)
        return {"message": "쿠키 업데이트 완료.", "authenticated": True}

    def get_auth_status(self) -> dict:
        """인증 상태를 반환한다."""
        return {"authenticated": self._auth.is_authenticated}
