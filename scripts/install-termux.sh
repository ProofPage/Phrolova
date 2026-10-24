#!/data/data/com.termux/files/usr/bin/bash
# Native Android/Bionic은 Termux 패키지와 내부 HOME의 가상환경을 사용한다.
# Termux는 롤링 시스템 Python 패키지('python')를 사용하며 특정 패치 단위 패키지(예: python3.14.8)는 제공되지 않습니다.
set -euo pipefail
trap 'echo "[ERROR] Termux installation failed at line $LINENO. See the command output; existing data was retained." >&2' ERR
[[ "${PHROLOVA_ENVIRONMENT:-}" != termux-proot && ( -n "${TERMUX_VERSION:-}" || "${PREFIX:-}" == /data/data/*/files/usr ) ]] || { echo 'Use this script inside Native Termux.' >&2; exit 1; }
APP_DIR="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
case "$APP_DIR" in /sdcard/*|/storage/*) echo 'Clone into Termux HOME; shared storage cannot host executable virtual environments.' >&2; exit 1;; esac
pkg install -y python python-pip git curl ffmpeg nodejs-lts clang rust make pkg-config libxml2 libxslt openssl libffi tmux procps

# 같은 관리 함수를 재사용하되 소스 로딩으로 설치 진입점을 다시 실행하지 않는다.
INSTALL_DIR="$APP_DIR"
source "$APP_DIR/scripts/manage.sh"
detect_os
ensure_python
ensure_node
ensure_ffmpeg
setup_python_env
build_frontend
setup_dirs
if [ ! -e "$APP_DIR/.env" ] && [ ! -e "$APP_DIR/backend/.env" ]; then
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  chmod 600 "$APP_DIR/.env"
fi
# 현재 엔진의 패키지만 검사한다. 삭제된 chzzkpy 의존성은 다시 설치하지 않는다.
"$APP_DIR/.venv/bin/python" -c 'import aiohttp, streamlink, yt_dlp, pydantic_core, fastapi, discord, uvicorn'
link_self
printf 'Installed. Start: bash "%s/scripts/manage.sh" start\n' "$APP_DIR"
echo 'Open http://127.0.0.1:8000 in the Android browser. Settings and media paths are retained.'
