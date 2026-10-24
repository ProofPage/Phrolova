"""Recording failures carry a stable reason and an explicit retry policy."""

from __future__ import annotations
import errno
import re


class RecordingError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def classify_recording_error(error: Exception) -> RecordingError:
    if isinstance(error, RecordingError):
        return error
    from app.engine.youtube_support import YouTubeAuthenticationError, youtube_access_error

    access_error = youtube_access_error(error)
    if access_error:
        return RecordingError(access_error.code, str(access_error))

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
    status = getattr(error, 'status', None)
    cause = error
    for _ in range(4):
        response = getattr(cause, 'response', None)
        if response is not None:
            status = getattr(response, 'status_code', status)
            break
        cause = getattr(cause, '__cause__', None)
        if cause is None:
            break
    if status in (401, 403):
        return RecordingError('authentication', '방송 접근 권한을 확인하지 못했습니다. 설정 → 인증을 확인하세요.')
    text = re.sub(r'https?://\S+', '<url>', str(error).lower())
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
    if any(marker in text for marker in (
        "video unavailable", "this video is private", "private video",
        "live stream recording is not available", "removed by the uploader",
        "this video has been removed", "is not a live stream", "video is unavailable",
        "비공개 동영상", "사용할 수 없는 동영상", "삭제된 동영상", "비공개로 전환"
    )):
        return RecordingError(
            "not_available",
            "동영상을 볼 수 없거나 비공개로 전환되었습니다.",
            retryable=False,
        )
    if status in (404, 500, 502, 503, 504) or (status is None and re.search(r'(?<!\d)(?:404|500|502|503|504)(?!\d)', text)):
        return RecordingError(
            "stream_unavailable",
            "송출 서버에서 스트림을 제공하지 않습니다. 복구를 기다립니다.",
            retryable=True,
        )
    if ((status is None and re.search(r'(?<!\d)(?:401|403)(?!\d)', text))
            or any(x in text for x in ("권한", "쿠키", "not a bot", "sign in"))):
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
