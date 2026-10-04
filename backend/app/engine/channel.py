"""
Rookery: 감시 채널 런타임 상태

ChannelTask는 채널 하나의 "지금 상태"를 담는다.
영속 필드(채널 ID, 자동 녹화, 태그, 캡처 URL)는 저장소에도 남지만,
파이프라인 핸들이나 감시 태스크 같은 런타임 전용 필드는 여기에만 있다.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Optional

from app.engine.base import Platform
from app.engine.chat import ChatArchiver
from app.engine.pipeline import RecordingState, YtdlpLivePipeline


@dataclass
class ChannelTask:
    """감시 대상 채널 정보."""

    channel_id: str
    platform: Platform = Platform.CHZZK
    auto_record: bool = True
    pipeline: Optional[YtdlpLivePipeline] = field(default=None, repr=False)
    chat_archiver: Optional[ChatArchiver] = field(default=None, repr=False)
    monitor_task: Optional[asyncio.Task] = field(default=None, repr=False)
    is_live: bool = False
    channel_name: Optional[str] = None
    title: Optional[str] = None
    category: Optional[str] = None
    viewer_count: int = 0
    thumbnail_url: Optional[str] = None
    profile_image_url: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    last_error: Optional[str] = None
    # X Spaces 전용
    spaces_process: Optional[asyncio.subprocess.Process] = field(default=None, repr=False)
    spaces_output_path: Optional[str] = None
    _current_space_id: Optional[str] = None
    # X Spaces 전용: 라이브 중 캡처한 dynamic m3u8 URL
    captured_m3u8_url: Optional[str] = None
    captured_m3u8_at: Optional[str] = None
    # X Spaces 전용: master_playlist.m3u8 (안정적, 종료 후 ~30일 유효)
    master_url: Optional[str] = None
    master_url_captured_at: Optional[str] = None
    # X Spaces 전용: master URL이 저장된 .txt 파일 경로 (녹화 실패 시 백업용)
    master_url_file: Optional[str] = None

    # ── 파생 상태 ────────────────────────────────────────

    @property
    def display_name(self) -> str:
        """UI/알림에 쓸 표시 이름."""
        return self.channel_name or self.channel_id

    @property
    def is_recording(self) -> bool:
        """지금 녹화 중인지 (파이프라인 또는 Spaces 프로세스)."""
        if self.spaces_process is not None:
            return True
        return (
            self.pipeline is not None
            and self.pipeline.state == RecordingState.RECORDING
        )

    def clear_space_capture(self) -> None:
        """Space가 끝났을 때 캡처 상태를 초기화한다 (다음 Space 준비)."""
        self.master_url = None
        self.master_url_captured_at = None
        self.captured_m3u8_url = None
        self.captured_m3u8_at = None
        self.master_url_file = None
        self._current_space_id = None
