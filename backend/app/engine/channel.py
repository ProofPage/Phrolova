"""
Phrolova: 감시 채널 런타임 상태

ChannelTask는 채널 하나의 "지금 상태"를 담는다.
영속 필드(채널 ID, 자동 녹화, 태그, 캡처 URL)는 저장소에도 남지만,
파이프라인 핸들이나 감시 태스크 같은 런타임 전용 필드는 여기에만 있다.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
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
    recording_inspection: Optional[dict] = None
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
    thumbnail_url: Optional[str] = None
    profile_image_url: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    broadcast_tags: Optional[list[str]] = None
    is_watchalong: Optional[bool] = None
    watchalong_tag: Optional[str] = None
    download_condition: Optional[str] = None
    watchalong_tags: Optional[str] = None
    last_error: Optional[str] = None
    # ── 파생 상태 ────────────────────────────────────────

    @property
    def display_name(self) -> str:
        """UI/알림에 쓸 표시 이름."""
        return self.channel_name or self.channel_id

    @property
    def is_recording(self) -> bool:
        """Streamlink 수신 파이프라인이 녹화 중인지."""
        return (
            self.pipeline is not None
            and self.pipeline.state == RecordingState.RECORDING
        )
