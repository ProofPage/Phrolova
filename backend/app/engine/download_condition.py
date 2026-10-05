"""치지직 방송 태그에 따른 자동 라이브 다운로드 조건."""

import re
import unicodedata
from typing import Literal

DownloadCondition = Literal["all", "watchalong", "exclude_watchalong"]


def parse_watchalong_tags(value: str) -> list[str]:
    """쉼표나 줄바꿈으로 구분한 태그를 정리한다."""
    return list(dict.fromkeys(tag.strip().lstrip("#").strip()
                              for tag in re.split(r"[,\r\n]", value)
                              if tag.strip().lstrip("#").strip()))


def matches_download_condition(
    condition: DownloadCondition, broadcast_tags: list[str] | None, watchalong_tags: str,
    is_watchalong: bool | None = None,
    watchalong_tag: str | None = None,
) -> bool:
    if condition == "all":
        return True
    if condition not in {"watchalong", "exclude_watchalong"}:
        return False
    def normalize(tag: str) -> str:
        return "".join(unicodedata.normalize("NFKC", tag).casefold().split()).lstrip("#")

    # 제외 모드는 콘텐츠 선택 태그와 관계없이 모든 같이보기를 제외한다.
    if condition == "exclude_watchalong":
        if is_watchalong is True:
            return False
        if broadcast_tags is None:
            return is_watchalong is False
        return not any(normalize(tag) == "같이보기" for tag in broadcast_tags)

    if broadcast_tags is None and is_watchalong is not True:
        return False
    candidates = list(broadcast_tags or [])
    if is_watchalong is True:
        candidates.append("같이보기")
        if watchalong_tag:
            candidates.append(watchalong_tag)
    markers = {normalize(tag) for tag in parse_watchalong_tags(watchalong_tags)}
    if not markers:
        return False
    return any(normalize(tag) in markers for tag in candidates)
