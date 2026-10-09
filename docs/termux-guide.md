# Android Termux 설치 및 운영

Native는 Android/Bionic이고 proot의 Ubuntu/Debian은 GNU/glibc입니다. 둘은 같은 Python 바이너리·가상환경을 공유할 수 없습니다. 비루팅 실행을 대상으로 하며 **사용자 단말에서 Native 설치·웹 UI·치지직 녹화·정상 종료·재시작 후 채널 유지·녹화 파일 재생을 확인했습니다**. 추가 VOD·YouTube·X Spaces 및 장시간 백그라운드 동작은 사용자 검증 완료 보고를 받았지만 상세 로그와 실행 조건은 수집하지 않았습니다. Native의 C/Rust 패키지 소스 빌드가 실패하면 proot 방법을 사용하세요.

## A. Native Termux

```bash
pkg update
pkg install -y git
cd "$HOME"
git clone https://github.com/ProofPage/Phrolova.git
cd "$HOME/Phrolova"
bash scripts/install-termux.sh
cd backend
"$HOME/Phrolova/.venv/bin/python" run.py
```

추가한 설치 스크립트는 Python, python-pip, FFmpeg, Node.js LTS, Clang, Rust, make, pkg-config, libxml2, libxslt, OpenSSL, libffi, tmux를 `pkg`로 설치합니다. 새 가상환경과 `requirements-termux.txt`를 사용하고 웹 UI를 빌드합니다. 기존 `.env`/`backend/.env`를 덮어쓰지 않고 DB·녹화·인증 정보를 삭제하지 않습니다. 반복 실행은 같은 설치 폴더를 재사용합니다. 실패 시 줄 번호와 명령 오류를 출력합니다. `pkg update`는 사용자가 필요할 때 수행하고 전체 패키지를 자동 업그레이드하지 않습니다.

수동 Python 단계:

```bash
cd "$HOME/Phrolova"
python -c 'import sys; assert sys.version_info >= (3, 12)'
python -m venv .venv
.venv/bin/python -m pip install setuptools wheel
.venv/bin/python -m pip install -r backend/requirements-termux.txt
.venv/bin/python -m pip check
(cd frontend && npm ci && npm run build)
```

Termux 관리 대상 pip를 임의 업그레이드하지 마세요. Rust/maturin/pydantic-core 빌드 오류는 실제 로그를 확인해야 합니다. manylinux ARM64 wheel을 Android wheel 대신 설치하거나 `--no-deps`로 필수 의존성을 생략하지 마세요. 빌드 격리가 원인인 경우에만 필요한 빌드 도구 버전을 별도 설치하고 `--no-build-isolation`을 검토하세요. 이 방식도 단말에서 미검증이며 성공 보장 대안이 아닙니다.

Android 브라우저에서 <http://127.0.0.1:8000> 또는 <http://localhost:8000>을 엽니다. 서버는 기본 헤드리스 모드이며 트레이가 필요 없습니다. 폴더 열기는 서버의 저장 경로를 반환하며 Android 파일 앱을 자동 실행하지 않습니다.

## 저장소

저장소·가상환경·DB·쿠키는 `$HOME/Phrolova`에 두세요. 기본 녹화는 `$HOME/Phrolova/backend/recordings`에 저장됩니다. 공유 저장소 권한 없이도 내부 HOME에서 운영할 수 있습니다. 공유 저장소에는 실행 권한·심볼릭 링크·파일 잠금 제약이 있으므로 저장소나 SQLite WAL DB를 두지 마세요.

미디어만 공유 저장소에 저장하려면:

```bash
termux-setup-storage
# Android 권한 창에서 저장소 접근을 허용한 후:
mkdir -p "$HOME/storage/shared/Phrolova-recordings"
test -w "$HOME/storage/shared/Phrolova-recordings"
```

웹 설정에서 실제 절대경로를 지정하거나 `.env`의 `DOWNLOAD_DIR`을 해당 경로로 지정하세요. `.env`의 `$HOME` 확장에 의존하지 마세요. 권한이 거부되면 공유 경로를 쓰지 말고 기본 내부 경로를 유지하세요. 허용되지 않은 경로에 대한 저장 작업은 실패할 수 있으나 기존 DB를 초기화할 필요는 없습니다.

## 백그라운드·종료·재시작

```bash
termux-wake-lock
tmux new -s phrolova
cd "$HOME/Phrolova/backend"
"$HOME/Phrolova/.venv/bin/python" run.py
# Ctrl+B, D: 분리
# tmux attach -t phrolova: 복귀
# Ctrl+C: 정상 종료
# 녹화를 더 하지 않을 때:
termux-wake-unlock
```

Android 설정에서 Termux 배터리 제한을 완화하세요. wake-lock은 화면 꺼짐 중 수면을 줄이지만 강제 종료·제조사 절전·네트워크 손실을 막는 보장은 없습니다. proot도 Android의 정책에서 벗어나지 못합니다. 강제 종료 후 같은 명령으로 서버를 다시 실행하세요. 완료 기록과 설정은 유지되고 중단 VOD는 오류 작업으로 복원되어 수동 재시도가 가능합니다. 정확한 바이트 위치 자동 재개는 보장하지 않습니다. `.part`를 보존하려면 `KEEP_DOWNLOAD_PARTS=true`를 설정하세요. 장시간 녹화에는 TS/MKV가 강제 종료 후 복구에 유리하며 일반 MP4는 최종화 전에 종료되면 재생이 어려울 수 있습니다.

자동 시작은 별도 Termux:Boot 설치와 권한 설정이 필요하고 미검증입니다. 설정했다면 `$HOME/.termux/boot/phrolova.sh`에 다음 내용을 넣을 수 있습니다. 중복 세션을 만들지 않습니다.

```bash
#!/data/data/com.termux/files/usr/bin/bash
termux-wake-lock
tmux has-session -t phrolova 2>/dev/null || tmux new-session -d -s phrolova 'cd "$HOME/Phrolova/backend" && "$HOME/Phrolova/.venv/bin/python" run.py'
```

로그·공간 확인:

```bash
tail -f "$HOME/Phrolova/logs/service.log"
df -h "$HOME"
du -sh "$HOME/Phrolova/backend/recordings"
```

기본 동시 VOD는 3개입니다. 휴대폰에서는 우선 1개로 제한하고 발열·메모리·배터리·저장 공간을 관찰하세요. 공간 부족 보호/열 제어가 구현되어 있다고 주장하지 않습니다. Node는 웹 서버 실행에 불필요하지만 YouTube JavaScript 처리에는 필요하므로 YouTube 이용 시 유지하세요.

## B. proot-distro Ubuntu/Debian

Native Termux에서:

```bash
pkg update
pkg install -y proot-distro tmux
proot-distro list
proot-distro install ubuntu
termux-wake-lock
proot-distro login ubuntu
```

Ubuntu 내부에서만:

```bash
apt-get update
apt-get install -y git python3 python3-venv python3-dev ffmpeg nodejs npm build-essential pkg-config libxml2-dev libxslt1-dev libffi-dev libssl-dev
python3 -c 'import sys; assert sys.version_info >= (3, 12), "Python 3.12+ required"'
node --version
# Python 또는 Node가 오래되면 배포판에 맞게 먼저 준비하세요.
git clone https://github.com/ProofPage/Phrolova.git "$HOME/Phrolova"
cd "$HOME/Phrolova"
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
(cd frontend && npm ci && npm run build)
if [ ! -e .env ] && [ ! -e backend/.env ]; then cp .env.example .env; chmod 600 .env; fi
cd backend
PHROLOVA_ENVIRONMENT=termux-proot "$HOME/Phrolova/.venv/bin/python" run.py
```

Debian을 사용하려면 지원 목록에서 확인한 뒤 `proot-distro install debian`과 `proot-distro login debian`을 사용하고 내부 설치는 같은 방식으로 진행하세요. Python 3.11 기본 배포판에는 별도 3.12+가 필요합니다. proot 안의 root는 Android 실제 root 권한이 아닙니다. systemd 서비스 등록은 사용하지 마세요.

Native Termux에서 tmux 세션을 먼저 만든 뒤 proot에 로그인하면 세션 분리 상태로 운영할 수 있습니다. Ctrl+C로 서버를 종료하고 동일한 로그인·실행 명령으로 재시작합니다. 브라우저는 같은 단말의 <http://127.0.0.1:8000>입니다. Native의 가상환경을 복사하지 마세요. 공유 저장소가 필요하면 로그인 때 명시적으로 bind하고 미디어 경로만 사용하세요.

proot는 glibc wheel과 배포판 바이너리를 사용할 수 있어 Native 소스 빌드 문제의 보조 수단입니다. 실행 오버헤드와 Android 강제 종료 문제를 해결하지 못하고, 기기에서 실제 실행은 미검증입니다.

## 업데이트

서버를 정상 종료한 다음 `git pull --ff-only`, 해당 환경의 requirements 설치, `npm ci && npm run build`를 수행하고 재시작하세요. Native에서는 `scripts/manage.sh`를 사용하지 마세요. 로컬 수정으로 pull이 실패하면 변경 사항을 검토하고 강제 초기화하지 마세요.
