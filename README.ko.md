# 🎬 Phrolova (프로로바)

<p align="center">
  <b>현대적인 웹 UI, 스케줄 예약 감시, 무손실 원본 화질을 지원하는 개인용 라이브 스트림 녹화 및 VOD 다운로드 스위트</b>
</p>

<p align="center">
  <a href="https://github.com/ProofPage/Phrolova/releases/latest"><img alt="Release" src="https://img.shields.io/github/v/release/ProofPage/Phrolova?color=blue&label=Release"></a>
  <a href="https://github.com/ProofPage/Phrolova/releases/latest"><img alt="Platform" src="https://img.shields.io/badge/Platform-Windows%20x64-lightgrey"></a>
  <a href="https://github.com/ProofPage/Phrolova/releases/latest"><img alt="Python" src="https://img.shields.io/badge/Python-3.14%2B-blue"></a>
  <img alt="License" src="https://img.shields.io/badge/License-MIT-green">
</p>

<p align="center">
  <a href="https://github.com/ProofPage/Phrolova/releases/latest"><b>최신 릴리즈 다운로드 (Windows x64) ↓</b></a> ·
  <a href="#-주요-기능"><b>주요 기능</b></a> ·
  <a href="#-지원-플랫폼"><b>지원 플랫폼</b></a> ·
  <a href="#-빠른-시작"><b>빠른 시작</b></a> ·
  <a href="docs/CHANGELOG.md"><b>변경 기록</b></a> ·
  <a href="README.md"><b>English</b></a>
</p>

---

## ✨ 주요 기능

- 🎯 **멀티 플랫폼 라이브 & VOD 캡처**: 치지직(CHZZK), 숲(SOOP), 유튜브(YouTube), 킥(Kick), 트위치(Twitch), 틱톡(TikTok), 빌리빌리(Bilibili), 팬더티비(PandaTV), 팝콘티비(PopkonTV), 알플레이(RPLAY), 씨미(CIME), 트윗캐스팅(TwitCasting), 스푼(Spoon), 베리즈(Berriz) 등 폭넓은 플랫폼 지원.
- 🔁 **24/7 무중단 자동 감시 가디언**: 실시간 방송 시작을 자동 감지하여 녹화를 시작하며, 네트워크 일시 단절 및 토큰 만료 시에도 누락 없이 안전하게 스트림을 이어받아 복구합니다.
- 📅 **채널별 스케줄 예약 감시**: 24시간 불필요한 감시 트래픽을 방지하기 위해 채널별로 요일과 시간대를 지정하여 정해진 시간에만 집중 감시할 수 있습니다.
- 📊 **검증된 실시간 해상도 및 FPS 표시**: HLS 스트림 정보를 실시간 분석하여 단순 명칭뿐 아니라 실제 비디오 해상도 및 프레임률(예: `1920×1080 · 60fps`)을 상세하게 표시합니다.
- ⏱️ **치지직 타임머신 녹화**: 방송이 시작된 후 늦게 감시를 켜더라도, 치지직 서버가 제공하는 이전 버퍼(최대 1시간)를 되감아 방송 처음부터 완벽하게 녹화합니다.
- ⚡ **단일 실행 파일 제공 (Windows x64)**: 복잡한 Python 환경 설정 없이 더블 클릭 한 번으로 바로 실행할 수 있는 독립형 포터블 실행 파일(`.exe`) 제공.
- 🖥️ **현대적인 반응형 웹 대시보드**: 실시간 방송 상태, 데스크톱 시스템 트레이, 8개 언어 네이티브 다국어 지원(**한국어, 영어, 일본어, 중국어 간체, 중국어 번체, 독일어, 스페인어, 러시아어**)을 갖춘 완성도 높은 React 대시보드.
- 🛠️ **스마트 도구 자동 감지 및 초고속 미러링**: 시스템 PATH, WinGet, Chocolatey, Scoop, 수동 압축 해제 폴더(`ffmpeg-*`)까지 완벽 감지하며, 미설치 시 초고속 글로벌 CDN을 통해 원클릭 자동 설치를 지원합니다.
- 🔐 **통합 인증 및 쿠키 관리자**: 성인 인증, 구독자 전용 방송, 비공개 스트림 녹화를 위해 브라우저 쿠키를 쉽게 가져오거나 등록할 수 있습니다.

---

## 🐱 지원 플랫폼

| 플랫폼 | 라이브 녹화 | VOD / 다시보기 다운로드 | 화질 선택 | 주요 특징 및 기능 |
| :--- | :---: | :---: | :---: | :--- |
| **CHZZK (치지직)** | ✅ | ✅ | 원본 / 1080p60 ~ 360p | 타임머신 되감기 녹화, 네이버 쿠키 인증, 60fps 감지 |
| **SOOP (숲)** | ✅ | ✅ | 원본 / 1080p ~ 360p | 실시간 방송 및 VOD 다운로드, 쿠키 인증 연동, 세그먼트 보호 |
| **YouTube (유튜브)** | ✅ | ✅ | 최고 화질 / 4K ~ 360p | 라이브 DASH/HLS 수집, 멤버십 전용 방송 쿠키 지원 |
| **Twitch (트위치)** | ✅ | ✅ | 원본 / 1080p60 ~ 160p | TTV-AB 광고 차단 필터 토글, 구독자 화질 연동 |
| **Kick (킥)** | ✅ | ✅ | 원본 / 1080p60 ~ 360p | 즉각적인 라이브 감지 및 직접 HLS 스트림 추출 |
| **TikTok (틱톡)** | ✅ | ✅ | 원본 / 가변 화질 | 실시간 라이브 수집 및 단일 영상 다운로드 |
| **Bilibili (빌리빌리)** | ✅ | ✅ | 원본 / 1080p ~ 360p | 세션 헤더 자동 주입 및 다중 파트 VOD 지원 |
| **PandaTV (팬더티비)** | ✅ | — | 원본 / 최고 화질 | 한국 라이브 플랫폼 네이티브 스트림 캡처 |
| **PopkonTV (팝콘티비)** | ✅ | ✅ | 원본 / 최고 화질 | 파트너 코드 유지 및 계정/비밀방 비밀번호 연동 |
| **RPLAY (알플레이)** | ✅ | ✅ | 원본 / 최고 화질 | 세션 파일 가져오기 및 회원 전용 스트림 인증 |
| **CIME (씨미)** | ✅ | ✅ | UHD / 1080p60 | MCO 로그인 인증 및 4K 고화질 스트림 수집 |
| **특화 비디오 사이트** | — | ✅ | 원본 / 최고 화질 | MissAV, AV19(Node.js WASM 디코더), YamiKorea 및 회차별 시리즈 사이트 |

---

## 🚀 빠른 시작

### 1. Windows 단일 실행 파일 (가장 권장)

1. [GitHub Releases](https://github.com/ProofPage/Phrolova/releases/latest)에서 최신 **`Phrolova-v2.2.8-windows-x64.exe`**와 **`SHA256SUMS.txt`**를 다운로드합니다.
2. 실행 파일을 쓰기 권한이 있는 폴더에 넣고 실행합니다. (별도의 Python 설치 불필요)
3. 첫 실행 시 시스템에 FFmpeg가 없으면 안내에 따라 `y`를 입력하여 Windows 표준 프로그램 경로(`%LOCALAPPDATA%\Programs\ffmpeg\bin`)에 고속 자동 설치를 진행합니다.
4. 브라우저에서 `http://localhost:8000`에 접속하거나 시스템 트레이 메뉴에서 **브라우저 열기**를 선택합니다.
5. 대시보드에서 원하는 스트리머의 채널 링크나 ID를 등록하면 즉시 감시 및 자동 녹화가 시작됩니다.

> **보안 권장사항**: Phrolova는 로컬 우선(Local-first) 프로그램입니다. 기본 `127.0.0.1:8000` 바인딩을 유지하시고, 인증된 리버스 프록시나 SSH 터널 없이 공용 인터넷에 포트를 직접 노출하지 마세요.

---

### 2. Docker / Docker Compose (NAS 및 홈 서버 권장)

FFmpeg, Node.js WASM 디코더, Python 환경이 모두 포함된 컨테이너로 손쉽게 구동할 수 있습니다:

```bash
# 저장소 복제
git clone https://github.com/ProofPage/Phrolova.git
cd Phrolova

# Docker Compose 백그라운드 실행
docker compose up -d
```

구동 후 `http://localhost:8000`에서 웹 대시보드에 접근할 수 있으며, 다운로드된 영상과 데이터베이스는 `./downloads` 및 `./data`에 영구 보존됩니다.

---

### 3. 소스코드 직접 실행 (Linux / macOS / Windows)

#### 사전 요구 사양
- **Python 3.14.8 이상** (표준 GIL)
- **Node.js 22 이상** 및 **npm**
- **FFmpeg / FFprobe** (시스템 PATH에 등록)

#### 설치 및 실행
```bash
# 저장소 복제
git clone https://github.com/ProofPage/Phrolova.git
cd Phrolova

# 백엔드 가상환경 설정 및 패키지 설치
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate | Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

# 프론트엔드 빌드
cd ../frontend
npm install
npm run build

# 서버 기동
cd ../backend
python run.py
```

브라우저에서 `http://127.0.0.1:8000`으로 접속합니다.

---

## 📌 시스템 요구 사양

| 구성 요소 | 요구 사양 | 비고 |
| :--- | :--- | :--- |
| **운영체제** | Windows 10 / 11 (64-bit), Linux x64/ARM64, macOS | 단일 포터블 `.exe`, 소스코드, 또는 Docker 환경 |
| **FFmpeg & FFprobe** | 7.0 이상 권장 | PATH, WinGet, Scoop, `ffmpeg-*` 폴더 자동 감지 또는 자동 설치 |
| **웹 브라우저** | Chrome, Edge, Whale, Firefox, Safari | 최신 웹 대시보드 인터페이스 지원 |

---

## ⚙️ 핵심 동작 및 기능

- **무손실 원본 스트림 저장**: 별도의 손실 압축이나 재인코딩 없이 원본 컨테이너 포맷(`.ts` 또는 `.native.mp4`) 그대로 저장하여 방송 송출 원본의 화질과 음질을 100% 보존합니다.
- **예약 감시 윈도우**: 채널별 설정에서 방송 시간대와 요일을 지정하여, 불필요한 네트워크 대역폭과 시스템 자원 낭비를 줄입니다.
- **시스템 트레이 백그라운드 동작**: Windows 시스템 트레이로 최소화하여 작업 표시줄을 차지하지 않고 백그라운드에서 조용히 감시 및 녹화를 수행합니다.
- **타임머신 및 되감기 녹화**: 치지직 등 타임머신을 지원하는 플랫폼의 경우 최대 1시간의 이전 버퍼를 되감아 방송 시작 시점부터 녹화할 수 있습니다.

---

## 🔐 인증 및 보안 주의사항

브라우저 로그인 상태는 Phrolova 서버에 자동으로 전송되지 않습니다. 성인 인증이나 구독자 전용 콘텐츠를 저장하려면 **설정 → 인증** 탭에서 해당 플랫폼의 쿠키나 세션 파일을 등록하세요.

- **숲 (SOOP)**: 스트리머 ID(예: `y1026`) 또는 라이브 주소를 입력합니다. 다시보기는 `vod.sooplive.com/player/...` 링크를 사용합니다.
- **알플레이 (RPLAY)**: 브라우저 쿠키 파일이 아닌 세션 JSON 파일 가져오기를 사용합니다.
- **유튜브 (YouTube)**: 봇 확인이나 요청 제한 방지를 위해 필요 시 설정에서 쿠키를 등록할 수 있습니다.
- **대시보드 보안**: 대시보드 자체에는 별도의 계정 로그인 기능이 없으므로, 기본 루프백 주소(`127.0.0.1:8000`)를 유지하고 외부 접근 시에는 SSH 터널을 사용하세요:

```bash
ssh -N -L 8000:127.0.0.1:8000 사용자@서버주소
```

---

## 📜 라이선스

Phrolova는 [MIT 라이선스](docs/release-notes/v2.2.8.md)에 따라 배포됩니다. FFmpeg, Streamlink, yt-dlp 등 외부 도구는 각자의 오픈소스 라이선스를 따릅니다. 사용자는 정당한 권한이 있는 콘텐츠만 녹화 및 저장해야 합니다.

