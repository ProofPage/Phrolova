import shutil
import sys
import tempfile
from contextlib import contextmanager
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
