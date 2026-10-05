# Phrolova

![Version](https://img.shields.io/badge/version-2.0.33-13d9a3)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=111827)
![License](https://img.shields.io/badge/license-MIT-64748B)

치지직·TwitCasting·YouTube 라이브 녹화와 X Spaces 오디오 저장, 다시보기 다운로드를 한곳에서 관리하는 셀프호스팅 미디어 아카이빙 도구입니다. Streamlink와 FFmpeg 기반 라이브 녹화, yt-dlp 기반 VOD 다운로드, 채팅 보관, 통계, 로그, Discord 알림을 웹 화면에서 제공합니다.

> Phrolova는 비공식 개인 프로젝트입니다. 각 플랫폼과 제휴하거나 승인받지 않았습니다. 이용자는 플랫폼 약관과 저작권을 준수해야 합니다.

## 주요 기능

### 라이브 녹화

- 치지직, TwitCasting, YouTube 채널 상태를 감시하고 방송이 시작되면 자동 녹화
- 채널별 자동 녹화 설정, 수동 시작·중지, 실패 후 자동 재시도
- 대시보드에서 치지직 자동 다운로드 조건 설정: 모든 라이브, 같이보기만, 같이보기 제외
- 채널 추가 전 설정 창과 기존 스트리머별 다운로드 설정 수정
- Streamlink로 라이브 스트림을 받고 FFmpeg로 파일에 기록
- 치지직 타임머신 스트림 선택, 시작 오프셋 및 화질 설정
- TS, MKV, MP4 포맷 선택과 라이브 파일명 템플릿
- 라이브 녹화와 채팅 로그 저장 경로 분리

TS와 MKV는 녹화가 예기치 않게 중단되어도 이미 받은 구간을 보존하기 쉽습니다. MP4는 호환성이 좋지만 라이브 녹화가 비정상 종료되면 파일이 재생되지 않을 수 있습니다.

같이보기 여부는 치지직의 공식 같이보기 정보와 방송 태그로 판단합니다. 공식 같이보기 방송은 일반 태그에 ‘같이보기’가 없어도 감지합니다. 추가로 지정할 같이보기 태그는 쉼표로 구분해 입력하며, 방송 태그 중 하나라도 일치하면 같이보기로 분류합니다. 스트리머별 설정에서 기본 조건을 따르거나 개별 조건을 지정할 수 있습니다. 공식 같이보기 여부를 확인하지 못하고 방송 태그도 읽을 수 없으면 조건 확인을 기다립니다. 변경한 조건은 다음 자동 시작부터 적용되며, 진행 중인 녹화와 수동 시작은 계속 사용할 수 있습니다.

### 다시보기와 클립 다운로드

- 치지직 VOD·클립 및 yt-dlp가 지원하는 외부 영상 URL 다운로드
- 다운로드 대기열, 동시 다운로드 수, 화질, 포맷, 속도 제한 설정
- 대기열 순서 변경, 일시정지, 재개, 취소, 재시도
- 완료 파일 위치 열기와 완료·오류 작업 정리
- 라이브와 다시보기 저장 위치 및 품질 설정 분리
- 필요할 때 FFmpeg로 영상·오디오 병합 및 포맷 처리

### 대시보드와 운영 도구

- 여러 플랫폼 채널의 방송 상태, 녹화 상태와 파일 정보를 한 화면에서 확인
- 카드·목록 보기, 검색, 상태·태그 필터, 채널 순서 변경
- 치지직 채팅 JSONL 저장 및 채팅 로그 검색
- 녹화 시간·용량, 최근 세션, 채널별 통계
- 실시간 시스템 로그, 알림 센터와 Discord 알림
- 다크 테마, 포인트 컬러, 브라우저 페이지 제목 등 외관 설정

### Discord 연동

- Webhook만으로 이벤트 알림 전송 또는 Discord Bot과 함께 사용
- 녹화 시작·종료·실패 및 다운로드 완료 알림
- 허용 사용자·채널을 지정하는 슬래시 명령
- Bot 연결이 끊겼을 때 Webhook 알림 폴백

## 지원 플랫폼

| 플랫폼 | 라이브 감시·녹화 | 다시보기·클립 | 필요한 설정 |
|---|:---:|:---:|---|
| 치지직 | ✅ | VOD·클립 다운로드 | 연령 제한·로그인 화질에는 네이버 쿠키 권장 |
| TwitCasting | ✅ | 과거 방송 조회·다운로드 | Client ID와 Client Secret |
| YouTube | ✅ | yt-dlp 지원 영상 | 기본 다운로드는 별도 인증 없이 사용 가능 |
| X Spaces | Space 감지·수동 캡처 | 오디오 다운로드 | Netscape 형식 X 쿠키 파일 |

플랫폼의 API, 로그인 정책, 미디어 형식은 변경될 수 있습니다. 따라서 일부 기능은 플랫폼 정책이나 서비스 변경에 따라 일시적으로 제한될 수 있습니다.

## 설치

### Windows

1. [최신 릴리즈](https://github.com/ProofPage/Phrolova/releases/latest)에서 `Phrolova-v*-windows-x64.exe`를 다운로드합니다.
2. 실행 파일을 열고 첫 실행 설정을 진행합니다.
3. 브라우저에서 `http://localhost:8000`에 접속합니다. 앱이 기본 브라우저를 자동으로 열 수도 있습니다.

첫 실행 시 라이브 저장 폴더와 다시보기 저장 폴더를 각각 지정합니다. 기본값은 `Downloads/Phrolova/Live`와 `Downloads/Phrolova/Video`입니다. 기존 저장 경로를 사용 중인 경우 설정에서 경로를 확인하세요.

라이브 녹화에는 FFmpeg가 필요합니다. 설치된 FFmpeg를 PATH에 추가하거나 설정에서 실행 파일 경로를 지정하세요. 앱 시작 시 Python 런타임, FFmpeg, Streamlink를 확인하고 yt-dlp가 없으면 다운로드를 시도합니다.

### Linux 및 macOS

저장소의 관리 스크립트로 설치 및 업데이트할 수 있습니다.

```bash
curl -fsSL https://raw.githubusercontent.com/ProofPage/Phrolova/main/scripts/manage.sh | bash
```

설치가 끝나면 `rookery` 명령으로 서비스를 관리합니다.

```bash
rookery status
rookery start
rookery stop
rookery restart
rookery logs
rookery update
rookery --help
```

기본 설치 위치는 `~/rookery`입니다. 필요하면 `INSTALL_DIR`로 바꿀 수 있습니다.

```bash
INSTALL_DIR=/opt/rookery curl -fsSL https://raw.githubusercontent.com/ProofPage/Phrolova/main/scripts/manage.sh | bash
```

관리 스크립트와 수동 설치 방법은 [Linux 설치 가이드](docs/linux-guide.md)를 참고하세요. systemd 서비스 등록은 systemd를 사용하는 Linux 환경에서만 제공됩니다.

## 소스에서 실행

### 요구 사항

- Python 3.12 이상
- Node.js 20 이상
- FFmpeg 6 이상
- Windows, Linux 또는 macOS

Streamlink와 yt-dlp를 비롯한 Python 의존성은 `backend/requirements.txt`에서 설치합니다.

### 설치 및 실행

```bash
git clone https://github.com/ProofPage/Phrolova.git
cd Phrolova
python -m venv backend/.venv
```

Windows PowerShell:

```powershell
backend\.venv\Scripts\python -m pip install -r backend\requirements.txt
cd frontend
npm ci
npm run build
cd ..
backend\.venv\Scripts\python -m uvicorn app.main:app --app-dir backend
```

Linux 또는 macOS:

```bash
backend/.venv/bin/python -m pip install -r backend/requirements.txt
cd frontend
npm ci
npm run build
cd ..
backend/.venv/bin/python -m uvicorn app.main:app --app-dir backend
```

브라우저에서 `http://localhost:8000`을 엽니다. 개발 중에는 별도 터미널에서 `npm run dev`를 실행할 수 있으며, 프런트엔드 개발 서버는 `http://localhost:3000`을 사용합니다.

## 설정과 저장 데이터

대부분의 설정은 웹 화면에서 변경할 수 있습니다. `.env`를 직접 관리하는 경우 프로젝트 루트에 다음처럼 지정합니다.

```dotenv
PORT=8000
FFMPEG_PATH=ffmpeg
DOWNLOAD_DIR=./recordings
LIVE_DOWNLOAD_DIR=./recordings/live
VOD_DOWNLOAD_DIR=./recordings/video
LIVE_FORMAT=ts
RECORDING_QUALITY=best
VOD_FORMAT=mp4
VOD_DEFAULT_QUALITY=best
MONITOR_INTERVAL=60
```

- `LIVE_DOWNLOAD_DIR`: 라이브 녹화와 채팅 로그
- `VOD_DOWNLOAD_DIR`: 다시보기, 클립, 외부 영상
- `FFMPEG_PATH`: FFmpeg 실행 파일 또는 PATH에서 찾을 실행 파일 이름
- `RECORDING_QUALITY`: 라이브 기본 품질
- `VOD_DEFAULT_QUALITY`: 다시보기 기본 품질

실행 파일 배포판은 `.env`와 영속 `data/`를 실행 파일 옆에 둡니다. 소스 실행은 프로젝트의 `.env`와 `backend/data/`를 사용합니다. 녹화 파일 위치는 각 저장 경로 설정에 따라 달라집니다. 자세한 내용은 [저장소와 데이터 안내](docs/storage.md)를 참고하세요.

## 인증과 계정 정보

- 치지직: 설정 → 인증에서 `NID_AUT`, `NID_SES`를 등록합니다. 로그인 전용 방송이나 화질 접근에 필요할 수 있습니다.
- TwitCasting: [개발자 페이지](https://twitcasting.tv/developer.php)에서 앱을 등록하고 Client ID와 Client Secret을 입력합니다.
- X Spaces: 로그인한 브라우저에서 Netscape 형식 쿠키 파일을 내보내 설정에 등록합니다. 상세 내용은 [X Spaces 가이드](docs/x-spaces-guide.md)를 참고하세요.
- Discord: Bot 토큰과 알림 채널 ID 또는 Webhook URL을 설정합니다. 알림만 필요하면 Webhook만 사용할 수 있습니다.

쿠키와 토큰은 계정 접근 정보입니다. `.env`와 쿠키 파일을 외부에 공유하지 말고, 만료되거나 노출된 인증 정보는 플랫폼에서 갱신하세요.

## 문제 해결

<details>
<summary>FFmpeg를 찾지 못한다는 메시지가 나옵니다.</summary>

FFmpeg를 설치한 뒤 PATH에 추가하거나 설정 화면에서 실행 파일 경로를 지정하세요. 재시작 후 시스템 정보 화면에서 경로를 확인할 수 있습니다.
</details>

<details>
<summary>Streamlink가 없거나 라이브 녹화가 시작되지 않습니다.</summary>

최신 Phrolova 실행 파일을 사용 중인지 확인하세요. 소스 실행에서는 `backend/requirements.txt`의 패키지를 설치해야 합니다. 라이브 수신은 Streamlink를 사용하고 파일 기록은 FFmpeg가 담당합니다.
</details>

<details>
<summary>치지직의 성인 방송이나 고화질 영상이 작동하지 않습니다.</summary>

설정 → 인증에서 현재 유효한 네이버 쿠키를 저장하세요. 로그인 쿠키는 만료될 수 있으므로 필요하면 새로 발급해야 합니다.
</details>

<details>
<summary>Discord 알림이나 명령이 오지 않습니다.</summary>

알림 설정에서 Webhook URL 또는 Bot 토큰과 채널 ID를 확인하세요. Bot 명령은 허용 사용자·채널 설정과 슬래시 명령 등록 상태도 확인해야 합니다.
</details>

## 개발 및 기여

- [변경 이력](docs/CHANGELOG.md)
- [Linux 설치 가이드](docs/linux-guide.md)
- [X Spaces 가이드](docs/x-spaces-guide.md)
- [테스트 가이드](docs/test-guide.md)
- [기여 가이드](CONTRIBUTING.md)
- [이슈 및 기능 제안](https://github.com/ProofPage/Phrolova/issues)

## 라이선스와 고지

Phrolova는 [MIT License](LICENSE)로 배포됩니다. FFmpeg는 별도로 설치되며 Phrolova에 포함되지 않습니다. FFmpeg의 빌드와 배포에 적용되는 조건은 [FFmpeg 법률 안내](https://ffmpeg.org/legal.html)를 확인하세요.

플랫폼 이름과 로고는 각 소유자의 상표입니다. Phrolova는 네이버·치지직, TwitCasting, YouTube, X 또는 Discord와 제휴·후원·승인 관계가 없는 비공식 도구입니다. 다운로드한 콘텐츠의 보관과 이용에 관한 책임은 사용자에게 있습니다.
