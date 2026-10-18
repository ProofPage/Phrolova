"""
Phrolova: 데스크톱 실행 진입점

PyInstaller로 빌드된 .exe 실행 시:
  1. Python 3.12+ 및 FFmpeg 의존성 자동 감지
  2. 없으면 CMD 창에서 대화형 설치 안내
  3. 통과 시 서버 시작 → 브라우저 자동 오픈
  4. 시스템 트레이 아이콘 표시 (종료, 브라우저 열기)

--desktop 플래그 또는 PyInstaller 빌드 환경에서 자동 데스크톱 모드 진입.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path


# Windows 기본 콘솔(cp949)에서 이모지 출력이 앱 시작을 중단하지 않게 한다.
for stream in (sys.stdout, sys.stderr):
    if stream is not None and hasattr(stream, "reconfigure"):
        stream.reconfigure(errors="replace")


# ── PyInstaller SSL 인증서 번들 설정 ────────────────────────────
# PyInstaller 빌드 시 certifi CA 번들이 자동으로 포함되지 않아
# aiohttp/yt-dlp 등에서 SSL 인증서 검증 실패가 발생한다.
# 앱 시작 전에 SSL_CERT_FILE 환경변수를 설정하여 해결.
def _setup_ssl_certs() -> None:
    """PyInstaller 환경에서 SSL 인증서 경로를 설정한다."""
    if getattr(sys, "frozen", False):
        try:
            import certifi
            os.environ.setdefault("SSL_CERT_FILE", certifi.where())
        except ImportError:
            pass

_setup_ssl_certs()


# ── PyInstaller 빌드 판별 ────────────────────────────────────
IS_FROZEN = getattr(sys, "frozen", False)


# ── 의존성 검사 ──────────────────────────────────────────────

def _check_python_version() -> bool:
    """Python 3.12 이상인지 확인한다."""
    return sys.version_info >= (3, 12)


def _find_ytdlp() -> str | None:
    """yt-dlp 실행 파일을 탐색한다.

    탐색 순서:
        1. exe 옆 bin/yt-dlp.exe (배포 번들용)
        2. 시스템 PATH
    """
    if IS_FROZEN:
        bundle_dir = Path(sys.executable).parent
    else:
        bundle_dir = Path(__file__).resolve().parent.parent

    for fname in (("yt-dlp.exe", "yt-dlp") if sys.platform == "win32" else ("yt-dlp",)):
        p = bundle_dir / "bin" / fname
        if p.is_file() and (sys.platform == "win32" or os.access(p, os.X_OK)):
            return str(p)

    return shutil.which("yt-dlp")


def _download_ytdlp(bin_dir: Path) -> str | None:
    """yt-dlp.exe를 GitHub Releases에서 자동 다운로드한다."""
    if sys.platform != "win32":
        print("  yt-dlp: python -m pip install yt-dlp")
        return None
    import urllib.request

    url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
    dest = bin_dir / "yt-dlp.exe"
    tmp = bin_dir / "yt-dlp.tmp"
    bin_dir.mkdir(parents=True, exist_ok=True)
    try:
        print("  yt-dlp 다운로드 중... (GitHub Releases)")
        urllib.request.urlretrieve(url, tmp)
        tmp.replace(dest)
        return str(dest)
    except Exception as e:
        if tmp.exists():
            tmp.unlink()
        print(f"  ⚠️  yt-dlp 자동 다운로드 실패: {e}")
        return None


def _find_ffmpeg() -> str | None:
    """FFmpeg 실행 파일을 탐색한다.

    탐색 순서:
        1. exe 옆 bin/ffmpeg.exe (배포 번들용)
        2. 시스템 PATH
    """
    # 1) exe 옆 bin/ 폴더 (배포 시 사용자가 넣어두는 경로)
    if IS_FROZEN:
        bundle_dir = Path(sys.executable).parent
    else:
        bundle_dir = Path(__file__).resolve().parent.parent

    names = ("ffmpeg.exe", "ffmpeg") if sys.platform == "win32" else ("ffmpeg",)
    candidates = [bundle_dir / "bin" / name for name in names]
    for p in candidates:
        if p.is_file() and (sys.platform == "win32" or os.access(p, os.X_OK)):
            return str(p)

    # 2) 시스템 PATH
    return shutil.which("ffmpeg")


def _get_streamlink_version() -> str | None:
    """Streamlink 설치 버전을 읽는다. 라이브 녹화에 필요한 패키지다."""
    try:
        from importlib.metadata import PackageNotFoundError, version

        try:
            return version("streamlink")
        except PackageNotFoundError:
            # 개발 환경이나 일부 패키징 환경에서는 배포 메타데이터가 없을 수 있다.
            import streamlink

            return getattr(streamlink, "__version__", "설치됨")
    except Exception:
        return None


def _run_dependency_check() -> bool:
    """의존성을 검사하고, 없으면 대화형으로 설치 안내한다.

    Returns:
        True: 모든 의존성 충족 (진행 가능)
        False: 의존성 미충족 (종료)
    """
    from app.core.console import print_check, wrap_console_text
    from app.engine.media_tools import check_media_tool
    from app.version import __version__

    print(f"\nPhrolova v{__version__}\n")
    warnings = 0
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    python_ok = _check_python_version()
    print_check("정상" if python_ok else "오류", "Python", py_ver if python_ok else f"{py_ver} · 3.12 이상 필요")
    all_ok = python_ok

    ffmpeg_health = check_media_tool("ffmpeg")
    ffmpeg_path = ffmpeg_health.get("path") if ffmpeg_health["available"] else None
    if ffmpeg_path:
        print_check("정상", "FFmpeg", ffmpeg_health.get("version", "실行確認").split(" Copyright")[0].removeprefix("ffmpeg version "), path=ffmpeg_path)
    else:
        print_check("오류", "FFmpeg", ffmpeg_health["message"])
        all_ok = False

    ffprobe_health = check_media_tool("ffprobe")
    if ffprobe_health["available"]:
        print_check("정상", "FFprobe", ffprobe_health.get("version", "실행 확인 완료").split(" Copyright")[0].removeprefix("ffprobe version "), path=ffprobe_health.get("path"))
    else:
        warnings += 1
        print_check("주의", "FFprobe", ffprobe_health["message"])
        print(wrap_console_text("원본 녹화는 계속합니다. 파일 검사·변환을 사용하려면 FFprobe를 설치하거나 FFPROBE_PATH를 설정하세요.", indent="         "))

    streamlink_version = _get_streamlink_version()
    if streamlink_version:
        print_check("정상", "Streamlink", f"v{streamlink_version}")
    else:
        print_check("오류", "Streamlink", "패키지 없음 · 라이브 녹화에 필요")
        all_ok = False

    ytdlp_path = _find_ytdlp()
    if not ytdlp_path:
        print_check("확인", "yt-dlp", "실행 파일 없음 · 설치 확인 중")
        bin_dir = Path(sys.executable).parent / "bin" if IS_FROZEN else Path(__file__).resolve().parent.parent / "bin"
        ytdlp_path = _download_ytdlp(bin_dir)
    if ytdlp_path:
        print_check("정상", "yt-dlp", "실행 파일 확인", path=ytdlp_path)
    else:
        warnings += 1
        print_check("주의", "yt-dlp", "설치 실패 · 동영상 다운로드와 일부 라이브 기능을 사용할 수 없습니다.")

    if all_ok:
        from app.engine.youtube_tools import youtube_tools
        youtube_tools.prepare()
        if youtube_tools.status == "ready":
            print_check("정상", "YouTube", youtube_tools.message)
        else:
            warnings += 1
            print_check("주의", "YouTube", youtube_tools.message)
        print(f"\n필수 항목 확인 완료 · 주의 {warnings}건. 서버를 시작합니다.\n" if warnings else "\n모든 항목 정상 · 서버를 시작합니다.\n")
        return True

    if sys.platform != "win32" or not sys.stdin.isatty():
        print("필수 의존성을 설치하세요: Python 3.12+, 시스템 FFmpeg, backend/requirements.txt")
        return False

    # ── 의존성 미충족 → 대화형 안내 ─────────────────────────
    print()
    print("  ❌ 필수 의존성이 설치되어 있지 않습니다.")
    print()

    if not _check_python_version():
        print("  📌 Python 3.12 설치 방법:")
        print("     https://www.python.org/downloads/")
        print("     설치 시 'Add Python to PATH' 체크박스를 반드시 선택하세요.")
        print()

    if not ffmpeg_path or not ffprobe_health['available']:
        print("  📌 FFmpeg 설치 방법 (아래 중 하나 선택):")
        print()
        print("  [방법 1] winget으로 자동 설치 (Windows 10/11 권장)")
        print("     winget install --id Gyan.FFmpeg -e")
        print()
        print("  [방법 2] 수동 설치")
        print("     1. https://ffmpeg.org/download.html 에서 Windows 빌드 다운로드")
        print("     2. 압축 해제 후 bin/ffmpeg.exe와 bin/ffprobe.exe를 이 프로그램 옆 'bin' 폴더에 복사")
        print("        또는 시스템 PATH에 추가")
        print()

    if not streamlink_version:
        print("  📌 Streamlink를 사용할 수 없습니다:")
        if IS_FROZEN:
            print("     최신 Phrolova 실행 파일로 교체한 뒤 다시 시작하세요.")
        else:
            print("     backend/requirements.txt의 의존성을 설치한 뒤 다시 시작하세요.")
        print()

    # FFmpeg와 FFprobe를 검증한 후 함께 설치한다.
    if (not ffmpeg_path or not ffprobe_health['available']) and _check_python_version():
        answer = input("  FFmpeg를 지금 자동으로 다운로드하고 설치할까요? [y/N]: ").strip().lower()
        if answer == "y":
            print()
            print("  FFmpeg 다운로드 및 설치 중... (파일 크기와 네트워크 상태에 따라 수 분이 소요될 수 있습니다)")
            try:
                # 대상 폴더: 프로그램 폴더 (또는 실행 파일 폴더) 내의 'bin'
                if IS_FROZEN:
                    bin_dir = Path(sys.executable).parent / "bin"
                else:
                    bin_dir = Path(__file__).resolve().parent.parent / "bin"
                
                bin_dir.mkdir(parents=True, exist_ok=True)

                # Read exactly the two approved ZIP entries; no extraction paths or shell interpolation.
                import tempfile, urllib.request, zipfile
                with tempfile.TemporaryDirectory(prefix='phrolova-tools-') as staging:
                    archive = Path(staging) / 'ffmpeg.zip'
                    with urllib.request.urlopen('https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip', timeout=30) as response, archive.open('wb') as output:
                        shutil.copyfileobj(response, output)
                    with zipfile.ZipFile(archive) as package:
                        for name in ('ffmpeg.exe', 'ffprobe.exe'):
                            matches = [item for item in package.infolist() if Path(item.filename).name == name and not item.is_dir()]
                            if len(matches) != 1:
                                raise RuntimeError(f'{name} not found uniquely in package')
                            candidate = Path(staging) / name
                            with package.open(matches[0]) as source, candidate.open('wb') as output:
                                shutil.copyfileobj(source, output)
                            checked = subprocess.run([str(candidate), '-version'], capture_output=True, timeout=5, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                            if checked.returncode:
                                raise RuntimeError(f'{name} execution failed')
                        for name in ('ffmpeg.exe', 'ffprobe.exe'):
                            shutil.copy2(Path(staging) / name, bin_dir / name)
                if (bin_dir / 'ffmpeg.exe').is_file() and (bin_dir / 'ffprobe.exe').is_file():
                    print("  ✅ FFmpeg와 FFprobe 설치 완료! (bin 폴더)")
                    return bool(streamlink_version)
                else:
                    print()
                    print("  ⚠️  자동 설치에 실패했습니다. 수동으로 설치해 주세요.")
            except Exception as e:
                print()
                print(f"  ⚠️  설치 중 오류가 발생했습니다: {e}")
                print("      수동 설치: https://ffmpeg.org/download.html")
        print()

    input("  Enter를 눌러 종료...")
    return False


# ── 아이콘 경로 ──────────────────────────────────────────────

def _get_icon_path() -> Path:
    """아이콘 파일 경로를 반환한다. PyInstaller 빌드 환경을 고려."""
    if IS_FROZEN:
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(__file__).resolve().parent.parent
    icon = base / "assets" / "icon.png"
    return icon if icon.exists() else base / "assets" / "icon.ico"


# ── 시스템 트레이 ────────────────────────────────────────────

def _run_tray(url: str, stop_event: threading.Event) -> None:
    """시스템 트레이 아이콘을 실행한다. (별도 스레드에서 호출)"""
    try:
        import pystray
        from PIL import Image, ImageDraw

        icon_path = _get_icon_path()
        if icon_path.exists():
            image = Image.open(icon_path)
        else:
            # 아이콘 파일 없으면 기본 도형으로 대체
            image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            draw.ellipse([4, 4, 60, 60], fill=(99, 102, 241))  # 인디고 원

        def on_open_browser(icon, item):
            webbrowser.open(url)

        def on_quit(icon, item):
            stop_event.set()
            icon.stop()

        icon = pystray.Icon(
            "Phrolova",
            image,
            "Phrolova",
            menu=pystray.Menu(
                pystray.MenuItem("브라우저 열기", on_open_browser, default=True),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("종료", on_quit),
            ),
        )
        icon.run()
    except ImportError:
        # pystray 없으면 트레이 없이 동작 (stop_event 대기)
        stop_event.wait()


# ── 서버 실행 ────────────────────────────────────────────────

def _run_server(settings, stop_event: threading.Event) -> None:
    """uvicorn 서버를 실행한다. (별도 스레드에서 호출)"""
    import uvicorn
    from app.main import app

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        try:
            from asyncio.proactor_events import _ProactorBasePipeTransport
            _orig = _ProactorBasePipeTransport._call_connection_lost
            def _silent(self, exc):
                if isinstance(exc, (ConnectionResetError, ConnectionAbortedError)) or (
                    isinstance(exc, OSError) and getattr(exc, "winerror", None) in (10053, 10054)
                ):
                    exc = None
                try:
                    return _orig(self, exc)
                except (ConnectionResetError, ConnectionAbortedError, OSError):
                    pass
            _ProactorBasePipeTransport._call_connection_lost = _silent
        except (ImportError, AttributeError):
            pass

    config = uvicorn.Config(
        app,
        host=settings.host,
        port=settings.port,
        reload=False,
        loop="asyncio",
        log_level="info",
        # None이어야 uvicorn이 자기 stderr 핸들러를 달지 않는다.
        # 그래야 app.core.logger가 잡아둔 라우팅이 유지된다.
        log_config=None,
        timeout_graceful_shutdown=10,
    )
    server = uvicorn.Server(config)
    app.state.uvicorn_server = server

    def _watch_stop():
        stop_event.wait()
        server.should_exit = True

    threading.Thread(target=_watch_stop, daemon=True).start()
    try:
        server.run()
    except KeyboardInterrupt:
        # Uvicorn re-raises SIGINT after graceful shutdown; match uvicorn.run().
        pass


# ── 진입점 ───────────────────────────────────────────────────

if __name__ == "__main__":
    if sys.argv[1:2] == ['--youtube-worker']:
        from app.engine.youtube_worker import main
        main(sys.argv[2:])
        sys.exit(0)

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        try:
            from asyncio.proactor_events import _ProactorBasePipeTransport
            _orig = _ProactorBasePipeTransport._call_connection_lost
            def _silent(self, exc):
                if isinstance(exc, (ConnectionResetError, ConnectionAbortedError)) or (
                    isinstance(exc, OSError) and getattr(exc, "winerror", None) in (10053, 10054)
                ):
                    exc = None
                try:
                    return _orig(self, exc)
                except (ConnectionResetError, ConnectionAbortedError, OSError):
                    pass
            _ProactorBasePipeTransport._call_connection_lost = _silent
        except (ImportError, AttributeError):
            pass

    # PyInstaller 빌드이거나 --desktop 플래그가 있으면 데스크톱 모드
    desktop_mode = (IS_FROZEN or "--desktop" in sys.argv) and sys.platform == "win32"
    if not _check_python_version():
        sys.exit("Python 3.12 이상이 필요합니다.")

    if desktop_mode:
        # 의존성 검사 (없으면 안내 후 종료)
        if not _run_dependency_check():
            sys.exit(1)

    from app.core.config import get_settings
    settings = get_settings()
    url = f"http://localhost:{settings.port}"
    stop_event = threading.Event()

    if desktop_mode:
        # 서버를 별도 스레드에서 실행
        server_thread = threading.Thread(
            target=_run_server, args=(settings, stop_event), daemon=True
        )
        server_thread.start()

        # 서버 기동 대기 후 브라우저 자동 오픈
        time.sleep(1.5)
        webbrowser.open(url)

        # 트레이 아이콘 실행 (메인 스레드 블로킹)
        _run_tray(url, stop_event)
    else:
        # Run on the main thread, sharing shutdown handling with desktop mode.
        if sys.platform == 'win32':
            _run_server(settings, stop_event)
        else:
            from app.core.process_control import registered_server
            with registered_server():
                _run_server(settings, stop_event)
