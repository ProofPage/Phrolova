# CHZZK VOD CDN 선택 구현 및 검증

검수 기준: main 5b076d1e021c7946e37400f8892a83055f2b58af, 2026-10-09. 초기 검증은 로컬 브랜치 audit/cdn-20261009에서 수행했다. 이후 사용자 요청에 따라 v2.0.50 릴리즈를 준비했다.

## A. 분석 및 구현 결과

VOD API → RecorderService → VodEngine → yt-dlp 요청/다운로더 → FFmpeg 병합 → FFprobe → 작업 기록과 UI의 연결을 조사했다. 설정 API, 환경 파일 저장, 취소/재시도/파일명 충돌, 기존 DASH 패치, 라이브 파이프라인과 테스트도 확인했다. 이번 변경은 CDN 기능과 그 경로에서 확인한 결함에 한정하며 저장소 전체에 버그가 없다는 판정은 아니다.


설정 → 다운로드의 VOD 영역에 다음 선택을 추가했다.

- 기본 CDN (권장): 기본값. yt-dlp가 원본에서 제공받은 URL을 유지한다.
- Akamai CDN (재생 시간 오류 발생 시 사용): 사용자가 선택한 새 치지직 VOD 작업에만 적용한다. 느릴 수 있다는 안내를 표시한다.

CHZZK_VOD_CDN=default 또는 akamai를 기존 .env에 저장한다. 기존 API가 cdn을 생략하면 default이다. UI는 시작/재시도 직전에 저장된 값을 읽어 명시적으로 전달한다. 작업마다 선택을 복사하므로 실행 중 설정 변경은 영향을 주지 않는다. 선택 CDN, 적용 여부, 검사 경고, 결과 길이를 기존 SQLite JSON 작업 기록에 저장하고 재시작 시 복원한다. CDN을 바꾸는 재시도는 새 작업과 충돌 없는 파일명을 사용하며 기존 완성 파일을 삭제하지 않는다.

## B. 확인 및 수정된 문제

Critical 0, High 2, Medium 3, Low 0: 이번 변경에서 처리한 구체적인 결함 5건. 전체 저장소의 결함 총수는 아니다.

| 심각도 | 파일/위치 | 원인과 증상 | 수정/검증 |
|---|---|---|---|
| Medium | backend/app/engine/vod.py, _download_with_ytdlp | 기존 첫 시도가 Akamai이며 재시도마다 CDN 교대. 선택이 없고 MPD 정보만 바꾸므로 절대 세그먼트 URL은 원래 CDN에 남을 수 있음 | 기본 원본 유지, 수동 작업별 선택, 요청 단위 변환. HLS/DASH/AES 키 실제 모의 요청 검증 |
| High | backend/app/engine/vod.py, _download_with_ytdlp/_probe_media_duration | 길이 불일치 시 결과 삭제·실패·다른 CDN 재시도. FFprobe 부재도 실패 | 파일 유지, 완료 상태와 별도 경고. 원본 길이가 신뢰 가능한 완료 VOD만 비교; 검사 실패도 경고 |
| High | backend/app/engine/vod.py, 파일명 예약/_download_with_ytdlp | 병합 확장자를 예약하지 않아 기존 MKV 충돌 가능; 병합 전 파일명을 최종 결과로 가정해 실제 완료 파일을 못 찾음 | 병합 확장자 충돌 확인, yt-dlp 최종 requested_downloads 경로 사용. 기존 파일 보존 및 MP4/MKV 실제 병합 테스트 |
| Medium | backend/app/engine/vod.py, _build_ytdlp_options | DASH 영상/음성 분리 형식에 단일 best를 요청하여 형식 선택 실패 | 치지직 VOD의 best/worst에만 영상+음성 조합과 단일 형식 대안 적용. 모의 DASH 실패 재현 후 실제 병합 통과 |
| Medium | backend/app/api/settings/media.py, update_vod_settings | 검증 전 런타임 값 변경, 분할 저장, 저장 오류 무시로 설정 불일치 | 먼저 전체 검증, 한 번 저장 성공 후 메모리 반영. 실패 시 HTTP 500 및 기존 설정 유지 회귀 테스트 |

부가적으로 치지직 판별을 hostname으로 제한해 다른 URL의 query 문자열을 치지직으로 오인하지 않게 했다. 필요한 영상/음성 세그먼트를 조용히 건너뛰지 않도록 치지직 VOD에서 skip_unavailable_fragments=False를 설정했다.

## CDN 요청 처리와 안전성

backend/app/engine/chzzk_cdn.py의 작업별 YoutubeDL 인스턴스에서 실제 urlopen을 처리한다. 전역 monkey patch를 추가하지 않는다. 기본 모드는 일반 YoutubeDL 경로를 그대로 사용한다.

명시적 Akamai 모드는 정확한 호스트 ex-nlive-slitvod-streaming.navercdn.com만 light-slit.akamaized.net으로 매핑한다. urllib.parse로 구조를 검증하고 escape된 경로 및 query/token 바이트를 보존한다. 메타데이터 API 호스트, 알 수 없는 CDN, userinfo, 비표준 포트, 인식 가능한 호스트 종속 서명은 변환하지 않고 원본을 유지하며 적용 불가 경고를 제공한다. 모든 종류의 서명을 판별할 수 있다고 보장하지 않는다. 교차 호스트의 Cookie/Authorization/Host 등은 제거한다.

MPD/HLS뿐 아니라 상대 및 절대 미디어 URL, DASH 초기화 조각, 영상/음성 조각, Range 헤더, AES-128 키 요청도 같은 인스턴스를 통과한다. Akamai의 네이티브 HLS가 지원하지 않는 형식은 FFmpeg 네트워크 경로로 조용히 넘기지 않고 명확한 오류를 낸다. FFmpeg의 정상 병합 기능은 유지한다. 403/404/429/5xx/timeout은 기존 유한 재시도로 처리하고 다른 CDN으로 자동 전환하지 않는다.

중요한 한계: 위 매핑의 경로/query 보존과 다운로드 처리는 로컬 모의 CDN으로 검증했다. 실제 CHZZK 메타데이터 요청은 제한 시간 내 응답하지 않아 외부 두 CDN의 경로 호환성/토큰 유효성/속도를 실서버에서 확인하지 못했다. 이 옵션은 실서버 검증이 필요한 조건부 기능이며 모든 영상에서 접근 가능하다고 보장하지 않는다.

FFprobe는 컨테이너/영상·음성 트랙/유효 길이를 검사한다. 완료 원본 길이와 차이가 max(10초, 2%)보다 크면 재다운로드 안내를 표시한다. 라이브/예정/진행 중 재생 길이는 비교하지 않는다. 전체 프레임 디코딩 검사가 아니므로 모든 구간 손상/누락을 검출하지는 못한다.

## C. 테스트 결과

Linux x86_64, Python 3.12의 별도 가상환경에서 실행했다.

| 명령/검증 | 결과 |
|---|---|
| python -m pytest -c backend/pytest.ini backend/tests | 457 passed, 2 warnings |
| python -m compileall -q backend/app | 통과 |
| python -m pip check | No broken requirements found |
| cd frontend && npx tsc --noEmit -p tsconfig.json | 통과 |
| cd frontend && npm run build | 통과. 기존 큰 JS chunk 경고 있음 |
| python scripts/audit-posix.py | 서버/health/HTML/SSE/로컬 VOD/취소/설정 저장/재시작 DB·기록·설정/SIGTERM·SIGINT 통과 |
| 동일 실행 검증의 라이브 경로 | 실제 Streamlink HLS 수신 → FFmpeg TS 저장, FFprobe 12.023초 확인, MP4/MKV remux 통과 |
| 새 모의 CDN 통합 테스트 | 기본/Akamai × HLS/DASH/AES-128 HLS 6개 실제 다운로드. 영상+음성 및 약 2초 길이와 목적 호스트/query 확인 |
| API/회귀 테스트 | 기본값/422/저장 실패/작업 격리/히스토리/취소/파일 충돌/서명 URL/헤더/HTTP 오류/timeout/지원 불가 HLS 통과 |

라이브 실행 검증은 유한한 테스트 HLS가 끝나면 기존 자동 재연결 로직에 따라 RecordingState.ERROR를 보고한다. 파일 저장·재생 구조는 정상이며 장시간 라이브와 재연결 전체를 검증한 결과는 아니다.

초기 테스트의 DASH 형식 선택 및 최종 출력 경로 실패를 재현하고 수정했다. 마지막 새 테스트의 outtmpl 자료형 오류도 수정했다. 최종 suite에 실패/skip은 없다. 경고는 Starlette TestClient의 httpx 및 discord audioop deprecation이다.

미검증: 실제 외부 CDN 다운로드, 실제 치지직 장시간 방송/VOD, Windows/ARM64/Android 기기의 이번 패치, 모바일 화면 직접 조작. 사용자가 이전 버전 Termux에서 확인한 재생/녹화 결과는 이번 패치의 기기 검증으로 대체하지 않는다. chzzkpy의 기존 의존성 pin과 보안 상태는 별도 과제로 남으며 pip check는 보안 검사가 아니다.

## D. 변경 파일

- .env.example, backend/app/core/config.py: CDN 기본 설정과 허용값.
- backend/app/api/settings/general.py, media.py: 설정 반환/검증/영구 저장.
- backend/app/api/vod.py, services/recorder.py: 선택 전달, 기존 요청 기본값 유지.
- backend/app/engine/chzzk_cdn.py: VOD 한정 URL/요청 처리, 네이티브 HLS 사전 검사.
- backend/app/engine/vod.py: 작업 snapshot/상태 저장, 수동 CDN, DASH 선택, 최종 파일 경로/충돌 보호, 비파괴 FFprobe 경고.
- frontend/src/api/client.ts, contexts/VodContext.tsx: 타입 및 작업 시작 시 CDN 전달.
- frontend/src/components/settings/DownloadTab.tsx, pages/VodDownload.tsx: 선택 UI/속도 안내/작업 CDN/결과 경고.
- backend/tests/test_chzzk_cdn.py: 45개 회귀·모의 CDN 테스트.
- docs/cdn-audit-ko.md: 이 보고서.

의존성 추가/변경 없음. 기존 파일 줄바꿈 유지. 사용자 DB/설정/완성 파일 초기화 없음.

## E. 최종 평가 및 적용

기본 원본 CDN과 라이브 Streamlink 동작은 유지했으며 로컬 회귀/미디어 통합 테스트를 통과했다. Akamai 경로는 실제 외부 CDN 검증이 남아 있어 운영 환경에서 완전히 검증되었다고 판단하지 않는다. FFprobe 경고는 완료 파일을 보존하며 자동 CDN 전환은 없다.

패치는 기준 커밋에서 확인해야 한다. 이미 수정된 코드나 다른 버전에는 억지 적용하지 않는다. 저장소 루트에서 실제 패치 위치를 사용한다.

```sh
# Android 공유 저장소 최상위에 패치가 있을 때의 예시
cd "$HOME/Phrolova-termux"
git apply --check /storage/emulated/0/phrolova-cdn.patch &&
git apply /storage/emulated/0/phrolova-cdn.patch
# 현재 폴더에 내려받았다면 경로를 ./phrolova-cdn.patch 로 바꾼다.
cd frontend
npm ci
npm run build
cd ../backend
"$HOME/Phrolova-termux/.venv/bin/python" run.py
```

실행 전 기존 서비스를 정상 종료한다. Node는 UI 재빌드에 필요하며 빌드 후 서버 운영에 필요하지 않다. 브라우저 http://127.0.0.1:8000 → 설정 → 다운로드 → VOD CDN 선택 → 저장 → 새 다운로드/재시도 순서로 사용한다. 패치 파일 다운로드 위치를 자동으로 가정하지 않는다.
