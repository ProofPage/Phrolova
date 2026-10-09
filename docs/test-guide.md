# 테스트 가이드

## 환경별 테스트 시나리오 개요

| 환경 | 목적 | 방법 |
|---|---|---|
| Windows (빌드 전) | 기능/API 최종 검증 | Python + Vite dev server |
| Windows (빌드 후) | 통합 서버 및 `.exe` 검증 | PyInstaller 빌드 후 실행 |
| Ubuntu VM (설치형) | Linux Native 배포 검증 | `manage.sh` + Native 실행 |

> [!NOTE]
> **빌드 후 테스트부터는 `.env`를 직접 편집하지 않아도 됩니다.**
> 서버 최초 실행 시 브라우저에 **초기 설정 마법사**가 자동으로 표시되어 저장 경로와 품질/포맷을 UI에서 설정할 수 있습니다. 인증 쿠키는 설정의 인증 탭에서 등록합니다.
> 마법사를 다시 띄우고 싶으면 `data/.setup_complete` 파일을 삭제하세요.

---

## 1. Windows — 빌드 전 기능 테스트

개발 환경 그대로 프론트엔드(Vite)와 백엔드(FastAPI)를 분리 실행한다.
이 환경에서는 개발 편의상 `.env`를 직접 편집해 사용한다.

### 사전 준비
```powershell
cd c:\Project\Phrolova\backend
.venv\Scripts\pip install -r requirements.txt
```

### 실행

**터미널 1 — 백엔드**
```powershell
cd c:\Project\Phrolova\backend
.venv\Scripts\python run.py
# 서버 시작 로그 확인: "Uvicorn running on http://0.0.0.0:8000"
```

**터미널 2 — 프론트엔드**
```powershell
cd c:\Project\Phrolova\frontend
npm install
npm run dev
# 브라우저: http://localhost:3000
```

> [!TIP]
> `localhost:3000`의 `/api/*` 요청은 Vite Proxy를 통해 `:8000`으로 자동 포워딩된다.

### 체크리스트
- [ ] 채널 추가/삭제 동작
- [ ] 라이브 녹화 시작/중지
- [ ] VOD 다운로드
- [ ] 설정 저장 및 불러오기
- [ ] `http://localhost:8000/health` → JSON 응답 확인

---

## 2. Windows — 빌드 후 통합 서버 테스트

`npm run build` 후 FastAPI 단독으로 프론트엔드까지 서빙하는 구조를 검증한다.

### Step A: 프론트엔드 빌드
```powershell
cd c:\Project\Phrolova\frontend
npm run build
# 완료 후 확인: backend\app\static\index.html 파일 존재 여부
```

### Step B: FastAPI 단독 실행 (Vite 없이)
```powershell
cd c:\Project\Phrolova\backend
.venv\Scripts\python run.py
# 브라우저: http://localhost:8000
```

**초기 설정 마법사 확인:**
1. `http://localhost:8000` 접속 시 마법사 팝업 자동 표시
2. Step 1: 저장 경로 입력, 품질/포맷 선택
3. Step 2: 설정 요약 확인 후 "설정 완료" 클릭
4. `data/.setup_complete` 파일 생성 확인 → 이후 재접속 시 마법사 미표시

### 체크리스트
- [ ] 마법사 팝업 표시 확인 (최초 접속 시)
- [ ] 마법사 완료 후 `data/.setup_complete` 파일 생성 확인
- [ ] 재접속 시 마법사 미표시 확인
- [ ] `http://localhost:8000/settings` → 새로고침 시에도 React 앱 유지 (SPA 라우팅)
- [ ] `http://localhost:8000/api/stream/channels` → JSON API 응답

### Step C: `.exe` 빌드 및 테스트

> [!IMPORTANT]
> `.exe` 빌드 전 반드시 **Step A**의 `npm run build`를 먼저 완료해야 한다.
> `bin/` 폴더에 `ffmpeg.exe`를 배치하거나 `phrolova.spec`의 `binaries` 항목 주석을 해제해야 FFmpeg가 번들에 포함된다.

```powershell
# PyInstaller 설치 (최초 1회)
.venv\Scripts\pip install pyinstaller

# 빌드 (프로젝트 루트에서 실행)
cd c:\Project\Phrolova
.venv\Scripts\pyinstaller phrolova.spec

# 빌드 결과물: dist\ChzzkRecorder\ChzzkRecorder.exe
```

**클린 환경 테스트** (중요):
- `dist\ChzzkRecorder\` 폴더를 Python/Node가 없는 다른 경로로 복사
- `ChzzkRecorder.exe` 더블클릭 → 브라우저 자동 열림 + **마법사 팝업** 표시 확인
- 트레이 아이콘 우클릭 → 메뉴 동작 확인

---

## 3. Ubuntu VM — 설치형(Native) 테스트

### 사전 준비
```bash
sudo apt update && sudo apt install -y python3.12 python3.12-venv ffmpeg git

cd /path/to/Phrolova
```

### 설치 스크립트 실행
```bash
bash scripts/manage.sh install --native
# .env 파일이 자동으로 .env.example에서 복사됨
# → 직접 편집 불필요, 마법사에서 설정 가능
```

### 프론트엔드 빌드 (Node.js가 없는 서버)
> [!TIP]
> Windows에서 미리 `npm run build`를 실행한 뒤 `backend/app/static/` 폴더를 함께 복사하면 Ubuntu에서 별도 빌드가 필요 없다.

```bash
# Node.js가 있는 경우에만 서버에서 직접 빌드
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
cd frontend && npm install && npm run build
```

### 서버 실행
```bash
cd /path/to/Phrolova/backend
../.venv/bin/python run.py
# 브라우저: http://[VM_IP]:8000 → 마법사 팝업 확인
```

### systemd 서비스 등록 (선택사항)
```bash
phrolova service install

sudo systemctl status phrolova
sudo journalctl -u phrolova -f
```

### 체크리스트
- [ ] `http://[VM_IP]:8000` → 마법사 팝업 표시
- [ ] 마법사 완료 후 API 정상 응답 확인
- [ ] systemd 등록 후 재부팅 시 자동 시작 확인

---

## 4. 멀티 플랫폼 기능 테스트

### Twitter Spaces 수동 캡처 테스트

> [!NOTE]
> Twitter Spaces는 비공식 GraphQL API의 Rate Limit 문제로 **자동 감시 없이 수동 캡처** 방식을 사용한다.
> Space가 라이브 중일 때 Discord 커맨드로 직접 캡처해야 한다.

**사전 준비:**
- 트위터 계정 쿠키(`auth_token`, `ct0`) Netscape 포맷 파일 준비
- 설정 페이지 → 인증 탭 → Twitter Spaces 섹션에 쿠키 파일 경로 입력
- Discord 봇 설정 완료

**테스트 절차:**

1. Dashboard → 채널 추가에서 `Twitter Spaces` 선택, 대상 트위터 핸들(예: `KalserianT`) 입력
2. 대상 계정에서 Space가 라이브 중인 시점에 Discord에서 캡처 커맨드 실행:
   ```
   /capture-space username:KalserianT
   ```
3. Space 라이브 중이면 녹색 Embed + m3u8 URL 반환 확인
4. Space가 없으면 파란 Embed (오프라인 안내) 확인
5. 캡처 후 다운로드:
   ```
   /download-space url:<캡처된_m3u8_url>
   또는
   Archive 페이지 → Twitter Spaces 탭에서 다운로드
   ```
6. `service.log`에서 429 오류 로그가 출력되지 않는지 확인

**체크리스트:**
- [ ] `/capture-space` 커맨드로 m3u8 URL 캡처 성공
- [ ] 캡처 결과 Discord Embed 색상 정상 (성공: 녹색, 오프라인: 파란색)
- [ ] `/download-space` 또는 Archive 페이지에서 다운로드 시작 확인
- [ ] 쿠키 만료 시 Discord 알림 수신 확인 (`POST /api/settings/cookie-status/check`)

---

## 포트 접근 문제 해결

Ubuntu VM에서 외부(Windows 호스트)에서 접근이 안 될 경우:
```bash
sudo ufw allow 8000
ip addr show | grep 'inet '
```

