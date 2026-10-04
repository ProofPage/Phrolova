"""
Rookery: 공통 유틸리티
중복 방지를 위한 공용 헬퍼 함수 모음.
"""

from __future__ import annotations

import re
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Optional

from app.core.config import resolve_env_path
from app.core.logger import logger


def _get_env_path() -> Path:
    """설정을 쓸 .env 경로. 규칙은 config.resolve_env_path 한 곳에 있다.

    테스트가 이 이름을 통째로 갈아끼워 임시 파일로 돌리므로 함수는 남겨 둔다.
    """
    return resolve_env_path()


def extract_channel_id(channel_id: str) -> str:
    """치지직 URL 또는 순수 채널 ID에서 채널 ID만 추출한다.

    지원 형식:
        - https://chzzk.naver.com/live/CHANNEL_ID
        - https://chzzk.naver.com/CHANNEL_ID
        - CHANNEL_ID (순수 ID)
    """
    channel_id = channel_id.strip()
    if "chzzk.naver.com/" in channel_id:
        channel_id = channel_id.rstrip("/").split("/")[-1].split("?")[0]
    return channel_id


def extract_twitcasting_id(value: str) -> str:
    """TwitCasting URL 또는 순수 유저 ID에서 유저 ID만 추출한다.

    지원 형식:
        - https://twitcasting.tv/someuser
        - https://twitcasting.tv/someuser/movie/123456
        - someuser (순수 ID)
    """
    value = value.strip().rstrip("/")
    if "twitcasting.tv/" in value:
        # path의 첫 번째 세그먼트가 유저 ID
        path = value.split("twitcasting.tv/", 1)[1]
        value = path.split("/")[0].split("?")[0]
    return value


def extract_x_id(value: str) -> str:
    """X URL 또는 순수 유저 ID에서 유저 ID만 추출한다.

    지원 형식:
        - https://x.com/someuser
        - https://twitter.com/someuser
        - @someuser (@핸들)
        - someuser (순수 ID, 숫자 numeric ID도 그대로 통과)
    """
    value = value.strip().rstrip("/")
    for domain in ("x.com/", "twitter.com/"):
        if domain in value:
            path = value.split(domain, 1)[1]
            value = path.split("/")[0].split("?")[0]
            break
    # @핸들 처리
    value = value.lstrip("@")
    return value


def extract_youtube_id(value: str) -> str:
    """유튜브 URL 또는 순수 채널 ID/핸들에서 고유 식별자만 추출한다.

    지원 형식:
        - https://www.youtube.com/@username
        - https://www.youtube.com/@username/live
        - https://www.youtube.com/channel/UC-9-kyTE8y5JhEl5xWd-R4A
        - @username
        - UC-9-kyTE8y5JhEl5xWd-R4A
    """
    value = value.strip().rstrip("/")
    
    # 1) channel/UC... 형식 주소 파싱
    if "youtube.com/channel/" in value:
        path = value.split("youtube.com/channel/", 1)[1]
        value = path.split("/")[0].split("?")[0]
    # 2) youtube.com/@username 형식 주소 파싱
    elif "youtube.com/@" in value:
        path = value.split("youtube.com/@", 1)[1]
        value = "@" + path.split("/")[0].split("?")[0]
    # 3) @username 핸들이나 UC... 채널 ID가 직접 들어온 경우
    elif value.startswith("@"):
        pass
    elif value.startswith("UC") and len(value) == 24:
        pass
    # @가 없는데 일반 핸들 이름으로 추정되는 경우 자동으로 @ 붙여주기
    elif not value.startswith("UC"):
        value = "@" + value
        
    return value


def clean_filename(name: str, max_length: int = 150) -> str:
    """파일명에서 사용할 수 없는 특수문자를 제거한다.

    Args:
        name: 원본 파일명.
        max_length: 최대 길이 (기본 150자).

    Returns:
        정제된 파일명.
    """
    # Windows 파일명 금지 문자: \ / : * ? " < > |
    cleaned = re.sub(r'[\\/:*?"<>|]', "_", name)
    cleaned = cleaned.strip()
    return cleaned[:max_length]


def update_env_file(updates: dict[str, str]) -> None:
    """updates 딕셔너리의 키-값을 .env 파일에 반영한다.

    기존 키는 덮어쓰고, 없는 키는 끝에 추가한다.
    """
    env_path = _get_env_path()
    if not env_path.exists():
        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_path.touch(exist_ok=True)

    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
        remaining = dict(updates)
        new_lines: list[str] = []

        for line in lines:
            if line.strip().startswith("#") or "=" not in line:
                new_lines.append(line)
                continue

            key = line.split("=", 1)[0].strip().upper()

            if key in remaining:
                new_lines.append(f"{key}={remaining.pop(key)}")
            else:
                new_lines.append(line)

        # 파일에 없던 새 키 추가
        for key, val in remaining.items():
            new_lines.append(f"{key}={val}")

        env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    except Exception as e:
        logger.error(f".env 파일 업데이트 실패: {e}")


@lru_cache(maxsize=1)
def get_ffmpeg_version(ffmpeg_path: Optional[str] = None) -> tuple[int, int, int]:
    """FFmpeg 버전을 (major, minor, patch) 튜플로 반환한다.

    ffmpeg -version 출력에서 버전 숫자를 파싱한다.
    파싱 실패 시 (0, 0, 0)을 반환하여 옵션이 안전하게 생략되도록 한다.

    Args:
        ffmpeg_path: ffmpeg 실행 파일 경로. None이면 PATH에서 탐색.

    Returns:
        (major, minor, patch) 정수 튜플. 예: (7, 1, 1) 또는 (8, 0, 0)
    """
    cmd = ffmpeg_path or "ffmpeg"
    try:
        result = subprocess.run(
            [cmd, "-version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        # 첫 번째 줄: "ffmpeg version 7.1.1 Copyright ..."
        first_line = result.stdout.splitlines()[0] if result.stdout else ""
        match = re.search(r"version\s+(\d+)\.(\d+)(?:\.(\d+))?", first_line)
        if match:
            major = int(match.group(1))
            minor = int(match.group(2))
            patch = int(match.group(3)) if match.group(3) else 0
            logger.debug(f"FFmpeg 버전 감지: {major}.{minor}.{patch}")
            return (major, minor, patch)
    except Exception as e:
        logger.warning(f"FFmpeg 버전 감지 실패: {e}")
    return (0, 0, 0)


def ffmpeg_supports_extension_picky(ffmpeg_path: Optional[str] = None) -> bool:
    """`-extension_picky` 옵션이 필요한 버전인지 판단한다.

    extension_picky는 ffmpeg 7.1.1에서 엄격해진 보안 패치로,
    Chzzk CDN의 .m4v 확장자 세그먼트를 거부하는 문제를 일으킨다.
    7.1.1 이상 버전에서만 `-extension_picky 0` 옵션이 필요하다.

    Returns:
        True이면 `--extension_picky 0` 옵션 추가가 필요함.
    """
    major, minor, patch = get_ffmpeg_version(ffmpeg_path)
    # 7.1.1+ 또는 8.0+ 이상
    if major >= 8:
        return True
    if major == 7 and minor >= 2:
        return True
    if major == 7 and minor == 1 and patch >= 1:
        return True
    return False

