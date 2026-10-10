"""
Phrolova: 멀티 플랫폼 엔진 공통 인터페이스
Platform Enum, LiveStatus TypedDict, PlatformEngine Protocol을 정의한다.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional
from typing_extensions import TypedDict, Protocol, runtime_checkable


class Platform(str, Enum):
    """지원 플랫폼 열거형."""

    CHZZK = "chzzk"
    YOUTUBE = "youtube"
    SOOP = "soop"
    CIME = "cime"


class LiveStatus(TypedDict, total=False):
    """플랫폼 공통 라이브 상태 정보."""

    channel_id: str
    is_live: bool
    channel_name: str
    title: str
    category: str
    broadcast_tags: Optional[list[str]]
    is_watchalong: Optional[bool]
    watchalong_tag: Optional[str]
    viewer_count: int
    thumbnail_url: str
    profile_image_url: str


@runtime_checkable
class PlatformEngine(Protocol):
    """플랫폼 엔진 프로토콜.

    CHZZK, YouTube, SOOP, CIME 엔진이 이를 구현한다.

    @runtime_checkable이라 issubclass()로 검사할 수 있다. CI에 파이썬 타입
    체커가 없으므로 tests/test_engine_modules.py가 각 엔진의 준수 여부를 확인한다 —
    이 규약을 어기면 그 테스트가 알려준다.
    """

    async def check_live_status(self, channel_id: str) -> LiveStatus:
        """채널의 라이브 상태를 확인한다."""
        ...

    def get_stream_url(self, channel_id: str) -> str:
        """yt-dlp에 넘길 라이브 페이지 URL을 반환한다."""
        ...
