"""
Phrolova: Conductor (비동기 오케스트레이터)
다중 채널 감시 루프를 관리하고, 방송 시작 시 자동 녹화를 트리거한다.
CHZZK, YouTube, SOOP, CIME를 단일 Conductor로 통합 관리한다.
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
from app.engine.downloader import ChzzkLiveEngine
from app.engine.download_condition import matches_download_condition
from app.engine.events import EventBus
from app.engine.pipeline import YtdlpLivePipeline, RecordingState
from app.services.notifications import NotificationKind
from app.store.repositories import ChannelRepository, LiveHistoryRepository

if TYPE_CHECKING:
    from app.services.notifications import NotificationService
    from app.engine.youtube import YoutubeLiveEngine


class Conductor:
    """비동기 오케스트레이터.

    Python asyncio를 활용하여 단일 스레드로 수십 개의 채널을 동시 감시한다.
    CHZZK, YouTube, SOOP, CIME를 통합 관리한다.

    채널 키 형식: "platform:channel_id" (예: "chzzk:abc123", "youtube:someuser")
    기존 Chzzk 전용 키("abc123")는 자동으로 "chzzk:abc123"으로 마이그레이션된다.

    주요 기능:
        - 채널 등록/제거 (플랫폼 포함)
        - 주기적 라이브 상태 확인
        - 방송 시작 감지 시 자동 녹화 트리거
        - 방송 종료 감지 시 녹화 중지
    """

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
        self._youtube_engine: Optional[YoutubeLiveEngine] = None
        self._extra_engines: dict[Platform, object] = {}
        self._channels: dict[str, ChannelTask] = {}
        self._running = False
        self._channel_repo = channel_repo or ChannelRepository()
        self._history_repo = history_repo or LiveHistoryRepository()
        self._notifier = notifier
        self._events = EventBus()
        self._scan_events: dict[str, asyncio.Event] = {}
        self._stats_broadcast_task: Optional[asyncio.Task] = None
        from app.engine.recording_finalizer import RecordingFinalizer

        self.finalizer = RecordingFinalizer(
            self._broadcast_status, self._notify_finalized
        )
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
            kind=kind, title=title, description=description, color=color, fields=fields
        )

    def _notify_finalized(self, job):
        success = job["state"] == "completed"
        try:
            self._notify(
                (
                    NotificationKind.RECORDING_COMPLETED
                    if success
                    else NotificationKind.RECORDING_FAILED
                ),
                title="녹화 파일 처리 완료" if success else "녹화 파일 변환 실패",
                description=f"채널: {job['channel_name']}\n형식: {job['target_format'].upper()}",
                color="green" if success else "red",
                fields={
                    "파일": job.get("output_path") or job["source_paths"][0],
                    "상태": "파일 검사 완료" if success else "원본 TS 보관",
                },
            )
        except Exception as error:
            logger.warning(f"파일 처리 알림 등록 실패: {error}")

    def _get_engine(self, platform: Platform):
        """플랫폼에 맞는 엔진 인스턴스를 반환한다."""
        if platform == Platform.CHZZK:
            return self._chzzk_engine
        elif platform == Platform.YOUTUBE:
            if self._youtube_engine is None:
                from app.engine.youtube import YoutubeLiveEngine

                self._youtube_engine = YoutubeLiveEngine()
            return self._youtube_engine
        elif platform in (Platform.SOOP, Platform.CIME):
            if platform not in self._extra_engines:
                from app.engine.soop import SoopLiveEngine
                from app.engine.cime import CimeLiveEngine

                self._extra_engines[platform] = (
                    SoopLiveEngine if platform == Platform.SOOP else CimeLiveEngine
                )()
            return self._extra_engines[platform]
        else:
            raise ValueError(f"지원하지 않는 플랫폼: {platform}")

    async def get_live_preview_url(self, composite_key: str) -> str:
        """Resolve playback independently of the channel's recording pipeline."""
        task = self._channels.get(composite_key)
        if task is None:
            raise KeyError(composite_key)
        if not task.is_live:
            raise ValueError("오프라인")
        engine = self._get_engine(task.platform)
        if task.platform in (Platform.CHZZK, Platform.SOOP, Platform.CIME):
            return await engine.get_preview_url(task.channel_id)
        page_url = engine.get_stream_url(task.channel_id)
        pipeline = YtdlpLivePipeline(task.channel_id)
        from app.engine.youtube_support import youtube_cookies

        with youtube_cookies() as cookie_file:
            url, _, _ = await asyncio.wait_for(
                pipeline._extract_preview_hls_url(page_url, cookie_file=cookie_file),
                timeout=30,
            )
        return url

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
            return (Platform.CHZZK, key)
        platform_str, channel_id = key.split(":", 1)
        try:
            return (Platform(platform_str), channel_id)
        except ValueError:
            logger.warning(
                f"알 수 없는 플랫폼 값 '{platform_str}', Chzzk으로 처리합니다."
            )
            return (Platform.CHZZK, channel_id)

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
        recording_quality: Optional[str] = None,
        output_format: Optional[str] = None,
        output_format_provided: bool = False,
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
            recording_quality=recording_quality,
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
        if recording_quality is not None:
            self._channel_repo.set_recording_quality(composite_key, recording_quality)
        if output_format_provided:
            task.output_format = output_format
            self.finalizer.db.execute(
                "UPDATE channels SET output_format=? WHERE composite_key=?",
                (output_format, composite_key),
            )
        self._scan_events[composite_key] = asyncio.Event()
        logger.info(f"채널 등록: {composite_key} (auto_record={auto_record})")
        self._broadcast_status()
        if self._running:
            task.monitor_task = asyncio.create_task(
                self._monitor_channel(composite_key)
            )

    def set_download_options(
        self,
        composite_key: str,
        auto_record: bool,
        condition: Optional[str],
        tags: Optional[str],
        recording_quality: Optional[str] = None,
        output_format: Optional[str] = None,
        output_format_provided: bool = False,
    ) -> None:
        task = self._channels.get(composite_key)
        if task is None:
            raise ValueError("등록된 채널을 찾을 수 없습니다.")
        self._channel_repo.set_download_options(
            composite_key, auto_record, condition, tags
        )
        task.auto_record = auto_record
        task.download_condition = condition
        task.watchalong_tags = tags
        if recording_quality is not None:
            self._channel_repo.set_recording_quality(composite_key, recording_quality)
            task.recording_quality = recording_quality
        if output_format_provided:
            self.finalizer.db.execute(
                "UPDATE channels SET output_format=? WHERE composite_key=?",
                (output_format, composite_key),
            )
            task.output_format = output_format
        self._broadcast_status()
        self.trigger_scan_now(composite_key)

    @staticmethod
    def _can_auto_record(task: ChannelTask) -> bool:
        return (
            task.auto_record
            and not task.broadcast_ended
            and Conductor._matches_download_condition(task)
        )

    @staticmethod
    def _matches_download_condition(task: ChannelTask) -> bool:
        if task.platform != Platform.CHZZK:
            return True
        settings = get_settings()
        return matches_download_condition(
            task.download_condition or settings.live_download_condition,
            task.broadcast_tags,
            (
                task.watchalong_tags
                if task.watchalong_tags is not None
                else settings.watchalong_tags
            ),
            is_watchalong=task.is_watchalong,
            watchalong_tag=task.watchalong_tag,
        )

    def _download_hold_reason(self, task: ChannelTask) -> Optional[str]:
        if (
            not task.is_live
            or task.is_recording
            or self._matches_download_condition(task)
        ):
            return None
        condition = task.download_condition or get_settings().live_download_condition
        if task.is_watchalong is None and task.broadcast_tags is None:
            return "같이보기 정보 확인 대기"
        if condition == "exclude_watchalong":
            return "같이보기 방송을 제외하도록 설정되어 있습니다."
        is_watchalong = matches_download_condition(
            "watchalong",
            task.broadcast_tags,
            "같이보기",
            is_watchalong=task.is_watchalong,
            watchalong_tag=task.watchalong_tag,
        )
        if task.is_watchalong is False and (not is_watchalong):
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
        logger.info(f"[{composite_key}] 자동 녹화 {('ON' if value else 'OFF')}")
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
        logger.info(
            f"[{composite_key}] 자동 녹화 {('ON' if task.auto_record else 'OFF')}"
        )
        self._channel_repo.set_auto_record(composite_key, task.auto_record)
        self._broadcast_status()
        if (
            task.auto_record
            and self._can_auto_record(task)
            and task.is_live
            and (
                task.pipeline is None or task.pipeline.state != RecordingState.RECORDING
            )
        ):
            logger.info(f"[{composite_key}] 라이브 중 자동 녹화 ON → 즉시 녹화 시작")
            await self._start_recording(
                composite_key,
                channel_name=task.channel_name,
                title=task.title,
                automatic=True,
            )
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
        task = self._channels.get(composite_key)
        if task is None:
            logger.warning(f"채널 '{composite_key}'을(를) 찾을 수 없습니다.")
            return
        mt = task.monitor_task
        if mt is not None and (not mt.done()):
            mt.cancel()
            await asyncio.gather(mt, return_exceptions=True)
        if task.pipeline is not None:
            await self._stop_recording(composite_key)
        self._channels.pop(composite_key, None)
        self._scan_events.pop(composite_key, None)
        logger.info(f"채널 제거: {composite_key}")
        self._channel_repo.delete(composite_key)
        self._broadcast_status()

    async def start(self) -> None:
        """모든 등록된 채널의 감시를 시작한다."""
        if self._running:
            logger.warning("Conductor가 이미 실행 중입니다.")
            return
        await self.finalizer.start(recover=True)
        self._running = True
        logger.info(f"Conductor 시작. 감시 채널 수: {self.channel_count}")
        for composite_key, task in self._channels.items():
            task.monitor_task = asyncio.create_task(
                self._monitor_channel(composite_key)
            )
        self._stats_broadcast_task = asyncio.create_task(self._stats_broadcast_loop())

    async def stop(self, close_finalizer: bool = True) -> None:
        """모든 감시 및 녹화를 중지한다."""
        self._running = False
        if close_finalizer:
            self.finalizer._stopping = True
        logger.info("Conductor 종료 요청...")
        self.broadcast_event("shutdown")
        pending = []
        for task in self._channels.values():
            mt = task.monitor_task
            if mt is not None and (not mt.done()):
                mt.cancel()
                pending.append(mt)
        if self._stats_broadcast_task is not None and (
            not self._stats_broadcast_task.done()
        ):
            self._stats_broadcast_task.cancel()
            pending.append(self._stats_broadcast_task)
        await asyncio.gather(*pending, return_exceptions=True)
        for composite_key, task in list(self._channels.items()):
            if task.pipeline is not None:
                await self._stop_recording(composite_key)
        if close_finalizer:
            await self.finalizer.close()
        logger.info("Conductor 종료 완료.")

    async def _stats_broadcast_loop(self) -> None:
        """녹화 중인 채널이 있을 때 2초마다 통계를 SSE로 브로드캐스트한다."""
        while self._running:
            await asyncio.sleep(2.0)
            any_recording = any(
                (
                    t.pipeline is not None
                    and t.pipeline.state == RecordingState.RECORDING
                    for t in self._channels.values()
                )
            )
            if any_recording and self._events.subscriber_count:
                self._broadcast_status()

    def _broadcast_status(self) -> None:
        """현재 전체 채널 상태를 SSE로 밀어낸다."""
        self._events.publish("status_update", self.get_all_status())

    def add_event_queue(self, queue: asyncio.Queue) -> None:
        self._events.subscribe(queue)

    def remove_event_queue(self, queue: asyncio.Queue) -> None:
        self._events.unsubscribe(queue)

    def broadcast_event(
        self, event_type: str, data: Optional[dict | list] = None
    ) -> None:
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
                    "지원하지 않는 플랫폼의 저장 채널을 감시 목록에서 제외합니다."
                )
                continue
            composite_key = self.make_composite_key(platform, record["channel_id"])
            task = ChannelTask(
                channel_id=record["channel_id"],
                platform=platform,
                auto_record=record["auto_record"],
                tags=list(record["tags"]),
                download_condition=record.get("download_condition"),
                watchalong_tags=record.get("watchalong_tags"),
                recording_quality=record.get("recording_quality"),
            )
            task.output_format = record.get("output_format")
            self._channels[composite_key] = task
            self._scan_events[composite_key] = asyncio.Event()
        if records:
            logger.info(f"채널 목록 로드 완료 ({len(records)}개)")

    def _poll_interval_for(self, task: Optional[ChannelTask]) -> int:
        """이 채널을 몇 초마다 확인할지 정한다."""
        return get_settings().monitor_interval

    @staticmethod
    def _apply_status(task: ChannelTask, status: dict) -> None:
        """조회한 라이브 상태를 채널에 반영한다."""
        if not status["is_live"] or (
            status.get("live_started_at")
            and status.get("live_started_at") != task.live_started_at
        ):
            task.broadcast_ended = False
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
            f"[{composite_key}] 🔴 방송 시작 감지! 스트리머: {task.channel_name}, 제목: {task.title}"
        )
        self._notify(
            NotificationKind.LIVE_DETECTED,
            title="🔴 방송 시작",
            description=f"**{task.channel_name or task.channel_id}**\n{task.title or '제목 없음'}",
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
                f"[{composite_key}] 자동 다운로드 조건으로 시작 보류 (조건={task.download_condition or settings.live_download_condition}, 공식 같이보기={task.is_watchalong}, 같이보기 태그={task.watchalong_tag}, 방송 태그={task.broadcast_tags})."
            )
        return retry_count

    async def _handle_live_ended(self, composite_key: str, task: ChannelTask) -> None:
        """방송 종료를 처리한다."""
        logger.info(f"[{composite_key}] ⚫ 방송 종료 감지.")
        await self._stop_recording(composite_key)

    async def _retry_stalled_recording(
        self, composite_key: str, task: ChannelTask, retry_count: int, max_retries: int
    ) -> int:
        """방송은 켜져 있는데 녹화가 멈춘 경우 다시 시작한다. 새 재시도 횟수를 돌려준다."""
        pipe = task.pipeline
        if pipe is None or pipe.state not in (
            RecordingState.ERROR,
            RecordingState.COMPLETED,
        ):
            return retry_count
        if retry_count < max_retries:
            retry_count += 1
            logger.warning(
                f"[{composite_key}] 녹화 중단 감지. 자동 재녹화 시도 ({retry_count}/{max_retries})..."
            )
            await asyncio.sleep(5)
            if not self._running:
                return retry_count
            if pipe.state == RecordingState.ERROR and hasattr(pipe, "reconnect"):
                try:
                    await pipe.reconnect()
                except Exception as error:
                    task.last_error = str(error)
            else:
                await self._start_recording(
                    composite_key,
                    channel_name=task.channel_name,
                    title=task.title,
                    is_retry=True,
                )
        elif retry_count == max_retries:
            retry_count += 1
            task.last_error = "최대 재시도 횟수 초과로 녹화 중단됨"
            await self._stop_recording(composite_key)
            logger.error(
                f"[{composite_key}] 최대 재시도 횟수 초과. 녹화 시작 버튼으로 수동 재시작하세요."
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
                self._broadcast_status()
                if status["is_live"]:
                    self._record_live_detection(composite_key)
                if status["is_live"] and (not was_live):
                    retry_count = await self._handle_live_started(
                        composite_key, task, retry_count
                    )
                elif not status["is_live"] and was_live:
                    await self._handle_live_ended(composite_key, task)
                    retry_count = 0
                elif status["is_live"] and self._can_auto_record(task):
                    if task.pipeline is None:
                        await self._start_recording(
                            composite_key,
                            channel_name=task.channel_name,
                            title=task.title,
                            automatic=True,
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
                if task.platform in (Platform.SOOP, Platform.CIME):
                    from app.engine.platform_auth import redact_media_error

                    task.last_error = f"감시 오류: {redact_media_error(e)}"
                    logger.error(f"[{composite_key}] {task.last_error}")
                else:
                    task.last_error = f"감시 오류: {str(e)}"
                    logger.error(f"[{composite_key}] 감시 오류: {e}", exc_info=e)
            await self._wait_for_next_scan(composite_key, interval)

    async def _stop_recording(self, composite_key: str) -> None:
        task = self._channels.get(composite_key)
        if task is None:
            return
        async with task.recording_lock:
            if self._channels.get(composite_key) is task:
                await self._stop_recording_locked(composite_key)

    async def _stop_recording_locked(self, composite_key: str) -> None:
        task = self._channels.get(composite_key)
        if task is None or task.pipeline is None:
            return
        pipe = task.pipeline
        await pipe.stop_recording()
        if not getattr(pipe, "_closed", True):
            raise RuntimeError("녹화 파일 쓰기가 아직 종료되지 않았습니다.")
        if task.recording_job_id:
            await self.finalizer.capture_finished(task.recording_job_id, pipe)
        elif pipe.state == RecordingState.COMPLETED:
            self._save_live_history(composite_key, task, pipe.get_status())
        task.pipeline = None
        self._broadcast_status()

    async def _start_recording(
        self,
        composite_key: str,
        channel_name=None,
        title=None,
        is_retry=False,
        automatic=False,
    ) -> None:
        task = self._channels.get(composite_key)
        if task is None:
            return
        async with task.recording_lock:
            if self._channels.get(composite_key) is task:
                await self._start_recording_locked(
                    composite_key,
                    channel_name=channel_name,
                    title=title,
                    is_retry=is_retry,
                    automatic=automatic,
                )

    async def _start_recording_locked(
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
        if (automatic or is_retry) and (not self._can_auto_record(task)):
            return
        if task.pipeline is not None:
            if task.pipeline.state in (
                RecordingState.RECORDING,
                RecordingState.STOPPING,
            ):
                return
            await self._stop_recording_locked(composite_key)
        try:
            settings = get_settings()
            quality = task.recording_quality or settings.recording_quality or "best"
            await self.finalizer.start()
            engine = self._get_engine(task.platform)
            live_url = engine.get_stream_url(task.channel_id)
            cookie_str = self._auth.get_ytdlp_cookies()
            if not is_retry:
                logger.debug(f"[{composite_key}] 스트림 CDN 준비 대기 (5초)...")
                await asyncio.sleep(5)
                if automatic and not self._running:
                    return
                if automatic and (not self._can_auto_record(task)):
                    return
            pipeline = YtdlpLivePipeline(channel_id=task.channel_id)
            task.pipeline = pipeline
            from app.engine.recording_finalizer import recording_policy

            policy = recording_policy()
            if task.output_format:
                policy = {**policy, "output_format": task.output_format}

            def registered(capture):
                task.recording_job_id = self.finalizer.register_capture(
                    composite_key, capture, task, policy
                )

            pipeline._on_capture_started = registered

            async def capture_ended(capture):
                async with task.recording_lock:
                    if task.pipeline is not capture:
                        return
                    if task.recording_job_id:
                        await self.finalizer.capture_finished(
                            task.recording_job_id, capture
                        )
                    task.broadcast_ended = True
                    task.pipeline = None
                    self._broadcast_status()

            pipeline._on_capture_ended = capture_ended
            extra = {}
            if task.platform == Platform.YOUTUBE:
                from app.engine.youtube_support import with_youtube_cookie_fallback

                async def resolve_youtube(selected_quality):
                    return await with_youtube_cookie_fallback(
                        lambda cookie_file: pipeline._extract_hls_url(
                            live_url, selected_quality, None, cookie_file=cookie_file
                        )
                    )

                extra["source_resolver"] = resolve_youtube
                cookie_str = None
            elif task.platform in (Platform.SOOP, Platform.CIME):
                extra["source_resolver"] = (
                    lambda selected_quality: engine.resolve_stream(
                        task.channel_id, selected_quality
                    )
                )
                cookie_str = None
            await pipeline.start_recording(
                stream_obj=live_url,
                streamer_name=channel_name or task.channel_name,
                title=title or task.title,
                category=task.category,
                live_started_at=task.live_started_at,
                quality=quality,
                cookie_str=cookie_str,
                thumbnail_url=task.thumbnail_url,
                **extra,
            )
            logger.info(f"[{composite_key}] 자동 라이브 녹화 시작 (quality={quality}).")
            if not is_retry:
                self._notify(
                    NotificationKind.RECORDING_STARTED,
                    title="🎬 녹화 시작",
                    description=f"채널: **{channel_name or composite_key}**\n제목: {title or 'N/A'}",
                    color="green",
                    fields={"화질": quality, "플랫폼": task.platform.value},
                )
        except Exception as e:
            message = str(e)
            if task.platform in (Platform.SOOP, Platform.CIME):
                from app.engine.platform_auth import redact_media_error

                message = redact_media_error(e)
            task.last_error = f"녹화 시작 오류: {message}"
            logger.error(f"[{composite_key}] 녹화 시작 실패: {message}")
            self._notify(
                NotificationKind.RECORDING_FAILED,
                title="❌ 녹화 시작 실패",
                description=f"채널: **{channel_name or composite_key}**\n오류: {message}",
                color="red",
            )
        self._broadcast_status()

    async def start_manual_recording(self, composite_key: str) -> dict:
        """수동으로 특정 채널의 녹화를 시작한다."""
        task = self._channels.get(composite_key)
        if task is None:
            platform, channel_id = self.parse_composite_key(composite_key)
            task = ChannelTask(
                channel_id=channel_id, platform=platform, auto_record=False
            )
            self._channels[composite_key] = task
        pipe = task.pipeline
        if pipe is not None and pipe.state == RecordingState.RECORDING:
            return {"error": "이미 녹화 중입니다.", **pipe.get_status()}
        try:
            engine = self._get_engine(task.platform)
            status = await engine.check_live_status(task.channel_id)
            task.channel_name = status.get("channel_name")
            task.title = status.get("title")
        except Exception:
            pass
        await self._start_recording(composite_key)
        pipe = task.pipeline
        if pipe is not None:
            return pipe.get_status()
        return {"error": "녹화 시작 실패."}

    async def stop_manual_recording(self, composite_key: str) -> dict:
        """수동으로 특정 채널의 녹화를 중지한다."""
        task = self._channels.get(composite_key)
        if task is None:
            return {"error": "녹화 중인 채널이 아닙니다."}
        pipe = task.pipeline
        if pipe is None:
            return {"error": "녹화 중인 채널이 아닙니다."}
        await self._stop_recording(composite_key)
        return pipe.get_status()

    async def stop_all_recordings(self) -> dict:
        """현재 진행 중인 모든 채널의 녹화를 중지한다."""
        stopped_count = 0
        for composite_key, task in list(self._channels.items()):
            if (
                task.pipeline is not None
                and task.pipeline.state == RecordingState.RECORDING
            ):
                await self._stop_recording(composite_key)
                stopped_count += 1
        return {
            "stopped_count": stopped_count,
            "message": f"{stopped_count}개의 채널 녹화를 중지했습니다.",
        }

    def get_all_status(self) -> list[dict]:
        """모든 채널의 상태를 반환한다."""
        result: list[dict] = []
        for composite_key, task in self._channels.items():
            status: dict = {
                "composite_key": composite_key,
                "platform": task.platform.value,
                "channel_id": task.channel_id,
                "auto_record": task.auto_record,
                "recording_quality": task.recording_quality,
                "recording_inspection": task.recording_inspection,
                "output_format": task.output_format,
                "postprocess": (
                    self.finalizer.get(task.recording_job_id)
                    if task.recording_job_id
                    else next(
                        (
                            j
                            for j in self.finalizer.list_jobs()
                            if j["composite_key"] == composite_key
                        ),
                        None,
                    )
                ),
                "channel_url": (
                    self._get_engine(task.platform).get_stream_url(task.channel_id)
                    if task.platform in (Platform.SOOP, Platform.CIME)
                    else None
                ),
                "is_live": task.is_live,
                "recording": None,
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
            result.append(status)
        return result

    def _save_live_history(
        self, composite_key: str, task: ChannelTask, pipe_status: dict
    ) -> None:
        """라이브 녹화 완료 이력을 저장한다.

        기존 JSON 구현은 매번 전체 파일을 읽고 다시 썼기 때문에 이력이 쌓일수록
        녹화 종료 처리가 느려졌다. 지금은 INSERT 한 번이다.
        """
        try:
            self._history_repo.add_session(
                {
                    "composite_key": composite_key,
                    "platform": task.platform.value,
                    "channel_id": task.channel_id,
                    "channel_name": task.channel_name or task.channel_id,
                    "started_at": pipe_status.get("start_time"),
                    "ended_at": datetime.now().isoformat(),
                    "duration_seconds": pipe_status.get("duration_seconds", 0),
                    "file_size_bytes": pipe_status.get("file_size_bytes", 0),
                    "output_path": pipe_status.get("output_path"),
                }
            )
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
