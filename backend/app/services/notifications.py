"""
Rookery: 알림 서비스
전송 채널(Discord Bot / Webhook)에 독립적인 큐 기반 알림 파이프라인.

설계 목표:
    - 호출부는 절대 블록되지 않는다. notify()는 큐에 적재만 하고 즉시 반환한다.
      (기존에는 감시 루프 안에서 await 하다가 Discord 레이트 리밋에 걸리면
       녹화 시작까지 함께 지연됐다.)
    - 알림을 버리지 않는다. 봇이 재연결 중이거나 앱이 재시작돼도
      TTL 안이라면 연결 복구 후 전송된다.
    - 전송 실패는 지수 백오프로 재시도하고, 영구 실패(권한 없음 등)만 포기한다.
    - Bot이 죽어 있으면 Webhook으로 폴백한다.

새 런타임 의존성 없음 (httpx는 이미 사용 중).
"""

from __future__ import annotations

import asyncio
import random
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Protocol, runtime_checkable

from app.core.config import get_settings
from app.core.logger import logger
from app.store.repositories import NotificationRepository

# ── Discord 제약 ────────────────────────────────────────
# 초과하면 400을 반환하며 알림이 통째로 유실되므로 전송 전에 강제한다.
MAX_TITLE = 256
MAX_DESCRIPTION = 4096
MAX_FIELD_NAME = 256
MAX_FIELD_VALUE = 1024
MAX_FIELDS = 25
MAX_EMBED_TOTAL = 6000

# ── 재시도 정책 ─────────────────────────────────────────
MAX_ATTEMPTS = 8
BACKOFF_BASE = 2.0      # 초
BACKOFF_MAX = 300.0     # 5분
QUEUE_LIMIT = 500       # 큐 상한 (초과 시 가장 오래된 항목부터 폐기)
FLUSH_INTERVAL = 15.0   # 대기 큐 디스크 저장 최소 간격 (초)

COLOR_VALUES = {
    "green": 0x2ECC71,
    "red": 0xE74C3C,
    "blue": 0x3498DB,
    "yellow": 0xF1C40F,
    "grey": 0x99AAB5,
}


class NotificationKind(str, Enum):
    """알림 종류. 설정에서 종류별로 ON/OFF 및 멘션을 지정한다."""

    LIVE_DETECTED = "live_detected"
    RECORDING_STARTED = "recording_started"
    RECORDING_COMPLETED = "recording_completed"
    RECORDING_FAILED = "recording_failed"
    SPACE_DETECTED = "space_detected"
    VOD_COMPLETED = "vod_completed"
    VOD_FAILED = "vod_failed"
    COOKIE_EXPIRED = "cookie_expired"
    UPDATE_AVAILABLE = "update_available"
    SYSTEM = "system"


#: 설정 UI에 표시할 한국어 라벨.
KIND_LABELS: dict[NotificationKind, str] = {
    NotificationKind.LIVE_DETECTED: "방송 시작 감지",
    NotificationKind.RECORDING_STARTED: "녹화 시작",
    NotificationKind.RECORDING_COMPLETED: "녹화 완료",
    NotificationKind.RECORDING_FAILED: "녹화 실패",
    NotificationKind.SPACE_DETECTED: "X Spaces 감지",
    NotificationKind.VOD_COMPLETED: "VOD 다운로드 완료",
    NotificationKind.VOD_FAILED: "VOD 다운로드 실패",
    NotificationKind.COOKIE_EXPIRED: "쿠키 만료",
    NotificationKind.UPDATE_AVAILABLE: "신규 버전",
    NotificationKind.SYSTEM: "시스템",
}


class DeliveryResult(Enum):
    """전송 시도 결과."""

    DELIVERED = "delivered"           # 성공
    RETRY = "retry"                   # 일시적 실패 (레이트 리밋, 5xx, 네트워크)
    PERMANENT_FAIL = "permanent_fail" # 영구 실패 (권한 없음, 채널 없음, 잘못된 설정)
    UNAVAILABLE = "unavailable"       # 지금은 사용 불가 (봇 재연결 중) → 나중에 재시도


@runtime_checkable
class NotificationTransport(Protocol):
    """알림 전송 채널 인터페이스."""

    name: str

    def is_configured(self) -> bool:
        """사용자가 이 채널을 설정했는지 여부. False면 알림을 큐에 넣지 않는다."""
        ...

    def is_available(self) -> bool:
        """지금 즉시 전송 가능한지 여부."""
        ...

    async def send(self, payload: "EmbedPayload") -> DeliveryResult:
        """알림을 전송한다."""
        ...


# ── 알림 데이터 ──────────────────────────────────────────


@dataclass
class Notification:
    """전송 대기 중인 알림 한 건."""

    kind: NotificationKind
    title: str
    description: str = ""
    color: str = "green"
    fields: dict[str, str] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: float = field(default_factory=time.time)
    attempts: int = 0
    next_attempt_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "title": self.title,
            "description": self.description,
            "color": self.color,
            "fields": self.fields,
            "created_at": self.created_at,
            "attempts": self.attempts,
            "next_attempt_at": self.next_attempt_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Notification":
        try:
            kind = NotificationKind(data.get("kind", "system"))
        except ValueError:
            kind = NotificationKind.SYSTEM
        return cls(
            kind=kind,
            title=data.get("title", ""),
            description=data.get("description", ""),
            color=data.get("color", "green"),
            fields=dict(data.get("fields") or {}),
            id=data.get("id") or uuid.uuid4().hex[:12],
            created_at=float(data.get("created_at") or time.time()),
            attempts=int(data.get("attempts") or 0),
            next_attempt_at=float(data.get("next_attempt_at") or 0.0),
        )


@dataclass
class EmbedPayload:
    """Discord 제약을 이미 만족하도록 정규화된 전송 페이로드."""

    title: str
    description: str
    color: int
    fields: list[tuple[str, str]]
    mention: Optional[str] = None
    kind: NotificationKind = NotificationKind.SYSTEM


# ── 정규화 헬퍼 ──────────────────────────────────────────


def truncate(text: str, limit: int) -> str:
    """limit을 넘으면 말줄임표로 자른다."""
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _chunk_field(name: str, value: str) -> list[tuple[str, str]]:
    """1024자를 넘는 필드 값을 여러 필드로 분할한다.

    Master URL처럼 잘라내면 쓸모없어지는 값을 보존하기 위한 처리다.
    (기존 구현은 긴 URL을 그대로 보내 400 에러로 알림 자체가 유실됐다.)
    """
    name = truncate(name, MAX_FIELD_NAME)
    if len(value) <= MAX_FIELD_VALUE:
        return [(name, value or "​")]

    # 접미사 "(n/m)"가 이름 길이에 들어갈 공간을 확보한다.
    body_limit = MAX_FIELD_VALUE
    parts = [value[i : i + body_limit] for i in range(0, len(value), body_limit)]
    total = len(parts)
    suffix_len = len(f" ({total}/{total})")
    base = truncate(name, MAX_FIELD_NAME - suffix_len)
    return [(f"{base} ({i + 1}/{total})", part) for i, part in enumerate(parts)]


def build_payload(n: Notification, mention: Optional[str]) -> EmbedPayload:
    """Notification을 Discord 제약에 맞는 EmbedPayload로 변환한다."""
    fields: list[tuple[str, str]] = []
    for key, value in n.fields.items():
        fields.extend(_chunk_field(str(key), str(value)))

    title = truncate(n.title, MAX_TITLE)
    description = truncate(n.description, MAX_DESCRIPTION)

    # 전체 6000자 제한 — 초과분은 뒤쪽 필드부터 버린다.
    budget = MAX_EMBED_TOTAL - len(title) - len(description)
    kept: list[tuple[str, str]] = []
    for name, value in fields[:MAX_FIELDS]:
        cost = len(name) + len(value)
        if cost > budget:
            break
        budget -= cost
        kept.append((name, value))

    if len(kept) < len(fields):
        logger.warning(
            f"알림 '{n.title}'의 필드 {len(fields) - len(kept)}개가 "
            f"Discord 크기 제한으로 생략되었습니다."
        )

    return EmbedPayload(
        title=title,
        description=description,
        color=COLOR_VALUES.get(n.color, COLOR_VALUES["grey"]),
        fields=kept,
        mention=mention,
        kind=n.kind,
    )


# ── Webhook Transport ────────────────────────────────────


class DiscordWebhookTransport:
    """Discord Webhook 전송 채널.

    Bot 연결과 완전히 독립적이므로 봇이 죽어 있어도 알림이 전달된다.
    discord.py가 설치되지 않은 환경에서도 동작한다.
    """

    name = "webhook"

    def _url(self) -> Optional[str]:
        url = (get_settings().discord_webhook_url or "").strip()
        return url or None

    def is_configured(self) -> bool:
        return self._url() is not None

    def is_available(self) -> bool:
        return self._url() is not None

    async def send(self, payload: EmbedPayload) -> DeliveryResult:
        import httpx

        url = self._url()
        if not url:
            return DeliveryResult.UNAVAILABLE

        body: dict = {
            "embeds": [
                {
                    "title": payload.title,
                    "description": payload.description,
                    "color": payload.color,
                    "fields": [
                        {"name": name, "value": value, "inline": False}
                        for name, value in payload.fields
                    ],
                }
            ],
            # 봇이 아닌 웹훅이므로 멘션 파싱을 명시적으로 허용해야 한다.
            "allowed_mentions": {"parse": ["everyone", "roles"]},
        }
        if payload.mention:
            body["content"] = payload.mention

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, json=body)
        except Exception as e:
            logger.warning(f"Webhook 전송 실패 (네트워크): {e}")
            return DeliveryResult.RETRY

        if resp.status_code in (200, 204):
            return DeliveryResult.DELIVERED
        if resp.status_code == 429:
            logger.warning("Webhook 레이트 리밋 — 재시도 예약")
            return DeliveryResult.RETRY
        if resp.status_code in (401, 403, 404):
            logger.error(
                f"Webhook URL이 유효하지 않습니다 (HTTP {resp.status_code}). "
                "설정에서 Webhook URL을 확인하세요."
            )
            return DeliveryResult.PERMANENT_FAIL
        if 500 <= resp.status_code < 600:
            return DeliveryResult.RETRY

        logger.error(f"Webhook 전송 실패 (HTTP {resp.status_code}): {resp.text[:300]}")
        return DeliveryResult.PERMANENT_FAIL


# ── 알림 서비스 ──────────────────────────────────────────


class NotificationService:
    """알림 큐 + 워커.

    사용법:
        service = NotificationService(data_dir)
        service.register(bot_transport)     # 우선순위 순으로 등록
        service.register(webhook_transport)
        await service.start()
        service.notify(NotificationKind.RECORDING_STARTED, "🔴 녹화 시작", ...)
        await service.stop()
    """

    def __init__(self, repo: Optional[NotificationRepository] = None) -> None:
        self._transports: list[NotificationTransport] = []
        self._pending: list[Notification] = []
        self._wake = asyncio.Event()
        self._worker_task: Optional[asyncio.Task] = None
        self._running = False
        self._dirty = False
        self._last_flush = 0.0
        self._repo = repo or NotificationRepository()
        self._stats = {"queued": 0, "delivered": 0, "dropped": 0, "expired": 0}

    # ── 구성 ────────────────────────────────────────────

    def register(self, transport: NotificationTransport) -> None:
        """전송 채널을 등록한다. 먼저 등록된 채널이 우선 사용된다."""
        self._transports.append(transport)

    def wake(self) -> None:
        """워커를 즉시 깨운다. 전송 채널이 복구됐을 때 호출한다."""
        self._wake.set()

    @property
    def has_transport(self) -> bool:
        """사용자가 설정한 전송 채널이 하나라도 있는지."""
        return any(t.is_configured() for t in self._transports)

    def get_stats(self) -> dict:
        """알림 파이프라인 상태를 반환한다 (진단 및 설정 화면용)."""
        return {
            **self._stats,
            "pending": len(self._pending),
            "transports": [
                {
                    "name": t.name,
                    "configured": t.is_configured(),
                    "available": t.is_available(),
                }
                for t in self._transports
            ],
        }

    # ── 적재 ────────────────────────────────────────────

    def notify(
        self,
        kind: NotificationKind,
        title: str,
        description: str = "",
        color: str = "green",
        fields: Optional[dict[str, str]] = None,
    ) -> None:
        """알림을 큐에 적재한다. 블록되지 않으며 예외를 던지지 않는다.

        호출부(감시 루프, 녹화 파이프라인)가 Discord 응답을 기다리지 않도록
        의도적으로 동기 메서드로 만들었다.
        """
        try:
            if not self.has_transport:
                return

            settings = get_settings()
            if not _kind_enabled(settings.discord_notify_events, kind):
                return

            note = Notification(
                kind=kind,
                title=title,
                description=description,
                color=color,
                fields=dict(fields or {}),
            )

            if len(self._pending) >= QUEUE_LIMIT:
                dropped = self._pending.pop(0)
                self._stats["dropped"] += 1
                logger.warning(
                    f"알림 큐가 가득 찼습니다({QUEUE_LIMIT}). "
                    f"가장 오래된 알림을 폐기합니다: {dropped.title}"
                )

            self._pending.append(note)
            self._stats["queued"] += 1
            self._dirty = True
            self._wake.set()
        except Exception as e:
            # 알림 실패가 녹화를 방해해서는 안 된다.
            logger.error(f"알림 적재 실패: {e}")

    # ── 라이프사이클 ────────────────────────────────────

    async def start(self) -> None:
        """워커를 시작하고 이전 실행에서 남은 대기 알림을 복구한다."""
        if self._running:
            return
        self._running = True
        self._restore_pending()
        self._worker_task = asyncio.create_task(self._worker())
        logger.info("📨 알림 서비스 시작.")

    async def stop(self, drain_timeout: float = 5.0) -> None:
        """워커를 중지한다.

        종료 직전에 발생한 알림(예: 마지막 '녹화 완료')이 다음 실행까지 밀리지
        않도록 drain_timeout 동안 남은 큐를 먼저 비운다. 그래도 남으면
        디스크에 보관했다가 다음 실행에서 이어서 전송한다.
        """
        if self._pending and drain_timeout > 0:
            try:
                await asyncio.wait_for(self._drain(), timeout=drain_timeout)
            except asyncio.TimeoutError:
                logger.info("📨 종료 대기 시간 초과 — 남은 알림은 보관합니다.")
            except Exception as e:
                logger.error(f"알림 큐 비우기 실패: {e}")

        self._running = False
        self._wake.set()

        task = self._worker_task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

        self._flush_pending(force=True)
        if self._pending:
            logger.info(f"📨 미전송 알림 {len(self._pending)}건을 보관했습니다.")

    async def _drain(self) -> None:
        """워커가 큐를 비울 때까지 기다린다 (재시도 대기 중인 항목은 제외)."""
        while any(n.next_attempt_at <= time.time() for n in self._pending):
            self._wake.set()
            await asyncio.sleep(0.1)

    # ── 워커 ────────────────────────────────────────────

    async def _worker(self) -> None:
        while self._running:
            try:
                note = self._take_ready()

                if note is None:
                    delay = self._seconds_until_next()
                    try:
                        await asyncio.wait_for(self._wake.wait(), timeout=delay)
                    except asyncio.TimeoutError:
                        pass
                    self._wake.clear()
                    self._flush_pending()
                    continue

                result = await self._deliver(note)

                if result is DeliveryResult.DELIVERED:
                    self._stats["delivered"] += 1
                    self._dirty = True
                else:
                    self._requeue(note, result)

                self._flush_pending()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"알림 워커 오류: {e}")
                await asyncio.sleep(1.0)

    async def _deliver(self, note: Notification) -> DeliveryResult:
        """등록된 전송 채널을 우선순위대로 시도한다.

        첫 성공에서 멈춘다. 모든 채널이 실패하면 가장 낙관적인 결과를 반환해
        일시적 장애가 영구 폐기로 이어지지 않게 한다.
        """
        settings = get_settings()
        mention = (
            (settings.discord_mention_target or "@here").strip()
            if _kind_enabled(settings.discord_mention_events, note.kind, default_all=False)
            else None
        )
        payload = build_payload(note, mention)

        best = DeliveryResult.UNAVAILABLE
        attempted = False

        for transport in self._transports:
            if not transport.is_configured() or not transport.is_available():
                continue
            attempted = True
            try:
                result = await transport.send(payload)
            except Exception as e:
                logger.warning(f"{transport.name} 전송 중 예외: {e}")
                result = DeliveryResult.RETRY

            if result is DeliveryResult.DELIVERED:
                logger.debug(f"알림 전송 완료 [{transport.name}]: {note.title}")
                return DeliveryResult.DELIVERED
            if result is DeliveryResult.RETRY:
                best = DeliveryResult.RETRY
            elif result is DeliveryResult.PERMANENT_FAIL and best is DeliveryResult.UNAVAILABLE:
                best = DeliveryResult.PERMANENT_FAIL

        if not attempted:
            # 봇이 재연결 중이고 웹훅도 없는 상태 — 버리지 말고 대기시킨다.
            return DeliveryResult.UNAVAILABLE
        return best

    def _requeue(self, note: Notification, result: DeliveryResult) -> None:
        """실패한 알림을 백오프와 함께 큐에 되돌린다."""
        if result is DeliveryResult.PERMANENT_FAIL:
            self._stats["dropped"] += 1
            logger.error(f"알림 전송 영구 실패 — 폐기합니다: {note.title}")
            self._dirty = True
            return

        note.attempts += 1
        if note.attempts > MAX_ATTEMPTS:
            self._stats["dropped"] += 1
            logger.error(
                f"알림 재시도 {MAX_ATTEMPTS}회 초과 — 폐기합니다: {note.title}"
            )
            self._dirty = True
            return

        # UNAVAILABLE(봇 재연결 대기)은 시도 횟수를 소모하지 않는다.
        if result is DeliveryResult.UNAVAILABLE:
            note.attempts -= 1
            delay = 5.0
        else:
            delay = min(BACKOFF_BASE * (2 ** (note.attempts - 1)), BACKOFF_MAX)
            delay += random.uniform(0, delay * 0.2)  # 동시 재시도 분산

        note.next_attempt_at = time.time() + delay
        self._pending.append(note)
        self._dirty = True

    # ── 큐 조작 ─────────────────────────────────────────

    def _take_ready(self) -> Optional[Notification]:
        """전송 시각이 도래한 알림 중 가장 오래된 것을 꺼낸다."""
        self._drop_expired()
        if not self._pending:
            return None

        now = time.time()
        ready = [n for n in self._pending if n.next_attempt_at <= now]
        if not ready:
            return None

        note = min(ready, key=lambda n: (n.next_attempt_at, n.created_at))
        self._pending.remove(note)
        return note

    def _drop_expired(self) -> None:
        """TTL이 지난 알림을 폐기한다 (뒤늦게 도착한 녹화 시작 알림 방지)."""
        ttl = max(60, get_settings().discord_notify_ttl)
        cutoff = time.time() - ttl
        fresh = [n for n in self._pending if n.created_at >= cutoff]
        expired = len(self._pending) - len(fresh)
        if expired:
            self._stats["expired"] += expired
            logger.warning(f"TTL({ttl}초)이 지난 알림 {expired}건을 폐기했습니다.")
            self._pending = fresh
            self._dirty = True

    def _seconds_until_next(self) -> float:
        """다음 재시도까지 남은 대기 시간 (최대 30초)."""
        if not self._pending:
            return 30.0
        now = time.time()
        soonest = min(n.next_attempt_at for n in self._pending)
        return max(0.5, min(30.0, soonest - now))

    # ── 영속화 ──────────────────────────────────────────

    def _flush_pending(self, force: bool = False) -> None:
        """미전송 알림을 저장소에 반영한다 (앱 재시작 시 복구용)."""
        if not self._dirty:
            return
        now = time.time()
        if not force and (now - self._last_flush) < FLUSH_INTERVAL:
            return

        try:
            self._repo.replace_all([n.to_dict() for n in self._pending])
            self._dirty = False
            self._last_flush = now
        except Exception as e:
            logger.error(f"미전송 알림 저장 실패: {e}")

    def _restore_pending(self) -> None:
        """이전 실행에서 전송하지 못한 알림을 복구한다."""
        try:
            restored = [Notification.from_dict(item) for item in self._repo.list_all()]
        except Exception as e:
            logger.error(f"미전송 알림 복구 실패: {e}")
            return
        if not restored:
            return

        ttl = max(60, get_settings().discord_notify_ttl)
        cutoff = time.time() - ttl
        alive = [n for n in restored if n.created_at >= cutoff]
        for note in alive:
            note.next_attempt_at = 0.0  # 재시작 직후 즉시 재시도

        if alive:
            self._pending.extend(alive)
            self._wake.set()
            logger.info(f"📨 이전 실행의 미전송 알림 {len(alive)}건을 복구했습니다.")
        if len(alive) < len(restored):
            logger.info(f"만료된 알림 {len(restored) - len(alive)}건은 건너뜁니다.")
        self._dirty = True


# ── 설정 파싱 ────────────────────────────────────────────


def _kind_enabled(
    csv_value: Optional[str],
    kind: NotificationKind,
    default_all: bool = True,
) -> bool:
    """CSV 설정값에 해당 알림 종류가 포함되는지 판정한다.

    "all"    → 전체 허용
    ""/None  → default_all에 따름 (알림 종류는 기본 전체 ON, 멘션은 기본 전체 OFF)
    그 외    → 콤마 구분 목록에 포함될 때만 허용
    """
    if csv_value is None:
        return default_all
    raw = csv_value.strip()
    if not raw:
        return default_all
    if raw.lower() == "all":
        return True
    if raw.lower() == "none":
        return False
    selected = {part.strip().lower() for part in raw.split(",") if part.strip()}
    return kind.value in selected
