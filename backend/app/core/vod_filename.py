"""다시보기 파일명 형식을 yt-dlp 템플릿으로 변환한다."""
import re
import os
from pathlib import Path
from datetime import datetime

DEFAULT_VOD_FILENAME_TEMPLATE = "[{name}] {title} {date_year}-{date_month}-{date_day} {date_hour}-{date_minute}-{date_second}"
DATE_TOKENS = {"date_year": "%Y", "date_month": "%m", "date_day": "%d",
               "date_hour": "%H", "date_minute": "%M", "date_second": "%S"}
TOKENS = {
    "name": "%(uploader,channel|Unknown)s", "title": "%(title|Untitled)s",
    "id": "%(id)s", "extractor": "%(extractor_key|Video)s",
    "upload_date": "%(upload_date|Unknown)s",
}


def bounded_vod_path(value, collision=0) -> Path:
    """Reserve space for yt-dlp format/fragment/part suffixes and collisions."""
    path = Path(value)
    suffix = path.suffix
    marker = f' ({collision})' if collision else ''
    stem = path.stem
    if marker and stem.endswith(marker):
        stem = stem[:-len(marker)]
    while (len((stem + marker + suffix).encode('utf-8')) > 210 or
           (os.name == 'nt' and len(str(path.parent / (stem + marker + suffix))) > 220)):
        if len(stem) <= 1:
            raise ValueError('저장 폴더 경로가 너무 깁니다. 더 짧은 경로를 선택하세요.')
        stem = stem[:-1]
    return path.with_name(stem.rstrip() + marker + suffix)


def validate_vod_template(value: str) -> str:
    value = value.strip()
    if not value or len(value) > 240 or re.search(r'[\\/:*?"<>|\r\n]', value):
        raise ValueError("파일명 형식은 1~240자이며 경로 구분자와 파일명에 사용할 수 없는 문자를 포함할 수 없습니다.")
    stripped = re.sub(r"\{([^{}]+)\}", "", value)
    if "{" in stripped or "}" in stripped:
        raise ValueError("파일명 변수의 중괄호를 확인하세요.")
    for token in re.findall(r"\{([^{}]+)\}", value):
        if token not in {*TOKENS, *DATE_TOKENS, "download_date", "quality"}:
            raise ValueError(f"지원하지 않는 파일명 변수: {token}")
    return value


def build_vod_outtmpl(template: str, quality: str, started_at: datetime | None = None) -> str:
    template = validate_vod_template(template)
    date = started_at or datetime.now()
    mapping = {**TOKENS, **{key: date.strftime(fmt) for key, fmt in DATE_TOKENS.items()},
               "download_date": date.strftime("%Y-%m-%d"),
               "quality": re.sub(r'[\\/:*?"<>|]', "_", quality).replace("%", "%%")}
    return "".join(mapping[part[1:-1]] if part.startswith("{") else part.replace("%", "%%")
                   for part in re.split(r"(\{[^{}]+\})", template)) + ".%(ext)s"
