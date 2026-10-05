"""
Rookery: 데스크톱 실행 진입점

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
            os.environ["SSL_CERT_FILE"] = certifi.where()
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

    for fname in ("yt-dlp.exe", "yt-dlp"):
        p = bundle_dir / "bin" / fname
        if p.is_file():
            return str(p)

    return shutil.which("yt-dlp")


def _download_ytdlp(bin_dir: Path) -> str | None:
    """yt-dlp.exe를 GitHub Releases에서 자동 다운로드한다."""
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

    candidates = [
        bundle_dir / "bin" / "ffmpeg.exe",
        bundle_dir / "bin" / "ffmpeg",
    ]
    for p in candidates:
        if p.is_file():
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
    print("=" * 60)
    print("  Phrolova 의존성 검사")
    print("=" * 60)

    all_ok = True

    # ── Python 버전 확인 ─────────────────────────────────────
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if _check_python_version():
        print(f"  [OK]  Python {py_ver}")
    else:
        print(f"  [!!]  Python {py_ver} - 3.12 이상이 필요합니다.")
        all_ok = False

    # ── FFmpeg 확인 ──────────────────────────────────────────
    ffmpeg_path = _find_ffmpeg()
    if ffmpeg_path:
        print(f"  [OK]  FFmpeg: {ffmpeg_path}")
    else:
        print("  [!!]  FFmpeg를 찾을 수 없습니다.")
        all_ok = False

    # ── Streamlink 확인 (라이브 녹화 필수) ──────────────────
    streamlink_version = _get_streamlink_version()
    if streamlink_version:
        print(f"  [OK]  Streamlink: v{streamlink_version}")
    else:
        print("  [!!]  Streamlink를 찾을 수 없습니다. 라이브 녹화에 필요합니다.")
        all_ok = False

    # ── yt-dlp 확인 (없으면 자동 다운로드) ──────────────────
    ytdlp_path = _find_ytdlp()
    if ytdlp_path:
        print(f"  [OK]  yt-dlp: {ytdlp_path}")
    else:
        print("  [--]  yt-dlp를 찾을 수 없습니다. 자동 다운로드 시도 중...")
        if IS_FROZEN:
            bin_dir = Path(sys.executable).parent / "bin"
        else:
            bin_dir = Path(__file__).resolve().parent.parent / "bin"
        ytdlp_path = _download_ytdlp(bin_dir)
        if ytdlp_path:
            print(f"  [OK]  yt-dlp 설치 완료: {ytdlp_path}")
        else:
            print("  [!!]  yt-dlp 설치 실패 — 녹화 기능이 동작하지 않을 수 있습니다.")

    print("=" * 60)

    if all_ok:
        print("  ✅ 모든 의존성 확인 완료. 서버를 시작합니다...\n")
        return True

    # ── 의존성 미충족 → 대화형 안내 ─────────────────────────
    print()
    print("  ❌ 필수 의존성이 설치되어 있지 않습니다.")
    print()

    if not _check_python_version():
        print("  📌 Python 3.12 설치 방법:")
        print("     https://www.python.org/downloads/")
        print("     설치 시 'Add Python to PATH' 체크박스를 반드시 선택하세요.")
        print()

    if not ffmpeg_path:
        print("  📌 FFmpeg 설치 방법 (아래 중 하나 선택):")
        print()
        print("  [방법 1] winget으로 자동 설치 (Windows 10/11 권장)")
        print("     winget install --id Gyan.FFmpeg -e")
        print()
        print("  [방법 2] 수동 설치")
        print("     1. https://ffmpeg.org/download.html 에서 Windows 빌드 다운로드")
        print("     2. 압축 해제 후 bin/ffmpeg.exe를 이 프로그램 옆 'bin' 폴더에 복사")
        print("        또는 시스템 PATH에 추가")
        print()

    if not streamlink_version:
        print("  📌 Streamlink를 사용할 수 없습니다:")
        if IS_FROZEN:
            print("     최신 Phrolova 실행 파일로 교체한 뒤 다시 시작하세요.")
        else:
            print("     backend/requirements.txt의 의존성을 설치한 뒤 다시 시작하세요.")
        print()

    # FFmpeg 자동 설치 제안 (PowerShell 다운로드 및 압축 해제)
    if not ffmpeg_path and _check_python_version():
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

                # PowerShell로 다운로드 및 압축 해제 명령 (gyan.dev essentials 빌드)
                ps_script = f"""
                $ProgressPreference = 'SilentlyContinue'
                $zipUrl = 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'
                $zipPath = '{bin_dir}\\ffmpeg.zip'
                $extractPath = '{bin_dir}\\temp_extracted'
                
                Write-Host '다운로드 시작...'
                Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath
                
                Write-Host '압축 해제 중...'
                Expand-Archive -Path $zipPath -DestinationPath $extractPath -Force
                
                # 풀린 폴더 내에서 ffmpeg.exe 찾아서 bin 폴더로 이동
                $exePath = Get-ChildItem -Path $extractPath -Recurse -Filter 'ffmpeg.exe' | Select-Object -First 1
                if ($exePath) {{
                    Move-Item -Path $exePath.FullName -Destination '{bin_dir}\\ffmpeg.exe' -Force
                }}
                
                # 임시 파일 정리
                Remove-Item -Path $zipPath -Force
                Remove-Item -Path $extractPath -Recurse -Force
                """
                
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps_script],
                    check=False,
                )
                
                if result.returncode == 0 and (bin_dir / "ffmpeg.exe").exists():
                    print()
                    print("  ✅ FFmpeg 설치 완료! (bin 폴더에 배치됨)")
                    print("  ⚠️  서버를 시작합니다...")
                    return True  # 설치 성공 시 바로 계속 진행
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
            "ChzzkRecorderPro",
            image,
            "Rookery",
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
    )
    server = uvicorn.Server(config)

    def _watch_stop():
        stop_event.wait()
        server.should_exit = True

    threading.Thread(target=_watch_stop, daemon=True).start()
    server.run()


# ── 진입점 ───────────────────────────────────────────────────

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    # PyInstaller 빌드이거나 --desktop 플래그가 있으면 데스크톱 모드
    desktop_mode = IS_FROZEN or "--desktop" in sys.argv

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
        # CLI 모드: 단순 uvicorn 실행
        import uvicorn
        from app.main import app
        uvicorn.run(
            app,
            host=settings.host,
            port=settings.port,
            reload=False,
            loop="asyncio",
            log_level="info",
            # 위 _run_server와 같은 이유로 None.
            log_config=None,
        )
