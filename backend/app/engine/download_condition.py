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
    condition: DownloadCondition, broadcast_tags: list[str] | None, watchalong_tags: str
) -> bool:
    if condition == "all":
        return True
    if condition not in {"watchalong", "exclude_watchalong"}:
        return False
    # 태그 정보가 없는 응답을 '같이보기 아님'으로 잘못 판단하지 않는다.
    if broadcast_tags is None:
        return False

    def normalize(tag: str) -> str:
        return "".join(unicodedata.normalize("NFKC", tag).casefold().split()).lstrip("#")

    markers = {normalize(tag) for tag in parse_watchalong_tags(watchalong_tags)}
    if not markers:
        return False
    watchalong = any(normalize(tag) in markers for tag in broadcast_tags)
    return watchalong if condition == "watchalong" else not watchalong
