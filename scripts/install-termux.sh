#!/data/data/com.termux/files/usr/bin/bash
# Native Android/Bionic only. Run from a checked-out repository in Termux HOME.
set -euo pipefail
trap 'echo "[ERROR] Termux installation failed at line $LINENO. See the command output; existing data was retained." >&2' ERR
[[ -n "${TERMUX_VERSION:-}" || "${PREFIX:-}" == /data/data/*/files/usr ]] || { echo 'Use this script inside Native Termux.' >&2; exit 1; }
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
case "$APP_DIR" in /sdcard/*|/storage/*) echo 'Clone into Termux HOME; shared storage cannot host executable virtual environments.' >&2; exit 1;; esac
pkg install -y python python-pip git ffmpeg nodejs-lts clang rust make pkg-config libxml2 libxslt openssl libffi tmux
python -c 'import sys; assert sys.version_info >= (3, 12), "Python 3.12+ required"'
cd "$APP_DIR"
[ -x .venv/bin/python ] || python -m venv .venv
# Never upgrade Termux-managed pip. Native C/Rust dependencies may need source builds.
.venv/bin/python -m pip install setuptools wheel
.venv/bin/python -m pip install -r backend/requirements-termux.txt
.venv/bin/python -m pip check
(cd frontend && npm ci && npm run build)
if [ ! -e .env ] && [ ! -e backend/.env ]; then
  cp .env.example .env
  chmod 600 .env
fi
mkdir -p backend/data recordings logs
.venv/bin/python -c 'import aiohttp, streamlink, yt_dlp, chzzkpy, pydantic_core, fastapi, discord'
printf 'Installed. Start: cd "%s/backend" && "%s/.venv/bin/python" run.py\n' "$APP_DIR" "$APP_DIR"
echo 'Open http://127.0.0.1:8000 in Android browser. Native installation and recording were confirmed on a user device; dependency builds can vary by device.'
