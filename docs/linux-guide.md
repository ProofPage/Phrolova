# Linux 설치 및 운영

Python 3.12+가 필요합니다. 아래 명령은 Ubuntu 24.04 또는 Python 3.12+를 제공하는 Debian 배포판을 기준으로 합니다. Debian 12의 기본 Python 3.11에서는 실행 진입점이 중지되므로 Python 3.12+를 별도로 준비하거나 배포판을 업그레이드하세요. Debian에 Ubuntu PPA를 추가하지 마세요. x86_64에서 검증했고 ARM64 실제 실행은 미검증입니다.

## 설치

```bash
sudo apt-get update
sudo apt-get install -y git python3 python3-venv python3-dev ffmpeg nodejs npm build-essential pkg-config libxml2-dev libxslt1-dev libffi-dev libssl-dev tmux
python3 -c 'import sys; assert sys.version_info >= (3, 12), "Python 3.12+ required"'
node --version
# Node.js 22+ 권장. 배포판 Node가 오래되면 공식 설치 방법으로 먼저 갱신하세요.
git clone https://github.com/ProofPage/Phrolova.git "$HOME/Phrolova"
cd "$HOME/Phrolova"
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
.venv/bin/python -m pip check
(cd frontend && npm ci && npm run build)
# 빌드는 backend/app/static에 직접 출력됩니다. dist 복사 불필요.
if [ ! -e .env ] && [ ! -e backend/.env ]; then
  cp .env.example .env
  chmod 600 .env
fi
# 새 템플릿 기본 HOST는 127.0.0.1. 기존 .env는 직접 확인하세요.
cd backend
../.venv/bin/python run.py
```

브라우저: <http://127.0.0.1:8000> 또는 <http://localhost:8000>. Ctrl+C로 종료하고 같은 명령으로 재시작합니다. 기본 상대 다운로드 경로는 실행 작업 디렉터리 기준입니다. 모든 시작 방식을 `backend/`에서 실행하거나 `.env`의 다운로드 경로를 절대경로로 지정하세요. 데이터베이스는 `backend/data/rookery.db`, 설정은 루트 `.env`(기존 `backend/.env` 지원), 로그는 루트 `logs/service.log`입니다.

Node.js는 웹 UI 빌드 이후 웹 서버 자체에는 필요하지 않습니다. 다만 YouTube의 JavaScript 처리에는 Node 또는 Deno가 필요하므로 YouTube를 쓰면 런타임을 유지하세요. `ffmpeg-python`은 FFmpeg 실행 파일을 설치하지 않습니다.

## 백그라운드 실행

```bash
cd "$HOME/Phrolova"
bash scripts/manage.sh start
# systemd 없는 환경에서는 포그라운드 실행입니다.
# 별도 세션에서:
tmux new -s phrolova
cd "$HOME/Phrolova/backend"
../.venv/bin/python run.py
# Ctrl+B, D로 분리; tmux attach -t phrolova로 복귀 후 Ctrl+C로 종료.
```

systemd가 실제로 동작하는 일반 Linux에서만:

```bash
cd "$HOME/Phrolova"
bash scripts/manage.sh service install
bash scripts/manage.sh status
bash scripts/manage.sh logs
bash scripts/manage.sh stop
bash scripts/manage.sh restart
```

자동 등록은 현재 사용자와 저장소 경로를 사용합니다. systemd 부팅 자동 실행은 이 검수 컨테이너에서 미검증입니다. 직접 작성할 때도 `WorkingDirectory`를 `backend`로 지정하고 `ExecStart`에 가상환경 Python과 `run.py` 절대경로를 사용하세요. 서비스 종료는 네트워크 타임아웃/yt-dlp 재시도가 끝날 때까지 지연될 수 있습니다.

## 업데이트와 점검

녹화·다운로드가 끝난 다음 서버를 종료하세요. 아래 명령은 로컬 수정을 강제로 덮어쓰지 않습니다.

```bash
cd "$HOME/Phrolova"
git pull --ff-only
.venv/bin/python -m pip install -r backend/requirements.txt
(cd frontend && npm ci && npm run build)
cd backend
../.venv/bin/python run.py
```

```bash
cd "$HOME/Phrolova"
tail -f logs/service.log
curl -f http://127.0.0.1:8000/health
.venv/bin/streamlink --version
.venv/bin/yt-dlp --version
ffmpeg -version
ffprobe -version
```

오류: Python 버전 오류는 3.12+ 환경을 준비하세요. UI가 없으면 프론트엔드를 다시 빌드하세요. `Permission denied`이면 설치 폴더·`backend/data`·`logs`·다운로드 경로에 실행 사용자 쓰기 권한이 있는지 확인하세요. `address already in use`이면 기존 인스턴스를 종료하세요. 임의 프로세스 전체 종료 명령을 사용하지 마세요. 설정·DB·쿠키를 삭제하여 해결하지 마세요.

## 원격 접속

API에는 일반 웹 사용자 인증이 없습니다. CHZZK/YouTube/X 쿠키와 Discord 명령 허용 목록은 웹 API 접근 통제가 아닙니다. 외부 공개 전에 인증을 제공하는 리버스 프록시/VPN과 접근 제한을 구성해야 합니다. 원격 관리의 간단한 방법은 SSH 터널입니다.

```bash
ssh -N -L 8000:127.0.0.1:8000 user@server
```

그 뒤 로컬 브라우저의 <http://127.0.0.1:8000>을 사용합니다. 새 기본 설정은 로컬 전용이며 기존 명시적 HOST 값은 유지됩니다.
