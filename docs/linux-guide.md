# Linux 서버 설치 가이드

## 📋 개요

설치 방법은 두 가지입니다.

| 방식 | 대상 | 특징 |
|------|------|------|
| **원라이너** | 대부분의 경우 | 한 줄로 설치·업데이트·실행까지 전부 처리 |
| **수동 설치** | 개발/고급 사용자 | 단계별로 직접 제어 |

---

## 🚀 방법 1: 원라이너 (권장)

```bash
curl -fsSL https://raw.githubusercontent.com/ProofPage/Phrolova/main/scripts/manage.sh | bash
```

이 한 줄이 설치와 업데이트를 겸합니다. 설치되어 있지 않으면 설치하고, 이미 설치되어 있으면 최신 버전으로 갱신한 뒤 재시작합니다.


**자동으로 처리되는 것**

- Ubuntu / Debian / CentOS / Fedora / Arch / macOS 감지
- Python 3.10+, ffmpeg 6+, Node.js 20+ 설치
- 프론트엔드 빌드 (React → 정적 파일) 및 Python 가상환경 구성
- systemd 서비스 등록 (선택, 부팅 시 자동 실행)
- 헬스체크로 정상 기동 확인

### 설치 후 관리

설치가 끝나면 `rookery` 명령이 등록됩니다.
`/usr/local/bin`에 걸 수 있으면 그곳에, 권한이 없으면 `~/.local/bin`에 등록합니다.

```bash
rookery status          # 상태 요약
rookery status --full   # 상세 점검 (프로세스·DB·디스크·로그)
rookery update          # 최신 버전으로 갱신 후 재시작
rookery start           # 시작
rookery stop            # 중지
rookery restart         # 재시작
rookery logs            # 로그 실시간 보기
rookery service install # systemd 등록
rookery service remove  # systemd 해제
rookery uninstall       # 제거 (녹화 파일·데이터는 유지)
```

> **`rookery: command not found` 가 나온다면** 코드를 `git pull` 로만 갱신해 와서
> 명령이 한 번도 등록되지 않은 경우입니다. 아래 원라이너가 업데이트를 겸하며
> 명령도 함께 등록합니다.
>
> ```bash
> curl -fsSL https://raw.githubusercontent.com/ProofPage/Phrolova/main/scripts/manage.sh | bash
> ```
>
> `~/.local/bin`에 등록됐는데 PATH에 없다는 경고가 나왔다면 셸 설정에 아래를 추가하세요.
> root 계정은 이 경로가 기본 PATH에 없습니다.
>
> ```bash
> echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
> ```

### 옵션

```bash
# 설치 경로 변경 (기본: ~/rookery)
INSTALL_DIR=/opt/rookery curl -fsSL https://raw.githubusercontent.com/ProofPage/Phrolova/main/scripts/manage.sh | bash

# 명시적으로 설치만 수행 (업데이트 판단 없이)
curl -fsSL https://raw.githubusercontent.com/ProofPage/Phrolova/main/scripts/manage.sh | bash -s -- install
```

---


## 🔧 방법 2: 수동 설치 (고급 사용자)

### 사전 요구사항

```bash
# Ubuntu/Debian 기준
sudo apt-get update
sudo apt-get install -y python3.12 python3.12-venv ffmpeg git
```

### 설치

```bash
# 저장소 클론
git clone https://github.com/ProofPage/Phrolova.git
cd Rookery

# 프론트엔드 빌드
cd frontend
npm ci && npm run build
cp -r dist ../backend/app/static
cd ..

# Python 의존성 설치
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

### 실행

```bash
# 프로젝트 루트에서
source .venv/bin/activate
cd backend
python run.py
```

접속: `http://서버IP:8000`

### 백그라운드 실행 (systemd)

`/etc/systemd/system/rookery.service` 생성:

```ini
[Unit]
Description=Rookery
After=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/Rookery/backend
ExecStart=/home/ubuntu/Rookery/.venv/bin/python run.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable rookery
sudo systemctl start rookery
sudo systemctl status rookery
```

---

## 🌐 방화벽 설정

원격 접속 시 포트 개방:

```bash
# UFW (Ubuntu)
sudo ufw allow 8000/tcp

# firewalld (CentOS/RHEL)
sudo firewall-cmd --permanent --add-port=8000/tcp
sudo firewall-cmd --reload
```

---

## 🧙 초기설정 마법사

설치 후 처음 접속하면 브라우저 기반 마법사가 표시됩니다.

1. `http://서버IP:8000` 접속
2. 마법사 완료 → `.env` 파일 자동 생성
3. 이후 재시작해도 설정 유지

> `.env` 파일을 삭제하면 마법사가 다시 표시됩니다.

---

## 🔄 재설치 / 완전 초기화

대부분의 경우 재설치할 필요 없이 `rookery update` 로 충분합니다.
완전히 지우고 다시 깔아야 한다면:

```bash
# 1. 서비스와 실행 환경 정리 (녹화 파일과 data/ 는 남습니다)
rookery uninstall

# 2. 저장소까지 지우려면
rm -rf ~/rookery

# 3. 재설치
curl -fsSL https://raw.githubusercontent.com/ProofPage/Phrolova/main/scripts/manage.sh | bash
```

> ⚠️ **`address already in use` 오류가 나는 경우**
> 기존 서비스가 포트를 점유하고 있는 상태입니다. 먼저 중지하세요.
> ```bash
> rookery stop
> ```

---


## 🛠️ 트러블슈팅

| 증상 | 해결 |
|------|------|
| `python3.12` 없음 | `sudo add-apt-repository ppa:deadsnakes/ppa && sudo apt install python3.12` |
| `ffmpeg` 명령 없음 | `sudo apt install ffmpeg` |
| 포트 접속 불가 | 방화벽 확인, `sudo ufw allow 8000/tcp` |
| `address already in use` 오류 | `sudo systemctl stop rookery` 후 재실행 |
| Permission denied | `chown -R $USER:$USER ./recordings ./data ./logs` |
