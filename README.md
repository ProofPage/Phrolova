<div align="center">

# Phrolova

**라이브 방송 감시·녹화와 다시보기·클립·오디오 다운로드를 관리하는 자체 호스팅 웹 애플리케이션**

[![Latest release](https://img.shields.io/github/v/release/ProofPage/Phrolova?display_name=tag&label=latest%20release)](https://github.com/ProofPage/Phrolova/releases/latest)
[![CI](https://github.com/ProofPage/Phrolova/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/ProofPage/Phrolova/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/License-MIT-64748B)](LICENSE)

[Windows 다운로드](https://github.com/ProofPage/Phrolova/releases/latest) · [설치 및 실행](#설치-및-실행) · [변경 내역](docs/CHANGELOG.md) · [문제 보고](https://github.com/ProofPage/Phrolova/issues)

</div>

Phrolova는 개인 PC나 서버에서 실행하는 방송 저장 도구입니다. 웹 화면에서 채널을 등록하고 방송 상태를 확인하며, 자동 또는 수동으로 라이브를 녹화할 수 있습니다. 다시보기와 클립 등 기존 미디어는 다운로드 대기열에서 관리합니다.

이 문서에서 **녹화**는 진행 중인 라이브를 저장하는 작업, **다운로드**는 다시보기·클립·영상·오디오를 가져오는 작업을 뜻합니다. 저장 작업은 Phrolova가 실행되는 PC 또는 서버에서 수행됩니다.

## 주요 기능

- **라이브 관리:** CHZZK, YouTube, X Spaces 채널 감시, 자동·수동 녹화, 즉시 스캔, 채널 태그와 카드·목록 보기.
- **CHZZK 녹화 설정:** 같이보기 태그를 기준으로 자동 녹화 조건을 지정하고, 기본 스트림 또는 타임머신 스트림을 선택.
- **영상 다운로드:** CHZZK 다시보기·클립, YouTube 영상·채널 영상 목록, yt-dlp가 지원하는 미디어 URL 처리.
- **다운로드 대기열:** 순서 변경, 일시정지·재개, 취소·재시도, 동시 다운로드 수와 속도 제한 설정.
- **저장 설정:** 라이브와 영상 저장 위치 분리, 화질·파일 형식·파일명 규칙 지정, CHZZK 녹화 시작 시 미리보기 이미지 저장.
- **채팅 기록:** CHZZK 라이브 채팅을 JSONL로 저장하고, 웹 화면에서 메시지·닉네임 검색 및 원본 로그 다운로드.
- **상태 확인:** 라이브 영상 미리보기, 녹화·다운로드 이력, 통계, 디스크 사용량, 애플리케이션 로그 조회.
- **Discord 연동:** Bot 또는 Webhook 알림, Bot 명령어를 통한 녹화·캡처 제어.
- **웹 인터페이스:** 모바일·태블릿·데스크톱에 맞춘 화면과 한국어·영어·일본어 UI.

## 지원 서비스

| 서비스 | 라이브 감시·녹화 | 기존 미디어 다운로드 | 인증 및 제한 |
| --- | --- | --- | --- |
| CHZZK | 지원 | 다시보기, 클립 | 성인 인증이나 일부 화질 접근에 NID_AUT·NID_SES 쿠키가 필요할 수 있습니다. 채팅 저장과 같이보기 조건은 CHZZK 기능입니다. |
| YouTube | 지원 | 개별 영상, 채널 영상 목록 | 채널 URL·핸들·ID를 사용할 수 있습니다. 로그인 필요 콘텐츠는 쿠키 파일이 필요할 수 있습니다. |
| X Spaces | Space 감지, 라이브 오디오 녹화 | Space URL 또는 저장한 재생 목록 URL의 오디오 | X 쿠키 파일이 필요합니다. 감시 주기는 300초이며, 다시보기 제공 여부와 링크 유효 기간은 서비스 상태에 따라 달라집니다. |
| 기타 yt-dlp 지원 사이트 | 채널 감시 미지원 | 지원되는 미디어 URL | 사이트별 extractor, 콘텐츠 공개 상태, 인증 요구 사항에 따라 다운로드 가능 여부가 달라집니다. |

지원 서비스의 모든 콘텐츠나 화질을 받을 수 있다는 의미는 아닙니다. 비공개·삭제된 콘텐츠나 계정 권한이 없는 콘텐츠에는 접근할 수 없습니다.

## 요구 사항

| 사용 방식 | 필요한 환경 |
| --- | --- |
| Windows 배포 파일 | Windows x64용 실행 파일, FFmpeg. Python 런타임과 Node.js는 실행 파일에 포함됩니다. |
| 소스 실행·개발 | Python 3.12 기준, Node.js 20 이상, FFmpeg, Git. CI는 Python 3.12와 Node.js 20으로 구성되어 있습니다. |
| Windows 실행 파일 빌드 | Windows, Python 3.12 기준, Node.js 22 이상. 릴리스 워크플로는 Node.js 24를 사용합니다. |

Linux·macOS 관리 스크립트는 Python 3.10 이상, Node.js 20 이상, FFmpeg 6 이상을 검사합니다. 이는 설치 스크립트의 검사 기준이며, Python 3.10·3.11에서의 전체 동작을 CI가 검증하는 것은 아닙니다. 소스 실행 환경은 CI와 같은 Python 3.12를 기준으로 구성하세요. macOS의 자동 의존성 설치에는 Homebrew가 필요합니다.

## 설치 및 실행

### Windows

1. [최신 릴리스](https://github.com/ProofPage/Phrolova/releases/latest)에서 `Phrolova-v*-windows-x64.exe`를 내려받습니다.
2. 쓰기 권한이 있는 폴더에 실행 파일을 놓고 실행합니다.
3. FFmpeg가 없으면 시작 콘솔의 설치 안내를 따릅니다. 자동 다운로드·설치 여부를 묻는 절차가 있습니다.
4. 열린 브라우저에서 초기 설정을 완료합니다. 브라우저가 열리지 않으면 [http://127.0.0.1:8000](http://127.0.0.1:8000)에 접속합니다.

FFmpeg는 실행 파일에 포함되지 않습니다. 직접 설치할 경우 실행 파일 옆 `bin/ffmpeg.exe`에 배치하거나 시스템 PATH에 추가할 수 있습니다. yt-dlp 실행 파일이 없으면 Windows 배포 환경에서 자동으로 내려받을 수 있습니다.

**업데이트:** 실행 중인 앱을 종료한 뒤 최신 실행 파일로 교체합니다. 기존 `.env`, `data/`, `bin/`과 녹화·다운로드 폴더를 유지하세요.

### Linux·macOS

저장소의 설치·관리 스크립트를 실행합니다.

```bash
curl -fsSL https://raw.githubusercontent.com/ProofPage/Phrolova/main/scripts/manage.sh | bash
```

스크립트는 의존성 확인·설치, 저장소 복제, Python 가상환경 구성과 프론트엔드 빌드를 수행합니다. 기본 설치 경로는 `~/rookery`입니다. Linux에서는 systemd 서비스 등록을 선택할 수 있으며, 서비스로 등록하지 않았다면 `rookery start`로 실행합니다.

```bash
rookery start
rookery status
rookery status --full
rookery stop
rookery restart
rookery logs
rookery update
```

설치 후 로컬에서는 [http://127.0.0.1:8000](http://127.0.0.1:8000), 원격에서는 `http://서버IP:8000`에 접속합니다. systemd 등록·서비스 로그 조회는 Linux 서비스 설치 환경에 해당합니다. macOS 또는 서비스 미등록 환경의 `rookery start`는 포그라운드로 실행되며, 종료는 해당 터미널에서 Ctrl+C를 사용하세요.

프로젝트 이름은 Phrolova이지만 관리 명령, 서비스명, 일부 내부 파일명은 현재 구현대로 `rookery`를 사용합니다.

### 소스에서 실행

프로젝트를 복제하고 백엔드 의존성을 설치합니다. 아래는 Linux·macOS 셸 기준입니다.

```bash
git clone https://github.com/ProofPage/Phrolova.git
cd Phrolova
python3.12 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt
```

일반 실행은 프론트엔드를 먼저 빌드한 뒤 백엔드를 시작합니다.

```bash
cd frontend
npm ci
npm run build
cd ..
backend/.venv/bin/python backend/run.py
```

빌드 결과는 `backend/app/static/`에 생성되고 FastAPI가 웹 화면과 API를 함께 제공합니다. 기본 접속 주소는 [http://127.0.0.1:8000](http://127.0.0.1:8000)입니다.

프론트엔드를 개발할 때는 백엔드를 실행한 상태에서 별도 터미널로 다음 명령을 실행합니다.

```bash
cd frontend
npm ci
npm run dev
```

Vite의 기본 포트는 `3000`이며, `/api`와 `/health` 요청을 `http://127.0.0.1:8000`으로 전달합니다. 실제 접속 주소는 터미널 안내를 확인하세요.

Windows PowerShell에서는 가상환경 생성에 `py -3.12 -m venv backend/.venv`, 의존성 설치에 `backend/.venv/Scripts/python -m pip install -r backend/requirements.txt`, 백엔드 실행에 `backend/.venv/Scripts/python backend/run.py`를 사용합니다. 프론트엔드의 npm 명령은 동일합니다.

## 사용 방법

1. **설정**에서 라이브·영상 저장 위치와 화질을 지정하고, 필요한 서비스의 인증 정보를 등록합니다.
2. **라이브**에서 플랫폼을 선택해 채널을 추가합니다. 자동 녹화를 켜면 방송 감지 후 녹화를 시작하며, 수동으로 시작·중지할 수도 있습니다.
3. CHZZK 채널은 녹화 조건을 **모든 방송**, **같이보기만**, **같이보기 제외** 중에서 선택할 수 있습니다.
4. **다운로드**에 영상 URL을 입력합니다. YouTube 채널 URL·핸들·ID로 채널 영상 목록을 불러와 대기열에 추가할 수도 있습니다.
5. **X Spaces**에는 Space URL 또는 라이브 감시 중 저장한 재생 목록 URL을 입력합니다. 진행 상황은 **다운로드**에서 확인합니다.
6. 채팅 저장을 켠 CHZZK 녹화의 로그는 **채팅 기록**, 완료 이력과 저장 용량은 **통계**, 오류 상세는 **로그**에서 확인합니다.

X Spaces 다시보기는 사전에 캡처한 링크뿐 아니라 직접 입력한 Space URL로도 요청할 수 있습니다. 실제 다운로드는 쿠키 유효성, 공개 상태, 서비스가 제공하는 재생 목록의 가용성에 따라 달라집니다.

## 설정 및 데이터

일반 사용에 필수로 입력해야 하는 환경 변수는 없습니다. 초기 설정과 웹 화면에서 대부분의 옵션을 변경할 수 있으며, 설정은 `.env`에 저장됩니다. 환경 변수와 설정 기본값의 구현 기준은 [config.py](backend/app/core/config.py)입니다. [.env.example](.env.example)은 참고용 템플릿이며 일부 구버전 설정도 포함합니다.

| 설정 | 기본값 | 설명 |
| --- | --- | --- |
| `HOST` | `0.0.0.0` | 서버가 연결을 받는 주소 |
| `PORT` | `8000` | 웹 서버 포트 |
| `FFMPEG_PATH` | `ffmpeg` | FFmpeg 실행 파일 경로 또는 이름 |
| `MONITOR_INTERVAL` | `60` | 일반 채널 감시 주기(초). X Spaces는 별도로 300초를 사용 |
| `LIVE_DOWNLOAD_DIR`, `VOD_DOWNLOAD_DIR` | 빈 값 | 라이브·영상 저장 위치. 별도 지정이 없으면 기존 저장 경로 설정 사용 |
| `DOWNLOAD_DIR` | `./recordings` | 별도 경로가 없을 때 사용하는 기본 저장 위치 |
| `LIVE_FORMAT`, `VOD_FORMAT` | `ts`, `mp4` | 라이브·영상 파일 형식. TS·MKV·MP4 선택 가능 |
| `VOD_MAX_CONCURRENT` | `3` | 동시 영상 다운로드 수 |
| `VOD_MAX_SPEED` | `0` | 다운로드 속도 제한(MB/s). 0은 제한 없음 |
| `CHAT_ARCHIVE_ENABLED` | `false` | CHZZK 라이브 채팅 저장 |
| `CHZZK_STREAM_MODE` | `request-timemachine` | 타임머신 스트림을 우선 요청하고, 사용할 수 없으면 기본 스트림으로 전환 |

`CHZZK_STREAM_MODE`의 다른 값은 기본 스트림을 사용하는 `standard`, 타임머신을 사용할 수 없으면 녹화를 실패 처리하는 `force-timemachine`입니다. 웹 설정에서 녹화 방식을 선택할 수 있습니다.

### 파일명

기본 파일명은 **[채널명] 제목 날짜 시-분-초** 형식입니다. 파일 확장자는 선택한 형식에 맞춰 붙습니다.

라이브의 `LIVE_FILENAME_TEMPLATE` 기본값:

```text
[{name}] {title} {live_date_year}-{live_date_month}-{live_date_day} {live_date_hour}-{live_date_minute}-{live_date_second}
```

영상 다운로드의 `VOD_FILENAME_TEMPLATE` 기본값:

```text
[{name}] {title} {date_year}-{date_month}-{date_day} {date_hour}-{date_minute}-{date_second}
```

라이브 날짜 변수는 방송 시작 시각을 사용하며, 시작 시각을 가져오지 못하면 녹화 시작 시각을 사용합니다. 영상 다운로드의 날짜 변수는 다운로드 시작 시각입니다. 파일명에 사용할 수 없는 문자는 정리됩니다.

### 인증과 알림

- **CHZZK:** `NID_AUT`, `NID_SES` 쿠키.
- **YouTube:** 로그인이 필요한 콘텐츠에 사용할 Netscape 형식 쿠키 파일.
- **X Spaces:** `auth_token`과 `ct0`가 포함된 Netscape 형식 X 쿠키 파일.
- **Discord:** Bot Token과 알림 채널 ID, 또는 Webhook URL. Bot 명령어를 사용할 때는 허용 사용자·채널을 설정합니다.

쿠키 파일은 **설정 → 인증**, Discord 연동은 **설정 → 알림**에서 관리합니다.

### 데이터 보관

| 실행 방식 | 설정 파일 | 채널·작업·이력 데이터 |
| --- | --- | --- |
| Windows 배포 파일 | 실행 파일 옆 `.env` | 실행 파일 옆 `data/rookery.db` |
| 소스·관리 스크립트 | 저장소 루트의 `.env` | `backend/data/rookery.db` |

소스 실행 시 루트에 `.env`가 없고 기존 `backend/.env`가 있으면 해당 파일을 읽습니다. 녹화 파일과 채팅 로그, 다운로드 파일은 설정한 저장 폴더에 보관됩니다.

백업·이전 전에는 앱을 정상 종료하고 `.env`, 데이터 폴더와 미디어 폴더를 함께 보관하세요. 데이터 폴더에는 업로드한 쿠키 파일도 저장됩니다. SQLite 저장 구조는 [데이터 저장 문서](docs/storage.md)를 참고하세요.

## Windows 실행 파일 빌드

[릴리스 워크플로](.github/workflows/release.yml)는 Python 3.12와 Node.js 24를 사용합니다. [rookery.spec](rookery.spec)은 Node.js 22 이상을 검사하고 Node.js 실행 파일을 포함합니다. Windows에서 저장소 루트를 기준으로 실행합니다.

```powershell
python -m pip install -r backend/requirements.txt pyinstaller pillow pystray
Set-Location frontend
npm ci
npm run build
Set-Location ..
python -m PyInstaller --clean --noconfirm rookery.spec
```

빌드 결과는 `dist/Rookery.exe`입니다. 릴리스 워크플로가 이를 `Phrolova-<태그>-windows-x64.exe`로 이름을 바꿔 배포하며, FFmpeg는 포함하지 않습니다. `v*.*.*` 태그를 푸시하면 Windows 빌드 및 GitHub Release 게시 절차가 실행됩니다.

## 개발 및 검증

프론트엔드는 React·TypeScript·Vite·Tailwind CSS, 백엔드는 FastAPI·SQLite를 사용합니다. Streamlink, yt-dlp, FFmpeg가 스트림 처리와 미디어 저장을 담당합니다.

테스트 의존성은 `backend/requirements-dev.txt`에 있습니다. [CI 워크플로](.github/workflows/ci.yml)는 `main` 브랜치의 push와 pull request에서 백엔드 pytest, 프론트엔드 타입 검사와 빌드를 실행하도록 구성되어 있습니다. 기여 규칙과 검증 명령은 [CONTRIBUTING.md](CONTRIBUTING.md)를 확인하세요.

## 주의 사항 및 문제 해결

- **접근 제어:** 앱 자체에 사용자 계정이나 접속 인증이 없고 기본적으로 모든 네트워크 인터페이스에서 연결을 받습니다. 개인 PC에서만 쓸 경우 `HOST=127.0.0.1`을 지정할 수 있습니다. 서버에서는 방화벽 또는 인증을 갖춘 reverse proxy로 접근을 제한하세요.
- **녹화 파일 형식:** 라이브 녹화는 TS·MKV를 사용할 수 있습니다. MP4는 비정상 종료 시 파일 손상 가능성이 있으므로 녹화 환경에 맞게 선택하세요.
- **녹화 시작 실패:** 자동 녹화 상태, CHZZK 녹화 조건, 인증 정보와 FFmpeg 경로를 확인하고 **로그**에서 오류를 확인하세요.
- **다운로드 실패:** URL 지원 여부와 콘텐츠 공개 상태, 쿠키 유효성을 확인하세요. CHZZK VOD는 Naver CDN과 Akamai CDN을 번갈아 재시도하는 처리가 구현되어 있지만 모든 다운로드의 성공을 보장하지는 않습니다.
- **X Spaces 오류:** 쿠키 만료, API 요청 제한, 재생 목록 만료로 감지나 다운로드가 실패할 수 있습니다.
- **포트 충돌:** 기본 포트 8000을 사용하는 다른 앱 또는 기존 Phrolova 프로세스를 종료하거나 `PORT`를 변경하세요. Vite 개발 서버의 API 프록시는 기본 포트 8000을 기준으로 설정되어 있습니다.

문제 보고에는 앱 버전, 운영체제, 대상 서비스, 재현 절차와 관련 로그를 포함하세요. 쿠키·토큰·Webhook URL 등 인증 정보는 제거한 뒤 [Issues](https://github.com/ProofPage/Phrolova/issues)에 등록하세요.

## 라이선스 및 출처

Phrolova는 [MIT License](LICENSE)로 배포됩니다. 저장소의 라이선스에 명시된 저작권 표기는 **Copyright (c) 2026 Serian (github.com/eruminyu)**입니다. 원작자 정보는 [Serian](https://github.com/eruminyu)으로 보존하며, 현재 저장소는 [ProofPage/Phrolova](https://github.com/ProofPage/Phrolova)에서 관리합니다.

FFmpeg는 별도로 설치하며 해당 배포본의 라이선스를 따릅니다. 자세한 내용은 [FFmpeg 라이선스 안내](https://ffmpeg.org/legal.html)를 확인하세요. 포함된 Node.js의 라이선스 문서는 빌드 시 함께 수집됩니다.

Phrolova는 CHZZK·Naver·YouTube·X·Discord와 제휴하거나 이들의 승인을 받은 프로젝트가 아닙니다. 저장 권한이 있는 콘텐츠에 사용하고 각 서비스의 이용약관과 저작권을 준수하세요.
