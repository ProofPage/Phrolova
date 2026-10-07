"""
Rookery: 설정 관리 모듈
pydantic-settings 기반으로 환경변수 및 .env 파일에서 설정을 로드한다.
"""

from __future__ import annotations

import sys
import shutil
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _download_ytdlp_exe(dest: Path) -> None:
    """yt-dlp.exe를 GitHub Releases에서 자동 다운로드한다."""
    import urllib.request

    url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    try:
        urllib.request.urlretrieve(url, tmp)
        tmp.replace(dest)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise


def resolve_env_path() -> Path:
    """실행 환경에 맞는 .env 파일의 절대 경로를 반환한다.

    탐색 순서:
        1. PyInstaller exe 빌드: exe 파일 옆
        2. 개발 환경: 프로젝트 루트

    읽기(설정 로드)와 쓰기(설정 저장)가 같은 파일을 봐야 하므로
    이 규칙은 한 곳에만 둔다. 예전에는 core/utils.py에 같은 함수가 한 벌 더
    있어서 한쪽만 고치면 조용히 어긋날 수 있었다.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / ".env"

    project_root = Path(__file__).resolve().parents[3]
    candidate = project_root / ".env"
    if candidate.exists():
        return candidate
    backend_env = project_root / "backend" / ".env"
    if backend_env.exists():
        return backend_env
    return candidate  # 없으면 프로젝트 루트에 만든다


def _resolve_env_file() -> str:
    """pydantic-settings의 env_file 인자용 문자열 경로."""
    return str(resolve_env_path())


def resolve_data_dir() -> Path:
    """영속 데이터(채널 목록, 이력, 대기 알림)를 둘 디렉터리를 반환한다.

    PyInstaller onefile은 임시 압축 해제 경로에서 실행되므로 그곳에 쓰면
    재시작 때 사라진다. exe 옆 data/ 폴더를 사용한다.
    """
    if getattr(sys, "frozen", False):
        data_dir = Path(sys.executable).parent / "data"
    else:
        data_dir = Path(__file__).resolve().parents[2] / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


class Settings(BaseSettings):
    """애플리케이션 전역 설정."""

    model_config = SettingsConfigDict(
        env_file=_resolve_env_file(),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── 앱 메타 ──────────────────────────────────────────
    app_name: str = "Phrolova"
    debug: bool = False

    # ── FFmpeg ───────────────────────────────────────────
    ffmpeg_path: str = "ffmpeg"

    # ── 저장 경로 ────────────────────────────────────────
    download_dir: str = "./recordings"
    live_download_dir: str = ""       # 라이브 녹화 경로 (빈 문자열 = 구버전 DOWNLOAD_DIR 사용)
    vod_download_dir: str = ""         # 다시보기/VOD 경로 (빈 문자열 = 구버전 경로 설정 사용)
    split_download_dirs: bool = False   # 분할 저장 경로 사용 여부
    vod_chzzk_dir: str = ""             # 치지직 VOD/클립 저장 경로 (빈 문자열 = download_dir 사용)
    vod_external_dir: str = ""          # 외부 URL(유튜브 등) 저장 경로 (빈 문자열 = download_dir 사용)

    @property
    def effective_live_download_dir(self) -> str:
        """새 설정이 없으면 기존 DOWNLOAD_DIR을 라이브 경로로 사용한다."""
        return self.live_download_dir or self.download_dir

    def effective_vod_download_dir(self, is_chzzk: bool) -> str:
        """새 공통 VOD 경로를 우선하고, 구버전의 서비스별 설정도 보존한다."""
        if self.vod_download_dir:
            return self.vod_download_dir
        if self.split_download_dirs:
            legacy_dir = self.vod_chzzk_dir if is_chzzk else self.vod_external_dir
            if legacy_dir:
                return legacy_dir
        return self.download_dir

    # ── 치지직 인증 쿠키 (Optional) ──────────────────────
    nid_aut: Optional[str] = None
    nid_ses: Optional[str] = None

    # ── 서버 ─────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8000

    # ── Discord Bot ──────────────────────────────────────
    discord_bot_token: Optional[str] = None
    discord_notification_channel_id: Optional[str] = None  # 알림을 보낼 채널 ID
    discord_command_user_ids: Optional[str] = None    # 명령어 허용 사용자 ID (쉼표 구분)
    discord_command_channel_id: Optional[str] = None  # 명령어 허용 채널 ID (미설정 시 알림 채널 사용)

    # ── Discord 알림 ─────────────────────────────────────
    # Bot 연결이 끊겨도 알림이 도착하도록 하는 폴백 경로.
    discord_webhook_url: Optional[str] = None
    # 전송할 알림 종류: "all" | "none" | 콤마 구분 목록 (NotificationKind 값)
    discord_notify_events: str = "all"
    # 멘션을 붙일 알림 종류. 기본은 멘션 없음.
    discord_mention_events: str = ""
    # 멘션 대상: "@here", "@everyone", "<@&역할ID>"
    discord_mention_target: str = "@here"
    # 큐에서 대기하는 알림의 최대 수명 (초). 초과 시 폐기해 뒷북 알림을 막는다.
    discord_notify_ttl: int = 3600

    # ── 감시 주기 (초) ───────────────────────────────────
    monitor_interval: int = 60

    # ── 다운로드 설정 ─────────────────────────────────────
    keep_download_parts: bool = False  # VOD 다운로드 중단 시 .part 파일 유지 여부
    max_record_retries: int = 3        # 라이브 녹화 자동 재시도 최대 횟수
    chzzk_stream_mode: Optional[str] = None   # standard | request-timemachine | force-timemachine
    chzzk_time_machine_enabled: Optional[bool] = None  # 구버전 설정 호환용
    chzzk_time_machine_offset: Optional[int] = None  # 스트림 시작 기준 건너뛸 초 수
    chzzk_time_machine_shift: Optional[int] = None  # 구버전 설정 호환용
    save_live_preview: bool = False           # 치지직 녹화 시작 시 미리보기 이미지 저장
    live_download_condition: Literal["all", "watchalong", "exclude_watchalong"] = "all"
    watchalong_tags: str = "같이보기"
    live_filename_template: str = "[{name}] {title} {live_date_year}-{live_date_month}-{live_date_day} {live_date_hour}-{live_date_minute}-{live_date_second}"

    @field_validator("live_filename_template", mode="before")
    @classmethod
    def migrate_default_live_filename_template(cls, value: object) -> object:
        """기존 기본 템플릿만 새 날짜·시간 파일명 형식으로 옮긴다."""
        if value == "[{download_date}][{name}] {title}":
            return "[{name}] {title} {live_date_year}-{live_date_month}-{live_date_day} {live_date_hour}-{live_date_minute}-{live_date_second}"
        return value

    @property
    def effective_chzzk_stream_mode(self) -> str:
        """Resolve current and legacy time-machine settings to the reference modes."""
        if self.chzzk_stream_mode in {
            "standard", "request-timemachine", "force-timemachine"
        }:
            return self.chzzk_stream_mode
        if self.chzzk_time_machine_enabled is True:
            return "force-timemachine"
        if self.chzzk_time_machine_enabled is False:
            return "standard"
        return "request-timemachine"

    @property
    def effective_chzzk_time_machine_offset(self) -> int:
        """Use the new start offset, migrating older rewind settings if present."""
        if self.chzzk_time_machine_offset is not None:
            return max(0, min(86400, self.chzzk_time_machine_offset))
        if self.chzzk_time_machine_shift is not None:
            return max(0, min(86400, self.chzzk_time_machine_shift))
        return 0

    # ── 녹화 포맷/품질 ─────────────────────────────────────
    live_format: str = "ts"            # 라이브 녹화 포맷: ts(권장), mkv, mp4
    vod_filename_template: str = "[{name}] {title} {date_year}-{date_month}-{date_day} {date_hour}-{date_minute}-{date_second}"

    @field_validator("vod_filename_template")
    @classmethod
    def validate_vod_filename_template(cls, value: str) -> str:
        from app.core.vod_filename import validate_vod_template
        return validate_vod_template(value)

    vod_format: str = "mp4"            # VOD 다운로드 포맷: mp4(권장), mkv, ts
    recording_quality: str = "best"    # 녹화 품질: best, 1080p, 720p, 480p

    # ── VOD 다운로드 설정 ──────────────────────────────────
    vod_max_concurrent: int = 3        # 동시 다운로드 최대 개수
    vod_default_quality: str = "best"  # 기본 화질: best, 1080p, 720p, 480p
    vod_max_speed: int = 0             # 최대 다운로드 속도 (MB/s, 0 = 무제한)

    # ── 채팅 아카이빙 ────────────────────────────────────
    chat_archive_enabled: bool = False  # 녹화 시 채팅 자동 아카이빙 여부

    youtube_cookie_file: Optional[str] = None

    # ── X Spaces 인증 ────────────────────────────────────
    x_cookie_file: Optional[str] = None  # Netscape 형식 쿠키 파일 경로

    def resolve_ytdlp_path(self, auto_download: bool = False) -> str:
        """yt-dlp 실행 파일 경로를 탐색 순서에 따라 결정한다.

        탐색 순서:
            1. 시스템 PATH
            2. exe/스크립트 옆 bin/ 폴더 (배포 번들 및 개발 환경)
            3. venv bin/ (개발 환경)
            4. Windows exe 환경에서 자동 다운로드 (auto_download=True 시)
        """
        import sys as _sys

        # 1) 시스템 PATH
        for name in ("yt-dlp", "yt-dlp.exe"):
            found = shutil.which(name)
            if found:
                return found

        # 2) exe/프로젝트 옆 bin/ 폴더
        if getattr(_sys, "frozen", False):
            base_dir = Path(_sys.executable).parent
        else:
            base_dir = Path(__file__).resolve().parents[3]

        for fname in ("yt-dlp.exe", "yt-dlp"):
            candidate = base_dir / "bin" / fname
            if candidate.is_file():
                return str(candidate)

        # 3) venv bin/ (개발 환경)
        venv_bin = Path(_sys.executable).parent
        for name in ("yt-dlp", "yt-dlp.exe"):
            candidate = venv_bin / name
            if candidate.is_file():
                return str(candidate)

        # 4) Windows exe 환경에서 자동 다운로드
        if auto_download and getattr(_sys, "frozen", False) and _sys.platform == "win32":
            dest = base_dir / "bin" / "yt-dlp.exe"
            _download_ytdlp_exe(dest)
            return str(dest)

        raise FileNotFoundError(
            "yt-dlp를 찾을 수 없습니다. "
            "pip install yt-dlp 또는 프로그램 옆 bin/yt-dlp.exe를 배치하세요."
        )

    def resolve_ffmpeg_path(self) -> str:
        """FFmpeg 실행 파일 경로를 탐색 순서에 따라 결정한다.

        탐색 순서:
            1. 설정값 (FFMPEG_PATH)
            2. exe/스크립트 옆 bin/ 폴더 (배포 번들 및 개발 환경)
            3. 시스템 PATH
        """
        import sys as _sys

        # 1) 설정값이 유효한 경우
        configured = Path(self.ffmpeg_path)
        if configured.is_file():
            return str(configured)

        # 2) exe 옆 bin/ 폴더 (PyInstaller 빌드 환경 포함)
        if getattr(_sys, "frozen", False):
            # 빌드된 .exe 기준
            base_dir = Path(_sys.executable).parent
        else:
            # 개발 환경: 프로젝트 루트 기준
            base_dir = Path(__file__).resolve().parents[3]

        for fname in ("ffmpeg.exe", "ffmpeg"):
            candidate = base_dir / "bin" / fname
            if candidate.is_file():
                return str(candidate)

        # 3) 시스템 PATH
        system_ffmpeg = shutil.which("ffmpeg")
        if system_ffmpeg:
            return system_ffmpeg

        raise FileNotFoundError(
            "FFmpeg를 찾을 수 없습니다. "
            "FFMPEG_PATH 환경변수를 설정하거나 "
            "프로그램 옆 bin/ffmpeg.exe를 배치하거나 "
            "시스템 PATH에 ffmpeg를 추가하세요."
        )


@lru_cache
def get_settings() -> Settings:
    """싱글턴 Settings 인스턴스를 반환한다."""
    return Settings()
