# macOS 설치 및 운영

Apple Silicon과 Intel Mac에서 동일한 소스 설치 방식을 사용합니다. Python 3.12+, Node.js 22+와 npm, FFmpeg/FFprobe 6+가 필요합니다. 브라우저 대시보드 방식이며 `.app`·`.dmg` 패키지는 제공하지 않습니다.

## Homebrew 설치

[Homebrew 공식 안내](https://docs.brew.sh/Installation)에 따라 Homebrew를 설치한 후 일반 사용자 터미널에서 실행하세요.

```bash
brew install git python@3.12 node@22 ffmpeg
# 저장소 접근 권한이 있는 GitHub 계정의 Git 인증 필요
git clone https://github.com/ProofPage/Phrolova.git "$HOME/Phrolova"
cd "$HOME/Phrolova"
bash scripts/manage.sh install
bash scripts/manage.sh start
```

관리 스크립트는 Apple Silicon의 `/opt/homebrew`와 Intel의 `/usr/local`에서 Homebrew를 찾습니다. PATH에 연결되지 않은 버전별 Node 경로를 활성화하고 Python 3.12+를 확인합니다.

<http://127.0.0.1:8000>에서 저장 경로·화질·MKV/MP4 형식을 설정하세요. macOS에서 저장 폴더 쓰기 권한이 필요합니다.

## 수동 설치

```bash
cd "$HOME/Phrolova"
export PATH="$(brew --prefix node@22)/bin:$PATH"
"$(brew --prefix python@3.12)/bin/python3.12" -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
.venv/bin/python -m pip check
(cd frontend && npm ci && npm run build)
cd backend
../.venv/bin/python run.py
```

프론트엔드는 `backend/app/static`에 직접 빌드됩니다. 서버는 메인 스레드에서 Ctrl+C·SIGTERM을 처리하며 Linux `/proc`나 GNU `readlink -f`를 요구하지 않습니다. 로컬 파일 위치 열기는 Finder의 `open` 또는 `open -R`을 사용하고 실패하면 저장 경로를 제공합니다.

## 실행·종료·백그라운드

```bash
bash scripts/manage.sh status
bash scripts/manage.sh stop
bash scripts/manage.sh restart
bash scripts/manage.sh logs
```

`start`와 `restart`는 포그라운드 실행입니다. Ctrl+C 또는 다른 터미널의 `stop`으로 정상 종료하세요. 설치 경로·PID·시작 정보·명령을 확인해 종료 대상을 식별하고 파일 잠금으로 중복 실행을 차단합니다.

```bash
brew install tmux
tmux new -s phrolova 'cd "$HOME/Phrolova" && bash scripts/manage.sh start'
# Ctrl+B, D로 분리; tmux attach -t phrolova로 복귀
```

macOS에는 systemd 유닛을 등록하지 않습니다. 장시간 녹화 시 Mac의 절전 설정을 확인하세요.

## 업데이트·데이터

작업 완료 후 정상 종료하고 `.env`, 전체 `backend/data/`, 미디어를 백업하세요.

```bash
cd "$HOME/Phrolova"
bash scripts/manage.sh stop
bash scripts/manage.sh update
bash scripts/manage.sh start
```

설정·DB·쿠키·미디어 경로를 유지합니다. Python 업그레이드로 깨진 `.venv`는 `.venv-backups/`에 보존한 뒤 재생성합니다. 업데이트는 `main` 기준이며 비공개 저장소의 Git 인증을 유지해야 합니다.

[README](../README.md) · [검증 범위](native-platform-support.md)
