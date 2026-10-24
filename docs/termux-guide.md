# Android Termux 설치 및 운영

Native Termux와 proot Linux는 의존성 설치 방식을 구분합니다. Native는 Android 패키지와 `requirements-termux.txt`, proot는 게스트 배포판 패키지와 `requirements.txt`를 사용합니다.

## Native Termux

[공식 설치 안내](https://github.com/termux/termux-app#installation)를 확인하세요. 비공개 저장소 접근 권한이 있는 GitHub 계정의 Git 인증이 필요합니다.

```bash
pkg update
pkg install -y git
cd "$HOME"
git clone https://github.com/ProofPage/Phrolova.git
cd Phrolova
bash scripts/install-termux.sh
bash scripts/manage.sh start
```

설치기는 Python·python-pip·FFmpeg·Node.js LTS·curl·procps·Clang·Rust·make·pkg-config·libxml2·libxslt·OpenSSL·libffi·tmux를 준비합니다. Termux 롤링 시스템 Python(Python 3.14+ 호환; Termux는 패치 지정 패키지 없이 단일 'python' 패키지 제공), Node 22+, FFmpeg/FFprobe 6+를 검사하고 필요한 Python 확장 모듈을 장치에서 빌드합니다.

`requirements-termux.txt`는 순수 Uvicorn을 사용합니다. FastAPI, Streamlink, yt-dlp, aiohttp, pydantic-core, discord.py와 Uvicorn import를 확인하며 제거된 라이브러리를 요구하지 않습니다. Linux/Windows 실행 파일이나 manylinux wheel로 Android 의존성을 대체하지 않고 Termux 관리 대상 pip도 자동 업그레이드하지 않습니다.

수동 Python 설치:

```bash
cd "$HOME/Phrolova"
python -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-termux.txt
.venv/bin/python -m pip check
(cd frontend && npm ci && npm run build)
cd backend
../.venv/bin/python run.py
```

<http://127.0.0.1:8000>을 Android 브라우저에서 엽니다. 서버는 트레이를 사용하지 않으며 폴더 열기 요청에는 저장 경로를 제공합니다.

## 저장 경로

앱·가상환경·DB·쿠키는 `$HOME/Phrolova` 내부에 두세요. 공유 저장소는 실행 권한·심볼릭 링크·SQLite 잠금 제약이 있어 앱 설치 위치로 사용하지 않습니다. 설치기는 `/sdcard`·`/storage` 아래 설치 경로를 거부합니다.

미디어만 공유 저장소로 보내려면:

```bash
termux-setup-storage
# Android 저장소 권한을 허용한 뒤 실행
mkdir -p "$HOME/storage/shared/Phrolova/Live" "$HOME/storage/shared/Phrolova/Video"
printf '%s\n' "$HOME/storage/shared/Phrolova/Live" "$HOME/storage/shared/Phrolova/Video"
```

출력된 실제 절대경로를 설정에 입력하세요. `.env`의 `$HOME` 자동 확장에 의존하지 않습니다. 권한을 받지 못하면 내부 HOME를 사용하세요.

## 백그라운드·관리·업데이트

```bash
termux-wake-lock
tmux new -s phrolova 'cd "$HOME/Phrolova" && bash scripts/manage.sh start'
# Ctrl+B, D로 분리; tmux attach -t phrolova로 복귀
# 다른 Termux 세션에서:
cd "$HOME/Phrolova"
bash scripts/manage.sh status
bash scripts/manage.sh logs
bash scripts/manage.sh stop
# 작업 종료 후:
termux-wake-unlock
```

Android 배터리 제한에서 Termux를 허용하세요. wake-lock과 tmux는 Android 강제 종료를 막지 못합니다. 중단된 다운로드는 재시작 시 오류 작업으로 복원되며 수동 재시도할 수 있습니다. 필요하면 `.part` 보존을 켜세요. 제품 기본 동시 다운로드는 5개이며 휴대폰에서는 1개부터 시작해 발열·저장 공간을 확인하세요.

작업 완료 후 정상 종료하고 `.env`, 전체 `backend/data/`, 미디어를 백업한 뒤:

```bash
bash scripts/manage.sh update
bash scripts/manage.sh start
```

Native 업데이트도 `requirements-termux.txt`를 사용합니다. 반복 설치는 `.env`·기존 `backend/.env`·DB·쿠키·미디어를 보존합니다. Python 업그레이드로 깨진 가상환경은 `.venv-backups/`에 보존하고 재생성합니다. Native 확장 빌드 오류는 컴파일 로그와 장치 저장 공간을 확인하세요. Termux:Boot 자동 시작은 별도 구성입니다.

## proot-distro Linux

Termux 셸에서:

```bash
pkg install -y proot-distro tmux
proot-distro install ubuntu
proot-distro login ubuntu
```

Ubuntu 게스트에서:

```bash
export PHROLOVA_ENVIRONMENT=termux-proot
apt-get update
apt-get install -y bash git curl
# Python 3.12+를 제공하는 게스트 사용
git clone https://github.com/ProofPage/Phrolova.git "$HOME/Phrolova"
cd "$HOME/Phrolova"
bash scripts/manage.sh install
bash scripts/manage.sh start
```

환경 변수는 게스트 셸 프로필에 보존하세요. 상위 Termux의 `TERMUX_VERSION`이 전달돼도 게스트가 Android 패키지 경로를 사용하지 않게 합니다. Native/proot 간 `.venv`를 재사용하지 않습니다. 게스트에는 Linux Node/Python/FFmpeg를 설치하며 systemd가 실행 중이지 않으면 서비스를 등록하지 않습니다.

## 검증 범위

설치·반복 실행·설정 보존은 격리된 패키지 명령으로 자동 검사합니다. Python 3.14/ARM64의 Termux 의존성 프로필은 Linux CI에서 검사합니다. 실제 Android ABI 빌드와 장시간 녹화는 단말 검증이 필요하며 이번 작업 환경에는 Android 단말이 없습니다.

[README](../README.md) · [Linux](linux-guide.md) · [검증 범위](native-platform-support.md)
