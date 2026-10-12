# 녹화 경계 종료·취소·디스크 버퍼 통합 보고서

검수일: 2026-10-12 (Asia/Seoul). 대상: ProofPage/Phrolova, 작업 브랜치 `fix/recording-boundary-buffer`. 선행 UI/모니터/CDN/파일명 수정 커밋 `4cb5a9f`를 포함한다. PR #8의 선행 변경을 기반으로 하며 이번 작업의 신규 코드는 아래에 구분한다.

## 참고 커밋을 적용한 방식

| 참고 Chzzk-Rekoda 커밋 | 참고 동작 | Phrolova 적용 |
|---|---|---|
| [f3c9212](https://github.com/munsy0227/Chzzk-Rekoda/commit/f3c921241d3f2d75a6fc4b984eb4fc94bc69896d) | 중지 요청을 세그먼트 전달 경계에서 처리 | writer의 delivery lock이 initialization+전체 media+checkpoint를 보호. 중지 요청 이후 새 전달을 막고 진행 중 전달이 끝난 후 RingBuffer를 닫음. 수신기는 잔여 바이트를 EOF까지 비운 뒤 파일 확정 |
| [35cd826](https://github.com/munsy0227/Chzzk-Rekoda/commit/35cd8263ea50b5d61cad64e532a90753debfba3a) | 취소·강제 종료와 정상 완료 구분 | in-process Streamlink reader 중지→강제 닫기→drain 순서로 통합. asyncio 취소에도 복사 worker 소유 task를 shield하여 열린 파일을 완료로 게시하지 않음. forced_stop/partial_input을 ERROR·attention으로 보존 |
| [449935d](https://github.com/munsy0227/Chzzk-Rekoda/commit/449935d0570a3b41af468ca37859c66cdf74d2f2) | 재연결 중 디스크 버퍼·checkpoint·복구 snapshot | 120초/256MiB/2,048개 bounded MediaBuffer, 원자적 payload+metadata, hash 검사, broadcast/rendition 검증. 마지막 전달 위치부터 빠진 구간을 복구하고 세션 전환에 동일 buffer owner와 recovery deadline 인계 |

Streamlink 라이브 구조, yt-dlp VOD 구조, 기존 플랫폼 resolver·callback, 선택 CDN 우선순위, 시작 offset·타임머신 정책을 유지했다. upstream CLI stop-file/watcher/별도 프로세스 명령은 복사하지 않고 Phrolova의 API·async task 수명에 맞췄다. MIT 고지와 `third_party/Chzzk-Rekoda-LICENSE`를 유지한다.

## 재현한 결함과 실제 수정

| 문제 | 원인 | 관련 파일 | 수정 | 검증/결과 |
|---|---|---|---|---|
| 수신 완료 전 중지를 누르면 마지막 데이터가 잘림 | 수신 루프가 intentional_stop 플래그를 먼저 보고 RingBuffer 잔여 바이트를 읽지 않음 | `backend/app/engine/pipeline/ytdlp.py` | producer 중지와 consumer drain 분리, EOF/force flag로 수신 종료 | 수정 전 drain 재현 실패, 수정 후 TS 바이트 일치 통과 |
| ERROR가 녹화 완료로 바뀜 | seal 경로에서 state를 무조건 COMPLETED로 변경 | 같은 파일, `recording_finalizer.py` | output_errors/ERROR 유지, actual_closed 확인 후 attention 기록 | 수정 전 상태 재현 실패, 수정 후 ERROR/원본 보존 통과 |
| 취소/timeout 뒤 파일 쓰기가 남아 있는데 후처리 시작 | thread 소유 feeder를 취소하면 실제 copy thread가 계속 실행 | 같은 파일 | 독립 stop task·shield·유한 대기; 열린 파일은 확정하지 않음; 실패한 stop task는 후속 cleanup 요청 가능 | 취소·짧은 drain timeout·후속 종료·잠긴 writer 경계 통과 |
| 빠진 구간 이후 위치로 resume하여 누락이 남음 | restart cursor가 마지막 checkpoint 대신 다음 발견 segment로 이동 | `chzzk_continuity.py`, `conductor.py`, `chzzk_stream.py` | missing 구간의 마지막 end부터 재개, 90초 recovery deadline 인계, 아직 playlist에 없는 media를 디스크 버퍼에서 전달 | 기존 gap 계약 유지, missing window loopback 실험에서 중복 없이 바이트 일치 |
| 버퍼 정리와 백그라운드 store 경합 | stop 뒤 disk store가 디렉터리를 다시 채워 Windows cleanup 실패 | `recording_buffer.py`, `chzzk_continuity.py` | buffer lock 아래 close fence, 새 store 차단; 한도/원자적 저장 실패 rollback | close/reopen·disk full·외부 파일 보존 통과 |
| HTTP 성공인데 잘린 조각을 병합 완료 | Content-Length 일치만으로는 container 잘림을 알 수 없음 | `vod_integrity.py`, `chzzk_cdn.py`, `chzzk_continuity.py` | native HLS/DASH append 전 decoded TS/fMP4 구조 검사; 각 moof와 뒤 mdat 짝 검사; emsg 허용 | 실제 HTTP 200·길이 일치 잘림, 잘못된 pair 3종, HLS/DASH append 거부 통과 |
| 403/404가 파일 손상/닫힌 파일 오류로 바뀜 | 병렬 worker 실패가 dest_stream을 닫아 다른 worker append에서 2차 예외 | `vod_integrity.py` | 최초 fatal HTTP 원인을 보존해 secondary exception 대신 전달 | init/전체 실패 403/404 및 500 검사 통과 |
| 수천 개 실패 segment가 모두 예약됨 | Executor.map에 manifest 전체를 제출 | 같은 파일 | 최대 workers window만 예약, 첫 오류 뒤 pending 취소 | 1,000개 실패 manifest에서 미디어 요청 ≤6회, 성공 산출물 없음 |
| 세로 VOD 해상도 목록/실제 선택 불일치 | 목록과 selector가 모두 height만 사용 | `vod_preparation.py`, `vod.py` | 짧은 변 품질·세로 width selector를 일치, 기존 가로 selector 유지 | 수정 전 portrait 재현 실패; 1080×1920/720×1280 및 동일 크기 최고 bitrate 통과 |
| 앱 재시작 후 .part 이어받기 경로가 바뀜 | 실제 filename/part/template/시작시각을 DB payload에 저장하지 않음 | `vod.py` | 첫 미디어 쓰기 전에 identity 저장, 중단 기록 복원, CDN/출력 부모 경로/기존 성공 파일 조건 확인 | 수정 전 DB 복원 재현 실패; 수정 후 이전 .part 바이트와 identity 유지 |
| 긴 제목·깊은 폴더에서 fragment 경로 초과 | 제목만 잘라도 suffix·충돌 번호·전체 Windows 경로 예산이 없음 | `core/vod_filename.py`, `vod.py`, `pipeline/ytdlp.py` | UTF-8 filename 210bytes, Windows 220chars, 임시 suffix 여유. 너무 깊으면 명확히 실패. 라이브 버퍼는 별도 temp 위치 | 한글 긴 제목·충돌 123·part/Frag 예산 통과 |
| remux 성공을 녹화 무결성 성공으로 표시 | FFmpeg returncode=0이면 corrupt 경고도 녹화 완료 | `recording_finalizer.py`, `frontend/src/api/client.ts`, `RecordingPostprocess.tsx` | 결과 container 성공은 completed 유지, corrupt/partial 경고는 continuity_valid=false와 output_errors 저장; 원본 보존·확인 필요/경고 색 표시 | 실제 손상 경고 fixture 및 브라우저 문구·색상 통과 |

파일 검사 재실행만으로 과거 capture continuity 오류를 지우지 않는다. valid container와 원본 데이터 연속성은 별도 값으로 유지한다. 무조건 TLS 검증 비활성화, 원본 자동 삭제, 테스트 삭제/비활성화, live/VOD 엔진 교체를 적용하지 않았다.

## 종료·버퍼 계약

- 정상 중지: cooperative 최대 15초 → 필요한 강제 close 최대 5초 → feeder drain 최대 10초. 실제 종료되지 않으면 `forced_stop`이며 파일 확정/자동 변환을 시작하지 않는다.
- 취소 요청이 있더라도 thread owner 정리를 기다린 뒤 CancelledError를 전달한다. timeout은 정상 완료로 간주하지 않는다.
- 의도한 중지/실제 방송 종료 시 미완성 fMP4 box 또는 TS packet tail은 `partial_input`. 수신 원본 바이트를 잘라 성공 파일로 꾸미지 않는다.
- transient network EOF 뒤의 기존 reconnect는 유지한다. valid mfra/footer가 붙은 fMP4는 partial로 오분류하지 않는다.
- 디스크 버퍼는 출력 녹화 파일과 다른 소유 전용 temp 디렉터리. metadata에는 URL·토큰·Cookie·Referer·인증 헤더가 없다.
- 파일은 owned 이름의 .bin/.json/.part만 다룬다. 파일 크기·hash·세션·rendition·timestamp·key 검증. 알 수 없는 외부 파일은 정리하지 않는다.
- buffer는 전달 checkpoint보다 앞의 자료만 정리. 같은 broadcast의 boundary/reconnect에 인계하며 다른 broadcast 자료를 다시 재생하지 않는다.
- 버퍼 생성/쓰기 실패 시 진단을 남기고 기존 네트워크 회복 경로를 유지한다. 확보하지 못한 구간은 gap/continuity 오류로 남긴다.

## 실제 실행한 검증

실행 위치는 저장소 루트. 로컬 Python 환경은 작업 폴더의 venv이며 FFmpeg/FFprobe는 설치된 media-tools 경로를 runner가 전달했다.

```powershell
$env:PYTHONUTF8='1'
& '../../work/venv/Scripts/python.exe' '../../work/run_tests.py' backend/tests -q --tb=short --basetemp=../../work/pytest-boundary-final-approved-20261012
& '../../work/venv/Scripts/python.exe' '../../work/run_tests.py' backend/tests/test_recording_shutdown.py backend/tests/test_recording_buffer.py backend/tests/test_reference_vod_regressions.py backend/tests/test_chzzk_continuity.py -q --tb=short --basetemp=../../work/pytest-final-boundary-focused-20261012
& '../../work/venv/Scripts/python.exe' -m ruff check --select E9,F63,F7,F82 backend
```

| 실행 | 결과 |
|---|---|
| 전체 backend | **866 passed, 1 skipped, 4 subtests passed**, 146.96초. 기존 deprecation 경고 2건 |
| 최종 boundary/buffer/VOD/continuity 집중 검사 | **91 passed, 4 subtests passed**, 28.10초 |
| Ruff E9/F63/F7/F82 | 통과 |
| `npm run build --prefix frontend` (번들 Node+작업 npm CLI) | TypeScript `tsc -b`·Vite build 통과. 기존 500KB chunk 안내 남음 |
| Git diff whitespace 검사 | 통과 |

샌드박스 재개 이후 첫 전체 실행은 **860 pass/4 fail**였다. 실패 4건은 기존 Git Bash 관리 스크립트 테스트가 `/c/Users/Administrator` 경로 접근을 거부당한 환경 문제였다. 소스/기대값을 바꾸지 않고 동일 격리 테스트를 정상 권한으로 다시 실행해 866개 통과를 확인했다. Vite의 상위 디렉터리 접근 실패도 정상 권한 동일 빌드에서 통과했다.

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH=(Resolve-Path '../../work/browsers').Path
$env:PHROLOVA_TEST_URL='http://127.0.0.1:3001'
$env:PHROLOVA_TEST_OUTPUT='../../outputs/boundary-buffer-ui-finalization'
& '../../work/venv/Scripts/python.exe' frontend/tests/recording_finalization.py
$env:PHROLOVA_TEST_OUTPUT='../../outputs/boundary-buffer-ui-download'
& '../../work/venv/Scripts/python.exe' frontend/tests/download_redesign.py
```

후처리: CHZZK/YouTube/SOOP/CIME fixture, 처리 상태·원본/파일/폴더/다시 검사/다시 변환/MKV 대체 버튼·API payload·busy 해제·삭제 채널 이력·설정 저장·경고 문구/색상. 360/390/768/1024/1440px 통과.

다시보기: 단일/다중 URL, 목록 추가/시작/전체 시작, 중복 안내, 외부/YouTube/채널 import, 화질 버튼, pause/resume/retry/inspect/file link, 취소·파일을 보존한 목록 제거. 360/390/768/1024/1280/1440/1920px × grid/list 통과. 테스트 마지막 출력의 “6 widths”는 기존 설명 문자열이며 실제 loop는 위 **7개 폭**이다.

스크린샷은 작업 산출물 `outputs/boundary-buffer-ui-finalization/` 6장, `outputs/boundary-buffer-ui-download/` 14장에 저장했다. 1440px live/VOD와 모바일을 검사했다. 브라우저 테스트는 isolated API route fixture이며 실제 사용자 다운로드를 만들거나 녹화 채널을 중지하지 않았다.

## 공개 CHZZK 실제 수신·변환

비공개 인증 쿠키 없이 공개 방송을 별도 DB·출력 폴더에서 짧게 수신했다. 실제 미디어 URL/서명 값은 보고서에 넣지 않았다.

| 실험 | 실제 선택/대기 source | 수신 파일 증가 | 결과 |
|---|---|---|---|
| 타임머신 HLS | Naver CDN HLS 선택, Akamai HLS 없음 | 1,179,648 → 92,299,203bytes | fMP4 원본 보존→TS 정규화→MKV→FFprobe passed, media duration 90.015초 |
| Akamai 요청·일반 LL-HLS | 방송 API가 제공한 Naver LL-HLS 선택, Akamai LL-HLS standby ready | 1,179,648 → 14,468,532bytes | 같은 경로 completed/inspection passed, duration 14.008초 |

두 번째 실험에서 실제 출력은 Naver이며 Akamai 수신 성공이라고 표시하지 않는다. 방송 API에 Akamai 선택 후보가 없는 경우 기존 fallback 동작을 확인했고, Akamai standby 경로를 별도로 준비/검증했다. Akamai-only 우선순위와 playlist 전환은 로컬 CDN 자동 테스트로 검증했다. 90.015초는 받아진 media 길이이며 테스트를 90초 동안 실행했다는 뜻이 아니다.

## 코드·데이터 보존과 남은 검증

SQLite schema를 새로 덮어쓰지 않고 기존 VOD payload JSON에 optional resume 필드만 더했다. 기존 채널/설정/녹화 기록 마이그레이션 회귀 통과. 사용자 출력 파일을 일괄 rename하거나 삭제하지 않았다. 관련 없는 `scripts/manage.bat` 줄바꿈 변경은 이번 커밋에서 제외한다.

| 환경 | 실제 확인 범위 |
|---|---|
| 현재 Windows x64 | 전체 backend, 실제 FFmpeg/FFprobe, 공개 CHZZK 수신 2건, Chromium route-fixture 버튼/레이아웃 |
| Ubuntu/Debian x64·ARM64 | OS 분기 자동 테스트는 포함. 새 PR의 GitHub Actions Ubuntu x64/ARM64 결과는 아래 CI 기록으로 구분 |
| Android Native Termux / proot | 새 코드의 실제 장시간 녹화·mount·폴더 열기 실기 미검증. 통과로 표기하지 않음 |
| macOS / RaiDrive 무응답 mount / 실제 멤버십 VOD | 대응 원칙/예외 fixture 외 실제 조건 미검증. 전체 이슈 보고서 E 항목에 기록 |

CPU·메모리·프로세스 누수의 수일 연속 실험, 수십 GB 실제 VOD 재시작, 무응답 OS mount의 강제 해제는 이 검증 범위에 포함되지 않는다. 제한 큐·buffer 한도·소유 cleanup·취소/timeout·교차세션 복구를 자동 테스트로 검사했다.

전체 148개 이슈의 분류·수정 경로·테스트·해결/참조 PR은 [참고 이슈 적용 보고서](reference-issue-audit.md)에 기록했다.

## GitHub CI

코드 커밋 `f81cd15388d1ef27a6e2a43cfbbc572803ba71ca`의 [GitHub Actions CI #101](https://github.com/ProofPage/Phrolova/actions/runs/38237997078) 전체 job이 통과했다. 아래 기록을 추가한 후속 커밋은 보고서만 변경하며 실행 코드는 같다.

| GitHub Actions job | 결과 |
|---|---|
| Windows x64 backend | success |
| Ubuntu x64 backend | success |
| Ubuntu ARM64 backend | success |
| frontend TypeScript / build | success |

코드와 보고서는 [PR #9](https://github.com/ProofPage/Phrolova/pull/9)로 제출했다. main과 merge conflict 없음. CI는 자동 테스트이며 OS별 모든 실제 방송·장시간·파일매니저 실험을 대신하지 않는다.
