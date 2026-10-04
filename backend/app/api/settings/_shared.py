"""설정 라우터들이 함께 쓰는 헬퍼와 허용값."""

from __future__ import annotations

from typing import Optional

# 라우터 넷이 같은 prefix를 쓴다. 각 파일에 문자열을 박아두면 한쪽만 바뀌어 어긋난다.
SETTINGS_PREFIX = "/api/settings"
SETTINGS_TAGS = ["Settings"]


VALID_FORMATS = {"ts", "mp4", "mkv"}
VALID_QUALITIES = {"best", "1080p", "720p", "480p"}


def _csv_to_list(value: Optional[str]) -> list[str]:
    """CSV 설정값을 목록으로 변환한다. 'all'/'none'은 그대로 보존한다."""
    raw = (value or "").strip()
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def _list_to_csv(values: Optional[list[str]]) -> str:
    """목록을 CSV 설정값으로 변환한다."""
    if values is None:
        return ""
    return ",".join(v.strip() for v in values if v.strip())
