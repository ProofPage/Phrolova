import shutil
import sys
import tempfile
import http.cookiejar
import warnings
from contextlib import ExitStack, contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from app.core.config import get_settings


def is_youtube_url(url):
    host = (urlsplit(url).hostname or "").lower()
    return host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com")


def runtime_options():
    runtimes = {}
    for name in ("deno", "node"):
        executable = shutil.which(name)
        for folder in (Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "bin",
                       Path(sys.executable).parent / "bin", Path(sys.executable).parent):
            candidate = folder / (name + (".exe" if sys.platform == "win32" else ""))
            if candidate.is_file():
                executable = str(candidate)
                break
        if executable:
            runtimes[name] = {"path": executable}
    return {"js_runtimes": runtimes} if runtimes else {}


def runtime_cli_options():
    args = []
    for name, options in runtime_options().get("js_runtimes", {}).items():
        args.extend(["--js-runtimes", f"{name}:{options['path']}"])
    return args


@contextmanager
def youtube_cookies():
    source = get_settings().youtube_cookie_file
    if not source:
        yield None
        return
    if not Path(source).is_file():
        raise ValueError("유튜브 쿠키 파일이 없습니다. 설정 → 인증에서 다시 등록해 주세요.")
    with tempfile.TemporaryDirectory(prefix="phrolova-youtube-") as folder:
        copy = Path(folder) / "cookies.txt"
        shutil.copyfile(source, copy)
        yield str(copy)


class YouTubeAuthenticationError(ValueError):
    """A user-facing authentication failure without upstream credentials."""


def youtube_auth_message(error, *, has_cookies=False):
    text = str(error).lower()
    if "private video" in text:
        return ("등록된 YouTube 계정에 이 비공개 영상의 시청 권한이 있는지 확인해 주세요." if has_cookies else
                "비공개 영상입니다. 시청 권한이 있는 계정의 YouTube 쿠키를 설정 → 인증 → 유튜브에 등록한 뒤 다시 시도해 주세요.")
    if any(marker in text for marker in ("members-only", "members only", "available to members", "join this channel")):
        return ("등록된 YouTube 계정에 이 영상의 멤버십 시청 권한이 있는지 확인해 주세요." if has_cookies else
                "멤버십 전용 영상입니다. 시청 권한이 있는 계정의 YouTube 쿠키를 설정 → 인증 → 유튜브에 등록한 뒤 다시 시도해 주세요.")
    if any(marker in text for marker in ("not a bot", "sign in to confirm", "login required", "login_required",
                                        "age-restricted", "age restricted", "account required", "sign in to view", "sign in to watch")):
        return ("YouTube 로그인을 확인하지 못했습니다. 설정 → 인증 → 유튜브에서 쿠키를 다시 등록하고 계정의 시청 권한을 확인해 주세요." if has_cookies else
                "이 영상은 YouTube 로그인 확인이 필요합니다. 설정 → 인증 → 유튜브에서 쿠키를 등록한 뒤 다시 시도해 주세요.")
    return None


@contextmanager
def youtube_cookie_fallback(error):
    """Borrow explicit user cookies only after a confirmed authentication error."""
    message = youtube_auth_message(error)
    if message is None:
        raise error
    with ExitStack() as stack:
        try:
            cookie_file = stack.enter_context(youtube_cookies())
            if cookie_file:
                # Validate before yt-dlp can log a malformed cookie line.
                with warnings.catch_warnings(record=True):
                    jar = http.cookiejar.MozillaCookieJar(cookie_file)
                    jar.load(ignore_discard=True, ignore_expires=True)
        except (OSError, ValueError, UnicodeError):
            raise YouTubeAuthenticationError(
                "등록된 YouTube 쿠키 파일을 읽을 수 없거나 형식이 올바르지 않습니다. 설정 → 인증 → 유튜브에서 다시 등록해 주세요."
            ) from None
        if cookie_file is None:
            raise YouTubeAuthenticationError(message) from None
        yield cookie_file


async def with_youtube_cookie_fallback(operation):
    try:
        return await operation(None)
    except Exception as error:
        with youtube_cookie_fallback(error) as cookie_file:
            try:
                return await operation(cookie_file)
            except Exception as authenticated_error:
                message = youtube_auth_message(authenticated_error, has_cookies=True)
                if message:
                    raise YouTubeAuthenticationError(message) from None
                raise
