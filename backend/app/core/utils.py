"""
Phrolova: 공통 유틸리티
중복 방지를 위한 공용 헬퍼 함수 모음.
"""

from __future__ import annotations

import re
import json
import io
from dotenv.parser import parse_stream
import os
import tempfile
import threading
import sys
from pathlib import Path

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
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name)
    cleaned = cleaned.strip()
    suffix = Path(cleaned).suffix
    if suffix.lower() not in {".ts", ".mp4", ".mkv", ".m4a", ".part"}:
        suffix = ""
    stem = cleaned[:-len(suffix)] if suffix else cleaned
    stem = stem[:max(0, max_length - len(suffix))]
    # Reserve room for downloader sidecars and numbered collisions.
    if sys.platform != "win32":
        stem = stem.encode("utf-8")[:240 - len(suffix.encode("utf-8"))].decode("utf-8", errors="ignore")
    return stem + suffix


_env_write_lock = threading.RLock()

def update_env_file(updates: dict[str, str], *, raise_on_error: bool = False) -> None:
    """updates 딕셔너리의 키-값을 .env 파일에 반영한다.

    기존 키는 덮어쓰고, 없는 키는 끝에 추가한다.
    """
    # 읽기-수정-교체를 직렬화하고 같은 디렉터리에서 원자 교체하여 손실/잘림을 막는다.
    with _env_write_lock:
        _write_env_file(updates, raise_on_error=raise_on_error)


def _write_env_file(updates: dict[str, str], *, raise_on_error: bool) -> None:
    temporary = None
    try:
        env_path = _get_env_path().resolve()
        env_path.parent.mkdir(parents=True, exist_ok=True)
        original = env_path.read_bytes() if env_path.exists() else b""
        newline = "\r\n" if b"\r\n" in original else "\n"
        # 기존 사용자가 작성한 여러 줄 인용 값도 하나의 항목으로 갱신한다.
        lines = [binding.original.string.rstrip("\r\n") for binding in parse_stream(io.StringIO(original.decode("utf-8")))]
        encoded = {}
        for key, value in updates.items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                raise ValueError("유효하지 않은 설정 키입니다.")
            # 개행은 한 물리적 줄 안에 이스케이프해 후속 갱신에서도 키 주입을 막는다.
            value = str(value)
            if any(c in value for c in "\r\n#'\"") or value != value.strip():
                value = json.dumps(value, ensure_ascii=False)
            encoded[key.upper()] = value
        remaining = dict(encoded)
        new_lines: list[str] = []

        for line in lines:
            if line.strip().startswith("#") or "=" not in line:
                new_lines.append(line)
                continue

            key = line.split("=", 1)[0].strip().removeprefix("export ").upper()

            if key in encoded:
                new_lines.append(f"{key}={encoded[key]}")
                remaining.pop(key, None)
            else:
                new_lines.append(line)

        # 파일에 없던 새 키 추가
        for key, val in remaining.items():
            new_lines.append(f"{key}={val}")

        with tempfile.NamedTemporaryFile(mode="wb", dir=env_path.parent, prefix=".env-", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write((newline.join(new_lines) + newline).encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        if env_path.exists():
            temporary.chmod(env_path.stat().st_mode & 0o777)
        os.replace(temporary, env_path)
    except Exception as e:
        logger.error(f".env 파일 업데이트 실패: {e}")
        if raise_on_error:
            raise
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

