#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  Phrolova — 통합 관리 스크립트 (Linux / macOS)
#
#  인증된 체크아웃에서 설치 · 업데이트:
#    bash scripts/manage.sh install | update
#
#  설치 후에는 어디서나 한 단어로 쓴다:
#    phrolova update | start | stop | status | logs
#
#  설계 원칙
#    - 같은 체크아웃의 관리 함수를 설치·업데이트에 재사용한다
#    - 같은 명령을 두 번 실행해도 안전하다 (idempotent)
#
# ═══════════════════════════════════════════════════════════════
set -euo pipefail

REPO_SLUG="ProofPage/Phrolova"
REPO_URL="https://github.com/${REPO_SLUG}.git"
RAW_URL="https://raw.githubusercontent.com/${REPO_SLUG}/main/scripts/manage.sh"
APP_NAME="phrolova"
DEFAULT_INSTALL_DIR="$HOME/Phrolova"
SERVICE_NAME="phrolova"
SYSTEMD_UNIT_DIR="${SYSTEMD_UNIT_DIR:-/etc/systemd/system}"
SYSTEMD_RUNTIME_DIR="${SYSTEMD_RUNTIME_DIR:-/run/systemd/system}"
DEFAULT_PORT=8000
REQUIRED_PYTHON_MINOR=14
REQUIRED_FFMPEG_MAJOR=6
REQUIRED_NODE_MAJOR=22

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
  echo "${CYAN}${BOLD}  Phrolova${NC} — 멀티 플랫폼 라이브 녹화 · 아카이빙"
  echo ""
}

has_cmd() { command -v "$1" >/dev/null 2>&1; }

# BSD readlink도 사용할 수 있게 심볼릭 링크를 한 단계씩 따라간다.
canonical_path() {
  local target="$1" parent count=0
  [ -n "$target" ] && { [ -e "$target" ] || [ -L "$target" ]; } || return 1
  [[ "$target" = /* ]] || target="$PWD/$target"
  while [ -L "$target" ]; do
    count=$((count + 1)); [ "$count" -le 40 ] || return 1
    parent="$(cd -P "$(dirname "$target")" && pwd)" || return 1
    target="$(readlink "$target")" || return 1
    [[ "$target" = /* ]] || target="$parent/$target"
  done
  parent="$(cd -P "$(dirname "$target")" && pwd)" || return 1
  printf '%s/%s\n' "$parent" "$(basename "$target")"
}

is_termux_native() {
  [ "${PHROLOVA_ENVIRONMENT:-}" != termux-proot ] || return 1
  [ -n "${TERMUX_VERSION:-}" ] || [[ "${PREFIX:-}" = /data/data/*/files/usr && "${BASH:-}" = /data/data/* ]]
}

# 로그인 셸과 서비스에서 같은 Homebrew 런타임을 찾도록 경로를 준비한다.
activate_runtime_path() {
  is_termux_native && return 0
  [ "$(uname -s)" = Darwin ] || return 0
  local location prefix
  if ! has_cmd brew; then
    for location in /opt/homebrew/bin /usr/local/bin; do
      if [ -x "$location/brew" ]; then export PATH="$location:$PATH"; break; fi
    done
  fi
  if has_cmd brew; then
    prefix="$(brew --prefix node@22 2>/dev/null || true)"
    if [ -n "$prefix" ] && [ -x "$prefix/bin/node" ]; then export PATH="$prefix/bin:$PATH"; fi
  fi
}


# root로 돌리는 서버가 흔한데, 최소 이미지에는 sudo가 아예 없는 경우가 있다.
# 이미 root면 sudo를 붙이지 않고, 아니면 있을 때만 쓴다.
SUDO=""
SUDO_E=""
if [ "$(id -u)" -ne 0 ] && ! is_termux_native; then
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
  if [ -n "${INSTALL_DIR:-}" ]; then
    [[ "$INSTALL_DIR" = /* ]] || INSTALL_DIR="$PWD/$INSTALL_DIR"
    return
  fi
  local self root legacy
  self="$(canonical_path "${BASH_SOURCE[0]:-}" 2>/dev/null || true)"
  if [ -n "$self" ]; then
    root="$(dirname "$(dirname "$self")")"
    if [ -d "$root/backend" ] && [ -d "$root/frontend" ]; then INSTALL_DIR="$root"; return; fi
  fi
  for legacy in "$HOME/Phrolova" "$HOME/rookery" "$HOME/signal-recorder" "$HOME/chzzk-recorder-pro"; do
    if [ -d "$legacy/.git" ] || [ -f "$legacy/.git" ]; then INSTALL_DIR="$legacy"; return; fi
  done
  INSTALL_DIR="$DEFAULT_INSTALL_DIR"
}

is_installed() { [ -d "$INSTALL_DIR/.git" ] || [ -f "$INSTALL_DIR/.git" ]; }

require_install() {
  is_installed || error "설치를 찾을 수 없습니다: $INSTALL_DIR
  GitHub 접근 권한으로 저장소를 clone한 뒤 bash scripts/manage.sh install을 실행하세요."
}

venv_python() { echo "$INSTALL_DIR/.venv/bin/python"; }
venv_pip()    { echo "$INSTALL_DIR/.venv/bin/pip"; }

# ── OS / 패키지 매니저 ────────────────────────────────────────
PKG_MANAGER=""

detect_os() {
  if is_termux_native; then PKG_MANAGER=pkg; return; fi
  if [ "$(uname -s)" = Darwin ]; then
    activate_runtime_path
    has_cmd brew || error "Homebrew가 필요합니다: https://brew.sh"
    [ "$(id -u)" -ne 0 ] || error "Homebrew 설치는 일반 사용자로 실행하세요."
    PKG_MANAGER=brew
    return
  fi
  local release="${PHROLOVA_OS_RELEASE:-/etc/os-release}"
  [ -f "$release" ] || error "운영체제를 확인할 수 없습니다. 의존성을 수동으로 준비하세요."
  . "$release"
  case "${ID:-} ${ID_LIKE:-}" in
    *debian*|*ubuntu*) PKG_MANAGER=apt ;;
    *fedora*) PKG_MANAGER=dnf ;;
    *rhel*|*centos*) PKG_MANAGER="$(has_cmd dnf && echo dnf || echo yum)" ;;
    *arch*) PKG_MANAGER=pacman ;;
    *alpine*) PKG_MANAGER=apk ;;
    *) PKG_MANAGER="" ;;
  esac
}

pkg_install() {
  case "$PKG_MANAGER" in
    apt)    $SUDO apt-get install -y "$@" ;;
    dnf)    $SUDO dnf install -y "$@" ;;
    yum)    $SUDO yum install -y "$@" ;;
    pacman) $SUDO pacman -S --noconfirm "$@" ;;
    brew)   brew install "$@" ;;
    pkg)    pkg install -y "$@" ;;
    apk)    $SUDO apk add "$@" ;;
    *)      error "패키지 매니저를 알 수 없습니다. $* 를 수동 설치한 뒤 다시 실행하세요." ;;
  esac
}

# ── 의존성 ────────────────────────────────────────────────────
PYTHON_CMD=""

install_ffmpeg_static() {
  local arch pattern url tmpdir bin probe
  [ "$(uname -s)" = Linux ] && ! is_termux_native && [ "$PKG_MANAGER" != apk ] || error "GNU/Linux 정적 바이너리를 이 환경에 설치하지 않습니다."
  arch="$(uname -m)"
  case "$arch" in
    x86_64)  pattern="linux64-gpl.tar.xz" ;;
    aarch64) pattern="linuxarm64-gpl.tar.xz" ;;
    *)       error "지원하지 않는 아키텍처: $arch (x86_64 / aarch64만 지원)" ;;
  esac

  url=$(curl -fsSL "https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/latest" \
        | "$PYTHON_CMD" -c 'import json,sys; print(next((a["browser_download_url"] for a in json.load(sys.stdin)["assets"] if sys.argv[1] in a["name"] and "shared" not in a["name"]), ""))' "$pattern")
  [ -n "$url" ] || error "ffmpeg 다운로드 URL을 찾지 못했습니다.
  수동 설치: https://github.com/BtbN/FFmpeg-Builds/releases"

  tmpdir="$(mktemp -d)"
  trap 'rm -rf "$tmpdir"' RETURN
  info "ffmpeg 정적 빌드 다운로드 중 ($arch)..."
  curl -fsSL --retry 3 -L -o "$tmpdir/ffmpeg.tar.xz" "$url" || error "ffmpeg 다운로드 실패."
  tar xf "$tmpdir/ffmpeg.tar.xz" -C "$tmpdir"

  bin="$(find "$tmpdir" -type f -name ffmpeg | sed -n '1p')"
  probe="$(find "$tmpdir" -type f -name ffprobe | sed -n '1p')"
  [ -n "$bin" ] || error "ffmpeg 압축 해제 실패."
  $SUDO install -m 755 "$bin" /usr/local/bin/ffmpeg
  [ -n "$probe" ] && $SUDO install -m 755 "$probe" /usr/local/bin/ffprobe
}

ensure_ffmpeg() {
  if ! has_cmd ffmpeg || ! has_cmd ffprobe; then
    if ! pkg_install ffmpeg; then
      if [ "$(uname -s)" = Linux ] && [ "$PKG_MANAGER" != pkg ] && [ "$PKG_MANAGER" != apk ]; then
        install_ffmpeg_static
      else
        error "FFmpeg와 FFprobe를 패키지 매니저로 설치하세요."
      fi
    fi
  fi
  local tool ver major
  for tool in ffmpeg ffprobe; do
    has_cmd "$tool" || error "$tool 실행 파일이 없습니다."
    ver="$("$tool" -version 2>&1 | awk 'NR==1 {print $3}')"
    major="$(printf '%s' "$ver" | sed 's/^[nN]//' | cut -d. -f1)"
    [ "$major" -ge "$REQUIRED_FFMPEG_MAJOR" ] 2>/dev/null || error "$tool 6+가 필요합니다 (현재: $ver)."
    info "$tool $ver ✓"
  done
}

ensure_python() {
  local cmd prefix=""
  if [ "$PKG_MANAGER" = brew ]; then prefix="$(brew --prefix python@3.14 2>/dev/null || true)"; fi

  for cmd in python3.14 python3.15 python3 python "${prefix:+$prefix/bin/python3.14}"; do
    [ -n "$cmd" ] && has_cmd "$cmd" || continue
    if "$cmd" -c 'import sys; assert sys.version_info >= (3, 14, 8) and getattr(sys, "_is_gil_enabled", lambda: True)()' >/dev/null 2>&1; then
      PYTHON_CMD="$(command -v "$cmd")"; break
    fi
  done

  if [ -z "$PYTHON_CMD" ]; then
    case "$PKG_MANAGER" in
      brew) brew install python@3.14; PYTHON_CMD="$(brew --prefix python@3.14)/bin/python3.14" ;;
      dnf) pkg_install python3.14; PYTHON_CMD="$(command -v python3.14)" ;;
      # Termux(pkg)는 롤링 시스템 Python 패키지를 제공하며 패치 지정 패키지(예: python3.14.8)는 지원하지 않습니다.
      pkg) pkg_install python; PYTHON_CMD="$(command -v python)" ;;
      apk) pkg_install python3 py3-pip; PYTHON_CMD="$(command -v python3)" ;;
      apt) pkg_install python3.14 python3.14-venv || pkg_install python3 python3-venv; PYTHON_CMD="$(command -v python3.14 || command -v python3)" ;;
      yum) pkg_install python3.14 || pkg_install python3; PYTHON_CMD="$(command -v python3.14 || command -v python3)" ;;
      *) error "Python 3.14.8+를 먼저 설치하세요. 배포판에 맞지 않는 PPA를 자동 추가하지 않습니다." ;;
    esac
  fi
  "$PYTHON_CMD" -c 'import sys; assert sys.version_info >= (3, 14, 8) and getattr(sys, "_is_gil_enabled", lambda: True)()' || error "Python 3.14.8+ (표준 GIL)가 필요합니다."
  if [ "$PKG_MANAGER" = apt ] && ! "$PYTHON_CMD" -c 'import ensurepip' >/dev/null 2>&1; then
    local minor
    minor="$("$PYTHON_CMD" -c 'import sys; print(sys.version_info.minor)')"
    pkg_install "python3.$minor-venv" || pkg_install python3-venv
  fi
  info "$("$PYTHON_CMD" --version) ✓"
}

ensure_node() {
  activate_runtime_path
  local major=0
  if has_cmd node; then major="$(node -e 'process.stdout.write(process.versions.node.split(".")[0])')"; fi
  if [ "$major" -ge "$REQUIRED_NODE_MAJOR" ] 2>/dev/null && has_cmd npm; then
    info "Node.js $(node --version) ✓"; return
  fi
  step "Node.js 22+ 및 npm 준비"
  case "$PKG_MANAGER" in
    brew) brew install node@22; activate_runtime_path ;;
    apt) curl -fsSL https://deb.nodesource.com/setup_22.x | $SUDO_E bash -; pkg_install nodejs ;;
    dnf|yum) curl -fsSL https://rpm.nodesource.com/setup_22.x | $SUDO_E bash -; pkg_install nodejs ;;
    pacman) pkg_install nodejs npm ;;
    apk) pkg_install nodejs npm ;;
    pkg) pkg_install nodejs-lts ;;
    *) error "Node.js 22+와 npm을 먼저 설치하세요: https://nodejs.org" ;;
  esac
  has_cmd node && has_cmd npm || error "Node.js/npm 경로를 찾지 못했습니다."
  major="$(node -e 'process.stdout.write(process.versions.node.split(".")[0])')"
  [ "$major" -ge "$REQUIRED_NODE_MAJOR" ] || error "설치된 Node.js가 22 미만입니다."
  info "Node.js $(node --version) ✓"
}

ensure_base_tools() {
  has_cmd git  || pkg_install git
  has_cmd curl || pkg_install curl
  if ! has_cmd ps; then
    case "$PKG_MANAGER" in
      apt) pkg_install procps ;;
      dnf|yum) pkg_install procps-ng ;;
      pacman|apk) pkg_install procps-ng ;;
      pkg) pkg_install procps ;;
      *) error "실행 프로세스 확인에 필요한 ps를 설치하세요." ;;
    esac
  fi
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

  # 리포 이름이 여러 번 바뀌었다(Chzzk_downloader → Signal-Recorder → Phrolova).
  # GitHub 리다이렉트로 당장은 동작하지만 영구 보장이 아니므로 정식 주소로 맞춘다.
  local current_remote
  current_remote="$(git -C "$INSTALL_DIR" remote get-url origin 2>/dev/null || true)"
  case "$current_remote" in
    "$REPO_URL"|"${REPO_URL%.git}"|git@github.com:ProofPage/Phrolova.git|ssh://git@github.com/ProofPage/Phrolova.git) ;;
    '') ;;
    *)
      # 비공개 저장소의 SSH 사용자는 주소 이전 후에도 같은 인증 방식을 유지한다.
      local replacement="$REPO_URL"
      case "$current_remote" in
        git@github.com:*) replacement="git@github.com:${REPO_SLUG}.git" ;;
        ssh://git@github.com/*) replacement="ssh://git@github.com/${REPO_SLUG}.git" ;;
      esac
      git -C "$INSTALL_DIR" remote set-url origin "$replacement" || return 2
      info "원격 주소를 갱신했습니다 → $replacement"
      ;;
  esac

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
  local stash_name="phrolova-update-$(date +%Y%m%d-%H%M%S)"
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
  mkdir -p "$INSTALL_DIR/backend/data" "$INSTALL_DIR/logs"
}

build_frontend() {
  step "프론트엔드 빌드"
  # vite.config.ts의 outDir이 ../backend/app/static 이라 결과물이 바로 백엔드로 들어간다.
  (cd "$INSTALL_DIR/frontend" && npm ci --silent && npm run build)
  info "빌드 완료 ✓"
}

setup_python_env() {
  step "Python 가상환경"
  local venv="$INSTALL_DIR/.venv" requirements=requirements.txt backup
  if [ -d "$venv" ] && ! "$venv/bin/python" -c 'import sys,pip; assert sys.version_info >= (3, 14, 8) and getattr(sys, "_is_gil_enabled", lambda: True)()' >/dev/null 2>&1; then
    backup="$INSTALL_DIR/.venv-backups/$(date +%Y%m%d-%H%M%S)-$$"
    mkdir -p "$(dirname "$backup")"
    mv "$venv" "$backup"
    info "호환되지 않는 가상환경을 보존했습니다: $backup"
  fi
  [ -d "$venv" ] || "$PYTHON_CMD" -m venv "$venv"
  if is_termux_native; then
    requirements=requirements-termux.txt
  else
    "$venv/bin/python" -m pip install --upgrade pip -q
  fi
  "$venv/bin/python" -m pip install -r "$INSTALL_DIR/backend/$requirements" -q
  "$venv/bin/python" -m pip check
  info "의존성 설치 완료 ✓"
}

# 명령을 걸어둘 후보 디렉터리.
#
# /usr/local/bin을 먼저 쓴다. root의 기본 PATH에 들어 있어 셸 설정을 건드리지
# 않아도 바로 잡히고, ffmpeg도 이미 같은 곳에 설치하므로 규칙이 하나로 맞는다.
# ~/.local/bin은 root의 기본 PATH에 없다 — 여기로 내려가면 안내가 한 단계 더 필요하다.
SYSTEM_BINDIR="/usr/local/bin"
if is_termux_native; then SYSTEM_BINDIR="${PREFIX}/bin"; fi
USER_BINDIR="$HOME/.local/bin"

# 이름이 바뀌기 전에 걸어둔 명령. systemd 유닛과 달리 지금까지 정리하지 않아
# 옛 이름이 낡은 경로를 가리킨 채 남아 있었다.
LEGACY_COMMAND_NAMES="rookery signal-recorder chzzk-recorder-pro"

# 우리가 만든 심볼릭 링크만 지운다. 같은 이름의 진짜 파일은 건드리지 않는다.
remove_legacy_commands() {
  local dir name link
  local resolved_target
  resolved_target="$(canonical_path "$INSTALL_DIR/scripts/manage.sh" 2>/dev/null || true)"
  [ -n "$resolved_target" ] || return 0
  for dir in "$SYSTEM_BINDIR" "$USER_BINDIR"; do
    for name in $LEGACY_COMMAND_NAMES; do
      link="$dir/$name"
      [ -L "$link" ] || continue
      [ "$(canonical_path "$link" 2>/dev/null || true)" = "$resolved_target" ] || continue
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
  [ ! -e "$dir/$APP_NAME" ] || [ -L "$dir/$APP_NAME" ] || return 1
  ln -sf "$target" "$dir/$APP_NAME" 2>/dev/null && return 0
  [ -n "$SUDO" ] || return 1
  # sudo 프롬프트가 보여야 하므로 여기서는 stderr를 가리지 않는다.
  $SUDO ln -sf "$target" "$dir/$APP_NAME"
}

# 어디서나 한 단어로 부를 수 있도록 이 스크립트를 PATH에 연결한다.
link_self() {
  local target="$INSTALL_DIR/scripts/manage.sh"
  chmod +x "$target" 2>/dev/null || true

  if link_into "$SYSTEM_BINDIR" "$target"; then
    remove_legacy_commands
    info "명령 등록: $SYSTEM_BINDIR/$APP_NAME ✓"
    return 0
  fi

  mkdir -p "$USER_BINDIR"
  if ! link_into "$USER_BINDIR" "$target"; then
    warn "$APP_NAME 명령을 등록하지 못했습니다. 스크립트를 직접 실행하세요:
    $target update"
    return 0
  fi
  remove_legacy_commands
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
  local python="$(venv_python)" port="" file
  if [ -x "$python" ]; then
    port="$(cd "$INSTALL_DIR/backend" && "$python" -c 'from app.core.config import get_settings; print(get_settings().port)' 2>/dev/null || true)"
  fi
  if ! [[ "$port" =~ ^[0-9]+$ ]]; then
    file="$INSTALL_DIR/.env"
    [ -f "$file" ] || file="$INSTALL_DIR/backend/.env"
    if [ -f "$file" ]; then port="$(sed -n 's/^[[:space:]]*PORT[[:space:]]*=[[:space:]]*//p' "$file" | tail -1 | tr -d '\"\047[:space:]')"; fi
  fi
  if [[ "$port" =~ ^[0-9]+$ ]] && [ "$port" -ge 1 ] && [ "$port" -le 65535 ]; then echo "$port"; else echo "$DEFAULT_PORT"; fi
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
  [ -d "$SYSTEMD_RUNTIME_DIR" ] && has_cmd systemctl && systemctl cat "${SERVICE_NAME}.service" >/dev/null 2>&1
}

# 이름이 두 번 바뀌었다: chzzk-recorder-pro → signal-recorder → phrolova.
# 어느 시절에 설치했든 옛 유닛이 남아 있으면 포트를 물고 있어 새 유닛이 뜨지 못한다.
LEGACY_SERVICE_NAMES="rookery signal-recorder chzzk-recorder-pro"

# systemd는 인용된 값 안에서도 %를 지정자로 처리한다.
systemd_value() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//%/%%}"
  printf '%s' "$value"
}

# 남아 있는 구버전 유닛 이름을 출력한다 (없으면 아무것도 출력하지 않음).
find_legacy_services() {
  [ -d "$SYSTEMD_RUNTIME_DIR" ] && has_cmd systemctl || return 0
  local name
  for name in $LEGACY_SERVICE_NAMES; do
    if systemctl cat "${name}.service" >/dev/null 2>&1; then
      echo "$name"
    fi
  done
}

legacy_service_active() {
  local name
  for name in $(find_legacy_services); do
    systemctl is-active --quiet "$name" && return 0
  done
  return 1
}

legacy_service_exists() {
  [ -n "$(find_legacy_services)" ]
}

# Keep legacy units installed but disabled; restore their state on failure.
service_install() {
  [ -d "$SYSTEMD_RUNTIME_DIR" ] && has_cmd systemctl || { warn "실행 중인 systemd가 없어 서비스 등록을 건너뜁니다."; return 0; }
  local found name active="" enabled="" backup target rc=0 new_active=0 new_enabled=0
  found="$(find_legacy_services)"
  target="$SYSTEMD_UNIT_DIR/${SERVICE_NAME}.service"
  backup="$(mktemp -d)"
  if [ -f "$target" ]; then
    $SUDO cp -p "$target" "$backup/previous.service" || { rm -rf "$backup"; return 1; }
  fi
  systemctl is-active --quiet "$SERVICE_NAME" && new_active=1 || true
  systemctl is-enabled --quiet "$SERVICE_NAME" && new_enabled=1 || true
  for name in $found; do
    systemctl is-active --quiet "$name" && active="$active $name" || true
    systemctl is-enabled --quiet "$name" && enabled="$enabled $name" || true
  done
  # Stop before registering the new unit to avoid duplicate port ownership.
  for name in $found; do
    $SUDO systemctl disable --now "$name" || { rc=1; break; }
  done
  if [ "$rc" -eq 0 ]; then
    $SUDO tee "$target" >/dev/null <<UNIT || rc=$?
[Unit]
Description=Phrolova - Live Stream Recorder
Documentation=https://github.com/${REPO_SLUG}
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory="$(systemd_value "$INSTALL_DIR/backend")"
ExecStart="$(systemd_value "$INSTALL_DIR/.venv/bin/python")" "$(systemd_value "$INSTALL_DIR/backend/run.py")"
Environment="PATH=$(systemd_value "$PATH")"
KillMode=mixed
TimeoutStopSec=180
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${SERVICE_NAME}
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
UNIT
  fi
  if [ "$rc" -eq 0 ]; then
    $SUDO systemctl daemon-reload && $SUDO systemctl enable --now "$SERVICE_NAME" || rc=1
  fi
  if [ "$rc" -eq 0 ]; then
    wait_for_health "$(current_port)" || rc=1
  fi
  if [ "$rc" -ne 0 ]; then
    warn "새 서비스 등록 실패. 이전 서비스 상태를 복구합니다."
    $SUDO systemctl disable --now "$SERVICE_NAME" || true
    if [ -f "$backup/previous.service" ]; then
      $SUDO cp -p "$backup/previous.service" "$target" || true
    else
      $SUDO rm -f "$target" || true
    fi
    $SUDO systemctl daemon-reload || true
    [ "$new_enabled" -eq 0 ] || $SUDO systemctl enable "$SERVICE_NAME" || true
    [ "$new_active" -eq 0 ] || $SUDO systemctl start "$SERVICE_NAME" || true
    for name in $enabled; do $SUDO systemctl enable "$name" || warn "복구 실패: $name enable"; done
    for name in $active; do $SUDO systemctl start "$name" || warn "복구 실패: $name start"; done
    rm -rf "$backup"
    return 1
  fi
  rm -rf "$backup"
  info "서비스 등록 완료 ✓ (이전 유닛은 비활성 상태로 보존)"
}

service_remove() {
  has_cmd systemctl || return 0
  $SUDO systemctl disable --now "$SERVICE_NAME" 2>/dev/null || true
  $SUDO rm -f "$SYSTEMD_UNIT_DIR/${SERVICE_NAME}.service"
  $SUDO systemctl daemon-reload
  info "서비스 제거 완료 ✓"
}

# ═══════════════════════════════════════════════════════════════
#  명령
# ═══════════════════════════════════════════════════════════════

cmd_install() {
  banner
  detect_os
  if [ "$PKG_MANAGER" = pkg ]; then
    require_install
    bash "$INSTALL_DIR/scripts/install-termux.sh"
    return
  fi
  ensure_base_tools
  ensure_python
  ensure_ffmpeg
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

  if [ -d "$SYSTEMD_RUNTIME_DIR" ] && has_cmd systemctl && confirm "부팅 시 자동 실행되도록 systemd 서비스로 등록할까요?"; then
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
    ensure_python
    ensure_ffmpeg
    setup_python_env
    info "갱신 완료 ✓"
  fi

  link_self

  # 구버전 유닛으로 돌고 있던 서버를 새 유닛으로 옮긴다.
  # 그냥 두면 옛 서비스가 계속 포트를 잡고 있어, 안내대로 start를 해도 충돌한다.
  if legacy_service_active || { ! service_exists && legacy_service_exists; }; then
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
  activate_runtime_path
  if legacy_service_active || { ! service_exists && legacy_service_exists; }; then service_install || return 1; return 0; fi
  if service_exists; then
    $SUDO systemctl start "$SERVICE_NAME"
    info "서비스 시작 ✓"
    wait_for_health "$(current_port)" || true
  else
    info "포그라운드로 실행합니다 (Ctrl+C 로 종료)."
    cd "$INSTALL_DIR/backend"
    exec "$(venv_python)" "$INSTALL_DIR/backend/run.py"
  fi
}

cmd_stop() {
  require_install
  if service_exists; then
    $SUDO systemctl stop "$SERVICE_NAME"
    info "서비스 중지 ✓"
  else
    (cd "$INSTALL_DIR/backend" && "$(venv_python)" -m app.core.process_control stop --root "$INSTALL_DIR")
  fi
}

cmd_restart() {
  require_install
  if service_exists; then
    $SUDO systemctl restart "$SERVICE_NAME"
    info "서비스 재시작 ✓"
    wait_for_health "$(current_port)" || true
  else
    cmd_stop || return 1
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
    local state
    state="$(cd "$INSTALL_DIR/backend" && "$(venv_python)" -m app.core.process_control status --root "$INSTALL_DIR" 2>/dev/null || true)"
    row "상태" "${state:-수동 실행}"
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
  local port
  port="$(current_port)"

  echo ""
  echo "${GREEN}${BOLD}  설치가 완료되었습니다.${NC}"
  echo ""
  echo "  ${BOLD}접속${NC}      ${CYAN}http://localhost:$port${NC}"
  echo ""
  echo "  ${BOLD}관리${NC}      $APP_NAME status     상태 확인"
  echo "            $APP_NAME update     최신 버전으로"
  echo "            $APP_NAME logs       로그 보기"
  echo "            $APP_NAME --help     전체 명령"
  echo ""
}

cmd_help() {
  cat <<HELP

${BOLD}Phrolova 관리 명령${NC}

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
  INSTALL_DIR   설치 경로 (기본: \$HOME/Phrolova)

${BOLD}최초 설치${NC}
  GitHub 접근 권한이 있는 계정의 Git 인증이 필요합니다.
  git clone $REPO_URL "\$HOME/Phrolova"
  bash "\$HOME/Phrolova/scripts/manage.sh" install

명령 없이 실행하면 설치되어 있지 않을 때는 설치를, 이미 설치되어 있으면 업데이트를 합니다.


HELP
}

# ═══════════════════════════════════════════════════════════════
main() {
  resolve_install_dir
  activate_runtime_path

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

# 관리 명령 진입점
if [[ "${BASH_SOURCE[0]:-}" == "$0" || -z "${BASH_SOURCE[0]:-}" ]]; then
  main "$@"
fi
