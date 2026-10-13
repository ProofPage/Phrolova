# Linux 설치 및 운영

Linux x86_64/ARM64에서 소스로 실행합니다. Python 3.12+, Node.js 22+와 npm, FFmpeg/FFprobe 6+, Bash, Git, curl, ps가 필요합니다. apt·dnf/yum·pacman·apk를 감지해 해당 배포판 패키지를 사용합니다.

## 설치

저장소는 비공개입니다. 접근 권한이 있는 GitHub 계정의 Git 자격 증명이나 SSH 키를 먼저 설정하세요.

```bash
# Ubuntu/Debian 초기 도구. 다른 배포판은 자체 패키지 매니저를 사용합니다.
sudo apt-get update
sudo apt-get install -y bash git curl
git clone https://github.com/ProofPage/Phrolova.git "$HOME/Phrolova"
cd "$HOME/Phrolova"
bash scripts/manage.sh install
bash scripts/manage.sh start
```

설치 명령은 기존 체크아웃을 재사용하고 의존성 검사, 가상환경 생성, 프론트엔드 빌드와 관리 명령 등록을 수행합니다. Python 기본 버전이 3.12 미만인 배포판에서는 적합한 Python을 먼저 설치해야 합니다. Debian에 Ubuntu PPA를 자동 추가하지 않습니다.

Node는 22 이상을 검사합니다. apt 계열은 NodeSource Debian 설치 방법, dnf/yum은 RPM 설치 방법을 사용하며 Arch/Alpine은 자체 패키지를 사용합니다. FFmpeg와 FFprobe를 각각 검사합니다. GNU/Linux 정적 FFmpeg 대체 설치는 x86_64/ARM64 glibc 환경에서만 사용하며 Alpine에는 적용하지 않습니다.

처음 실행한 후 <http://127.0.0.1:8000>에서 설정을 완료하세요. 루트 `.env`가 없으면 기본 설정 화면을 이용합니다. `DOWNLOAD_DIR`을 지정한 `.env`를 먼저 만들면 이 화면을 건너뜁니다.

## 실행 방식

systemd가 실제 실행 중이면 서비스 등록을 선택할 수 있습니다.

```bash
bash scripts/manage.sh service install
bash scripts/manage.sh status
bash scripts/manage.sh logs
bash scripts/manage.sh stop
bash scripts/manage.sh restart
```

유닛은 현재 사용자, 가상환경 Python과 `backend/` 작업 디렉터리를 사용하며 PATH에 Node를 포함합니다. 공백·퍼센트가 포함된 경로를 systemd 인용 규칙으로 처리합니다. 종료 신호는 우선 서버에 전달해 녹화 후처리와 자식 프로세스 정리를 수행합니다.

systemd가 없으면 `start`는 포그라운드 실행입니다. Ctrl+C로 종료하거나 다른 터미널에서 `stop`을 실행하세요. 설치본별 PID/시작 정보를 확인해 해당 서버만 종료하고, 종료가 지연되면 중복 재시작을 중단합니다.

```bash
# systemd 없는 서버의 백그라운드 세션
sudo apt-get install -y tmux
tmux new -s phrolova 'cd "$HOME/Phrolova" && bash scripts/manage.sh start'
# Ctrl+B, D로 분리; tmux attach -t phrolova로 복귀
```

## 저장 경로·업데이트·점검

설정은 루트 `.env` 우선, 기존 `backend/.env`는 폴백입니다. DB와 업로드 쿠키는 `backend/data/`, 로그는 루트 `logs/`에 있습니다. 상대 미디어 경로는 `backend/` 기준입니다. 절대경로를 설정하면 실행 방식에 관계없이 같은 위치를 사용합니다.

녹화·다운로드 완료 후 정상 종료하고 `.env`, 전체 `backend/data/`, 필요한 미디어를 백업하세요.

```bash
cd "$HOME/Phrolova"
bash scripts/manage.sh stop
bash scripts/manage.sh update
bash scripts/manage.sh start
bash scripts/manage.sh status --full
```

업데이트는 `main`을 가져오며 설정·DB·쿠키·미디어를 보존합니다. 로컬 코드 변경이 pull을 막으면 stash 위치를 표시합니다. Python 업그레이드로 깨진 가상환경은 `.venv-backups/`에 보존하고 재생성합니다.

상세 점검은 API 조회·읽기 전용 SQLite 접근·프로세스 확인을 수행합니다. 데스크톱 폴더 열기는 `xdg-open`을 사용하고 디스플레이 없는 서버에서는 경로만 제공합니다.

## 원격 접속

기본 루프백 바인딩을 유지하고 SSH 터널로 접속할 수 있습니다.

```bash
ssh -N -L 8000:127.0.0.1:8000 user@server
```

웹 API에 별도 로그인 기능은 없습니다. 외부 공개 시 인증 프록시 또는 사설 네트워크에서 접근을 제어하세요.

[README](../README.md) · [검증 범위](native-platform-support.md)
