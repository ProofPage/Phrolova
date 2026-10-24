"""
Phrolova: 감시 채널 런타임 상태

ChannelTask는 채널 하나의 "지금 상태"를 담는다.
영속 필드(채널 ID, 자동 녹화, 태그, 캡처 URL)는 저장소에도 남지만,
파이프라인 핸들이나 감시 태스크 같은 런타임 전용 필드는 여기에만 있다.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from app.engine.base import Platform
from app.engine.pipeline import RecordingState, YtdlpLivePipeline


@dataclass
class ChannelTask:
    """감시 대상 채널 정보."""

    channel_id: str
    platform: Platform = Platform.CHZZK
    auto_record: bool = True
    recording_quality: Optional[str] = None
    output_format: Optional[str] = None
    recording_job_id: Optional[str] = None
    broadcast_ended: bool = False
    capture_automatic: bool = False
    skip_pending: bool = False
    recording_inspection: Optional[dict] = None
    last_recording_status: Optional[dict] = None
    pipeline: Optional[YtdlpLivePipeline] = field(default=None, repr=False)
    monitor_task: Optional[asyncio.Task] = field(default=None, repr=False)
    # 수동 요청과 자동 감시가 동시에 같은 녹화 핸들을 덮어쓰지 않도록 보호한다.
    recording_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    is_live: bool = False
    channel_name: Optional[str] = None
    title: Optional[str] = None
    category: Optional[str] = None
    live_started_at: Optional[str] = None
    viewer_count: int = 0
    viewer_count_type: str = 'viewers'
    thumbnail_url: Optional[str] = None
    profile_image_url: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    broadcast_tags: Optional[list[str]] = None
    is_watchalong: Optional[bool] = None
    watchalong_tag: Optional[str] = None
    download_condition: Optional[str] = None
    watchalong_tags: Optional[str] = None
    # 예약 감시 시간대(JSON). 비어 있으면 상시 감시한다.
    monitor_schedule: Optional[str] = None
    last_error: Optional[str] = None
    retry_count: int = 0
    retry_blocked: bool = False
    retry_at: Optional[str] = None
    retry_code: Optional[str] = None
    error_detail: Optional[str] = None
    broadcast_status: str = "checking"
    monitor_status: str = "paused"
    monitor_error: Optional[str] = None
    monitor_error_detail: Optional[str] = None
    recent_errors: list[dict] = field(default_factory=list)

    # 같은 방송을 끊겼다가 다시 녹화할 때, 앞 세션과 겹치지 않는 파일명
    # 기준 시각을 기억한다. 창을 닫거나 새 방송이 시작되면 비운다.
    session_started_at: Optional[str] = None

    @property
    def composite_key(self) -> str:
        """Derive identity; legacy records need no new stored field."""
        return f"{self.platform.value}:{self.channel_id}"

    # ── 파생 상태 ────────────────────────────────────────

    @property
    def display_name(self) -> str:
        """UI/알림에 쓸 표시 이름."""
        return self.channel_name or self.channel_id

    def update_channel_name(self, value) -> None:
        incoming = value.strip() if isinstance(value, str) else ""
        self.channel_name = incoming or (self.channel_name or "").strip() or self.channel_id

    def new_session_stamp(self, broadcast_started_at: Optional[str]) -> Optional[str]:
        """다시 시작한 녹화의 파일명 시각을 고른다.

        같은 방송 시작 시각으로 파일명을 만들면 앞 세션과 이름이 겹쳐 `(2)`가
        붙는다. 겹치지 않도록 첫 세션 뒤의 시각을 쓰되, 그 이상으로 실제
        라이브가 시작된 시각을 넘지 않는다.
        """
        if not self.session_started_at:
            if broadcast_started_at:
                self.session_started_at = broadcast_started_at
            return broadcast_started_at
        try:
            start = datetime.fromisoformat(broadcast_started_at.replace("Z", "+00:00"))
            previous = datetime.fromisoformat(self.session_started_at.replace("Z", "+00:00"))
        except (AttributeError, ValueError):
            return broadcast_started_at
        if start.tzinfo and not previous.tzinfo:
            previous = previous.replace(tzinfo=start.tzinfo)
        if previous.tzinfo and not start.tzinfo:
            start = start.replace(tzinfo=previous.tzinfo)
        stamp = max(datetime.now(tz=previous.tzinfo), previous + timedelta(seconds=1))
        self.session_started_at = stamp.isoformat()
        return self.session_started_at

    @property
    def is_recording(self) -> bool:
        """Streamlink 수신 파이프라인이 녹화 중인지."""
        return (
            self.pipeline is not None
            and self.pipeline.state == RecordingState.RECORDING
        )
