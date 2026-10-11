"""Recording failures carry a stable reason and an explicit retry policy."""

from __future__ import annotations
import errno


class RecordingError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def classify_recording_error(error: Exception) -> RecordingError:
    if isinstance(error, RecordingError):
        return error
    from app.engine.youtube_support import YouTubeAuthenticationError

    if isinstance(error, YouTubeAuthenticationError):
        return RecordingError("authentication", str(error))
    if isinstance(error, FileNotFoundError):
        return RecordingError(
            "dependency_or_path",
            "필요한 실행 파일 또는 저장 경로를 찾을 수 없습니다. 설정을 확인하세요.",
        )
    if (
        isinstance(error, PermissionError)
        or isinstance(error, OSError)
        and error.errno in (errno.ENOSPC, errno.EROFS)
    ):
        return RecordingError("storage", "저장 위치의 권한과 남은 공간을 확인하세요.")
    text = str(error).lower()
    if "javascript runtime" in text:
        return RecordingError(
            "youtube_runtime",
            "유튜브 추출에 필요한 JavaScript 실행 도구를 찾을 수 없습니다. Deno 또는 Node.js 22 이상을 설치하세요.",
        )
    if any(x in text for x in ("cmaf", "fmp4", "ts 직접", "dash 전용")):
        return RecordingError(
            "unsupported_container",
            "이 방송은 TS 호환 스트림을 제공하지 않습니다. 녹화 설정을 확인하세요.",
        )
    if any(x in text for x in ("403", "401", "권한", "쿠키", "not a bot", "sign in")):
        return RecordingError(
            "authentication",
            "방송 접근 권한을 확인하지 못했습니다. 설정 → 인증을 확인하세요.",
        )
    if isinstance(error, ValueError):
        return RecordingError("invalid_settings", "채널 주소와 녹화 설정을 확인하세요.")
    return RecordingError(
        "connection",
        "스트림 연결이 중단되었습니다. 재연결을 시도합니다.",
        retryable=True,
    )
