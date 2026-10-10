# CHZZK VOD 준비 목록 및 일괄 다운로드 구현 결과

기준 소스: main/v2.0.50, 9045e85c2b82a15c512210a49074466359e42b99.
초기 검증 브랜치: feature/vod-batch-ui. 검증 완료 후 별도 사용자 승인에 따라 v2.0.51 릴리즈를 준비했다.

## 참고 영상과 기존 기능 비교

첨부 1004345139.mp4(약 27.27초)의 링크 드래그/복수 링크 입력, 썸네일 카드, 영상별 화질, 일괄 시작, 개별 작업 조작, 완료/전체 요약 흐름을 확인했다. 별도 데스크톱 도구나 페이지를 만들지 않고 기존 React 다운로드 페이지에 통합했다.

기존 Phrolova에는 즉시 다운로드 입력, 진행률·속도·용량·남은 시간, 일시정지·재개·취소·재시도, 동시 다운로드 세마포어, 작업 순서 변경, SQLite JSON 이력, 수동 CDN 선택, FFprobe 검사와 서버 경로 설정이 있었다. 이 경로를 재사용했다. 새로 만든 것은 준비 작업 등록/메타데이터/실제 화질 선택/시작/개별 이력 제거와 UI이다.

## 사용 방법 및 구현 범위

기존 상단 URL 입력과 즉시 다운로드 동작을 유지했다. 새 CHZZK VOD 준비 목록 영역에 링크를 놓거나 여러 URL을 줄바꿈으로 붙여넣고 `VOD 등록`을 누른다. 정보 조회 완료 후 각 카드에서 제공된 화질을 선택하고 개별 또는 전체 다운로드를 시작한다.

- 브라우저 드롭의 text/uri-list를 우선 사용하고 text/plain, HTML 링크를 대안으로 분석한다. HTML은 DOM에 삽입하지 않는다.
- 한 번에 최대 100개, URL당 최대 2048자, 준비 작업 최대 1000개로 제한한다. 잘못된 링크 한 건이 정상 링크 등록을 막지 않는다.
- 메타데이터 조회 동시 실행은 2개로 제한하고 기존 yt-dlp와 인증 쿠키 처리를 재사용한다. 제목, 썸네일, 방송자, ID, 길이, 업로드 날짜, 해상도를 추출한다. 프로필이 없으면 고정 CHZZK 채널 API에서 32자리 hex 채널 ID로 추가 조회하며 실패해도 나머지 정보는 표시한다. 사용자 URL을 그 API 호스트로 직접 전달하거나 리디렉션을 따라가지 않는다.
- 해상도는 실제 영상 형식의 height에서 중복을 제거해 표시한다. 영상별 선택을 저장하며 대기열에서 아직 시작하지 않은 준비 작업도 변경할 수 있다. 제공되지 않는 화질은 API에서 거부한다. 기본 설정을 이용하고 없으면 사용 가능한 대체 해상도를 안내한다.
- 다운로드 시 선택 높이의 영상과 음성을 함께 선택하는 yt-dlp selector를 사용한다. 시작 이후 선택 변경을 허용하지 않는다.
- 정보 조회 실패는 해당 카드에서만 재조회한다. 조회 중 제거된 항목은 늦게 도착한 결과로 복원되지 않는다. 동시에 시작을 요청해도 동일 작업을 두 번 예약하지 않는다.
- 준비 작업은 기존 작업 딕셔너리/SQLite JSON 이력을 사용한다. DB 스키마를 변경하지 않는다. 새로고침 후 목록·화질·메타데이터를 복원한다. 서버 종료 중 조회된 항목은 준비 완료 또는 정보 재조회 상태로 복원하며 자동 다운로드하지 않는다. 실행 중 중단된 작업은 기존 오류/새 작업 재시도 방식이다.
- 새 phase 필드로 정보 조회/준비/다운로드/병합/검증/취소 상태를 표시하되 기존 state 값과 API 계약은 유지한다. 기존 진행 통계를 그대로 이용한다.
- 새 UI의 `완료 목록 정리`는 완료 이력만 제거한다. 준비·대기·실패 작업은 개별 제거한다. 파일은 삭제하지 않는다. 기존 clear-completed API의 기본 동작은 유지하며 completed_only=true만 추가했다.
- 모든 새 UI 문구는 기존 한국어·영어·일본어 체계에 연결했다. 요청 중 버튼을 잠그며 기존 다크 테마·강조색·반응형 구성 요소를 재사용했다.

## 보존한 엔진 및 저장 동작

**라이브는 기존 Streamlink → FFmpeg를 유지한다.** 라이브 파이프라인/Conductor 소스와 CDN 라우팅 모듈은 수정하지 않았다. VOD는 기존 yt-dlp, DASH 패치, FFmpeg 병합, FFprobe 비파괴 경고를 사용한다.

현재 v2.0.50의 CDN 기능은 기본/수동 Akamai 선택 및 같은 선택 안에서 유한 재시도이다. 자동 CDN 전환을 복원하거나 새로 추가하지 않았다. 준비 작업 시작 시 현재 저장된 CDN 설정을 복사하고 실행 중 설정 변경은 영향을 주지 않는다. UI에는 시작 전 설정 적용 방식, 시작 후 실제 선택을 표시한다.

VOD_DOWNLOAD_DIR, VOD_FORMAT, VOD_FILENAME_TEMPLATE, 초 단위 날짜와 파일명 충돌 방지 로직을 유지했다. 준비 등록 당시 서버 설정의 다운로드 경로를 기록하고 해당 경로로 저장한다. 브라우저 로컬 폴더를 서버 경로로 바꾸는 기능을 추가하지 않았다. 사용자 설정/DB/완성 파일을 초기화하거나 삭제하지 않았다.

일시정지는 기존 yt-dlp progress hook에서 가능한 구간에만 작동한다. 병합/검증 중에는 UI의 일시정지 버튼을 표시하지 않는다. 서버 재시작 후 같은 네트워크 세션의 무손실 이어받기를 보장하지 않는다. 사용자가 이미 취소한 준비 작업을 정상 서버 종료가 새 중단 오류로 바꾸지 않도록 보완했다.

## 테스트 결과

Linux x86_64, Python 3.12.14 환경에서 수행했다. 프로덕션 Python/Node 의존성을 변경하지 않았다. Playwright/Chromium은 검사 도구로만 별도 설치했다.

| 검사 | 최종 결과 |
|---|---|
| python -m pytest -c backend/pytest.ini backend/tests | 490 passed, 2 warnings |
| python -m compileall -q backend/app | 통과 |
| python -m pip check | No broken requirements found |
| cd frontend && npx tsc --noEmit -p tsconfig.json | 통과 |
| cd frontend && npm run build | 통과. 기존 큰 JS chunk 경고 있음 |
| frontend/tests/vod_preparation.py | Chromium 390/1440px 통과. URI/plain/HTML DataTransfer, 복수 입력, 화질, 개별/전체 시작, 조회 재시도, pause/resume/cancel/retry, 이력 제거, 새로고침, 영어·일본어 표시 확인 |
| frontend/tests/filtered_reorder.py | Live/Downloads 필터 이동과 기존 payload 보존 통과 |
| frontend/tests/preview_layout.py | 320/390/820/1024/1440px 통과. 가로 overflow 0, 기존 실제 로컬 HLS 재생과 video 요소 유지 확인 |
| 새 준비 작업 실제 미디어 검사 | 기본/Akamai 모의 요청에서 선택 해상도의 DASH 영상+음성 다운로드·MKV 병합·약 2초 FFprobe 검사 통과 |
| 기존 CDN 테스트 | HLS/DASH/AES 키/HTTP 오류/timeout/작업 격리/비파괴 경고 회귀 통과 |
| scripts/audit-posix.py | 부팅/health/HTML/SSE/로컬 다운로드/취소/설정 저장/재시작 DB·기록·설정/SIGTERM·SIGINT 통과 |
| 동일 실행 검사의 라이브 | 실제 Streamlink로 로컬 HLS 수신 → FFmpeg TS 12.023초, MP4/MKV remux 통과 |

Python 경고는 기존 Starlette TestClient/httpx와 discord audioop deprecation이다. 처음 추가한 테스트의 parametrization/import/JS quoting 오류는 수정했다. 초기 API 표면 고정 테스트는 의도적으로 추가한 6개 경로 때문에 실패했으며 명시적 기대 목록을 확장했다. 최종 실패/skip은 없다.

브라우저 실행 도구의 초기 다운로드 실패와 환경 재시작에 따른 런타임 연결 실패를 해결한 뒤 최종 Chromium 검사를 수행했다. 드롭은 실제 브라우저 DataTransfer 이벤트 자동화이며 외부 CHZZK 탭을 사람이 드래그한 기기 시험은 아니다.

라이브의 유한한 모의 스트림은 종료 시 기존 재연결 로직에 따라 RecordingState.ERROR를 표시한다. 녹화 파일·길이·remux 검증이며 장시간 방송/재연결 전체 검증은 아니다.

## 추가 API 및 변경 파일

추가 API: POST /api/vod/prepare, POST /api/vod/start-prepared, POST /api/vod/{task_id}/metadata, PATCH /api/vod/{task_id}/quality, POST /api/vod/{task_id}/start, DELETE /api/vod/{task_id}. 기존 status에 prepared/phase/metadata를 추가하고 clear-completed에 선택적 completed_only query를 추가했다. 기존 download 요청/기본값을 바꾸지 않았다.

- backend/app/engine/vod_preparation.py: 준비 목록·정규화·실제 화질·조회/시작/삭제·경쟁 상태 처리.
- backend/app/engine/vod.py: 준비 필드 저장/복원, 메타데이터 확장, 선택 해상도와 음성, 병합/검증 phase, 재시도 시 준비 정보 유지, 취소 완료 이력 보존.
- backend/app/services/recorder.py, backend/app/api/vod.py: 기존 서비스 경유 API 확장, 완료 전용 정리.
- backend/tests/test_vod_preparation.py, test_api_surface.py: 33개 새 준비 기능 사례와 새 API 명세 기대값.
- frontend/src/utils/vodUrls.ts, components/VodPreparationPanel.tsx: 안전한 URL/드롭 분석, 준비 등록/전체 시작.
- frontend/src/pages/VodDownload.tsx: 기존 카드의 메타데이터/화질/조작/요약/완료 정리 확장.
- frontend/src/api/client.ts, contexts/VodContext.tsx: 신규 타입/API, 기존 완료 정리와의 호환성.
- frontend/src/contexts/LanguageContext.tsx: 새 UI 영어·일본어 번역.
- frontend/tests/vod_preparation.py: 신규 브라우저 검사. filtered_reorder.py/preview_layout.py: 선택적 Chromium 경로 지원. tests/README.md: 실행 문서.
- docs/vod-batch-ui-audit-ko.md: 이 보고서.

## 미검증 및 남은 제한

외부 CHZZK 메타데이터/제한 영상/실제 VOD 다운로드와 실제 CDN 접근은 이번 검사에서 수행하지 않았다. 인증/속도/외부 경로 호환성을 보장하지 않는다. Windows, Linux ARM64, Android Termux 기기의 이번 변경도 직접 검증하지 않았다. 모바일 Chromium viewport 검사는 Android 절전·권한·발열 검사가 아니다. 기존 Termux 설치 경로/네이티브 도구 선택을 바꾸지 않았지만 기기 검증이 필요하다.

기존 chzzkpy 의존성 pin과 알려진 advisory 문제는 이번 범위에서 변경하지 않았다. pip check는 보안 검사 결과가 아니다. FFprobe는 전체 프레임 디코딩 검사가 아니므로 모든 손상을 잡아내지는 못한다.

## 적용

v2.0.50 기준의 incremental patch이다. 저장소 루트에서 실제 내려받은 패치 경로로 먼저 git apply --check를 실행한다. 기존 서비스는 정상 종료하고 설정·DB·영상은 보존한다.

```sh
git apply --check ./phrolova-vod-ui.patch &&
git apply ./phrolova-vod-ui.patch
cd frontend
npm ci
npm run build
cd ../backend
# 사용 중인 가상환경의 Python으로 실행
../.venv/bin/python run.py
```

패치 파일이 다른 폴더에 있다면 정확한 절대 경로로 바꾼다. Termux의 설치 폴더가 $HOME/Phrolova-termux라면 실행 명령은 "$HOME/Phrolova-termux/.venv/bin/python" run.py이다. Node는 UI 빌드 단계에 필요하며 빌드 이후 운영에 필요하지 않다.
