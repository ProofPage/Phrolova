"""
Rookery: Conductor (비동기 오케스트레이터)
다중 채널 감시 루프를 관리하고, 방송 시작 시 자동 녹화를 트리거한다.
멀티 플랫폼(Chzzk, TwitCasting, X Spaces)을 단일 Conductor로 통합 관리한다.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from app.core.config import get_settings
from app.core.logger import logger
from app.engine.auth import AuthManager
from app.engine.base import Platform
from app.engine.channel import ChannelTask
from app.engine.chat import ChatArchiver
from app.engine.downloader import ChzzkLiveEngine
from app.engine.download_condition import matches_download_condition
from app.engine.events import EventBus
from app.engine.pipeline import YtdlpLivePipeline, RecordingState
from app.engine.spaces_recorder import SpacesRecorder
from app.engine.twitcasting import borrow_cookie_file
from app.services.notifications import NotificationKind
from app.store.repositories import ChannelRepository, LiveHistoryRepository

if TYPE_CHECKING:
    from app.services.notifications import NotificationService
    from app.engine.twitcasting import TwitcastingEngine
    from app.engine.x_spaces import XSpacesEngine
    from app.engine.youtube import YoutubeLiveEngine


class Conductor:
    """비동기 오케스트레이터.

    Python asyncio를 활용하여 단일 스레드로 수십 개의 채널을 동시 감시한다.
    Chzzk, TwitCasting, X Spaces를 통합 관리한다.

    채널 키 형식: "platform:channel_id" (예: "chzzk:abc123", "twitcasting:someuser")
    기존 Chzzk 전용 키("abc123")는 자동으로 "chzzk:abc123"으로 마이그레이션된다.

    주요 기능:
        - 채널 등록/제거 (플랫폼 포함)
        - 주기적 라이브 상태 확인
        - 방송 시작 감지 시 자동 녹화 트리거
        - 방송 종료 감지 시 녹화 중지
    """

    # 쿠키 검증 주기 (초) — 하루 1회
    _COOKIE_CHECK_INTERVAL = 86400
    # X Spaces 폴링 주기 (초) — 레이트 리밋 방어를 위해 5분 간격
    _X_SPACES_POLL_INTERVAL = 300

    def __init__(
        self,
        auth: Optional[AuthManager] = None,
        notifier: Optional[NotificationService] = None,
        channel_repo: Optional[ChannelRepository] = None,
        history_repo: Optional[LiveHistoryRepository] = None,
    ) -> None:
        settings = get_settings()
        self._auth = auth or AuthManager()
        self._chzzk_engine = ChzzkLiveEngine(auth=self._auth)
        self._twitcasting_engine: Optional[TwitcastingEngine] = None
        self._x_spaces_engine: Optional[XSpacesEngine] = None
        self._youtube_engine: Optional[YoutubeLiveEngine] = None
        self._channels: dict[str, ChannelTask] = {}
        self._running = False
        self._channel_repo = channel_repo or ChannelRepository()
        self._history_repo = history_repo or LiveHistoryRepository()
        self._notifier = notifier
        self._events = EventBus()
        self._spaces = SpacesRecorder(lambda: self._get_engine(Platform.X_SPACES))
        # 즉시 스캔 이벤트: composite_key → asyncio.Event
        self._scan_events: dict[str, asyncio.Event] = {}
        # X 쿠키 유효성 상태
        self._cookie_status: dict = {"valid": True, "checked_at": None, "reason": None}
        self._last_cookie_check: Optional[datetime] = None
        self._cookie_check_task: Optional[asyncio.Task] = None
        self._stats_broadcast_task: Optional[asyncio.Task] = None
        self._load_persistence()

    def _notify(
        self,
        kind: NotificationKind,
        title: str,
        description: str = "",
        color: str = "green",
        fields: Optional[dict[str, str]] = None,
    ) -> None:
        """알림을 큐에 넣는다. 논블로킹이며 실패해도 감시 루프를 막지 않는다.

        기존에는 감시 루프 안에서 Discord 응답을 await 했기 때문에
        레이트 리밋이 걸리면 라이브 감지와 녹화 시작까지 함께 지연됐다.
        """
        if self._notifier is None:
            return
        self._notifier.notify(
            kind=kind,
            title=title,
            description=description,
            color=color,
            fields=fields,
        )

    def _get_engine(self, platform: Platform):
        """플랫폼에 맞는 엔진 인스턴스를 반환한다."""
        if platform == Platform.CHZZK:
            return self._chzzk_engine
        elif platform == Platform.TWITCASTING:
            if self._twitcasting_engine is None:
                from app.engine.twitcasting import TwitcastingEngine
                self._twitcasting_engine = TwitcastingEngine()
            return self._twitcasting_engine
        elif platform == Platform.X_SPACES:
            if self._x_spaces_engine is None:
                from app.engine.x_spaces import XSpacesEngine
                self._x_spaces_engine = XSpacesEngine()
            return self._x_spaces_engine
        elif platform == Platform.YOUTUBE:
            if self._youtube_engine is None:
                from app.engine.youtube import YoutubeLiveEngine
                self._youtube_engine = YoutubeLiveEngine()
            return self._youtube_engine
        else:
            raise ValueError(f"지원하지 않는 플랫폼: {platform}")

    @staticmethod
    def make_composite_key(platform: Platform, channel_id: str) -> str:
        """복합 키를 생성한다."""
        return f"{platform.value}:{channel_id}"

    @staticmethod
    def parse_composite_key(key: str) -> tuple[Platform, str]:
        """복합 키를 (Platform, channel_id)로 파싱한다.

        ':' 없는 레거시 키는 Chzzk 채널로 처리한다.
        """
        if ":" not in key:
            return Platform.CHZZK, key
        platform_str, channel_id = key.split(":", 1)
        try:
            return Platform(platform_str), channel_id
        except ValueError:
            logger.warning(f"알 수 없는 플랫폼 값 '{platform_str}', Chzzk으로 처리합니다.")
            return Platform.CHZZK, channel_id

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def channel_count(self) -> int:
        return len(self._channels)

    def add_channel(
        self,
        channel_id: str,
        auto_record: bool = True,
        platform: Platform = Platform.CHZZK,
        download_condition: Optional[str] = None,
        watchalong_tags: Optional[str] = None,
    ) -> None:
        """감시할 채널을 등록한다."""
        composite_key = self.make_composite_key(platform, channel_id)

        if composite_key in self._channels:
            logger.warning(f"채널 '{composite_key}'은(는) 이미 등록되어 있습니다.")
            return

        task = ChannelTask(
            channel_id=channel_id,
            platform=platform,
            auto_record=auto_record,
            download_condition=download_condition,
            watchalong_tags=watchalong_tags,
        )
        self._channel_repo.upsert(
            composite_key=composite_key,
            platform=platform.value,
            channel_id=channel_id,
            auto_record=auto_record,
            tags=task.tags,
            download_condition=download_condition,
            watchalong_tags=watchalong_tags,
        )
        self._channels[composite_key] = task
        self._scan_events[composite_key] = asyncio.Event()
        logger.info(f"채널 등록: {composite_key} (auto_record={auto_record})")
        self._broadcast_status()

        # 이미 실행 중이면 즉시 감시 시작
        if self._running:
            task.monitor_task = asyncio.create_task(
                self._monitor_channel(composite_key)
            )

    def set_download_options(self, composite_key: str, auto_record: bool, condition: Optional[str], tags: Optional[str]) -> None:
        task = self._channels.get(composite_key)
        if task is None:
            raise ValueError("등록된 채널을 찾을 수 없습니다.")
        self._channel_repo.set_download_options(composite_key, auto_record, condition, tags)
        task.auto_record = auto_record
        task.download_condition = condition
        task.watchalong_tags = tags
        self._broadcast_status()
        self.trigger_scan_now(composite_key)

    @staticmethod
    def _can_auto_record(task: ChannelTask) -> bool:
        if not task.auto_record:
            return False
        if task.platform != Platform.CHZZK:
            return True
        settings = get_settings()
        return matches_download_condition(
            task.download_condition or settings.live_download_condition,
            task.broadcast_tags,
            task.watchalong_tags if task.watchalong_tags is not None else settings.watchalong_tags,
            is_watchalong=task.is_watchalong,
            watchalong_tag=task.watchalong_tag,
        )

    def _download_hold_reason(self, task: ChannelTask) -> Optional[str]:
        if not task.is_live or not task.auto_record or task.is_recording or self._can_auto_record(task):
            return None
        condition = task.download_condition or get_settings().live_download_condition
        if task.is_watchalong is None and task.broadcast_tags is None:
            return "같이보기 정보 확인 대기"
        if condition == "exclude_watchalong":
            return "같이보기 방송을 제외하도록 설정되어 있습니다."
        is_watchalong = matches_download_condition(
            "watchalong", task.broadcast_tags, "같이보기",
            is_watchalong=task.is_watchalong, watchalong_tag=task.watchalong_tag,
        )
        if task.is_watchalong is False and not is_watchalong:
            return "일반 라이브 방송입니다. 같이보기 방송만 다운로드하도록 설정되어 있습니다."
        if is_watchalong:
            return "방송의 같이보기 태그가 지정한 태그와 일치하지 않습니다."
        return "같이보기 태그 조건과 일치하지 않는 방송입니다."

    def set_auto_record(self, composite_key: str, value: bool) -> None:
        """채널의 자동 녹화 설정을 직접 지정한다."""
        task = self._channels.get(composite_key)
        if task is None:
            raise ValueError(f"채널 '{composite_key}'을(를) 찾을 수 없습니다.")
        task.auto_record = value
        logger.info(f"[{composite_key}] 자동 녹화 {'ON' if value else 'OFF'}")
        self._channel_repo.set_auto_record(composite_key, value)
        self._broadcast_status()

    def set_channel_tags(self, composite_key: str, tags: list[str]) -> None:
        """채널의 태그를 지정한다."""
        task = self._channels.get(composite_key)
        if task is None:
            raise ValueError(f"채널 '{composite_key}'을(를) 찾을 수 없습니다.")
        task.tags = tags
        logger.info(f"[{composite_key}] 태그 변경: {tags}")
        self._channel_repo.set_tags(composite_key, tags)
        self._broadcast_status()

    def remove_tag_from_all_channels(self, tag_name: str) -> bool:
        """모든 채널에서 특정 태그를 일괄 제거한다."""
        modified_any = False
        for task in self._channels.values():
            if tag_name in task.tags:
                task.tags.remove(tag_name)
                modified_any = True

        if modified_any:
            logger.info(f"모든 채널에서 태그 삭제: {tag_name}")
            self._channel_repo.remove_tag_everywhere(tag_name)
            self._broadcast_status()

        return modified_any

    async def toggle_auto_record(self, composite_key: str) -> bool:
        """채널의 자동 녹화 설정을 토글한다.

        Returns:
            변경 후의 auto_record 값.
        """
        task = self._channels.get(composite_key)
        if task is None:
            raise ValueError(f"채널 '{composite_key}'을(를) 찾을 수 없습니다.")

        task.auto_record = not task.auto_record
        logger.info(f"[{composite_key}] 자동 녹화 {'ON' if task.auto_record else 'OFF'}")
        self._channel_repo.set_auto_record(composite_key, task.auto_record)
        self._broadcast_status()

        # 이미 라이브 중인데 auto_record를 ON으로 켰고 녹화가 안 되고 있으면 즉시 시작
        if (
            task.auto_record
            and self._can_auto_record(task)
            and task.is_live
            and task.platform != Platform.X_SPACES
            and (task.pipeline is None or task.pipeline.state != RecordingState.RECORDING)
        ):
            logger.info(f"[{composite_key}] 라이브 중 자동 녹화 ON → 즉시 녹화 시작")
            await self._start_recording(composite_key, channel_name=task.channel_name, title=task.title, automatic=True)

        return task.auto_record

    def trigger_scan_now(self, composite_key: Optional[str] = None) -> None:
        """채널 폴링 주기를 무시하고 즉시 스캔을 트리거한다.

        Args:
            composite_key: 특정 채널만 스캔. None이면 모든 채널.
        """
        if composite_key:
            event = self._scan_events.get(composite_key)
            if event:
                event.set()
                logger.info(f"[{composite_key}] 즉시 스캔 요청")
        else:
            for key, event in self._scan_events.items():
                event.set()
            logger.info(f"전체 채널 즉시 스캔 요청 ({len(self._scan_events)}개)")

    async def remove_channel(self, composite_key: str) -> None:
        """채널을 감시 목록에서 제거한다."""
        task = self._channels.pop(composite_key, None)
        if task is None:
            logger.warning(f"채널 '{composite_key}'을(를) 찾을 수 없습니다.")
            return

        # 녹화 중이면 파이프라인 정지
        pipe = task.pipeline
        if pipe is not None and pipe.state in (RecordingState.RECORDING, RecordingState.ERROR):
            logger.info(f"[{composite_key}] 채널 제거 전 녹화 정지 중...")
            await self._stop_recording(composite_key)

        # X Spaces 녹화 프로세스 종료
        if task.spaces_process is not None:
            await self._stop_spaces_recording(composite_key)

        # 감시 태스크 취소
        mt = task.monitor_task
        if mt is not None and not mt.done():
            mt.cancel()

        self._scan_events.pop(composite_key, None)
        logger.info(f"채널 제거: {composite_key}")
        self._channel_repo.delete(composite_key)
        self._broadcast_status()

    async def start(self) -> None:
        """모든 등록된 채널의 감시를 시작한다."""
        if self._running:
            logger.warning("Conductor가 이미 실행 중입니다.")
            return

        self._running = True
        logger.info(f"Conductor 시작. 감시 채널 수: {self.channel_count}")

        for composite_key, task in self._channels.items():
            task.monitor_task = asyncio.create_task(
                self._monitor_channel(composite_key)
            )

        # 쿠키 검증 루프 시작
        self._cookie_check_task = asyncio.create_task(self._cookie_check_loop())
        # 녹화 통계 실시간 브로드캐스트 루프 시작
        self._stats_broadcast_task = asyncio.create_task(self._stats_broadcast_loop())

    async def stop(self) -> None:
        """모든 감시 및 녹화를 중지한다."""
        self._running = False
        logger.info("Conductor 종료 요청...")

        # 모든 이벤트 큐 종료 신호 전송
        self.broadcast_event("shutdown")

        # ── 1단계: 모든 monitor task를 먼저 취소 ─────────────────
        # retry sleep 중이거나 _start_recording 대기 중인 task가
        # 새 녹화를 시작하지 못하도록 recording stop보다 먼저 처리한다.
        for task in self._channels.values():
            mt = task.monitor_task
            if mt is not None and not mt.done():
                mt.cancel()

        if self._cookie_check_task is not None and not self._cookie_check_task.done():
            self._cookie_check_task.cancel()

        if self._stats_broadcast_task is not None and not self._stats_broadcast_task.done():
            self._stats_broadcast_task.cancel()

        # ── 2단계: 실행 중인 녹화 및 Spaces 프로세스 중지 ────────
        for composite_key, task in self._channels.items():
            pipe = task.pipeline
            if pipe is not None and pipe.state == RecordingState.RECORDING:
                await self._stop_recording(composite_key)

            if task.spaces_process is not None:
                await self._stop_spaces_recording(composite_key)

        logger.info("Conductor 종료 완료.")

    async def _stats_broadcast_loop(self) -> None:
        """녹화 중인 채널이 있을 때 2초마다 통계를 SSE로 브로드캐스트한다."""
        while self._running:
            await asyncio.sleep(2.0)
            any_recording = any(
                t.pipeline is not None and t.pipeline.state == RecordingState.RECORDING
                for t in self._channels.values()
            )
            if any_recording and self._events.subscriber_count:
                self._broadcast_status()

    async def _cookie_check_loop(self) -> None:
        """X 쿠키 유효성을 하루 1회 주기로 검증한다."""
        while self._running:
            try:
                # 마지막 검증 이후 24시간이 지났을 때만 실행
                now = datetime.now()
                if (
                    self._last_cookie_check is None
                    or (now - self._last_cookie_check).total_seconds() >= self._COOKIE_CHECK_INTERVAL
                ):
                    await self._check_x_cookie()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"쿠키 검증 루프 오류: {e}")

            # 1시간마다 깨어나서 24시간 경과 여부 확인
            await asyncio.sleep(3600)

    async def _check_x_cookie(self) -> None:
        """X 쿠키 유효성을 검증하고 만료 시 Discord 알림을 전송한다."""
        from app.engine.x_spaces import verify_cookie

        settings = get_settings()
        cookie_file = settings.x_cookie_file

        # X Spaces 채널이 없으면 검증 생략
        has_spaces = any(
            t.platform == Platform.X_SPACES for t in self._channels.values()
        )
        if not has_spaces:
            return

        if not cookie_file:
            self._cookie_status = {
                "valid": False,
                "checked_at": datetime.now().isoformat(),
                "reason": "쿠키 파일 경로가 설정되지 않았습니다.",
            }
            self._last_cookie_check = datetime.now()
            return

        logger.info("X 쿠키 유효성 검증 중...")
        result = await verify_cookie(cookie_file)
        prev_valid = self._cookie_status.get("valid", True)
        self._cookie_status = result
        self._last_cookie_check = datetime.now()

        if not result["valid"]:
            logger.warning(f"X 쿠키 만료 감지: {result.get('reason')}")
            # 이전에 유효했거나 처음 감지된 경우에만 알림 (반복 알림 방지)
            if prev_valid:
                self._notify(
                    NotificationKind.COOKIE_EXPIRED,
                    title="⚠️ X 쿠키 만료",
                    description=(
                        "X Spaces 쿠키가 만료되었습니다.\n"
                        "설정 페이지에서 쿠키 파일을 갱신해주세요."
                    ),
                    color="red",
                    fields={"이유": result.get("reason") or "알 수 없음"},
                )
        else:
            logger.info("X 쿠키 유효성 확인 완료: 정상")

    def get_cookie_status(self) -> dict:
        """X 쿠키 유효성 상태를 반환한다."""
        return dict(self._cookie_status)

    async def download_space(self, space_url: str) -> dict:
        """Space URL로 직접 다운로드한다.

        채널 등록 없이 space_url만으로 즉시 다운로드 가능.
        UserTweets API를 사용하지 않으므로 레이트 리밋 문제 없음.

        Args:
            space_url: X/Twitter Space URL (https://x.com/i/spaces/...)

        Returns:
            성공: {"started": True, "space_id": ..., "title": ..., "state": ..., "output": ...}
            실패: {"error": "오류 메시지"}
        """
        from app.engine.x_spaces import XSpacesEngine

        engine: XSpacesEngine = self._get_engine(Platform.X_SPACES)
        settings = get_settings()

        return await engine.download_by_space_url(
            space_url=space_url,
            output_dir=settings.effective_live_download_dir,
            cookie_file=settings.x_cookie_file,
        )

    async def capture_space(self, username: str) -> dict:
        """X Spaces 채널의 m3u8 URL을 즉시 1회 조회한다.

        Discord /capture-space 커맨드에서 호출. 레이트 리밋 문제로 자동 폴링을
        비활성화한 대신 사용자가 원하는 시점에 수동으로 캡처를 트리거한다.

        Returns:
            {
                "captured": bool,
                "m3u8_url": str | None,
                "is_live": bool,
                "title": str | None,
                "channel_name": str | None,
            }
        """
        composite_key = self.make_composite_key(Platform.X_SPACES, username)
        task = self._channels.get(composite_key)

        if task is None:
            return {"captured": False, "m3u8_url": None, "is_live": False,
                    "title": None, "channel_name": None, "error": f"등록되지 않은 채널: {username}"}

        try:
            engine = self._get_engine(Platform.X_SPACES)
            status = await engine.check_live_status(username)
        except Exception as e:
            logger.error(f"[{composite_key}] capture_space 조회 실패: {e}")
            return {"captured": False, "m3u8_url": None, "is_live": False,
                    "title": None, "channel_name": None, "error": str(e)}

        # 상태 업데이트
        task.is_live = status["is_live"]
        task.channel_name = status.get("channel_name")
        task.title = status.get("title")
        task._current_space_id = status.get("space_id")

        new_m3u8 = status.get("m3u8_url")
        if new_m3u8:
            task.captured_m3u8_url = new_m3u8
            task.captured_m3u8_at = datetime.now().isoformat()
            self._save_capture_state(composite_key)
            self._broadcast_status()
            logger.info(f"[{composite_key}] capture_space: m3u8 URL 캡처 완료")

        return {
            "captured": bool(new_m3u8),
            "m3u8_url": new_m3u8,
            "is_live": status["is_live"],
            "title": status.get("title"),
            "channel_name": status.get("channel_name"),
        }

    def _save_capture_state(self, composite_key: str) -> None:
        """X Spaces 캡처 URL 상태를 저장한다.

        기존에는 채널 하나가 바뀔 때마다 전체 목록을 JSON으로 다시 썼다.
        지금은 해당 행만 UPDATE 한다.
        """
        task = self._channels.get(composite_key)
        if task is None:
            return
        try:
            self._channel_repo.update_capture(
                composite_key=composite_key,
                captured_m3u8_url=task.captured_m3u8_url,
                captured_m3u8_at=task.captured_m3u8_at,
                master_url=task.master_url,
                master_url_captured_at=task.master_url_captured_at,
                master_url_file=task.master_url_file,
            )
        except Exception as e:
            logger.error(f"[{composite_key}] 캡처 상태 저장 실패: {e}")

    def _broadcast_status(self) -> None:
        """현재 전체 채널 상태를 SSE로 밀어낸다."""
        self._events.publish("status_update", self.get_all_status())

    # ── SSE 이벤트 Pub-Sub ─────────────────────────────────

    def add_event_queue(self, queue: asyncio.Queue) -> None:
        self._events.subscribe(queue)

    def remove_event_queue(self, queue: asyncio.Queue) -> None:
        self._events.unsubscribe(queue)

    def broadcast_event(self, event_type: str, data: Optional[dict | list] = None) -> None:
        self._events.publish(event_type, data)

    def _load_persistence(self) -> None:
        """저장소에서 채널 목록을 복원한다."""
        try:
            records = self._channel_repo.list_all()
        except Exception as e:
            logger.error(f"채널 목록 로드 실패: {e}")
            return

        for record in records:
            try:
                platform = Platform(record["platform"])
            except ValueError:
                logger.warning(
                    f"알 수 없는 플랫폼 '{record['platform']}', Chzzk으로 처리합니다."
                )
                platform = Platform.CHZZK

            composite_key = self.make_composite_key(platform, record["channel_id"])
            task = ChannelTask(
                channel_id=record["channel_id"],
                platform=platform,
                auto_record=record["auto_record"],
                tags=list(record["tags"]),
                download_condition=record.get("download_condition"),
                watchalong_tags=record.get("watchalong_tags"),
            )
            # X Spaces 캡처 URL 복원
            if platform == Platform.X_SPACES:
                task.captured_m3u8_url = record["captured_m3u8_url"]
                task.captured_m3u8_at = record["captured_m3u8_at"]
                task.master_url = record["master_url"]
                task.master_url_captured_at = record["master_url_captured_at"]
                task.master_url_file = record["master_url_file"]

            self._channels[composite_key] = task
            self._scan_events[composite_key] = asyncio.Event()

        if records:
            logger.info(f"채널 목록 로드 완료 ({len(records)}개)")

    def _poll_interval_for(self, task: Optional[ChannelTask]) -> int:
        """이 채널을 몇 초마다 확인할지 정한다.

        X Spaces는 X API의 레이트 리밋이 빡빡해 짧은 주기로 돌면 차단당한다.
        """
        if task and task.platform == Platform.X_SPACES:
            return self._X_SPACES_POLL_INTERVAL
        return get_settings().monitor_interval

    @staticmethod
    def _apply_status(task: ChannelTask, status: dict) -> None:
        """조회한 라이브 상태를 채널에 반영한다."""
        task.is_live = status["is_live"]
        task.last_error = None
        task.channel_name = status.get("channel_name")
        task.title = status.get("title")
        task.category = status.get("category")
        task.broadcast_tags = status.get("broadcast_tags")
        task.is_watchalong = status.get("is_watchalong")
        task.watchalong_tag = status.get("watchalong_tag")
        task.live_started_at = status.get("live_started_at")
        task.viewer_count = status.get("viewer_count", 0)
        task.thumbnail_url = status.get("thumbnail_url")
        task.profile_image_url = status.get("profile_image_url")

    def _capture_space_master_url(
        self, composite_key: str, task: ChannelTask, status: dict
    ) -> None:
        """X Spaces의 master URL을 Space당 한 번만 붙잡아 둔다.

        dynamic m3u8 URL은 금방 만료되지만 master URL은 종료 후에도 한동안 살아 있어,
        실시간 녹화가 실패해도 수동으로 받아낼 마지막 수단이 된다. 그래서 파일로도
        남기고 알림으로도 보낸다.
        """
        task._current_space_id = status.get("space_id")
        new_master = status.get("master_url")
        new_m3u8 = status.get("m3u8_url")

        # 이미 잡아둔 Space라면 다시 알리지 않는다.
        if not new_master or task.master_url:
            return

        now_iso = datetime.now().isoformat()
        task.master_url = new_master
        task.master_url_captured_at = now_iso
        task.captured_m3u8_url = new_m3u8
        task.captured_m3u8_at = now_iso
        # master URL을 파일로 저장 (녹화 실패 시 백업)
        task.master_url_file = self._spaces.save_master_url_file(
            task, new_master, task._current_space_id
        )
        logger.info(
            f"[{composite_key}] 🎙️ Space master URL 캡처 완료 "
            f"(space_id={task._current_space_id})"
        )
        self._save_capture_state(composite_key)
        self._broadcast_status()
        # 알림: master URL 캡처 + 자동 녹화 상태 안내
        # (Master URL은 1024자를 넘을 수 있어 알림 계층에서 분할 전송한다)
        rec_status = (
            "🔴 자동 녹화 시작됨 (실시간 저장 중)"
            if task.auto_record
            else "⏸️ 자동 녹화 OFF — 아래 URL로 수동 다운로드 가능"
        )
        self._notify(
            NotificationKind.SPACE_DETECTED,
            title="🎙️ X Spaces 감지",
            description=(
                f"**@{task.channel_name or task.channel_id}** — "
                f"{task.title or 'X Spaces'}\n{rec_status}"
            ),
            color="blue",
            fields={
                "Master URL": new_master,
                "URL 파일": (
                    f"`{task.master_url_file}`"
                    if task.master_url_file
                    else "저장 실패"
                ),
            },
        )

    def _record_live_detection(self, composite_key: str) -> None:
        """라이브 감지를 하루 1회 저장소에 남긴다 (날짜 경계는 저장소가 처리).

        메모리에만 두면 재시작할 때마다 통계가 초기화된다. 기록에 실패해도
        감시는 계속돼야 하므로 예외를 삼킨다.
        """
        try:
            self._history_repo.record_detection(composite_key)
        except Exception as e:
            logger.error(f"[{composite_key}] 라이브 감지 기록 실패: {e}")

    async def _handle_live_started(
        self, composite_key: str, task: ChannelTask, retry_count: int
    ) -> int:
        """방송 시작을 알리고, 자동 녹화가 켜져 있으면 녹화를 시작한다.

        새 방송이 시작됐으므로 재시도 횟수는 0부터 다시 센다.
        """
        logger.info(
            f"[{composite_key}] 🔴 방송 시작 감지! "
            f"스트리머: {task.channel_name}, 제목: {task.title}"
        )
        # 감지 즉시 알림 — 녹화 준비(CDN 대기 5초 + yt-dlp 기동)를
        # 기다리지 않는다. 녹화 결과는 별도 알림으로 이어진다.
        # X Spaces는 master URL 캡처 알림이 이 역할을 대신한다.
        if task.platform != Platform.X_SPACES:
            self._notify(
                NotificationKind.LIVE_DETECTED,
                title="🔴 방송 시작",
                description=(
                    f"**{task.channel_name or task.channel_id}**\n"
                    f"{task.title or '제목 없음'}"
                ),
                color="green",
                fields={
                    "플랫폼": task.platform.value,
                    "카테고리": task.category or "N/A",
                    "자동 녹화": "ON" if task.auto_record else "OFF",
                },
            )

        if self._can_auto_record(task):
            await self._start_recording(
                composite_key,
                channel_name=task.channel_name,
                title=task.title,
                automatic=True,
            )
            return 0
        if task.auto_record and task.platform == Platform.CHZZK:
            settings = get_settings()
            logger.info(
                f"[{composite_key}] 자동 다운로드 조건으로 시작 보류 "
                f"(조건={task.download_condition or settings.live_download_condition}, "
                f"공식 같이보기={task.is_watchalong}, 같이보기 태그={task.watchalong_tag}, "
                f"방송 태그={task.broadcast_tags})."
            )
        return retry_count

    async def _handle_live_ended(self, composite_key: str, task: ChannelTask) -> None:
        """방송 종료를 처리한다."""
        logger.info(f"[{composite_key}] ⚫ 방송 종료 감지.")
        # X Spaces: 다음 Space를 위해 master_url 초기화
        if task.platform == Platform.X_SPACES:
            task.clear_space_capture()
            self._save_capture_state(composite_key)
            self._broadcast_status()
            logger.info(f"[{composite_key}] 🎙️ Space 종료 — master URL 초기화 완료.")
        await self._stop_recording(composite_key)

    async def _retry_stalled_recording(
        self, composite_key: str, task: ChannelTask, retry_count: int, max_retries: int
    ) -> int:
        """방송은 켜져 있는데 녹화가 멈춘 경우 다시 시작한다. 새 재시도 횟수를 돌려준다."""
        pipe = task.pipeline
        if pipe is None or pipe.state not in (RecordingState.ERROR, RecordingState.COMPLETED):
            return retry_count

        if retry_count < max_retries:
            retry_count += 1
            logger.warning(
                f"[{composite_key}] 녹화 중단 감지. "
                f"자동 재녹화 시도 ({retry_count}/{max_retries})..."
            )
            await asyncio.sleep(5)
            # 대기하는 동안 종료 신호가 왔으면 새 녹화를 띄우지 않는다.
            if not self._running:
                return retry_count
            await self._start_recording(
                composite_key,
                channel_name=task.channel_name,
                title=task.title,
                is_retry=True,
            )
        elif retry_count == max_retries:
            # 한 번만 알리고 더는 시도하지 않도록 카운트를 한 칸 더 올린다.
            retry_count += 1
            task.last_error = "최대 재시도 횟수 초과로 녹화 중단됨"
            logger.error(
                f"[{composite_key}] 최대 재시도 횟수 초과. "
                f"녹화 시작 버튼으로 수동 재시작하세요."
            )
        return retry_count

    async def _wait_for_next_scan(self, composite_key: str, interval: float) -> None:
        """다음 확인까지 기다린다. 즉시 스캔 요청이 오면 기다리지 않고 깨어난다."""
        scan_event = self._scan_events.get(composite_key)
        if scan_event is None:
            await asyncio.sleep(interval)
            return
        scan_event.clear()
        try:
            await asyncio.wait_for(scan_event.wait(), timeout=float(interval))
        except asyncio.TimeoutError:
            pass

    async def _monitor_channel(self, composite_key: str) -> None:
        """단일 채널의 라이브 상태를 주기적으로 확인한다.

        한 번 도는 동안 하는 일은 네 가지다 — 상태 조회, 채널에 반영,
        상태 변화에 따른 처리, 다음 차례까지 대기. 각 처리는 아래 메서드로 나눠 두었고
        여기서는 어떤 조건에 무엇이 일어나는지만 읽히게 한다.
        """
        settings = get_settings()
        task = self._channels.get(composite_key)
        interval = self._poll_interval_for(task)
        retry_count = 0
        max_retries = settings.max_record_retries

        logger.info(f"[{composite_key}] 감시 시작 (주기: {interval}초)")

        while self._running:
            try:
                task = self._channels.get(composite_key)
                if task is None:
                    break

                engine = self._get_engine(task.platform)
                status = await engine.check_live_status(task.channel_id)

                was_live = task.is_live
                self._apply_status(task, status)
                # 조건 보류 및 자동 녹화 OFF도 방송 정보는 즉시 화면에 반영한다.
                self._broadcast_status()

                if task.platform == Platform.X_SPACES:
                    self._capture_space_master_url(composite_key, task, status)

                if status["is_live"]:
                    self._record_live_detection(composite_key)

                # ── 방송 시작 감지 ──
                if status["is_live"] and not was_live:
                    retry_count = await self._handle_live_started(
                        composite_key, task, retry_count
                    )

                # ── 방송 종료 감지 ──
                elif not status["is_live"] and was_live:
                    await self._handle_live_ended(composite_key, task)
                    retry_count = 0

                # ── 채팅 아카이빙 동적 시작 (녹화 도중 설정을 켠 경우) ──
                elif (
                    status["is_live"]
                    and task.pipeline is not None
                    and task.pipeline.state == RecordingState.RECORDING
                    and task.chat_archiver is None
                ):
                    await self._start_chat_archiver(composite_key, task, reason="동적 시작")

                # ── 녹화 오류 시 자동 재시작 (Chzzk/TwitCasting 전용) ──
                elif status["is_live"] and self._can_auto_record(task) and task.platform != Platform.X_SPACES:
                    if task.pipeline is None:
                        await self._start_recording(
                            composite_key, channel_name=task.channel_name,
                            title=task.title, automatic=True,
                        )
                        retry_count = 0
                    else:
                        retry_count = await self._retry_stalled_recording(
                            composite_key, task, retry_count, max_retries
                        )
                    if not self._running:
                        break

            except asyncio.CancelledError:
                break
            except BaseException as e:
                task.last_error = f"감시 오류: {str(e)}"
                logger.error(f"[{composite_key}] 감시 오류: {e}", exc_info=e)

            await self._wait_for_next_scan(composite_key, interval)

    async def _start_chat_archiver(
        self,
        composite_key: str,
        task: ChannelTask,
        reason: str = "시작",
    ) -> None:
        """녹화 중인 채널의 채팅 아카이빙을 시작한다.

        녹화 시작 직후와, 녹화 도중 설정을 켠 경우 양쪽에서 호출된다.
        채팅 저장 실패가 녹화를 중단시켜서는 안 되므로 예외를 삼킨다.
        """
        # 채팅 아카이빙은 Chzzk만 지원한다.
        if task.platform != Platform.CHZZK:
            return
        if not get_settings().chat_archive_enabled:
            return
        if task.chat_archiver is not None:
            return

        pipeline = task.pipeline
        if pipeline is None:
            return

        try:
            output_file = pipeline.get_status().get("output_path")
            if not output_file:
                return

            chat_file = Path(output_file).with_suffix(".jsonl")
            archiver = ChatArchiver(
                channel_id=task.channel_id,
                output_path=chat_file,
                auth=self._auth,
            )
            await archiver.start()
            task.chat_archiver = archiver
            logger.info(f"[{composite_key}] 채팅 아카이빙 {reason}: {chat_file}")
        except Exception as e:
            logger.error(f"[{composite_key}] 채팅 아카이빙 {reason} 실패: {e}")

    async def _stop_recording(self, composite_key: str) -> None:
        """채널의 녹화 및 채팅 아카이빙을 중지한다."""
        task = self._channels.get(composite_key)
        if task is None:
            return

        # X Spaces 녹화 중지
        if task.platform == Platform.X_SPACES:
            await self._stop_spaces_recording(composite_key)
            return

        # Chzzk/TwitCasting 파이프라인 중지
        pipe = task.pipeline
        if pipe is not None and pipe.state == RecordingState.RECORDING:
            await pipe.stop_recording()

            # ── 알림: 녹화 완료 ──
            status = pipe.get_status()
            duration = status.get("duration_seconds", 0) or 0
            output_file = status.get("output_file") or status.get("output_path") or "N/A"
            file_size = status.get("file_size_bytes", 0) / (1024 * 1024)
            duration_str = (
                f"{duration // 60:.0f}분 {duration % 60:.0f}초" if duration > 0 else "N/A"
            )
            self._notify(
                NotificationKind.RECORDING_COMPLETED,
                title="⏹ 녹화 완료",
                description=f"채널: **{task.channel_name or composite_key}**",
                color="blue",
                fields={
                    "녹화 시간": duration_str,
                    "파일 크기": f"{file_size:.1f} MB",
                    "저장 경로": str(output_file),
                },
            )

        # 녹화 완료 이력 저장
        if pipe is not None and pipe.state == RecordingState.COMPLETED:
            self._save_live_history(composite_key, task, pipe.get_status())

        # 채팅 아카이빙 중지
        archiver = task.chat_archiver
        if archiver is not None:
            try:
                await archiver.stop()
                task.chat_archiver = None
            except Exception as e:
                logger.error(f"[{composite_key}] 채팅 아카이빙 중지 실패: {e}")

        # 파이프라인 레퍼런스 정리 (모니터 루프의 의도치 않은 자동 재시작 방지)
        task.pipeline = None
        # 정지 후 프론트엔드에 즉시 상태 업데이트
        self._broadcast_status()

    async def _start_recording(
        self,
        composite_key: str,
        channel_name: Optional[str] = None,
        title: Optional[str] = None,
        is_retry: bool = False,
        automatic: bool = False,
    ) -> None:
        """채널의 녹화를 시작한다."""
        task = self._channels.get(composite_key)
        if task is None:
            return
        if (automatic or is_retry) and not self._can_auto_record(task):
            return

        # X Spaces는 별도 경로
        if task.platform == Platform.X_SPACES:
            await self._start_spaces_recording(composite_key, channel_name=channel_name, title=title)
            return

        try:
            settings = get_settings()
            quality = settings.recording_quality or "best"
            engine = self._get_engine(task.platform)
            live_url = engine.get_stream_url(task.channel_id)
            cookie_str = self._auth.get_ytdlp_cookies()

            # 최초 감지 시 CDN이 스트림 URL을 준비하는 시간을 확보
            if not is_retry:
                logger.debug(f"[{composite_key}] 스트림 CDN 준비 대기 (5초)...")
                await asyncio.sleep(5)
                if not self._running:
                    return
                if automatic and not self._can_auto_record(task):
                    return

            pipeline = YtdlpLivePipeline(channel_id=task.channel_id)
            task.pipeline = pipeline

            # URL 추출이 끝나면 사본은 필요 없다. 녹화 중인 ffmpeg는 쿠키 파일을 읽지 않는다.
            with borrow_cookie_file(live_url) as fallback_cookie_file:
                await pipeline.start_recording(
                    stream_obj=live_url,
                    streamer_name=channel_name or task.channel_name,
                    title=title or task.title,
                    category=task.category,
                    live_started_at=task.live_started_at,
                    quality=quality,
                    cookie_str=cookie_str,
                    fallback_cookie_file=fallback_cookie_file,
                    thumbnail_url=task.thumbnail_url,
                )
            logger.info(f"[{composite_key}] 자동 라이브 녹화 시작 (quality={quality}).")

            # ── 알림: 녹화 시작 (재시도 시엔 생략) ──
            if not is_retry:
                self._notify(
                    NotificationKind.RECORDING_STARTED,
                    title="🎬 녹화 시작",
                    description=(
                        f"채널: **{channel_name or composite_key}**\n제목: {title or 'N/A'}"
                    ),
                    color="green",
                    fields={"화질": quality, "플랫폼": task.platform.value},
                )

            # ── 채팅 아카이빙 시작 ──
            await self._start_chat_archiver(composite_key, task)
        except Exception as e:
            task.last_error = f"녹화 시작 오류: {str(e)}"
            logger.error(f"[{composite_key}] 녹화 시작 실패: {e}")

            self._notify(
                NotificationKind.RECORDING_FAILED,
                title="❌ 녹화 시작 실패",
                description=f"채널: **{channel_name or composite_key}**\n오류: {str(e)}",
                color="red",
            )

        # 녹화 시작/실패 후 프론트엔드에 즉시 상태 업데이트
        self._broadcast_status()

    async def _start_spaces_recording(
        self,
        composite_key: str,
        channel_name: Optional[str] = None,
        title: Optional[str] = None,
    ) -> None:
        """X Spaces 녹화를 시작한다 (프로세스 관리는 SpacesRecorder가 담당)."""
        task = self._channels.get(composite_key)
        if task is None:
            return

        display_name = channel_name or task.display_name

        try:
            await self._spaces.start(task, channel_name=channel_name, title=title)
            logger.info(
                f"[{composite_key}] X Spaces 녹화 시작 "
                f"(space_id={task._current_space_id})."
            )
            self._notify(
                NotificationKind.RECORDING_STARTED,
                title="🎬 Spaces 녹화 시작",
                description=f"채널: **{display_name}**\n제목: {title or 'N/A'}",
                color="green",
                fields={"플랫폼": "X Spaces"},
            )
        except Exception as e:
            task.last_error = f"Spaces 녹화 오류: {str(e)}"
            logger.error(f"[{composite_key}] Spaces 녹화 시작 실패: {e}")
            self._notify(
                NotificationKind.RECORDING_FAILED,
                title="❌ Spaces 녹화 시작 실패",
                description=f"채널: **{display_name}**\n오류: {str(e)}",
                color="red",
            )

        self._broadcast_status()

    async def _stop_spaces_recording(self, composite_key: str) -> None:
        """X Spaces 녹화 프로세스를 종료한다."""
        task = self._channels.get(composite_key)
        if task is None or task.spaces_process is None:
            return

        await self._spaces.stop(task, label=composite_key)
        self._broadcast_status()

    async def start_manual_recording(self, composite_key: str) -> dict:
        """수동으로 특정 채널의 녹화를 시작한다."""
        task = self._channels.get(composite_key)
        if task is None:
            # 미등록 채널 처리: 레거시 호환 (Chzzk 채널로 처리)
            platform, channel_id = self.parse_composite_key(composite_key)
            task = ChannelTask(
                channel_id=channel_id,
                platform=platform,
                auto_record=False,
            )
            self._channels[composite_key] = task

        pipe = task.pipeline
        if pipe is not None and pipe.state == RecordingState.RECORDING:
            return {"error": "이미 녹화 중입니다.", **pipe.get_status()}

        # 수동 녹화 시에도 상태 정보 업데이트 시도
        try:
            engine = self._get_engine(task.platform)
            status = await engine.check_live_status(task.channel_id)
            task.channel_name = status.get("channel_name")
            task.title = status.get("title")
            if task.platform == Platform.X_SPACES:
                task._current_space_id = status.get("space_id")
        except Exception:
            pass

        await self._start_recording(composite_key)

        if task.platform == Platform.X_SPACES:
            return {"message": "Spaces 녹화 시작됨.", "space_id": task._current_space_id}

        pipe = task.pipeline
        if pipe is not None:
            return pipe.get_status()
        return {"error": "녹화 시작 실패."}

    async def stop_manual_recording(self, composite_key: str) -> dict:
        """수동으로 특정 채널의 녹화를 중지한다."""
        task = self._channels.get(composite_key)
        if task is None:
            return {"error": "녹화 중인 채널이 아닙니다."}

        if task.platform == Platform.X_SPACES:
            await self._stop_spaces_recording(composite_key)
            return {"message": "Spaces 녹화 중지됨."}

        pipe = task.pipeline
        if pipe is None:
            return {"error": "녹화 중인 채널이 아닙니다."}

        await self._stop_recording(composite_key)
        return pipe.get_status()

    async def stop_all_recordings(self) -> dict:
        """현재 진행 중인 모든 채널의 녹화를 중지한다."""
        stopped_count = 0
        for composite_key, task in list(self._channels.items()):
            if task.platform == Platform.X_SPACES and task.spaces_process is not None:
                await self._stop_spaces_recording(composite_key)
                stopped_count += 1
            elif task.pipeline is not None and task.pipeline.state == RecordingState.RECORDING:
                await self._stop_recording(composite_key)
                stopped_count += 1

        return {"stopped_count": stopped_count, "message": f"{stopped_count}개의 채널 녹화를 중지했습니다."}

    def get_all_status(self) -> list[dict]:
        """모든 채널의 상태를 반환한다."""
        result: list[dict] = []
        for composite_key, task in self._channels.items():
            status: dict = {
                "composite_key": composite_key,
                "platform": task.platform.value,
                "channel_id": task.channel_id,
                "auto_record": task.auto_record,
                "is_live": task.is_live,
                "recording": None,
                "chat_archiving": None,
                "channel_name": task.channel_name,
                "title": task.title,
                "category": task.category,
                "viewer_count": task.viewer_count,
                "thumbnail_url": task.thumbnail_url,
                "profile_image_url": task.profile_image_url,
                "tags": getattr(task, "tags", []),
                "broadcast_tags": task.broadcast_tags,
                "is_watchalong": task.is_watchalong,
                "watchalong_tag": task.watchalong_tag,
                "download_condition": task.download_condition,
                "watchalong_tags": task.watchalong_tags,
                "auto_record_eligible": self._can_auto_record(task),
                "download_hold_reason": self._download_hold_reason(task),
                "last_error": getattr(task, "last_error", None),
            }
            pipe = task.pipeline
            if pipe is not None:
                status["recording"] = pipe.get_status()

            if task.spaces_process is not None:
                status["recording"] = {
                    "is_recording": True,
                    "state": "recording",
                    "platform": "x_spaces",
                    "space_id": task._current_space_id,
                }

            # X Spaces URL 캡처 정보
            if task.platform == Platform.X_SPACES:
                status["master_url"] = task.master_url
                status["master_url_captured_at"] = task.master_url_captured_at
                status["master_url_file"] = task.master_url_file
                status["captured_m3u8_url"] = task.captured_m3u8_url
                status["captured_m3u8_at"] = task.captured_m3u8_at

            archiver = task.chat_archiver
            if archiver is not None:
                status["chat_archiving"] = archiver.get_status()

            result.append(status)
        return result

    # ── 라이브 이력 관리 ─────────────────────────────────────

    def _save_live_history(self, composite_key: str, task: ChannelTask, pipe_status: dict) -> None:
        """라이브 녹화 완료 이력을 저장한다.

        기존 JSON 구현은 매번 전체 파일을 읽고 다시 썼기 때문에 이력이 쌓일수록
        녹화 종료 처리가 느려졌다. 지금은 INSERT 한 번이다.
        """
        try:
            self._history_repo.add_session({
                "composite_key": composite_key,
                "platform": task.platform.value,
                "channel_id": task.channel_id,
                "channel_name": task.channel_name or task.channel_id,
                "started_at": pipe_status.get("start_time"),
                "ended_at": datetime.now().isoformat(),
                "duration_seconds": pipe_status.get("duration_seconds", 0),
                "file_size_bytes": pipe_status.get("file_size_bytes", 0),
                "output_path": pipe_status.get("output_path"),
            })
            logger.debug(f"[{composite_key}] 라이브 이력 저장 완료.")
        except Exception as e:
            logger.error(f"[{composite_key}] 라이브 이력 저장 실패: {e}")

    def get_live_history(self) -> list[dict]:
        """저장된 라이브 녹화 이력을 반환한다."""
        try:
            return self._history_repo.list_sessions()
        except Exception as e:
            logger.error(f"라이브 이력 조회 실패: {e}")
            return []

    def get_live_detections(self) -> dict[str, int]:
        """채널별 라이브 감지 횟수를 반환한다 (최근 30일 기준, 하루 1회 카운트).

        Returns:
            { composite_key: 최근 30일 내 감지된 날짜 수 }
        """
        try:
            return self._history_repo.detection_counts(days=30)
        except Exception as e:
            logger.error(f"라이브 감지 통계 조회 실패: {e}")
            return {}
