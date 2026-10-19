"""App-owned, verified YouTube runtime installation and local provider lifecycle."""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path

import httpx

from app.core.config import get_settings
from app.core.logger import get_platform_logger

log = get_platform_logger("youtube", "tools")
DENO_VERSION = "2.9.7"
PROVIDER_VERSION = "2.0.2"
SOURCE_HASH = "8bdd5d68e5ffe40fcc0a1aa131d8c39d7f279b663eed7c6c068e37bb06bc1d41"
PLUGIN_HASH = "a26b980bf6d8e8400d8f21445daa4d8381bf6183d20f0be309391f86b31e27ef"
DENO_HASHES = {
    "x86_64-pc-windows-msvc": "a0c3101b4158d1dfb7d6a78a7bf0f3de80c96bb423c152beec8beb22786f2238",
    "aarch64-pc-windows-msvc": "c4c4ac8bfdaa37814bda5c05fc9cdf2154904e2ef8277673a30bdceaaa649807",
    "x86_64-apple-darwin": "95daaff11c116a52ad54785e7914c8e9c9cdcaba793c5ed929c74ca2d8e6259a",
    "aarch64-apple-darwin": "5cd46d6268f6f78f5d88bdc7159d20bd44cdaa4b3303474839f87ec6fe7ae25c",
    "x86_64-unknown-linux-gnu": "c6527f24f4b16031d3ae4fa9f658d5f11534c8d84ce7dc8502420280919c3490",
    "aarch64-unknown-linux-gnu": "c832298b1ad4422481334855f6003e0f54145762c5a134f20a489511d2f65bbf",
}
LOCAL_URL = "http://127.0.0.1:4416"


def deno_executable():
    root = Path(os.environ.get("DENO_INSTALL") or Path.home() / ".deno")
    return root / "bin" / ("deno.exe" if os.name == "nt" else "deno")


def target():
    arch = {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "aarch64", "aarch64": "aarch64"}.get(platform.machine().lower())
    system = {"Windows": "pc-windows-msvc", "Darwin": "apple-darwin", "Linux": "unknown-linux-gnu"}.get(platform.system())
    value = f"{arch}-{system}"
    if value not in DENO_HASHES or os.environ.get("ANDROID_ROOT"):
        raise RuntimeError("이 환경의 Deno 자동 설치는 지원하지 않습니다. 호환 런타임을 직접 설치하세요.")
    return value


def download(url, digest):
    with httpx.Client(timeout=60, follow_redirects=True, trust_env=True) as client:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            data = bytearray()
            for chunk in response.iter_bytes():
                data.extend(chunk)
                if len(data) > 128 * 1024 * 1024:
                    raise ValueError("YouTube 도구 다운로드 크기 제한을 초과했습니다.")
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("YouTube 도구 SHA-256 검증에 실패했습니다.")
    return bytes(data)


def unpack(data, destination, prefix=""):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if sum(item.file_size for item in archive.infolist()) > 512 * 1024 * 1024:
            raise ValueError("YouTube 도구 압축 해제 크기 제한을 초과했습니다.")
        for item in archive.infolist():
            if not item.filename.startswith(prefix):
                continue
            relative = item.filename[len(prefix):]
            path = destination / relative
            if (not path.resolve().is_relative_to(destination.resolve())
                    or "\\" in relative or (item.external_attr >> 16) & 0o170000 == 0o120000):
                raise ValueError("YouTube 도구 압축 파일에 허용되지 않은 경로가 있습니다.")
            if item.is_dir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(archive.read(item))


class YouTubeTools:
    def __init__(self):
        self.bundle = None
        self.process = None
        self.process_log = None
        self.status = "not_started"
        self.message = ""
        self.lock = threading.RLock()
        self.stopping = False

    def root(self):
        if sys.platform == "win32":
            base = Path(os.environ["LOCALAPPDATA"])
        elif sys.platform == "darwin":
            base = Path.home() / "Library" / "Application Support"
        else:
            base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
        return base / "Phrolova" / "youtube-tools"

    def external_provider(self):
        value = (get_settings().youtube_po_token_provider_url or "").strip().rstrip("/")
        return value if value and value != LOCAL_URL else None

    def executable(self, bundle):
        return deno_executable()

    def ensure_runtime(self, arch):
        executable = self.executable(None)
        self.report("installing", f"[1/6] Deno 검사·설치 중 · 경로: {executable}")
        if not executable.exists():
            executable.parent.mkdir(parents=True, exist_ok=True)
            data = download(f"https://github.com/denoland/deno/releases/download/v{DENO_VERSION}/deno-{arch}.zip", DENO_HASHES[arch])
            with tempfile.TemporaryDirectory(prefix=".phrolova-deno-", dir=executable.parent) as temporary:
                staging = Path(temporary)
                unpack(data, staging)
                source = staging / executable.name
                source.chmod(0o755)
                try:
                    # Publish the complete verified binary without replacing a
                    # concurrently installed or user-managed executable.
                    executable.hardlink_to(source)
                except FileExistsError:
                    pass
        version = self.run([str(executable), "--version"], executable.parent, 10)
        match = re.match(rb"deno (\d+)\.", version)
        if not match or int(match[1]) < 2:
            raise RuntimeError(f"기존 Deno는 덮어쓰지 않습니다. Deno 2 이상을 설치하세요: {executable}")
        log.info("Deno 실행 확인 완료 · 경로: %s", executable)

    def report(self, status, message):
        self.status, self.message = status, message
        log.info("%s", message)

    def run(self, args, cwd, timeout):
        result = subprocess.run(
            args, cwd=cwd, capture_output=True, timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode:
            from app.engine.platform_auth import redact_media_error
            raise RuntimeError(redact_media_error(result.stderr.decode("utf-8", "replace")[-1500:]))
        return result.stdout

    def load_bundle(self):
        state = json.loads((self.root() / "state.json").read_text(encoding="utf-8"))
        bundle = self.root() / state["directory"]
        if (not bundle.resolve().is_relative_to(self.root().resolve())
                or state["version"] != PROVIDER_VERSION or state["deno_version"] != DENO_VERSION):
            raise ValueError("YouTube 도구 설치 버전이 일치하지 않습니다.")
        if hashlib.sha256(self.executable(bundle).read_bytes()).hexdigest() != state["deno_hash"]:
            raise ValueError("설치된 Deno 검증에 실패했습니다.")
        if hashlib.sha256((bundle / "plugins/bgutil.zip").read_bytes()).hexdigest() != PLUGIN_HASH:
            raise ValueError("설치된 PO Token 플러그인 검증에 실패했습니다.")
        if not (bundle / "server/node_modules").is_dir() or not (bundle / "server/src/main.ts").is_file():
            raise ValueError("PO Token 서버 설치가 불완전합니다.")
        self.run([str(self.executable(bundle)), "--version"], bundle, 10)
        return bundle

    def install(self):
        arch = target()
        self.root().mkdir(parents=True, exist_ok=True)
        bundle = Path(tempfile.mkdtemp(prefix="install-", dir=self.root()))
        self.ensure_runtime(arch)
        self.report("installing", f"[2/6] bgutil {PROVIDER_VERSION} 서버 다운로드·SHA-256 검증 중")
        source = download("https://api.github.com/repos/Brainicism/bgutil-ytdlp-pot-provider/zipball/2.0.2", SOURCE_HASH)
        unpack(source, bundle, "Brainicism-bgutil-ytdlp-pot-provider-26475e9/")
        plugins = bundle / "plugins"
        plugins.mkdir()
        self.report("installing", f"[3/6] bgutil {PROVIDER_VERSION} yt-dlp 플러그인 다운로드·SHA-256 검증 중")
        (plugins / "bgutil.zip").write_bytes(download(
            f"https://github.com/Brainicism/bgutil-ytdlp-pot-provider/releases/download/{PROVIDER_VERSION}/bgutil-ytdlp-pot-provider.zip", PLUGIN_HASH))
        self.report("installing", "[4/6] Deno 서버 의존성 설치 중 · 최대 240초")
        self.run([str(self.executable(bundle)), "install", "--allow-scripts=npm:canvas", "--frozen"],
                 bundle / "server", 240)
        self.run([str(self.executable(bundle)), "--version"], bundle, 10)
        return bundle

    def ping(self):
        try:
            with httpx.Client(timeout=2, trust_env=False) as client:
                response = client.get(LOCAL_URL + "/ping")
                return response.status_code == 200 and response.json().get("version") == PROVIDER_VERSION
        except (httpx.HTTPError, ValueError):
            return False

    def activate_plugins(self):
        from yt_dlp.globals import plugin_dirs
        from yt_dlp.plugins import load_all_plugins
        directory = str(self.bundle / "plugins")
        if directory not in plugin_dirs.value:
            plugin_dirs.value.append(directory)
            load_all_plugins()
        # Import verification is separate from server health.
        from yt_dlp_plugins.extractor.getpot_bgutil_http import BgUtilHTTPPTP
        if BgUtilHTTPPTP.PROVIDER_NAME != "bgutil:http":
            raise RuntimeError("PO Token 플러그인을 확인하지 못했습니다.")

    def prepare(self):
        with self.lock:
            if self.stopping or self.status == "failed":
                return
            if self.status == "ready" and (self.external_provider() or self.ping()):
                return
            installed = False
            try:
                self.report("checking", "YouTube 보조 도구 검사 중 · Deno·bgutil 서버·yt-dlp 플러그인")
                try:
                    self.bundle = self.load_bundle()
                    log.info("YouTube 도구 설치 확인 완료 · 재설치 생략")
                except (OSError, ValueError, KeyError, subprocess.SubprocessError):
                    self.bundle = self.install()
                    installed = True
                self.report("checking", "[5/6] bgutil yt-dlp 플러그인 로드·확인 중")
                self.activate_plugins()
                if not self.external_provider() and not self.ping():
                    self.report("starting", f"[6/6] bgutil 로컬 서버 시작·응답 확인 중 · {LOCAL_URL} · 최대 30초")
                    if self.process is not None and self.process.poll() is None:
                        raise RuntimeError("PO Token 서버가 실행 중이지만 정상 응답하지 않습니다.")
                    self.process_log = (self.bundle / "provider.log").open("ab")
                    self.process = subprocess.Popen(
                        [str(self.executable(self.bundle)), "run", "--allow-env", "--allow-net",
                         "--allow-ffi=.", "--allow-read=.", "../src/main.ts", "--host", "127.0.0.1"],
                        cwd=self.bundle / "server/node_modules", stdout=self.process_log,
                        stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    deadline = time.monotonic() + 30
                    while not self.ping():
                        if self.process.poll() is not None or time.monotonic() >= deadline:
                            raise RuntimeError(f"PO Token 로컬 서버를 시작하지 못했습니다. 로그: {self.bundle / 'provider.log'}")
                        time.sleep(0.25)
                elif self.external_provider():
                    log.info("[6/6] 사용자 지정 PO Token 서버 설정 유지 · 로컬 서버 시작 생략")
                else:
                    log.info("[6/6] 실행 중인 bgutil 로컬 서버 응답 확인 완료 · 중복 실행 생략")
                if installed:
                    state = {"directory": self.bundle.name, "version": PROVIDER_VERSION,
                             "deno_version": DENO_VERSION,
                             "deno_hash": hashlib.sha256(self.executable(self.bundle).read_bytes()).hexdigest()}
                    path = self.root() / "state.json"
                    temporary = path.with_suffix(".tmp")
                    temporary.write_text(json.dumps(state), encoding="utf-8")
                    temporary.replace(path)
                self.report("ready", "Deno·bgutil 서버 연결 설정·PO Token 플러그인 준비 완료")
                log.info("토큰 발급과 유튜브 재생 성공은 별도 검증입니다.")
            except Exception as error:
                self.status, self.message = "failed", f"{self.message} · {error}"
                self.stop_process()
                log.warning("YouTube 도구 준비 실패 · 다른 플랫폼은 계속 실행합니다 · %s", self.message)

    def stop_process(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
            self.process = None
        if self.process_log is not None:
            self.process_log.close()
            self.process_log = None

    async def ready(self):
        # Installation failures are logged once, not repeated for every video.
        if self.status != "failed":
            await asyncio.to_thread(self.prepare)

    async def stop(self):
        self.stopping = True
        await asyncio.to_thread(self._stop)

    def _stop(self):
        with self.lock:
            self.stop_process()


youtube_tools = YouTubeTools()
