"""녹화 상태 enum.

파이프라인 구현 두 개가 함께 쓰므로 별도 모듈에 둔다.
"""

from __future__ import annotations

from enum import Enum


class RecordingState(str, Enum):
    """녹화 상태."""

    IDLE = "idle"
    RECORDING = "recording"
    STOPPING = "stopping"
    ERROR = "error"
    COMPLETED = "completed"
