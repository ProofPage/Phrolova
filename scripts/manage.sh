#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  Rookery — 통합 관리 스크립트 (Linux / macOS)
#
#  원라이너 (설치 · 업데이트 겸용):
#    curl -fsSL https://raw.githubusercontent.com/eruminyu/Rookery/main/scripts/manage.sh | bash
#
#  설치 후에는 어디서나 한 단어로 쓴다:
#    rookery update | start | stop | status | logs
#
#  설계 원칙
#    - 이 파일 하나로 설치·업데이트가 끝난다 (curl | bash 로 실행되므로 자기완결적이어야 함)
#    - 같은 명령을 두 번 실행해도 안전하다 (idempotent)
#
#  Docker로 띄우는 경우는 이 스크립트를 쓰지 않는다.
#  저장소 루트에서 `docker compose up --build -d` 를 직접 실행하면 된다 (docs/docker-guide.md).
# ═══════════════════════════════════════════════════════════════
set -euo pipefail

REPO_SLUG="eruminyu/Rookery"
REPO_URL="https://github.com/${REPO_SLUG}.git"
RAW_URL="https://raw.githubusercontent.com/${REPO_SLUG}/main/scripts/manage.sh"
APP_NAME="rookery"
SERVICE_NAME="rookery"
DEFAULT_PORT=8000
REQUIRED_PYTHON_MINOR=10
REQUIRED_FFMPEG_MAJOR=6
REQUIRED_NODE_MAJOR=20

# ── 출력 ──────────────────────────────────────────────────────
if [ -t 1 ]; then
  RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'
  CYAN=$'\033[0;36m'; BOLD=$'\033[1m'; NC=$'\033[0m'
else
  RED=""; GREEN=""; YELLOW=""; CYAN=""; BOLD=""; NC=""
fi

info()  { echo "${GREEN}[✔]${NC} $1"; }
warn()  { echo "${YELLOW}[!]${NC} $1"; }
error() { echo "${RED}[✘]${NC} $1" >&2; exit 1; }
step()  { echo ""; echo "${BOLD}${CYAN}▶ $1${NC}"; }

# 한글은 한 글자가 두 칸을 차지해 박스 테두리를 맞추기 어렵다.
# 터미널 폰트에 따라 어긋나므로 테두리 없이 간다.
banner() {
  echo ""
  echo "${CYAN}${BOLD}  Rookery${NC} — 멀티 플랫폼 라이브 녹화 · 아카이빙"
  echo ""
}

has_cmd() { command -v "$1" >/dev/null 2>&1; }

# root로 돌리는 서버가 흔한데, 최소 이미지에는 sudo가 아예 없는 경우가 있다.
# 이미 root면 sudo를 붙이지 않고, 아니면 있을 때만 쓴다.
SUDO=""
SUDO_E=""
if [ "$(id -u)" -ne 0 ]; then
  if command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
    SUDO_E="sudo -E"
  else
    echo "${YELLOW}[!]${NC} sudo를 찾을 수 없습니다. 권한이 필요한 단계에서 실패할 수 있습니다." >&2
  fi
fi

# curl | bash 로 실행되면 stdin이 스크립트 본문이라 read가 깨진다.
# 사용자에게 물을 때는 항상 터미널을 직접 연다.
confirm() {
  local reply=""
  if [ ! -e /dev/tty ]; then
    return 1
  fi
  read -rp "${YELLOW}[?]${NC} $1 [y/N]: " reply </dev/tty || reply=""
  [[ "$reply" =~ ^[Yy]$ ]]
}

# ── 설치 위치 ─────────────────────────────────────────────────
# 저장소 안에서 실행됐으면 그 저장소를, 아니면 기본 경로를 쓴다.
resolve_install_dir() {
  [ -n "${INSTALL_DIR:-}" ] && return

  local self_dir root
  self_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || true)"
  if [ -n "$self_dir" ]; then
    root="$(dirname "$self_dir")"
    if [ -d "$root/backend" ] && [ -d "$root/frontend" ]; then
      INSTALL_DIR="$root"
      return
    fi
  fi

  # 구버전 설치 경로를 쓰던 사용자를 그대로 이어받는다.
  # Rookery로 이름을 바꾸기 전 설치본이 ~/signal-recorder에 있다.
  local legacy
  for legacy in "$HOME/signal-recorder" "$HOME/chzzk-recorder-pro"; do
    if [ -d "$legacy/.git" ]; then
      INSTALL_DIR="$legacy"
      return
    fi
  done

  INSTALL_DIR="$HOME/$APP_NAME"
}

is_installed() { [ -d "$INSTALL_DIR/.git" ]; }

require_install() {
  is_installed || error "설치를 찾을 수 없습니다: $INSTALL_DIR
  먼저 설치하세요:  curl -fsSL $RAW_URL | bash"
}

venv_python() { echo "$INSTALL_DIR/.venv/bin/python"; }
venv_pip()    { echo "$INSTALL_DIR/.venv/bin/pip"; }

# ── OS / 패키지 매니저 ────────────────────────────────────────
PKG_MANAGER=""

detect_os() {
  if [ "$(uname -s)" = "Darwin" ]; then
    has_cmd brew || error "Homebrew가 필요합니다: https://brew.sh"
    PKG_MANAGER="brew"
    return
  fi

  [ -f /etc/os-release ] || error "지원하지 않는 OS입니다 (/etc/os-release 없음)."
  . /etc/os-release
  case "${ID:-} ${ID_LIKE:-}" in
    *debian*|*ubuntu*) PKG_MANAGER="apt" ;;
    *fedora*)          PKG_MANAGER="dnf" ;;
    *rhel*|*centos*)   PKG_MANAGER="$(has_cmd dnf && echo dnf || echo yum)" ;;
    *arch*)            PKG_MANAGER="pacman" ;;
    *)                 PKG_MANAGER="" ;;
  esac
}

pkg_install() {
  case "$PKG_MANAGER" in
    apt)    $SUDO apt-get install -y "$@" ;;
    dnf)    $SUDO dnf install -y "$@" ;;
    yum)    $SUDO yum install -y "$@" ;;
    pacman) $SUDO pacman -S --noconfirm "$@" ;;
    brew)   brew install "$@" ;;
    *)      error "패키지 매니저를 알 수 없습니다. $* 를 수동 설치한 뒤 다시 실행하세요." ;;
  esac
}

# ── 의존성 ────────────────────────────────────────────────────
PYTHON_CMD=""

install_ffmpeg_static() {
  local arch pattern url tmpdir bin probe
  arch="$(uname -m)"
  case "$arch" in
    x86_64)  pattern="linux64-gpl.tar.xz" ;;
    aarch64) pattern="linuxarm64-gpl.tar.xz" ;;
    *)       error "지원하지 않는 아키텍처: $arch (x86_64 / aarch64만 지원)" ;;
  esac

  url=$(curl -fsSL "https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/latest" \
        | grep browser_download_url | grep "$pattern" | grep -v shared \
        | cut -d'"' -f4 | head -1)
  [ -n "$url" ] || error "ffmpeg 다운로드 URL을 찾지 못했습니다.
  수동 설치: https://github.com/BtbN/FFmpeg-Builds/releases"

  tmpdir="$(mktemp -d)"
  trap 'rm -rf "$tmpdir"' RETURN
  info "ffmpeg 정적 빌드 다운로드 중 ($arch)..."
  curl -fsSL --retry 3 -L -o "$tmpdir/ffmpeg.tar.xz" "$url" || error "ffmpeg 다운로드 실패."
  tar xf "$tmpdir/ffmpeg.tar.xz" -C "$tmpdir"

  bin="$(find "$tmpdir" -type f -name ffmpeg | head -1)"
  probe="$(find "$tmpdir" -type f -name ffprobe | head -1)"
  [ -n "$bin" ] || error "ffmpeg 압축 해제 실패."
  $SUDO install -m 755 "$bin" /usr/local/bin/ffmpeg
  [ -n "$probe" ] && $SUDO install -m 755 "$probe" /usr/local/bin/ffprobe
}

ensure_ffmpeg() {
  if ! has_cmd ffmpeg; then
    if [ "$PKG_MANAGER" = "apt" ] || [ "$PKG_MANAGER" = "brew" ]; then
      pkg_install ffmpeg
    else
      install_ffmpeg_static
    fi
  fi

  local ver major
  ver="$(ffmpeg -version 2>&1 | head -1 | awk '{print $3}')"
  major="$(echo "$ver" | sed 's/^[nN]//' | cut -d. -f1)"
  if ! [ "$major" -ge "$REQUIRED_FFMPEG_MAJOR" ] 2>/dev/null; then
    error "ffmpeg ${REQUIRED_FFMPEG_MAJOR}.0 이상이 필요합니다 (현재: ${ver:-알 수 없음})."
  fi
  info "ffmpeg $ver ✓"
}

ensure_python() {
  local cmd ver minor
  for cmd in python3.13 python3.12 python3.11 python3.10 python3; do
    has_cmd "$cmd" || continue
    ver="$("$cmd" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    minor="$(echo "$ver" | cut -d. -f2)"
    if [ "$minor" -ge "$REQUIRED_PYTHON_MINOR" ]; then
      PYTHON_CMD="$cmd"
      info "Python $ver ✓"
      break
    fi
  done

  if [ -z "$PYTHON_CMD" ]; then
    info "Python 3.12 설치 중..."
    case "$PKG_MANAGER" in
      apt)
        $SUDO apt-get update -qq
        $SUDO apt-get install -y software-properties-common
        $SUDO add-apt-repository -y ppa:deadsnakes/ppa
        $SUDO apt-get update -qq
        $SUDO apt-get install -y python3.12 python3.12-venv
        ;;
      dnf)  $SUDO dnf install -y python3.12 ;;
      brew) brew install python@3.12 ;;
      *)    error "Python 3.${REQUIRED_PYTHON_MINOR}+ 를 찾을 수 없습니다. 수동 설치 후 다시 실행하세요." ;;
    esac
    PYTHON_CMD="python3.12"
    info "Python 3.12 설치 완료 ✓"
    return
  fi

  # Python은 있는데 venv 모듈이 빠진 배포판이 있다 (Ubuntu deadsnakes 등).
  if [ "$PKG_MANAGER" = "apt" ] && ! "$PYTHON_CMD" -c 'import ensurepip' 2>/dev/null; then
    local py_minor
    py_minor="$("$PYTHON_CMD" -c 'import sys; print(sys.version_info.minor)')"
    $SUDO apt-get install -y "python3.${py_minor}-venv" 2>/dev/null || $SUDO apt-get install -y python3-venv
    info "venv 패키지 설치 완료 ✓"
  fi
}

ensure_node() {
  if has_cmd node; then
    local major
    major="$(node -e 'process.stdout.write(process.versions.node.split(".")[0])')"
    if [ "$major" -ge "$REQUIRED_NODE_MAJOR" ]; then
      info "Node.js v$(node -e 'process.stdout.write(process.versions.node)') ✓"
      return
    fi
    warn "Node.js가 v${REQUIRED_NODE_MAJOR} 미만입니다. 최신 LTS로 교체합니다."
  fi

  info "Node.js 22 LTS 설치 중..."
  if [ "$PKG_MANAGER" = "brew" ]; then
    brew install node@22
  else
    curl -fsSL https://deb.nodesource.com/setup_22.x | $SUDO_E bash - 2>/dev/null \
      || curl -fsSL https://rpm.nodesource.com/setup_22.x | $SUDO bash - 2>/dev/null \
      || error "Node.js 설치 실패. https://nodejs.org 에서 수동 설치하세요."
    pkg_install nodejs
  fi
  info "Node.js $(node --version) ✓"
}

ensure_base_tools() {
  has_cmd git  || pkg_install git
  has_cmd curl || pkg_install curl
}

# ── 저장소 / 빌드 ─────────────────────────────────────────────
# 반환값: 0 = 갱신함, 1 = 이미 최신, 2 = 실패
#
# 호출부가 `if sync_repo` 형태라 이 함수 안에서는 set -e가 동작하지 않는다.
# (bash는 조건문에서 실행되는 명령의 실패를 종료 사유로 보지 않는다.)
# 그래서 모든 실패를 명시적으로 잡아 2로 돌려준다. 예전에는 이게 없어서
# git pull이 실패해도 "업데이트 완료"를 찍고 넘어갔다.
sync_repo() {
  step "저장소 동기화"

  if ! is_installed; then
    info "$INSTALL_DIR 에 클론 중..."
    git clone --quiet "$REPO_URL" "$INSTALL_DIR" || return 2
    info "클론 완료 ✓"
    return 0
  fi

  # 리포 이름이 여러 번 바뀌었다(Chzzk_downloader → Signal-Recorder → Rookery).
  # GitHub 리다이렉트로 당장은 동작하지만 영구 보장이 아니므로 정식 주소로 맞춘다.
  local current_remote
  current_remote="$(git -C "$INSTALL_DIR" remote get-url origin 2>/dev/null || true)"
  if [ -n "$current_remote" ] && [ "$current_remote" != "$REPO_URL" ]; then
    git -C "$INSTALL_DIR" remote set-url origin "$REPO_URL" || true
    info "원격 주소를 갱신했습니다 → $REPO_URL"
  fi

  git -C "$INSTALL_DIR" fetch origin --quiet || return 2

  local local_rev remote_rev
  local_rev="$(git -C "$INSTALL_DIR" rev-parse HEAD)" || return 2
  remote_rev="$(git -C "$INSTALL_DIR" rev-parse origin/main)" || return 2
  if [ "$local_rev" = "$remote_rev" ]; then
    info "이미 최신입니다."
    return 1
  fi

  if git -C "$INSTALL_DIR" pull --ff-only origin main --quiet; then
    info "코드 업데이트 완료 ✓"
    return 0
  fi

  # 예전 버전이 추적하던 빌드 산출물(frontend/tsconfig.tsbuildinfo 등)이
  # 지금은 gitignore 대상이라, 로컬 변경으로 남아 병합을 막는다.
  # 지우면 사용자가 직접 고친 파일까지 날릴 수 있으므로 stash로 치운다.
  warn "로컬 변경이 병합을 막고 있습니다. stash로 치우고 다시 시도합니다."
  local stash_name="rookery-update-$(date +%Y%m%d-%H%M%S)"
  if ! git -C "$INSTALL_DIR" stash push -u -m "$stash_name" >/dev/null 2>&1; then
    warn "stash에 실패했습니다."
    return 2
  fi

  if git -C "$INSTALL_DIR" pull --ff-only origin main --quiet; then
    info "코드 업데이트 완료 ✓"
    info "치워둔 로컬 변경: git -C $INSTALL_DIR stash list  (${stash_name})"
    return 0
  fi

  warn "stash 이후에도 병합에 실패했습니다."
  return 2
}

setup_dirs() {
  mkdir -p "$INSTALL_DIR/recordings" "$INSTALL_DIR/data" "$INSTALL_DIR/logs"
}

build_frontend() {
  step "프론트엔드 빌드"
  # vite.config.ts의 outDir이 ../backend/app/static 이라 결과물이 바로 백엔드로 들어간다.
  (cd "$INSTALL_DIR/frontend" && npm ci --silent && npm run build)
  info "빌드 완료 ✓"
}

setup_python_env() {
  step "Python 가상환경"
  local venv="$INSTALL_DIR/.venv"
  [ -d "$venv" ] || "$PYTHON_CMD" -m venv "$venv"
  "$venv/bin/pip" install --upgrade pip -q
  "$venv/bin/pip" install -r "$INSTALL_DIR/backend/requirements.txt" -q
  info "의존성 설치 완료 ✓"
}

# 명령을 걸어둘 후보 디렉터리.
#
# /usr/local/bin을 먼저 쓴다. root의 기본 PATH에 들어 있어 셸 설정을 건드리지
# 않아도 바로 잡히고, ffmpeg도 이미 같은 곳에 설치하므로 규칙이 하나로 맞는다.
# ~/.local/bin은 root의 기본 PATH에 없다 — 여기로 내려가면 안내가 한 단계 더 필요하다.
SYSTEM_BINDIR="/usr/local/bin"
USER_BINDIR="$HOME/.local/bin"

# 이름이 바뀌기 전에 걸어둔 명령. systemd 유닛과 달리 지금까지 정리하지 않아
# 옛 이름이 낡은 경로를 가리킨 채 남아 있었다.
LEGACY_COMMAND_NAMES="signal-recorder chzzk-recorder-pro"

# 우리가 만든 심볼릭 링크만 지운다. 같은 이름의 진짜 파일은 건드리지 않는다.
remove_legacy_commands() {
  local dir name link
  for dir in "$SYSTEM_BINDIR" "$USER_BINDIR"; do
    for name in $LEGACY_COMMAND_NAMES; do
      link="$dir/$name"
      [ -L "$link" ] || continue
      case "$(readlink "$link" 2>/dev/null)" in
        */scripts/manage.sh) ;;
        *) continue ;;
      esac
      rm -f "$link" 2>/dev/null || $SUDO rm -f "$link" 2>/dev/null || true
      [ -e "$link" ] || info "구버전 명령 정리: $link"
    done
  done
}

# 한 디렉터리에 링크를 시도한다. 권한이 없으면 sudo로 한 번 더 시도하고,
# 그래도 안 되면 실패를 돌려 다음 후보로 넘어가게 한다.
link_into() {
  local dir="$1" target="$2"
  [ -d "$dir" ] || return 1
  ln -sf "$target" "$dir/$APP_NAME" 2>/dev/null && return 0
  [ -n "$SUDO" ] || return 1
  # sudo 프롬프트가 보여야 하므로 여기서는 stderr를 가리지 않는다.
  $SUDO ln -sf "$target" "$dir/$APP_NAME"
}

# 어디서나 한 단어로 부를 수 있도록 이 스크립트를 PATH에 연결한다.
link_self() {
  local target="$INSTALL_DIR/scripts/manage.sh"
  chmod +x "$target" 2>/dev/null || true
  remove_legacy_commands

  if link_into "$SYSTEM_BINDIR" "$target"; then
    info "명령 등록: $SYSTEM_BINDIR/$APP_NAME ✓"
    return 0
  fi

  mkdir -p "$USER_BINDIR"
  if ! link_into "$USER_BINDIR" "$target"; then
    warn "$APP_NAME 명령을 등록하지 못했습니다. 스크립트를 직접 실행하세요:
    $target update"
    return 0
  fi
  info "명령 등록: $USER_BINDIR/$APP_NAME ✓"

  case ":$PATH:" in
    *":$USER_BINDIR:"*) ;;
    *) warn "$USER_BINDIR 가 PATH에 없어 '$APP_NAME' 명령이 바로 잡히지 않습니다.
    아래를 실행한 뒤 셸을 새로 열거나 'source ~/.bashrc' 하세요:
    echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc" ;;
  esac
}

# ── 포트 / 헬스체크 ───────────────────────────────────────────
current_port() {
  # config.py의 _resolve_env_file과 같은 규칙 — 프로젝트 루트의 .env를 본다.
  local f="$INSTALL_DIR/.env"
  if [ -f "$f" ] && grep -q '^PORT=' "$f" 2>/dev/null; then
    grep '^PORT=' "$f" | tail -1 | cut -d= -f2 | tr -d '[:space:]'
  else
    echo "$DEFAULT_PORT"
  fi
}

wait_for_health() {
  local port="$1" i
  printf "  서버 응답 대기"
  for i in $(seq 1 20); do
    if curl -sf "http://localhost:$port/health" >/dev/null 2>&1; then
      echo ""
      info "서버 정상 응답 ✓"
      return 0
    fi
    printf "."
    sleep 2
  done
  echo ""
  warn "서버가 아직 응답하지 않습니다. 로그를 확인하세요: $APP_NAME logs"
  return 1
}

app_version() {
  grep -oE '[0-9]+\.[0-9]+\.[0-9]+' "$INSTALL_DIR/backend/app/version.py" 2>/dev/null | head -1
}

# ── systemd ───────────────────────────────────────────────────
service_exists() {
  has_cmd systemctl && systemctl cat "${SERVICE_NAME}.service" >/dev/null 2>&1
}

# 이름이 두 번 바뀌었다: chzzk-recorder-pro → signal-recorder → rookery.
# 어느 시절에 설치했든 옛 유닛이 남아 있으면 포트를 물고 있어 새 유닛이 뜨지 못한다.
LEGACY_SERVICE_NAMES="signal-recorder chzzk-recorder-pro"

# 남아 있는 구버전 유닛 이름을 출력한다 (없으면 아무것도 출력하지 않음).
find_legacy_services() {
  has_cmd systemctl || return 0
  local name
  for name in $LEGACY_SERVICE_NAMES; do
    if systemctl cat "${name}.service" >/dev/null 2>&1; then
      echo "$name"
    fi
  done
}

legacy_service_exists() {
  [ -n "$(find_legacy_services)" ]
}

# Rookery로 이름을 바꾸기 전 유닛이 남아 있으면 같은 포트를 물고 있어
# 새 유닛이 뜨지 못한다. 등록 전에 먼저 걷어낸다.
remove_legacy_service() {
  local found name
  found="$(find_legacy_services)"
  [ -n "$found" ] || return 0

  for name in $found; do
    warn "구버전 서비스(${name})를 발견했습니다. 중지 후 제거합니다."
    $SUDO systemctl disable --now "$name" 2>/dev/null || true
    $SUDO rm -f "/etc/systemd/system/${name}.service"
  done
  $SUDO systemctl daemon-reload
  info "구버전 서비스 제거 완료 ✓"
}

service_install() {
  has_cmd systemctl || { warn "systemd가 없어 서비스 등록을 건너뜁니다."; return 0; }

  remove_legacy_service

  step "systemd 서비스 등록"
  $SUDO tee "/etc/systemd/system/${SERVICE_NAME}.service" >/dev/null <<UNIT
[Unit]
Description=Rookery - Live Stream Recorder
Documentation=https://github.com/${REPO_SLUG}
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=${INSTALL_DIR}/backend
ExecStart=${INSTALL_DIR}/.venv/bin/python run.py
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${SERVICE_NAME}
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
UNIT

  $SUDO systemctl daemon-reload
  $SUDO systemctl enable --now "$SERVICE_NAME"
  info "서비스 등록 완료 ✓"
  info "상태 확인: ${SUDO:+$SUDO }systemctl status $SERVICE_NAME"
}

service_remove() {
  has_cmd systemctl || return 0
  $SUDO systemctl disable --now "$SERVICE_NAME" 2>/dev/null || true
  $SUDO rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
  $SUDO systemctl daemon-reload
  info "서비스 제거 완료 ✓"
}

# ═══════════════════════════════════════════════════════════════
#  명령
# ═══════════════════════════════════════════════════════════════

cmd_install() {
  banner
  detect_os
  ensure_base_tools
  ensure_ffmpeg
  ensure_python
  ensure_node

  # 0 = 갱신함, 1 = 이미 최신(둘 다 정상), 2 = 실패.
  # 실패했는데 계속 가면 없거나 낡은 코드로 빌드하게 된다.
  local rc=0
  sync_repo || rc=$?
  [ "$rc" -le 1 ] || error "저장소를 가져오지 못했습니다. 위 메시지를 확인한 뒤 다시 시도하세요."

  setup_dirs
  build_frontend
  setup_python_env
  link_self

  if confirm "부팅 시 자동 실행되도록 systemd 서비스로 등록할까요?"; then
    service_install
    wait_for_health "$(current_port)" || true
  else
    info "서비스 등록을 건너뜁니다. '$APP_NAME start' 로 실행하세요."
  fi

  print_done
}

cmd_update() {
  require_install
  banner

  # 0 = 갱신함, 1 = 이미 최신, 2 = 실패.
  # 최신이어도 구버전 유닛 이전은 남아 있을 수 있어 여기서 곧장 빠져나가지 않는다.
  # 다만 실패했다면 옛 코드로 빌드·재시작하게 되므로 반드시 멈춰야 한다.
  local updated=0 rc=0
  sync_repo || rc=$?
  case "$rc" in
    0) updated=1 ;;
    1) ;;
    *) error "저장소 동기화에 실패했습니다. 위 메시지를 확인한 뒤 다시 시도하세요.
  코드가 갱신되지 않았으므로 서비스는 건드리지 않았습니다." ;;
  esac

  if [ "$updated" -eq 1 ]; then
    detect_os
    ensure_node
    build_frontend

    step "Python 의존성 갱신"
    "$(venv_pip)" install -r "$INSTALL_DIR/backend/requirements.txt" -q
    info "갱신 완료 ✓"
  fi

  link_self

  # 구버전 유닛으로 돌고 있던 서버를 새 유닛으로 옮긴다.
  # 그냥 두면 옛 서비스가 계속 포트를 잡고 있어, 안내대로 start를 해도 충돌한다.
  if ! service_exists && legacy_service_exists; then
    warn "구버전 서비스($(find_legacy_services | paste -sd' ' -))로 실행 중입니다. ${SERVICE_NAME} 유닛으로 옮깁니다."
    service_install
    wait_for_health "$(current_port)" || true
    info "업데이트 완료 — 버전 $(app_version)"
    return 0
  fi

  if [ "$updated" -eq 0 ]; then
    return 0
  fi

  if service_exists; then
    $SUDO systemctl restart "$SERVICE_NAME"
    info "서비스 재시작 완료 ✓"
    wait_for_health "$(current_port)" || true
  else
    warn "서비스로 등록되어 있지 않습니다. '$APP_NAME start' 로 다시 시작하세요."
  fi

  info "업데이트 완료 — 버전 $(app_version)"
}

cmd_start() {
  require_install
  if service_exists; then
    $SUDO systemctl start "$SERVICE_NAME"
    info "서비스 시작 ✓"
    wait_for_health "$(current_port)" || true
  else
    info "포그라운드로 실행합니다 (Ctrl+C 로 종료)."
    cd "$INSTALL_DIR/backend"
    exec "$(venv_python)" run.py
  fi
}

cmd_stop() {
  require_install
  if service_exists; then
    $SUDO systemctl stop "$SERVICE_NAME"
    info "서비스 중지 ✓"
  elif pkill -f 'uvicorn.*app.main' 2>/dev/null; then
    info "프로세스 종료 ✓"
  else
    warn "실행 중인 프로세스가 없습니다."
  fi
}

cmd_restart() {
  require_install
  if service_exists; then
    $SUDO systemctl restart "$SERVICE_NAME"
    info "서비스 재시작 ✓"
    wait_for_health "$(current_port)" || true
  else
    cmd_stop
    cmd_start
  fi
}

cmd_status() {
  require_install

  # --full 은 저장소에 함께 들어 있는 상세 점검 스크립트에 위임한다.
  if [ "${1:-}" = "--full" ] && [ -f "$INSTALL_DIR/scripts/healthcheck.sh" ]; then
    APP_DIR="$INSTALL_DIR" BASE="http://127.0.0.1:$(current_port)" \
      bash "$INSTALL_DIR/scripts/healthcheck.sh"
    return
  fi

  local port; port="$(current_port)"

  # 한글은 한 글자가 두 칸을 차지해 printf의 %-Ns 정렬이 어긋난다.
  # 라벨을 모두 두 글자로 맞추고 간격을 직접 넣는다.
  row() { printf "  %s   %s\n" "$1" "$2"; }

  echo ""
  row "경로" "$INSTALL_DIR"
  row "버전" "$(app_version)"
  row "포트" "$port"

  if curl -sf "http://localhost:$port/health" >/dev/null 2>&1; then
    row "서버" "${GREEN}응답 정상${NC}"
  else
    row "서버" "${RED}응답 없음${NC}"
  fi

  if service_exists; then
    row "상태" "$(systemctl is-active "$SERVICE_NAME" 2>/dev/null)"
    row "부팅" "$(systemctl is-enabled "$SERVICE_NAME" 2>/dev/null)"
  else
    row "상태" "systemd 미등록 (수동 실행)"
  fi
  echo ""
  echo "  상세 점검: ${CYAN}$APP_NAME status --full${NC}"
  echo ""
}

cmd_logs() {
  require_install
  if service_exists; then
    $SUDO journalctl -u "$SERVICE_NAME" -f -n 200
  else
    local log="$INSTALL_DIR/logs/service.log"
    [ -f "$log" ] || error "로그 파일이 없습니다: $log"
    tail -f -n 200 "$log"
  fi
}

cmd_service() {
  require_install
  case "${1:-install}" in
    install) service_install ;;
    remove)  service_remove ;;
    *)       error "사용법: $APP_NAME service [install|remove]" ;;
  esac
}

cmd_uninstall() {
  require_install
  warn "설치 경로: $INSTALL_DIR"
  warn "녹화 파일(recordings/)과 데이터(data/)는 지우지 않습니다."
  confirm "계속하시겠습니까?" || { info "취소했습니다."; return 0; }

  service_remove
  rm -f "$SYSTEM_BINDIR/$APP_NAME" 2>/dev/null || $SUDO rm -f "$SYSTEM_BINDIR/$APP_NAME" 2>/dev/null || true
  rm -f "$USER_BINDIR/$APP_NAME"
  rm -rf "$INSTALL_DIR/.venv"
  info "제거 완료. 저장소와 데이터는 $INSTALL_DIR 에 남아 있습니다."
}

print_done() {
  local port ip
  port="$(current_port)"
  ip="$(hostname -I 2>/dev/null | awk '{print $1}')"

  echo ""
  echo "${GREEN}${BOLD}  설치가 완료되었습니다.${NC}"
  echo ""
  echo "  ${BOLD}접속${NC}      ${CYAN}http://localhost:$port${NC}"
  [ -n "$ip" ] && echo "            ${CYAN}http://$ip:$port${NC}  (같은 네트워크)"
  echo ""
  echo "  ${BOLD}관리${NC}      $APP_NAME status     상태 확인"
  echo "            $APP_NAME update     최신 버전으로"
  echo "            $APP_NAME logs       로그 보기"
  echo "            $APP_NAME --help     전체 명령"
  echo ""
}

cmd_help() {
  cat <<HELP

${BOLD}Rookery 관리 명령${NC}

  ${CYAN}$APP_NAME${NC} [명령]

${BOLD}명령${NC}
  install                 설치 (의존성 · 빌드 · 가상환경 · 서비스 등록)
  update                  최신 코드로 갱신 후 재시작
  start | stop | restart  실행 제어
  status [--full]         상태 확인 (--full 은 상세 점검)
  logs                    로그 실시간 보기
  service install|remove  systemd 서비스 등록/해제
  uninstall               제거 (녹화 파일·데이터는 유지)

${BOLD}환경 변수${NC}
  INSTALL_DIR   설치 경로 (기본: \$HOME/$APP_NAME)

${BOLD}최초 설치${NC}
  curl -fsSL $RAW_URL | bash

명령 없이 실행하면 설치되어 있지 않을 때는 설치를, 이미 설치되어 있으면 업데이트를 합니다.

Docker로 띄우는 경우는 이 스크립트를 쓰지 않습니다.
저장소 루트에서 ${CYAN}docker compose up --build -d${NC} 를 실행하세요 (docs/docker-guide.md).

HELP
}

# ═══════════════════════════════════════════════════════════════
main() {
  resolve_install_dir

  local cmd="${1:-}"
  [ $# -gt 0 ] && shift || true

  case "$cmd" in
    install)          cmd_install ;;
    update|upgrade)   cmd_update ;;
    start)            cmd_start ;;
    stop)             cmd_stop ;;
    restart)          cmd_restart ;;
    status)           cmd_status "$@" ;;
    logs|log)         cmd_logs ;;
    service)          cmd_service "$@" ;;
    uninstall|remove) cmd_uninstall ;;
    help|--help|-h)   cmd_help ;;
    "")
      # 원라이너 진입점: 상황을 보고 알아서 설치 또는 업데이트한다.
      if is_installed; then cmd_update; else cmd_install; fi
      ;;
    *)
      error "알 수 없는 명령: $cmd  ('$APP_NAME --help' 참고)"
      ;;
  esac
}

main "$@"
