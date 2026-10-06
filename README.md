<div align="center">

# Phrolova

**라이브 녹화와 다시보기 다운로드를 한곳에서 관리하세요.**

[![Version](https://img.shields.io/badge/version-2.0.41-438dff)](https://github.com/ProofPage/Phrolova/releases/latest)
[![Windows](https://img.shields.io/badge/Windows-x64-0078D4)](https://github.com/ProofPage/Phrolova/releases/latest)
![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=111827)
[![License](https://img.shields.io/badge/License-MIT-64748B)](LICENSE)

[다운로드](https://github.com/ProofPage/Phrolova/releases/latest) · [변경 이력](docs/CHANGELOG.md) · [문제 신고](https://github.com/ProofPage/Phrolova/issues)

</div>

Phrolova는 치지직·TwitCasting·YouTube 라이브 녹화, X Spaces 오디오 저장, 다시보기·클립 다운로드를 관리하는 웹 기반 아카이빙 도구입니다. 내 컴퓨터나 서버에서 실행하고 브라우저로 채널, 다운로드, 로그와 통계를 확인합니다.

라이브는 **Streamlink와 FFmpeg**, 다시보기는 **yt-dlp와 FFmpeg**를 사용합니다.

## 목차

- [빠른 시작](#빠른-시작)
- [주요 기능](#주요-기능)
- [지원 플랫폼](#지원-플랫폼)
- [같이보기 다운로드 조건](#같이보기-다운로드-조건)
- [설정과 저장 데이터](#설정과-저장-데이터)
- [소스에서 실행](#소스에서-실행)
- [문제 해결](#문제-해결)

## 빠른 시작

### Windows 실행 파일

1. [최신 릴리즈](https://github.com/ProofPage/Phrolova/releases/latest)에서 `Phrolova-v*-windows-x64.exe`를 받습니다.
2. 실행 파일을 저장할 폴더에 넣고 실행합니다.
3. 시작 콘솔의 의존성 안내를 확인하고, 필요한 경우 FFmpeg를 설치하거나 경로를 지정합니다.
4. 브라우저에서 `http://localhost:8000`을 열고 첫 실행 설정을 완료합니다.
5. 라이브 대시보드에서 채널을 추가하거나, 다시보기 다운로드 화면에 영상 주소를 입력합니다.

실행 파일에는 Python 런타임과 Streamlink가 포함됩니다. **FFmpeg는 별도로 설치해야 합니다.** yt-dlp 실행 파일이 없으면 시작 시 자동 다운로드를 시도합니다.

기본 저장 위치는 사용자 다운로드 폴더 아래입니다.

| 용도 | 기본 폴더 |
|---|---|
| 라이브 녹화·채팅 로그 | `Downloads\Phrolova\Live` |
| 다시보기·클립·외부 영상 | `Downloads\Phrolova\Video` |

업데이트할 때는 앱을 종료하고 실행 파일을 교체하세요. 기존 `.env`, `data/`와 저장 폴더를 유지하면 설정과 이력을 이어서 사용할 수 있습니다.

### Linux · macOS

관리 스크립트로 설치와 업데이트를 진행할 수 있습니다.

```bash
curl -fsSL https://raw.githubusercontent.com/ProofPage/Phrolova/main/scripts/manage.sh | bash
```

설치 후에는 `rookery` 명령을 사용합니다. 기본 설치 폴더는 `~/rookery`입니다.

```bash
rookery status
rookery start
rookery stop
rookery logs
rookery update
```

기존 설치와의 호환을 위해 관리 명령과 일부 내부 파일에는 `rookery` 이름이 남아 있습니다. 자세한 설치 방법은 [Linux 설치 가이드](docs/linux-guide.md)를 참고하세요. systemd 서비스 등록은 systemd를 사용하는 Linux 환경에서 제공됩니다.

## 주요 기능

| 기능 | 설명 |
|---|---|
| 라이브 감시·녹화 | 방송 상태 감시, 채널별 자동 녹화, 수동 시작·중지, 실패 후 재시도 |
| 채널별 다운로드 설정 | 채널 추가 전 설정 창, 기존 채널 수정, 기본 조건 상속 또는 개별 조건 지정 |
| 치지직 같이보기 조건 | 모든 라이브, 같이보기만, 같이보기 제외 선택 |
| 타임머신·파일 설정 | 치지직 스트림 획득 방식, 시작 오프셋, 품질, 포맷, 파일명 템플릿 |
| 다시보기 다운로드 | 치지직 다시보기·클립과 yt-dlp 지원 외부 영상, 품질·포맷·속도 제한 |
| 다운로드 대기열 | 순서 변경, 일시정지·재개, 취소·재시도, 작업 정리 |
| 채팅 보관 | 치지직 채팅 JSONL 저장과 기록 검색 |
| 상태·통계·로그 | 카드·목록 보기, 상태·채널 태그 필터, 녹화 이력, 용량, 실시간 로그 |
| Discord 알림 | Webhook 또는 Bot으로 이벤트 알림, 허용 사용자·채널 기반 명령 |
| 화면 설정 | 다크 테마, 포인트 컬러, 브라우저 제목 설정 |

라이브와 다시보기의 **저장 경로와 품질은 각각 설정**할 수 있습니다. 라이브 포맷은 TS·MKV·MP4를 선택할 수 있으며, 녹화 안정성을 우선하면 TS를 권장합니다.

## 지원 플랫폼

| 플랫폼 | 지원 범위 | 인증·설정 |
|---|---|---|
| 치지직 | 라이브 감시·녹화, 같이보기 조건, 다시보기·클립, 채팅 보관 | 로그인·연령 제한 콘텐츠 접근에 네이버 쿠키가 필요할 수 있음 |
| TwitCasting | 라이브 감시·녹화, 과거 방송 조회·다운로드 | Client ID와 Client Secret |
| YouTube | 라이브 감시·녹화, yt-dlp 지원 영상 다운로드 | 콘텐츠에 따라 로그인이나 추가 인증이 필요할 수 있음 |
| X Spaces | Space 감지·수동 캡처, 오디오 저장 | Netscape 형식 X 쿠키 파일 |

플랫폼 API, 로그인 정책과 영상 제공 방식에 따라 이용 가능한 기능이 달라질 수 있습니다.

## 같이보기 다운로드 조건

치지직 채널의 자동 다운로드에 적용됩니다. 대시보드에서 기본값을 정하고, 채널의 **다운로드 설정**에서 개별 조건을 지정할 수 있습니다. 개별 설정이 기본값보다 우선합니다.

| 조건 | 동작 | 태그 입력 |
|---|---|---|
| 모든 라이브 다운로드 | 방송이 시작되면 자동 다운로드 | 필요 없음 |
| 같이보기만 다운로드 | 지정한 같이보기 태그에 맞는 방송만 자동 다운로드 | 필요 |
| 같이보기 제외하고 다운로드 | 같이보기 방송을 제외하고 자동 다운로드 | 필요 없음 |

같이보기 여부는 치지직의 **공식 같이보기 정보와 방송 태그**로 판단합니다. 화면에 같이보기로 표시되는 방송은 일반 태그에 해당 문구가 없어도 공식 같이보기 정보로 감지합니다.

- `같이보기`: 전체 같이보기 방송을 선택합니다.
- `신세기에반게리온` 등 콘텐츠 태그: 해당 태그에 맞는 방송을 선택합니다.
- 여러 태그는 쉼표로 구분하며, 하나라도 일치하면 선택합니다. 태그는 공백·대소문자를 정리한 뒤 정확히 비교합니다.
- 판단에 필요한 정보를 확인하지 못하면 확인을 기다립니다.

조건에 맞지 않으면 카드와 목록에 이유를 표시합니다. 자동 녹화가 켜져 있으면 **다운로드 보류**, 꺼져 있으면 **다운로드 조건 안내**로 표시합니다.

조건 변경은 다음 자동 시작부터 적용됩니다. 진행 중인 녹화를 강제로 중지하지 않으며, **수동 녹화 시작은 조건과 관계없이 사용할 수 있습니다.** 자동 녹화를 끄면 자동 다운로드는 시작하지 않습니다.

## 설정과 저장 데이터

대부분의 설정은 웹 화면에서 변경할 수 있습니다.

| 항목 | 위치·역할 |
|---|---|
| 일반 설정 | 라이브·다시보기 경로, 감시 주기, 녹화 포맷, 다시보기 품질 |
| 라이브 다운로드 설정 | 라이브 품질, 재시도, 타임머신, 파일명 형식 |
| 인증 | 네이버 쿠키, TwitCasting 인증, X 쿠키 |
| 알림 | Discord Bot·Webhook과 이벤트 설정 |
| 프로그램 정보 | 앱·의존성 버전과 저장소 정보 |

### 저장 위치와 백업

| 실행 방식 | 설정 | 채널·다운로드·녹화 이력 |
|---|---|---|
| Windows 실행 파일 | 실행 파일 옆 `.env` | 실행 파일 옆 `data/rookery.db` |
| 소스 실행 | 프로젝트 루트 `.env` | `backend/data/rookery.db` |

녹화 파일은 별도로 지정한 저장 경로에 보관됩니다. 앱을 정상 종료한 후 `.env`, `data/`와 녹화 폴더를 백업하세요. 자세한 구조는 [저장 데이터 안내](docs/storage.md)를 참고하세요.

### 직접 설정하는 경우

프로젝트 루트의 `.env` 예시입니다.

```dotenv
PORT=8000
FFMPEG_PATH=ffmpeg
LIVE_DOWNLOAD_DIR=./recordings/live
VOD_DOWNLOAD_DIR=./recordings/video
LIVE_FORMAT=ts
RECORDING_QUALITY=best
VOD_FORMAT=mp4
VOD_DEFAULT_QUALITY=best
MONITOR_INTERVAL=60
LIVE_DOWNLOAD_CONDITION=all
WATCHALONG_TAGS=같이보기
```

치지직 인증은 설정 화면에서 `NID_AUT`, `NID_SES`를 등록합니다. TwitCasting 인증은 [개발자 페이지](https://twitcasting.tv/developer.php), X 쿠키는 [X Spaces 가이드](docs/x-spaces-guide.md)를 참고하세요. 쿠키·토큰·`.env`는 공개 저장소나 이슈에 첨부하지 마세요.

## 소스에서 실행

Python 3.12 이상, Node.js 20 이상, FFmpeg를 준비합니다. Python 패키지는 `backend/requirements.txt`로 설치합니다.

```bash
git clone https://github.com/ProofPage/Phrolova.git
cd Phrolova
python -m venv backend/.venv
```

**Windows PowerShell**

```powershell
backend\.venv\Scripts\python -m pip install -r backend\requirements.txt
cd frontend
npm ci
npm run build
cd ..
backend\.venv\Scripts\python -m uvicorn app.main:app --app-dir backend
```

**Linux · macOS**

```bash
backend/.venv/bin/python -m pip install -r backend/requirements.txt
cd frontend
npm ci
npm run build
cd ..
backend/.venv/bin/python -m uvicorn app.main:app --app-dir backend
```

서버는 `http://localhost:8000`에서 확인합니다. 프런트엔드 개발 시 `frontend` 폴더의 별도 터미널에서 `npm run dev`를 실행하면 `http://localhost:3000`을 사용할 수 있습니다.

## 문제 해결

<details>
<summary><strong>라이브인데 자동 다운로드가 시작되지 않습니다.</strong></summary>

자동 녹화 스위치, 채널별 다운로드 조건과 화면의 보류 이유를 확인하세요. 같이보기만 선택했다면 입력한 콘텐츠 태그를 확인합니다. 기본 조건을 바꿔도 채널별 개별 조건이 우선합니다. 자세한 오류는 로그 화면에서 확인할 수 있습니다.

</details>

<details>
<summary><strong>FFmpeg를 찾지 못하거나 Streamlink가 표시되지 않습니다.</strong></summary>

FFmpeg를 설치한 후 PATH에 추가하거나 설정에서 실행 파일 경로를 지정하세요. Windows에서는 최신 Phrolova 실행 파일을 사용하고, 소스 실행에서는 `backend/requirements.txt`를 설치합니다. 프로그램 정보에서 의존성 버전을 확인할 수 있습니다.

</details>

<details>
<summary><strong>로그인·연령 제한 콘텐츠나 일부 품질에 접근할 수 없습니다.</strong></summary>

해당 플랫폼에 필요한 인증 정보를 등록하세요. 치지직은 현재 유효한 네이버 쿠키가 필요할 수 있습니다. 쿠키가 만료됐다면 설정에서 갱신합니다.

</details>

<details>
<summary><strong>Discord 알림이나 명령이 작동하지 않습니다.</strong></summary>

Webhook URL 또는 Bot 토큰·채널 ID를 확인하세요. Bot 명령은 허용 사용자·채널 설정과 슬래시 명령 등록 상태도 확인합니다. 알림만 필요하면 Webhook으로 사용할 수 있습니다.

</details>

## 문서와 기여

[변경 이력](docs/CHANGELOG.md) · [Linux 설치](docs/linux-guide.md) · [X Spaces](docs/x-spaces-guide.md) · [저장 데이터](docs/storage.md) · [테스트 가이드](docs/test-guide.md) · [기여 가이드](CONTRIBUTING.md)

문제 신고 시 앱 버전, 사용 플랫폼, 재현 순서와 인증 정보를 제거한 로그를 [이슈](https://github.com/ProofPage/Phrolova/issues)에 첨부해 주세요.

## 라이선스

[MIT License](LICENSE)로 배포됩니다. FFmpeg는 포함되지 않으며 별도로 설치합니다. FFmpeg의 배포 조건은 [법률 안내](https://ffmpeg.org/legal.html)를 참고하세요.

Phrolova는 비공식 프로젝트이며 네이버·치지직, TwitCasting, YouTube, X, Discord와 제휴하거나 승인받지 않았습니다. 콘텐츠 보관과 이용 시 해당 플랫폼의 약관과 저작권을 준수해 주세요.
