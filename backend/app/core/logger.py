"""
Phrolova: 구조화된 로깅 모듈
표준 logging 모듈 기반. 콘솔 + 파일 동시 출력.
"""

from __future__ import annotations

import logging
import copy
import re
from urllib.parse import urlsplit, urlunsplit
import sys
import threading
from pathlib import Path


# stderr에 찍히는 줄에서 레벨을 읽어내기 위한 접두어.
# yt-dlp가 "WARNING: ...", "ERROR: ..." 꼴로 쓰고 여러 라이브러리가 같은 관습을 따른다.
_LEVEL_PREFIXES: tuple[tuple[str, int], ...] = (
    ("CRITICAL:", logging.CRITICAL),
    ("WARNING:", logging.WARNING),
    ("ERROR:", logging.ERROR),
    ("DEBUG:", logging.DEBUG),
    ("INFO:", logging.INFO),
)


def _classify_stderr_line(line: str) -> tuple[int, str]:
    """stderr 한 줄에서 로그 레벨과 본문을 뽑는다.

    접두어가 없으면 ERROR로 본다. 레벨 표시 없이 stderr에 쓰는 출력은
    대개 트레이스백처럼 실제로 문제인 것들이기 때문이다.
    """
    stripped = line.lstrip()
    upper = stripped.upper()
    for prefix, level in _LEVEL_PREFIXES:
        if upper.startswith(prefix):
            body = stripped[len(prefix):].strip()
            return level, body or stripped
    return logging.ERROR, line


class _StderrToLogger:
    """sys.stderr를 로거로 리다이렉트하는 래퍼.

    yt-dlp 경고나 파이썬 트레이스백처럼 stderr로 가는 출력을 로거를 통해
    타임스탬프와 함께 기록한다. 줄 앞의 "WARNING:" 같은 접두어로 레벨을 맞춘다 —
    예전에는 전부 ERROR로 찍어서, 정상 기동 메시지까지 에러처럼 보였다.

    재진입 방지가 핵심이다. 콘솔 핸들러가 출력에 실패하면 logging은
    handleError()에서 sys.stderr에 쓰는데, 그 stderr가 다시 이 래퍼이므로
    로거 → 핸들러 실패 → stderr → 로거 … 로 무한 재귀에 빠진다.
    (한국어 Windows 콘솔에서 이모지가 섞인 로그를 찍을 때 실제로 발생했다.)
    """

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger
        self._buf = ""
        self._local = threading.local()

    def _emit(self, line: str) -> None:
        """로깅 중 재진입이면 원래 stderr로 직접 내보낸다."""
        if getattr(self._local, "busy", False):
            try:
                sys.__stderr__.write(line + "\n")
            except Exception:
                pass
            return

        level, message = _classify_stderr_line(line)
        self._local.busy = True
        try:
            self._logger.log(level, message)
        except Exception:
            try:
                sys.__stderr__.write(line + "\n")
            except Exception:
                pass
        finally:
            self._local.busy = False

    def write(self, msg: str) -> None:
        self._buf += msg
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                self._emit(line)

    def flush(self) -> None:
        if self._buf.strip():
            self._emit(self._buf)
        self._buf = ""

    def fileno(self) -> int:  # subprocess 호환성
        return sys.__stderr__.fileno()

    def isatty(self) -> bool:
        try:
            return sys.__stderr__.isatty()
        except Exception:
            return False


def _redact_log_secrets(text: str) -> str:
    # 라이브 CDN URL의 서명과 예외 트레이스에 포함된 쿠키를 최종 출력 단계에서 가린다.
    def url(match):
        try:
            parsed = urlsplit(match.group(0))
        except ValueError:
            return "<invalid-url>"
        host = parsed.netloc.rsplit("@", 1)[-1]
        path = parsed.path
        if "/webhooks/" in path:
            path = path.split("/webhooks/", 1)[0] + "/webhooks/<redacted>"
        return urlunsplit((parsed.scheme, host, path, "", ""))
    text = re.sub(r'https?://[^\s\"\'<>]+', url, text)
    text = re.sub(r'(?i)\b(NID_AUT|NID_SES|auth[-_]token|ct0|sessionid|sessionid_ss|sid_tt|sid_guard|ttwid)=([^;\s]+)', r'\1=<redacted>', text)
    return re.sub(r'(?im)\b(Authorization|Cookie|x-csrf-token):[^\r\n]+', r'\1: <redacted>', text)


class _SecretSafeFormatter(logging.Formatter):
    def format(self, record):
        # 공유 레코드를 바꾸면 파일·콘솔 및 다른 핸들러의 예외 출력이 오염된다.
        record = copy.copy(record)
        record.scope = _log_scope(record.name)
        if record.exc_info:
            record.exc_text = None
        status = _access_status(record) if record.name == "uvicorn.access" else None
        if status is not None and status >= 400:
            record.levelno = logging.ERROR if status >= 500 else logging.WARNING
            record.levelname = logging.getLevelName(record.levelno)
        # Streamlink가 전역 레벨 이름을 소문자로 바꿔도 웹 로그 필터와 형식을 유지한다.
        record.levelname = record.levelname.upper()
        return _redact_log_secrets(super().format(record))


class _ConsoleFormatter(_SecretSafeFormatter):
    def format(self, record):
        from app.core.console import wrap_console_text
        output = super().format(record).splitlines()
        return "\n".join(wrap_console_text(line, indent="" if index == 0 else "  ") for index, line in enumerate(output))


def _access_status(record) -> int | None:
    try:
        return int(record.args[4]) if isinstance(record.args, tuple) else None
    except (IndexError, TypeError, ValueError):
        return None


def _log_scope(name: str) -> str:
    if name == "uvicorn" or name.startswith("uvicorn."):
        return "HTTP" if name == "uvicorn.access" else "SERVER"
    if name == "phrolova":
        return "SYSTEM"
    if name.startswith("phrolova."):
        return name.removeprefix("phrolova.").upper().replace(".", "/")
    return name


class _AccessLogFilter(logging.Filter):
    def __init__(self, *, debug: bool = False):
        super().__init__()
        self.debug = debug

    def filter(self, record):
        if record.levelno >= logging.WARNING or self.debug:
            return True
        # Uvicorn의 정상 폴링·정적 파일 요청만 숨긴다. HTTP 실패는 파일에도 남긴다.
        status = _access_status(record)
        return status is None or status >= 400


def _make_formatter(*, console: bool = False) -> logging.Formatter:
    """콘솔·파일·uvicorn 핸들러가 같은 줄 모양을 쓰도록 한곳에서 만든다."""
    return (_ConsoleFormatter if console else _SecretSafeFormatter)(
        fmt="%(asctime)s | %(levelname)-7s | %(scope)-19s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _make_console_handler() -> logging.StreamHandler:
    """콘솔 핸들러를 만든다.

    Windows 기본 콘솔 코드페이지(cp949 등)는 로그에 쓰이는 이모지를
    인코딩하지 못해 UnicodeEncodeError를 낸다. 스트림을 UTF-8로 바꾸고,
    그마저 안 되면 인코딩 불가 문자를 대체 문자로 흘려보낸다.
    """
    stream = sys.stdout
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            # 파이프로 연결된 경우 등 재설정이 불가능하면 그대로 둔다.
            pass

    return logging.StreamHandler(stream)


def get_log_dir(log_dir: str = "logs") -> Path:
    """Return a persistent log directory shared by the writer and log API.

    PyInstaller one-file applications extract Python modules to a temporary
    ``_MEIPASS`` directory. Logs written relative to ``__file__`` disappear
    when the process exits, so frozen builds keep them beside the executable.
    """
    if getattr(sys, "frozen", False):
        return (Path(sys.executable).resolve().parent / log_dir).resolve()

    project_root = Path(__file__).resolve().parents[3]
    candidate = Path(log_dir)
    if not candidate.is_absolute():
        candidate = project_root / candidate
    return candidate.resolve()


def setup_logger(
    name: str = "phrolova",
    *,
    level: int = logging.INFO,
    log_dir: str | None = None,
) -> logging.Logger:
    """구조화된 로거를 생성하고 반환한다.

    Args:
        name: 로거 이름.
        level: 로그 레벨.
        log_dir: 로그 파일 저장 디렉토리. None이면 파일 출력 비활성화.
    """
    logger = logging.getLogger(name)

    logger.setLevel(level)
    logger.propagate = False

    # 핸들러 내부 오류를 stderr로 뱉지 않게 한다 — 위 재진입 문제의 근원이다.
    logging.raiseExceptions = False

    # ── 포맷터 ───────────────────────────────────────────
    fmt = _make_formatter()

    # ── 콘솔 핸들러 ─────────────────────────────────────
    has_console_handler = any(
        isinstance(handler, logging.StreamHandler)
        and not isinstance(handler, logging.FileHandler)
        for handler in logger.handlers
    )
    if not has_console_handler:
        console_handler = _make_console_handler()
        console_handler.setFormatter(_make_formatter(console=True))
        logger.addHandler(console_handler)

    # ── 파일 핸들러 (선택) ───────────────────────────────
    if log_dir:
        from logging.handlers import TimedRotatingFileHandler

        log_path = get_log_dir(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)

        # service.log 로 통일하고 TimedRotatingFileHandler 적용 (매일 자정 롤링, 7일간 보존)
        active_log_path = (log_path / "service.log").resolve()
        has_file_handler = any(
            isinstance(handler, TimedRotatingFileHandler)
            and Path(handler.baseFilename).resolve() == active_log_path
            for handler in logger.handlers
        )
        if not has_file_handler:
            file_handler = TimedRotatingFileHandler(
                active_log_path,
                when="midnight",
                interval=1,
                backupCount=7,
                encoding="utf-8",
            )
            file_handler.setFormatter(fmt)
            logger.addHandler(file_handler)

    return logger


def _attach_uvicorn_logging(target: logging.Logger) -> None:
    """uvicorn 로그를 우리 로거의 핸들러로 흘려보낸다.

    uvicorn은 기본 설정에서 자기 핸들러로 stderr에 찍는다. 그런데 위
    _StderrToLogger가 stderr를 통째로 가로채므로 "Application startup complete."
    같은 INFO가 ERROR로 둔갑했다. 로그가 온통 ERROR라 진짜 에러를 골라낼 수 없었다.

    uvicorn 쪽에 log_config=None을 넘겨야 uvicorn이 자기 핸들러를 달지 않아
    이 설정이 살아남는다 (backend/run.py, backend/app/main.py 참고).
    """
    # uvicorn.error(기동·종료 메시지)와 uvicorn.asgi는 부모 'uvicorn'으로
    # 전파되므로 부모 한 곳에만 붙이면 된다.
    parent = logging.getLogger("uvicorn")
    parent.handlers = list(target.handlers)
    parent.setLevel(target.level)
    # 나중에 루트에 핸들러가 생기면 같은 줄이 두 번 찍힌다.
    parent.propagate = False

    access = logging.getLogger("uvicorn.access")
    access.handlers = list(target.handlers)
    for old_filter in list(access.filters):
        if isinstance(old_filter, _AccessLogFilter):
            access.removeFilter(old_filter)
    access.addFilter(_AccessLogFilter(debug=target.level <= logging.DEBUG))
    # Uvicorn은 HTTP 500도 INFO 레코드로 보내므로 상태 필터 전에 잘라내지 않는다.
    access.setLevel(min(target.level, logging.INFO))
    access.propagate = False
    for name in ("uvicorn.error", "uvicorn.asgi"):
        child = logging.getLogger(name)
        child.handlers = []
        child.setLevel(target.level)
        child.propagate = True


# ── 기본 로거 인스턴스 ──────────────────────────────────
def _get_default_logger():
    from app.core.config import get_settings
    try:
        settings = get_settings()
        level = logging.DEBUG if settings.debug else logging.INFO
    except Exception:
        level = logging.INFO
    _logger = setup_logger(level=level, log_dir="logs")
    sys.stderr = _StderrToLogger(_logger)  # type: ignore[assignment]
    _attach_uvicorn_logging(_logger)
    return _logger

logger = _get_default_logger()


def get_platform_logger(platform: str | None, component: str | None = None) -> logging.Logger:
    """플랫폼 enum·저장된 채널 키를 같은 분류로 기록한다."""
    if platform is None:
        return logger.getChild(component) if component else logger
    value = str(getattr(platform, "value", platform)).split(":", 1)[0].lower()
    if value not in {"chzzk", "youtube", "soop", "cime", "kick", "twitch", "tiktok", "anilife", "linkani", "ohli24", "x_spaces", "external"}:
        value = "external"
    child = logger.getChild(value)
    return child.getChild(component) if component else child


def get_media_logger(url: str) -> logging.Logger:
    """플랫폼 로그를 공용 핸들러로 전달한다. 파일 핸들러는 공유한다."""
    from urllib.parse import urlsplit

    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        host = ""
    if host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com"):
        platform = "youtube"
    elif host == "chzzk.naver.com" or host.endswith(".chzzk.naver.com"):
        platform = "chzzk"
    elif any(host == domain or host.endswith("." + domain) for domain in ("sooplive.com", "sooplive.co.kr", "afreecatv.com")):
        platform = "soop"
    elif host in {"anilife01.tv", "anilife1.tv"}:
        platform = "anilife"
    elif host == "linkani.tv":
        platform = "linkani"
    elif host == "www.ohli24.net":
        platform = "ohli24"
    elif host in {"tiktok.com", "www.tiktok.com", "m.tiktok.com", "vm.tiktok.com", "vt.tiktok.com"}:
        platform = "tiktok"
    elif host in {"twitch.tv", "www.twitch.tv", "m.twitch.tv", "go.twitch.tv", "clips.twitch.tv", "player.twitch.tv"}:
        platform = "twitch"
    elif host in {"kick.com", "www.kick.com"}:
        platform = "kick"
    elif host in {"ci.me", "www.ci.me"}:
        platform = "cime"
    elif any(host == domain or host.endswith("." + domain) for domain in ("x.com", "twitter.com", "pscp.tv")):
        platform = "x_spaces"
    else:
        platform = "external"
    return get_platform_logger(platform)
