# -*- mode: python ; coding: utf-8 -*-
# Rookery PyInstaller 빌드 스펙 (onefile 방식)
# 사용법: pyinstaller rookery.spec --clean

import re
import shutil
import subprocess
import urllib.request
from pathlib import Path

import certifi
from PyInstaller.utils.hooks import collect_submodules, collect_data_files, copy_metadata
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

# ── 파일 속성용 버전 ─────────────────────────────────────────
# backend/app/version.py 하나만 보고 읽는다. 여기에 숫자를 또 적어두면
# 릴리즈할 때마다 두 곳을 고쳐야 하고, 반드시 한쪽을 잊는다.
APP_VERSION = re.search(
    r'__version__ = "([^"]+)"',
    Path("backend/app/version.py").read_text(encoding="utf-8"),
).group(1)

# 파일 버전은 항상 4자리여야 한다 (2.0.3 -> 2, 0, 3, 0).
_VERSION_TUPLE = (tuple(int(x) for x in APP_VERSION.split(".")) + (0, 0, 0, 0))[:4]

# 우클릭 → 속성 → 자세히에서 보이는 정보. 이게 없으면 배포한 실행 파일에
# 누가 만들었는지 흔적이 남지 않는다.
VERSION_RESOURCE = VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=_VERSION_TUPLE,
        prodvers=_VERSION_TUPLE,
        mask=0x3F,
        flags=0x0,
        OS=0x40004,
        fileType=0x1,
        subtype=0x0,
        date=(0, 0),
    ),
    kids=[
        # 0x0409(en-US) + 1200(Unicode). 어느 언어의 Windows에서도 이 블록을
        # 찾아 보여주므로 한국어 문자열을 담아도 문제가 없다.
        StringFileInfo([
            StringTable("040904B0", [
                StringStruct("CompanyName", "Serian"),
                StringStruct("FileDescription", "Rookery — 라이브 감시·녹화 및 아카이브 도구"),
                StringStruct("FileVersion", APP_VERSION),
                StringStruct("InternalName", "Rookery"),
                StringStruct("LegalCopyright", "Copyright (c) 2026 Serian (github.com/eruminyu). MIT License."),
                StringStruct("OriginalFilename", "Rookery.exe"),
                StringStruct("ProductName", "Rookery"),
                StringStruct("ProductVersion", APP_VERSION),
            ]),
        ]),
        VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
    ],
)

# ── 숨겨진 임포트 (자동 탐지가 안 되는 모듈) ─────────────────
hidden_imports = [
    *collect_submodules("uvicorn"),
    *collect_submodules("fastapi"),
    *collect_submodules("app"),
    # UI 트레이
    "pystray",
    "PIL",
    "PIL.Image",
    "PIL.ImageDraw",
    # 비동기 / HTTP
    *collect_submodules("aiofiles"),
    "aiofiles",
    "aiofiles.os",
    "aiofiles.threadpool",
    *collect_submodules("aiohttp"),
    "aiohttp",
    "websockets",
    # FastAPI 의존
    "multipart",
    "python_multipart",
    "email.mime.text",
    "email.mime.multipart",
    # pydantic / settings
    "pydantic",
    "pydantic.v1",
    "pydantic_settings",
    "pydantic_core",
    "pydantic_core._pydantic_core",
    # chzzkpy
    "chzzkpy",
    # discord
    "discord",
    "discord.ext.commands",
    # yt-dlp
    "yt_dlp",
    # Streamlink direct HLS API used by the live recording pipeline
    *collect_submodules("streamlink.stream"),
    "streamlink",
    # dotenv
    "dotenv",
    # ssl
    "certifi",
]

# ── 데이터 파일 ───────────────────────────────────────────────
datas = [
    # 빌드된 프론트엔드 정적 파일
    ("backend/app/static", "app/static"),
    # 앱 아이콘
    ("assets/icon.png", "assets"),
    # SSL 인증서 번들 (certifi)
    (certifi.where(), "certifi"),
    # 설정 화면과 시작 콘솔에서 Streamlink 설치 버전을 표시한다.
    *copy_metadata("streamlink"),
]

# ── 외부 바이너리: ffmpeg는 라이선스 문제로 번들하지 않음 ──────
# 사용자가 bin/ffmpeg.exe에 넣거나 시스템 PATH에 설치해야 함.
# run.py의 _run_dependency_check()가 시작 시 자동 감지 및 안내함.
# YouTube's EJS solver needs an external JavaScript runtime even in a frozen app.
node_path = shutil.which("node")
if not node_path:
    raise RuntimeError("Node.js 22+ is required to build the YouTube runtime bundle")
node_version = subprocess.check_output([node_path, "--version"], text=True).strip()
if not re.fullmatch(r"v\d+\.\d+\.\d+", node_version) or int(node_version.split('.')[0][1:]) < 22:
    raise RuntimeError("Node.js 22+ is required to build the YouTube runtime bundle")
license_path = Path("build/node-LICENSE.txt")
license_path.parent.mkdir(parents=True, exist_ok=True)
with urllib.request.urlopen(f"https://raw.githubusercontent.com/nodejs/node/{node_version}/LICENSE", timeout=30) as response:
    license_path.write_bytes(response.read())
datas.append((str(license_path), "third_party"))
binaries = [(node_path, "bin")]

a = Analysis(
    ["backend/run.py"],
    pathex=["backend"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "test", "unittest", "pytest", "setuptools"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Rookery",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX packing increases heuristic antivirus detections on unsigned one-file builds.
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,           # 의존성 감지 안내 때 CMD 창이 필요하므로 True
    icon="assets/icon.ico", # Windows 아이콘
    version=VERSION_RESOURCE,
)
