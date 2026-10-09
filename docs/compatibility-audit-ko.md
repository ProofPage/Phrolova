# Phrolova Linux 및 Android Termux 호환성 검수

검수 기준: `ProofPage/Phrolova`, 원본 커밋 `57c17e82984866db5328fd702f82bcbdbf827e4b`, 2026-10-09. Linux/Termux 수정본과 후속 종료 보완을 함께 기록합니다. 릴리스 바이너리 배포는 이번 작업 범위에 포함하지 않습니다. 실제 검수 호스트는 Ubuntu 24.04.3 x86_64 컨테이너, Python 3.12.14, Node 24.19.0, FFmpeg/FFprobe 6.1.1입니다.

## 1. 환경별 지원 판정

| 환경 | 원본 분석 | 수정 후 판정 | 실제 실행 근거 및 제한 |
| --- | --- | --- | --- |
| Ubuntu/Debian x86_64 | 수정 필요 | **조건부 지원** | Ubuntu 24.04에서 의존성 설치·서버·로컬 영상 다운로드·Streamlink HLS 수신·FFmpeg 저장·SSE 최초 응답·종료·재시작 검증. Debian 실제 실행, 외부 방송·장시간 운영·systemd 부팅은 미검증 |
| Ubuntu/Debian ARM64 | 조건부 지원 가능성 | **미검증** | CPython 3.12 manylinux2014_aarch64 의존성 wheel 전체 다운로드 성공. ARM64에서 설치·서버·FFmpeg 실행을 했다는 의미는 아님 |
| Android Termux Native aarch64, 비루팅 | 수정 필요 | **조건부 지원** | 사용자 단말 설치·pip check·프론트엔드 빌드·웹 UI·치지직 자동 녹화·Ctrl+C 정상 종료·재시작 후 채널 유지·파일 재생 확인. 추가 기능은 사용자 검증 보고이며 상세 로그 미수집 |
| Termux proot Ubuntu/Debian | 조건부 지원 가능성 | **미검증** | glibc 환경을 사용하는 별도 실행 방식. Python 3.12+ 및 배포판 FFmpeg 필요. Native 설치나 Android 절전 해소와 동일시하지 않음 |

현재 네 환경 모두 핵심 기능이 장시간 안정적으로 동작한다고 인증할 근거는 부족합니다. 특히 Ubuntu의 성공을 Debian·ARM64·Android의 성공으로 확대하지 않았습니다.

### 후속 실기기 검증 (2026-10-09)

사용자가 제공한 Native Termux 로그에서 pydantic-core 소스 설치를 포함한 의존성 설치 및 pip check, 웹 UI 빌드와 API 200 응답, 시스템 FFmpeg/yt-dlp 및 Streamlink 8.6.2 탐지, 치지직 방송 감지와 HLS 녹화 시작을 확인했습니다. 재시작 후 등록 채널 1개가 복원되었고 기존 파일과 충돌할 때 `(2)` 파일명으로 저장되었습니다. 사용자가 녹화 파일의 재생 성공을 확인했습니다.

후속 종료 보완은 POSIX FFmpeg를 별도 세션에서 시작하고 SSE가 서버 종료 요청을 감지하도록 합니다. 서버 진입 경로를 재사용하고 연결 종료 유예를 10초로 제한했습니다. 단말 로그에서는 Ctrl+C 후 녹화 완료 처리, DB 종료, Application shutdown complete 및 Finished server process까지 약 1초 안에 도달했습니다. 종료 요청 직후의 Streamlink EOF 경고는 이후 정상 완료 로그와 구분해야 합니다.

사용자는 추가 VOD·YouTube·X Spaces 및 장시간 백그라운드 검증도 완료했다고 보고했습니다. 이 항목들은 사용자 확인으로 기록하며, 상세 조건·길이·성공 로그가 없는 상태에서 자동화 검증 결과로 취급하지 않습니다. 아래 기능별 표의 외부 서비스 미검증 표기는 검수 컨테이너에서 수행한 검사 범위입니다.

후속 Linux 회귀 결과는 **354 passed, 29 skipped, 2 warnings**입니다. GitHub 반영 전 재실행에서도 동일한 통과 수를 확인했고 TypeScript 검사 및 프론트엔드 빌드가 성공했습니다. 테스트 종료 시 MagicMock stderr의 await 처리에서 수거되지 않은 태스크 예외가 출력되었습니다. 테스트 종료 코드는 0이지만 이 모의 프로세스 경고를 무경고 검증으로 취급하지 않습니다. SSE 연결을 유지한 종료 및 프로세스 그룹 신호 검사도 성공했습니다. ARM64 GNU/Linux, proot 및 Windows 실환경 실행은 여전히 미검증입니다.

## 2. 발견된 문제

| 심각도 | 파일·관련 함수 | 실제 원인 및 영향 플랫폼 | 처리 |
| --- | --- | --- | --- |
| 높음 | `scripts/manage.sh: ensure_python`, `backend/run.py: _check_python_version` | 설치는 3.10 허용, 실행/CI 기준은 3.12. Python 3.11 기본 Debian 설치에서 요구사항 불일치 | 최소 3.12 통일, 실행 초기에 검사 |
| 높음 | `scripts/manage.sh: ensure_python` | Debian/Ubuntu 분기에서 Ubuntu PPA를 공통 추가 | 자동 PPA 추가 제거, 명확한 버전 준비 오류 |
| 높음 | `backend/run.py: _download_ytdlp`, `_run_dependency_check` | `--desktop` 사용 시 Linux에서도 Windows yt-dlp.exe 다운로드 및 PowerShell FFmpeg 설치 안내 진입 가능 | Windows만 데스크톱/자동 바이너리 설치, POSIX 헤드리스 |
| 높음 | `backend/app/core/config.py: resolve_ytdlp_path`, `resolve_ffmpeg_path`; `backend/run.py: _find_*` | POSIX에서도 bin의 .exe 선택, 파일 존재만 확인하고 실행 권한 미검사 | 플랫폼별 후보와 POSIX X_OK 검사 |
| 높음 | `backend/requirements.txt` | `uvicorn[standard]`의 uvloop/httptools/watchfiles 네이티브 빌드가 Android에 추가 설치 장벽 | 공통 의존성 재사용, Native에 기본 uvicorn 제공. 서버 기능·SSE 유지 |
| 높음 | `backend/app/core/config.py: Settings.host`, `.env.example` | 인증 없는 API가 기본 0.0.0.0에서 노출됨. 다운로드·서버 파일 탐색·설정 쓰기 API 존재 | 새 기본값 127.0.0.1. 기존 HOST는 유지. 외부 인증은 여전히 별도 필요 |
| 높음 | `backend/app/engine/vod.py: _download_x_spaces_replay`, `cancel_download` | 취소 플래그가 직접 FFmpeg 프로세스에 전달되지 않음. Linux/Windows/Android 공통 | 프로세스 추적, terminate 및 10초 후 kill, 대기/정리 |
| 높음 | `backend/app/main.py: lifespan`, `VodEngine` | 종료 시 VOD 작업을 정리하기 전에 DB가 닫히고 yt-dlp 워커는 계속될 수 있음 | VOD shutdown 추가, 협력 취소 및 작업 완료 대기 후 DB 종료. 네트워크 재시도로 종료 지연 가능 |
| 높음 | `backend/app/engine/vod.py: download`, `_save_history`, `_load_history` | 완료/오류 작업만 저장하여 대기/진행 중 작업이 강제 종료 후 사라짐 | 작업 생성/실행 때 저장, 중단 작업을 오류로 복원하여 수동 재시도. 자동 바이트 단위 재개는 추가되지 않음 |
| 높음 | `backend/app/store/repositories.py: VodRepository.replace_all` | 전체 이력 삭제 후 개별 INSERT. 중간 실패하면 기존 이력 손실 위험 | 먼저 upsert 후 불필요한 행 제거. 중간 실패에는 기존 행이 남도록 변경. 전체 일괄 쓰기가 하나의 원자 트랜잭션이 된 것은 아님 |
| 높음 | `backend/app/core/utils.py: clean_filename` | 150자 한글 제목은 UTF-8 450바이트가 되어 POSIX 파일명 제한 초과. 긴 파일명 재정제에서 확장자 소실 가능 | POSIX 240바이트 제한, UTF-8 문자 경계 보존, 주요 미디어 확장자 보존 |
| 중간 | `backend/app/engine/youtube.py: _check_via_ytdlp`; `pipeline/ytdlp.py: _extract_hls_url` | CLI 경로에 Python VOD와 달리 Node/Deno runtime 설정이 전달되지 않음. Node만 설치한 YouTube 처리 제한 | 공통 runtime 탐색을 CLI 인자로 재사용 |
| 중간 | 위 두 subprocess 함수 | 메타데이터 조회 무기한 대기/취소 시 자식 프로세스 잔류 가능 | 30/60초 제한, timeout/cancel 시 kill 및 communicate로 회수 |
| 중간 | `scripts/manage.sh: cmd_start`, `cmd_stop` | python run.py로 시작했지만 uvicorn 명령 패턴으로 종료 탐색. 다른 앱 매칭 위험 | 설치본 PID와 cwd/cmdline 확인 후 해당 프로세스에만 SIGTERM |
| 중간 | `scripts/manage.sh: detect_os`, `service_install` | Native의 비표준 파일시스템과 proot의 비실행 systemd 구분 부족 | Native 전용 스크립트 안내, 실제 systemd 런타임 검사 |
| 중간 | `backend/app/engine/vod.py: open_file_location` | headless Linux/Native에서 xdg-open 실패 또는 실패 종료코드를 성공으로 보고 | headless에서는 경로 반환, Linux GUI는 종료코드/timeout 확인 |
| 중간 | `backend/app/api/system.py: _detect_environment`, `frontend/src/components/ui/UpdateModal.tsx` | 모든 소스 실행을 linux-native로 분류하여 Termux에도 rookery/일반 Linux 설치 안내 | Native/proot/Windows 소스/macOS 분류 추가 및 환경별 문서 안내. proot은 명시적 환경 마커 사용 |
| 낮음 | `.env.example`, `docs/linux-guide.md` | OUTPUT_FORMAT은 설정 모델에서 무시, 잘못된 cd Rookery와 불필요한 dist 복사 단계 | LIVE_FORMAT 사용, 실제 저장소/빌드 출력에 맞게 문서 수정 |
| 운영 제한 | `api/settings/general.py: browse_dirs` | 루트 접근 불가능 디렉터리는 건너뛰거나 빈 목록을 반환. 공유 저장소 권한은 Android가 결정 | 내부 HOME 권장 및 절대경로 안내. 권한 상승이나 사용자 데이터 초기화 없음 |
| 운영 제한 | `engine/vod.py`, `engine/youtube_channel.py` | yt-dlp 워커 스레드는 강제 중지할 수 없고 진행 hook 이전 네트워크/후처리 지연 발생 가능 | 협력 취소 유지. 종료 시간이 즉시 또는 일정 시간 이내라고 보장하지 않음 |
| 운영 제한 | 웹 API 전반 | CHZZK/YouTube/X 로그인 쿠키 및 Discord 인증은 웹 관리 화면 인증이 아님 | 외부 공개 전에 인증 프록시/VPN 필요. 웹 인증 구현은 이번 변경 범위에서 추가하지 않음 |

### 전체 소스 확인 범위

`backend/run.py`, `requirements*`, `app/main.py`, `core/`, `services/`(Discord 포함), `engine/`(CHZZK, YouTube, X Spaces, pipeline, VOD, updater), `api/`, `store/`, `frontend/src`, Vite/TS/npm 설정, `scripts/`, `.env.example`, PyInstaller 사양과 CI/release 워크플로를 조사했습니다. 173개 기존 주요 소스·설정·문서 파일의 해시와 Python import 목록은 `audit-evidence/source-inventory.json`에 있습니다. 이 목록은 파일 범위 증거이며 모든 분기가 실행되었다는 증거는 아닙니다.

Windows CREATE_NO_WINDOW 및 이벤트 루프 정책은 OS 분기가 되어 있고 Path/subprocess 인자 목록 기반 실행이 대부분입니다. PowerShell/.bat/PyInstaller Windows 릴리스 경로는 유지했습니다. updater는 GitHub 릴리스 확인/알림만 하며 Linux에서 EXE를 교체하는 자동 업데이트가 아닙니다. 웹 UI 업데이트 모달은 환경별 절차를 안내합니다.

### Python 의존성 결과

검수 시 설치된 버전과 배포 메타데이터의 Requires-Python을 직접 읽었습니다. 표의 Python 최소값은 해당 **패키지 버전**의 값이며 Phrolova 전체 지원 최소 버전은 3.12입니다. 3.13/3.14 실행은 미검증이고 무제한으로 향후 버전을 지원한다고 판정하지 않습니다. 대부분의 프로젝트 의존성은 버전이 고정되지 않아 이후 설치 결과가 달라질 수 있습니다.

| 패키지 | 설치 버전 | 패키지 Python 최소 | Native Termux 검토 |
| --- | --- | --- | --- |
| fastapi | 0.143.0 | 3.10 | 본체 pure Python, Pydantic/Rust 의존 |
| uvicorn | 0.54.0 | 3.10 | 기본 h11/click 사용 가능. standard는 uvloop(C/libuv), httptools(C), watchfiles(Rust) 등 추가 |
| python-multipart | 0.0.32 | 3.10 | pure Python |
| httpx | 0.28.1 | 3.8 | pure Python, SOCKS 추가 의존 socksio도 pure Python |
| aiofiles | 25.1.0 | 3.9 | pure Python/스레드 기반 파일 I/O |
| yt-dlp[default] | 2026.8.19 | 3.10 | 본체 pure Python. 기본 extras의 Brotli, pycryptodomex 등은 C 빌드 필요 가능. yt-dlp-ejs 0.8.0 포함 |
| streamlink | 8.6.2 | 3.10 | 본체 Python. lxml 및 pycryptodome C 의존, libxml2/libxslt 필요 가능 |
| ffmpeg-python | 0.2.0 | 메타데이터 명시 없음 | Python 래퍼. FFmpeg/FFprobe 네이티브 실행 파일 별도 필수 |
| python-dotenv | 1.2.4 | 3.10 | pure Python |
| pydantic-settings | 2.15.0 | 3.10 | Pydantic 및 pydantic-core Rust 의존 |
| chzzkpy | 2.2.0 | 3.10 | 패키지는 Python. aiohttp 3.12.13, pydantic 2.13.3/core 2.46.3, frozenlist 1.5.0, multidict 6.1.0, yarl 1.18.3 등을 정확한 버전으로 요구 |
| discord.py | 2.7.1 | 3.8 | aiohttp 의존. 3.13+에서는 audioop-lts 필요. 사용하지 않는 voice extras를 추가하지 않음 |

Android wheel만 허용한 requirements 해석은 lxml 등 호환 배포물이 없어 실패했습니다. `pydantic-core==2.46.3`의 Android 지정 태그 검사도 `No matching distribution found`입니다. glibc manylinux ARM64 wheel은 Android/Bionic에 그대로 쓸 수 없습니다. 이 검사는 지정 태그/인덱스에서의 wheel 가용성 검사이며 모든 Android ABI나 소스 빌드 불가능을 증명하지는 않습니다.

Native 대안은 필수 기능을 그대로 유지하고 Clang/Rust/maturin 및 라이브러리로 소스 빌드하는 방법입니다. 추가 스크립트는 빌드 도구를 준비하지만 해당 조합을 기기에서 성공시킨 것은 아닙니다. 실패 로그에 따라 빌드 의존성을 추가하거나 glibc proot 환경을 사용하세요. pydantic/chzzkpy를 임의로 제거하거나 --no-deps로 숨기지 않았습니다.

## 3. 적용한 수정

- 실행/설정: `backend/run.py`, `backend/app/core/config.py`, `.env.example`.
- 파일명: `backend/app/core/utils.py`.
- 녹화/YouTube: `backend/app/engine/youtube.py`, `youtube_support.py`, `pipeline/ytdlp.py`.
- VOD·종료·저장: `backend/app/engine/vod.py`, `backend/app/main.py`, `backend/app/store/repositories.py`.
- 환경별 UI: `backend/app/api/system.py`, `frontend/src/api/client.ts`, `frontend/src/components/ui/UpdateModal.tsx`.
- 설치: `backend/requirements.txt`, 새 `requirements-common.txt`, 새 `requirements-termux.txt`, `scripts/manage.sh`, 새 `scripts/install-termux.sh`.
- 문서: `README.md`, `docs/linux-guide.md`, 새 `docs/termux-guide.md`, 본 보고서.
- 검증: `backend/tests/test_config.py`, `test_youtube_engine.py`, 새 `test_posix_support.py`, 새 `scripts/audit-posix.py`, `audit-evidence/`.

Windows의 standard 의존성, .exe 배포 경로, PowerShell FFmpeg 자동 설치, Windows 프로세스 처리와 기존 API 경로는 유지했습니다. 환경 문자열만 지원 분류를 추가했고 파일 위치 응답은 기존 message/error/path 형태를 유지합니다. 신규 기본 HOST는 로컬 전용이지만 기존 환경 설정은 변경하지 않습니다. 기존 파일의 LF/CRLF 구분이 바뀌지 않았음을 검사했습니다. 사용자 DB·설정·쿠키·녹화는 삭제하거나 초기화하지 않았고 실동작 테스트는 임시 복제본에서 진행했습니다. Windows OS 자체 실행/패키징 회귀는 미검증입니다.

## 4. 기능별 검증 결과

| 기능 | 실제 실행 | 코드/모의 검증 및 제한 |
| --- | --- | --- |
| FastAPI 서버 | Ubuntu x86_64 부팅·/health·OpenAPI 66개 경로 확인 | ARM64/Android 미검증 |
| 웹 UI | TypeScript·Vite 빌드, 루트 HTML HTTP 제공 성공 | Android 브라우저와 실제 브라우저 JS 렌더링은 실행 검증 불가 |
| API/SSE | 로컬 VOD 생성·취소, 태그 쓰기, SSE 최초 status_update 확인 | 2초 ping 코드 존재. 장시간 연결 유지/재연결은 미검증. WebSocket 대신 SSE 사용 |
| CHZZK 라이브 | 외부 방송 녹화 안 함 | 타임머신·쿠키 폴백·재시도 단위 테스트와 로컬 HLS 수신 검증. 실제 CHZZK 인증/CDN 연결 미검증 |
| CHZZK VOD | 외부 VOD 다운로드 안 함 | 두 CDN 전환·완료 길이 검증·부분 파일 처리 단위 테스트. 실제 CDN 응답 미검증 |
| 일반 VOD | 로컬 HTTP MP4를 실제 yt-dlp로 다운로드·취소 성공 | 실제 외부 사이트 보장 아님 |
| YouTube | 실사이트 라이브/VOD 미검증 | 런타임 전달·쿠키 폴백·상태 판정·채널 수집 모의 테스트. Node/Deno가 빌드 후에도 필요할 수 있음 |
| X Spaces | 실서비스 미검증 | 쿠키/API/독립 subprocess 경로 분석, 취소 프로세스 전달 회귀 테스트. 직접 FFmpeg replay는 pause/resume·정밀 진행률·속도 제한 없음 |
| FFmpeg/FFprobe | 경로/버전 탐지, 실제 TS 저장, MP4/MKV remux, ffprobe 12.023초 확인 | 원격 스트림 및 Android 네이티브 바이너리 실행 미검증 |
| Streamlink | 8.6.2 탐지 및 실제 로컬 HLS read→FFmpeg pipe 성공 | 유한 테스트 HLS EOF는 기존 정책에 따라 ERROR로 표시됨. 파일은 정상 생성/파싱되고 cleanup은 성공. 이를 정상 장시간 라이브 종료로 주장하지 않음 |
| yt-dlp | CLI 2026.08.19 탐지 및 Python VOD 실제 동작 | 모듈 VOD와 CLI live 모두 사용. Node runtime 전달 회귀 포함 |
| HLS/DASH | HLS 실제 실행 | DASH parse_manifest/화질 분기 존재, 관련 단위 테스트. DASH 실제 네트워크 실행 미검증 |
| TS/MP4/MKV | TS 파이프라인 및 MP4/MKV remux 성공 | live MP4는 fragmented MP4 옵션 사용. 파일 포맷 강제 변환의 모든 경우를 보장하지 않음. X Spaces는 M4A |
| 자동 감시 | 서버 부팅 시 Conductor/업데이터 시작, 단위 테스트 | 실제 방송 전환·장시간 예약 감시 미검증 |
| 저장·복구 | 태그·완료 VOD 기록·.env 설정 재시작 후 유지, SQLite/WAL 단위 테스트 | 중단 작업은 오류로 복원/수동 retry. .part의 동일 파일명·정확한 이어받기 보장은 없음 |
| 권한/경로 | POSIX 실행 권한 선택과 UTF-8 긴 파일명 회귀 검증 | 비루팅 Android 공유 저장소 실측 미검증. 내부 HOME 사용은 코드상 가능 |
| 종료 | 유휴/완료 상태 SIGTERM·SIGINT 종료 코드 0 및 재시작 성공 | 활동 중 다운로드 shutdown 회귀 테스트. 모든 외부 네트워크 중단 상황의 종료 시간 보장 아님 |
| 업데이트 | OS 분류·안내/코드 검토 | 실제 git pull 재설치/systemd 재시작은 실행하지 않음 |

## 5. 테스트 결과

실행 명령과 로그는 `audit-evidence/`에 있습니다.

```bash
python -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-dev.txt
.venv/bin/python -m pip check
.venv/bin/python -m pytest -c backend/pytest.ini backend/tests
cd frontend
npm ci
npx tsc --noEmit -p tsconfig.json
npm run build
cd ..
.venv/bin/python scripts/audit-posix.py
bash -n scripts/manage.sh scripts/install-termux.sh
git diff --check
```

| 검사 | 결과 |
| --- | --- |
| 의존성 설치/검사 | 성공, pip check: No broken requirements found |
| pytest | **353 passed, 29 skipped, 2 warnings** (8.95초). 기존 29개 API tests는 저장소에 있는 lifespan/TestClient 문제로 skip되어 있어 통과로 세지 않음 |
| TypeScript | 성공 |
| Vite production build | 성공. JavaScript 번들이 500kB를 넘는 경고 있음, 빌드 실패는 아님 |
| 실제 서버/로컬 미디어 smoke | 부팅, UI HTML, SSE 최초 메시지, VOD 완료/취소, SIGTERM/SIGINT, 재시작 이력, HLS/TS, remux 성공 |
| Linux ARM64 CPython3.12 wheel 수집 | 모든 requirements 다운로드 성공, 실행 아님 |
| Android CPython3.12 wheel-only 의존성 해석 | 실패. Streamlink lxml 등 Android 지정 태그 배포물 부족 |
| Android pydantic-core 2.46.3 wheel-only | 실패: No matching distribution found |
| shell 문법/patch 공백/기존 EOL | 성공 |
| 실기기 Termux Native/proot 및 Windows | 실행 검증 불가 |

첫 테스트에서는 SOCKS 프록시용 socksio가 빠져 5개가 실패했고, 실행 권한 없는 `.exe`를 POSIX에서도 기대하던 기존 FFmpeg 테스트 1개가 실패했습니다. httpx[socks]를 설치 요구사항에 반영하고 테스트를 실제 POSIX 실행 파일 조건으로 수정했습니다. YouTube 오프라인 테스트는 외부 네트워크/방송 상태에 의존하지 않는 모의 응답으로 전환했습니다. 수정 과정의 임시 실패는 최종 통과 결과와 구분했습니다.

추가 회귀 테스트는 POSIX .exe 제외, Windows 설정 경로 유지, POSIX에서 EXE 자동 다운로드 안 함, Spaces 취소, 중단 이력 복원, shutdown drain, YouTube cancel 시 자식 회수, 한글 바이트 길이, 확장자 보존, JS runtime 인자 전달을 검사합니다. Windows 분기는 Linux에서 모의 검사했으므로 Windows 실제 OS 테스트와 같지 않습니다.

ARM64 wheel 명령:

```bash
.venv/bin/python -m pip download -r backend/requirements.txt \
  --platform manylinux2014_aarch64 --python-version 312 \
  --implementation cp --abi cp312 --only-binary=:all: \
  --dest /tmp/phrolova-arm64-wheels
```

Android 지정 태그 wheel 검사:

```bash
.venv/bin/python -m pip download 'pydantic-core==2.46.3' \
  --platform android_24_arm64_v8a --python-version 312 \
  --implementation cp --abi cp312 --only-binary=:all: \
  --dest /tmp/phrolova-android-wheels
```

`audit-posix.py`는 12초 합성 영상만 만들고 localhost로 제공하며 실제 방송을 녹화하지 않습니다. 테스트가 만든 임시 영상 경로는 smoke 로그에 있습니다. 저장소 데이터와 분리된 임시 백엔드에서 테스트합니다. 웹 UI의 Node 없는 서버 제공은 코드/정적 배포 구조로 확인했고, Node 제거 후 재부팅 실험은 하지 않았습니다.

## 6. 설치 및 실행 명령어

복사 가능한 전체 명령과 `.env`, 백그라운드, 로그, 오류 해결 절차는 아래 문서에 있습니다.

- Ubuntu/Debian: [linux-guide.md](linux-guide.md).
- Native Termux 및 proot 별도 절차: [termux-guide.md](termux-guide.md).

본 검수 수정본이 원격에 게시되기 전 `git clone`만 하면 원본이 내려옵니다. 제공된 패치를 먼저 적용하거나 수정 작업본을 사용해야 새 Termux 스크립트와 수정 기능이 포함됩니다. 원본 커밋에서 패치 적용:

```bash
cd Phrolova
git apply --check /path/to/phrolova-linux-termux.patch
git apply /path/to/phrolova-linux-termux.patch
```

다른 커밋에서 충돌하면 강제 덮어쓰지 말고 변경 내용을 검토하세요. 다운로드/DB/쿠키가 있는 폴더를 초기화하지 마세요.

## 7. 최종 판정

**수정본은 Ubuntu 24.04 x86_64에서 로컬 서버와 주요 미디어 처리 기반 기능이 검증된 조건부 지원 상태입니다. 모든 실제 플랫폼 녹화와 장시간 운영까지 검증된 운영 준비 완료 상태는 아닙니다.** GNU/Linux ARM64와 proot은 실행 미검증입니다. Native Termux는 위 실기기 증거에 따라 조건부 지원으로 갱신합니다. Android 전용 wheel 부족으로 C/Rust 소스 빌드가 필요할 수 있으며 사용자 단말에서는 설치에 성공했습니다. proot는 glibc 의존성 문제의 보조 수단이지만 Android 절전·강제 종료·발열을 해결하지 않습니다.

즉, 원본을 네 환경에서 추가 수정 없이 안정적으로 운영할 수 있다고 판정할 수 없습니다. 확인된 소스 수준 문제를 수정하고 재현 가능한 패치·테스트·설치 가이드를 제공했으며, 남은 독립 검증 항목은 GNU/Linux ARM64·proot 실환경 실행, 추가 서비스 및 장시간 운영의 상세 재현 로그, Windows 실제 회귀입니다.

### 외부 확인 자료

- Uvicorn 공식 설치 문서: <https://uvicorn.dev/installation/> — 기본 설치와 standard extras 구분.
- yt-dlp 공식 저장소: <https://github.com/yt-dlp/yt-dlp> 및 runtime 안내 <https://github.com/yt-dlp/yt-dlp/issues/15012>.
- Streamlink 공식 설치: <https://streamlink.github.io/install>.
- Termux Python/Rust 패키지 빌드 정의: <https://github.com/termux/termux-packages/tree/master/packages>.
- Termux wake-lock 공식 문서: <https://github.com/termux/termux-tools/blob/master/doc/termux.1.md.in>.
- proot-distro 공식 저장소: <https://github.com/termux/proot-distro>.

외부 문서는 일반 의존성/실행환경 근거로 사용했고 Phrolova 실제 테스트 성공의 대체 증거로 사용하지 않았습니다.
