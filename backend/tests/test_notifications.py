"""
test_notifications.py
알림 큐의 유실 방지, 재시도, Discord 크기 제한 처리, 종류별 필터링 테스트.

이 계층의 핵심 계약:
    - 전송 채널이 일시적으로 죽어 있어도 알림을 버리지 않는다.
    - 1024자를 넘는 필드 값(예: X Spaces Master URL)도 유실 없이 전달한다.
    - notify()는 절대 예외를 던지지 않고 블록되지 않는다.
"""

import asyncio
import time

import pytest

from app.core.config import get_settings
from app.store.repositories import NotificationRepository
from app.services.notifications import (
    MAX_FIELD_VALUE,
    DeliveryResult,
    EmbedPayload,
    Notification,
    NotificationKind,
    NotificationService,
    _kind_enabled,
    build_payload,
    truncate,
)


@pytest.fixture
def settings_reset():
    """설정 싱글턴을 테스트 기본값으로 되돌린다."""
    settings = get_settings()
    saved = (
        settings.discord_notify_events,
        settings.discord_mention_events,
        settings.discord_mention_target,
        settings.discord_notify_ttl,
        settings.discord_webhook_url,
    )
    settings.discord_notify_events = "all"
    settings.discord_mention_events = ""
    settings.discord_mention_target = "@here"
    settings.discord_notify_ttl = 3600
    settings.discord_webhook_url = None
    yield settings
    (
        settings.discord_notify_events,
        settings.discord_mention_events,
        settings.discord_mention_target,
        settings.discord_notify_ttl,
        settings.discord_webhook_url,
    ) = saved


class FakeTransport:
    """테스트용 전송 채널. 가용 여부와 반환 결과를 직접 제어한다."""

    name = "fake"

    def __init__(self, available: bool = True, result: DeliveryResult = DeliveryResult.DELIVERED):
        self.available = available
        self.result = result
        self.sent: list[EmbedPayload] = []

    def is_configured(self) -> bool:
        return True

    def is_available(self) -> bool:
        return self.available

    async def send(self, payload: EmbedPayload) -> DeliveryResult:
        if self.result is DeliveryResult.DELIVERED:
            self.sent.append(payload)
        return self.result


async def _wait_until(predicate, timeout: float = 2.0) -> bool:
    """조건이 참이 될 때까지 폴링한다."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return predicate()


# ── 크기 제한 처리 ───────────────────────────────────────


class TestPayloadLimits:
    def test_truncate_keeps_short_text(self):
        assert truncate("짧은 텍스트", 100) == "짧은 텍스트"

    def test_truncate_cuts_long_text(self):
        result = truncate("a" * 500, 100)
        assert len(result) == 100
        assert result.endswith("…")

    def test_long_field_is_split_not_dropped(self):
        """Master URL처럼 긴 값은 잘리지 않고 여러 필드로 나뉘어야 한다."""
        long_url = "https://prod-fastly.video.pscp.tv/" + ("x" * 3000)
        note = Notification(
            kind=NotificationKind.SPACE_DETECTED,
            title="🎙️ X Spaces 감지",
            fields={"Master URL": long_url},
        )

        payload = build_payload(note, mention=None)

        assert len(payload.fields) > 1, "긴 값이 분할되지 않았습니다."
        assert all(len(value) <= MAX_FIELD_VALUE for _, value in payload.fields)
        # 분할된 조각을 이으면 원본이 복원되어야 한다.
        assert "".join(value for _, value in payload.fields) == long_url

    def test_title_and_description_are_capped(self):
        note = Notification(
            kind=NotificationKind.SYSTEM,
            title="t" * 500,
            description="d" * 9000,
        )
        payload = build_payload(note, mention=None)

        assert len(payload.title) <= 256
        assert len(payload.description) <= 4096

    def test_field_count_is_capped(self):
        note = Notification(
            kind=NotificationKind.SYSTEM,
            title="많은 필드",
            fields={f"필드{i}": "값" for i in range(40)},
        )
        payload = build_payload(note, mention=None)
        assert len(payload.fields) <= 25


# ── 종류별 필터링 ────────────────────────────────────────


class TestKindFiltering:
    def test_all_allows_everything(self):
        assert _kind_enabled("all", NotificationKind.LIVE_DETECTED) is True

    def test_none_blocks_everything(self):
        assert _kind_enabled("none", NotificationKind.LIVE_DETECTED) is False

    def test_csv_selects_listed_kinds(self):
        csv = "live_detected,recording_failed"
        assert _kind_enabled(csv, NotificationKind.LIVE_DETECTED) is True
        assert _kind_enabled(csv, NotificationKind.VOD_COMPLETED) is False

    def test_empty_uses_default(self):
        """알림 종류는 기본 전체 ON, 멘션은 기본 전체 OFF."""
        assert _kind_enabled("", NotificationKind.SYSTEM, default_all=True) is True
        assert _kind_enabled("", NotificationKind.SYSTEM, default_all=False) is False


# ── 큐 동작 ─────────────────────────────────────────────


@pytest.mark.asyncio
class TestNotificationService:
    async def test_delivers_when_transport_available(self, settings_reset):
        service = NotificationService()
        transport = FakeTransport(available=True)
        service.register(transport)
        await service.start()

        try:
            service.notify(NotificationKind.RECORDING_STARTED, "🎬 녹화 시작")
            assert await _wait_until(lambda: len(transport.sent) == 1)
            assert transport.sent[0].title == "🎬 녹화 시작"
        finally:
            await service.stop(drain_timeout=0)

    async def test_notify_does_not_block(self, settings_reset):
        """호출부가 Discord 응답을 기다리지 않아야 한다."""
        service = NotificationService()
        service.register(FakeTransport(available=True))
        await service.start()

        try:
            started = time.monotonic()
            for i in range(50):
                service.notify(NotificationKind.SYSTEM, f"알림 {i}")
            assert time.monotonic() - started < 0.1
        finally:
            await service.stop(drain_timeout=0)

    async def test_unavailable_transport_does_not_drop(self, settings_reset):
        """봇 재연결 중에 발생한 알림은 버려지지 않고 대기해야 한다."""
        service = NotificationService()
        transport = FakeTransport(available=False)
        service.register(transport)
        await service.start()

        try:
            service.notify(NotificationKind.LIVE_DETECTED, "🔴 방송 시작")
            await asyncio.sleep(0.2)

            assert transport.sent == []
            assert service.get_stats()["pending"] == 1
            assert service.get_stats()["dropped"] == 0

            # 연결이 복구되면 대기 중이던 알림이 전송된다.
            # (프로덕션에선 5초 뒤 재시도하지만 테스트에선 즉시 앞당긴다.)
            transport.available = True
            for note in service._pending:
                note.next_attempt_at = 0.0
            service.wake()
            assert await _wait_until(lambda: len(transport.sent) == 1)
        finally:
            await service.stop(drain_timeout=0)

    async def test_permanent_failure_is_dropped(self, settings_reset):
        service = NotificationService()
        service.register(FakeTransport(available=True, result=DeliveryResult.PERMANENT_FAIL))
        await service.start()

        try:
            service.notify(NotificationKind.SYSTEM, "권한 없음")
            assert await _wait_until(lambda: service.get_stats()["dropped"] == 1)
            assert service.get_stats()["pending"] == 0
        finally:
            await service.stop(drain_timeout=0)

    async def test_no_transport_means_no_queue_growth(self, settings_reset):
        """Discord를 아예 설정하지 않은 사용자에게서 큐가 무한히 자라면 안 된다."""
        service = NotificationService()
        await service.start()

        try:
            for i in range(10):
                service.notify(NotificationKind.SYSTEM, f"알림 {i}")
            assert service.get_stats()["pending"] == 0
        finally:
            await service.stop(drain_timeout=0)

    async def test_disabled_kind_is_not_queued(self, settings_reset):
        settings_reset.discord_notify_events = "recording_failed"
        service = NotificationService()
        transport = FakeTransport(available=False)
        service.register(transport)
        await service.start()

        try:
            service.notify(NotificationKind.LIVE_DETECTED, "무시되어야 함")
            service.notify(NotificationKind.RECORDING_FAILED, "전송되어야 함")
            await asyncio.sleep(0.1)
            assert service.get_stats()["pending"] == 1
        finally:
            await service.stop(drain_timeout=0)

    async def test_mention_applied_only_to_selected_kinds(self, settings_reset):
        settings_reset.discord_mention_events = "recording_failed"
        service = NotificationService()
        transport = FakeTransport(available=True)
        service.register(transport)
        await service.start()

        try:
            service.notify(NotificationKind.RECORDING_FAILED, "❌ 실패")
            service.notify(NotificationKind.SYSTEM, "일반")
            assert await _wait_until(lambda: len(transport.sent) == 2)

            by_title = {p.title: p for p in transport.sent}
            assert by_title["❌ 실패"].mention == "@here"
            assert by_title["일반"].mention is None
        finally:
            await service.stop(drain_timeout=0)

    async def test_pending_survives_restart(self, settings_reset):
        """앱이 재시작돼도 미전송 알림이 이어서 전송되어야 한다."""
        service = NotificationService()
        service.register(FakeTransport(available=False))
        await service.start()
        service.notify(NotificationKind.RECORDING_COMPLETED, "⏹ 녹화 완료")
        await asyncio.sleep(0.1)
        await service.stop(drain_timeout=0)

        assert len(NotificationRepository().list_all()) == 1

        # 새 인스턴스 = 앱 재시작
        revived = NotificationService()
        transport = FakeTransport(available=True)
        revived.register(transport)
        await revived.start()

        try:
            assert await _wait_until(lambda: len(transport.sent) == 1)
            assert transport.sent[0].title == "⏹ 녹화 완료"
        finally:
            await revived.stop(drain_timeout=0)

    async def test_expired_notifications_are_discarded(self, settings_reset):
        """TTL이 지난 알림은 뒷북이 되므로 전송하지 않는다."""
        settings_reset.discord_notify_ttl = 60
        service = NotificationService()
        transport = FakeTransport(available=True)
        service.register(transport)

        stale = Notification(
            kind=NotificationKind.LIVE_DETECTED,
            title="오래된 알림",
            created_at=time.time() - 3600,
        )
        service._pending.append(stale)
        await service.start()

        try:
            await asyncio.sleep(0.2)
            assert transport.sent == []
            assert service.get_stats()["expired"] == 1
        finally:
            await service.stop(drain_timeout=0)
