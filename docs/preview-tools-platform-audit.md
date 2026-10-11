# 라이브 미리보기·미디어 도구·플랫폼 검수 보고서

## 첨부 로그 전체 분석

logs.txt의 18:15:22~18:19:04 구간 전체를 확인했다. CHZZK·SOOP·CIME 모두 자동 녹화가 시작됐다. CIME 프레임만 4294967291과 TLS 인증서 검증 실패로 중단됐고, 수동 중지 뒤 후처리는 FFprobe 누락으로 실패했다. 이후 자동 녹화 ON 상태의 감시 루프가 다음 스캔에서 다시 녹화를 시작했다. 마지막 동작은 무한 실패 재시도가 아니라 현재 자동 녹화 정책에 따른 재시작이다.

| 문제 | 실제 원인 및 수정 | 관련 코드 | 검증 |
|---|---|---|---|
| CIME 미리보기 TLS 실패 | Windows FFmpeg에 CA를 지정해도 중첩 HLS 세그먼트에 전달되지 않는 경로를 실제 공개 방송에서 재현. 미리보기 전용 Streamlink HTTPS 수신이 OS·Mozilla CA를 검증하고 FFmpeg는 stdin만 디코딩 | preview_transport.py, preview_frames.py, cime.py | 공개 CIME 1920×1080 JPEG 성공; 자체 HTTPS 미신뢰 CA 거부/등록 CA 복구 |
| 프레임 오류가 일반 연결 오류로 소실 | Streamlink 워커의 HTTP 실패를 별도로 수집하여 decoder EOF와 구분 | preview_transport.py, preview_frames.py, api/stream.py | TLS·401/403·404·429·5xx·timeout 코드 및 비밀 URL 마스킹 |
| 미리보기 실패 후 멈춤 | 서버 실패 캐시와 클라이언트 지수 백오프, 수동 재시도, 성공 시 오류 해제 | LiveFramePreview.tsx | 20개 viewport/mode, 자동 복구 및 프레임 비율 검사 |
| 미리보기 중복·종료 자원 | 채널별 잠금, 전체 동시성 2, 수신 워커 1, timeout/취소 시 reader/process 정리, 채널 삭제·오프라인 invalidate | preview_frames.py, preview_transport.py, conductor.py | 10개 동시 실패 요청 1회 생성, 취소/프로세스 종료/reader 정리 |
| FFprobe 설치 누락 | 기존 자동 설치가 ZIP에서 ffmpeg.exe만 옮김. 두 도구를 각각 검증한 후 함께 복사. ZIP 전체 추출과 PowerShell 문자열 경로 제거 | backend/run.py, core/config.py, media_tools.py | 명시 경로·FFmpeg 형제·번들·Python 실행 경로·PATH·PREFIX; -version 독립 검사 |
| MKV 변환 실패로만 표시 | 실제 검사 단계/error_code 저장, FFprobe 설치 안내, 시스템 도구 검사 UI | recording_finalizer.py, RecordingPostprocess.tsx, MediaToolsCard.tsx | 원본 보존 및 동일 작업에서 재검사·재변환 완료 |
| 복구 버튼 조건/원격 폴더 | 등록 작업 파일만 열기; 원격 요청은 서버 shell 대신 경로 제공, 비활성화 이유 표시 | api/recordings.py, RecordingPostprocess.tsx | 파일/폴더/검사/재변환/MKV 대체 기존 회귀 및 원격 shell 미실행 |
| VOD fragment 누락 완료 | 모든 플랫폼에서 누락 fragment 건너뛰기 금지, 동시 수신 2, 최대 10회 재시도·30초 백오프 | vod.py | 옵션 계약 검사 및 기존 실제 HLS/DASH 다운로드 회귀 |
| 메타데이터 timeout | 1회 제한 재시도 및 명확한 최종 메시지, 인증 폴백과 예외 타입 유지 | vod.py | 실패 후 복구/최종 실패/YouTube 비인증 오류 |
| 로그 URL 노출 | 모든 yt-dlp 플랫폼 로거, VOD 예외/트레이스 및 Streamlink HLS 오류 마스킹 | platform_media.py, platform_auth.py, preview_transport.py, vod.py | HTTPS 실패 로그에서 서명 제거 |
| 브라우저 서명 URL 노출 | CHZZK/YouTube HLS master·variant·segment·key·map·part 주소를 만료 토큰으로 대체. 검증된 TLS, 제한된 CDN 이동, 동시성/응답 크기 제한, byte range 유지 | preview_proxy.py, api/stream.py | 서명 쿼리 보존·사설 주소 차단·만료/종료 및 실제 Hls.js 디코딩 |
| 공통 UI 정리 | 이미지 display와 preview align-self 명시, stale 프레임 안내, Toast/복사 타이머 정리 및 clipboard 실패 처리 | index.css, LiveFramePreview.tsx, Toast.tsx, UpdateModal.tsx | 반응형·플랫폼·설정·다운로드 브라우저 회귀 및 TS 빌드 |

## 녹화·파일 보호

실제 라이브 녹화 엔진은 계속 Streamlink다. TS 우선, fMP4는 실제 원본으로 수신하며 녹화 종료 후 기존 TS 정규화 → MKV/MP4 remux → FFprobe 검증을 유지했다. 기본 MKV와 기존 사용자 선택, DB 및 녹화/다운로드 파일을 변경하지 않았다. 검사 도구가 누락돼도 라이브 녹화는 허용하고 원본을 보관한다. 실패 작업은 도구 설치 후 복구 가능하다. 실제 방송 TLS 검증에서 CIME 1920×1080, SOOP 960×540 원본 프레임이 생성됐고 해상도 확대는 하지 않았다.

## UI 검증 범위

320,375,430,640,768,1024,1280,1440,1920,2560px × 그리드/목록 20개 조합에서 SOOP 정상·CIME TLS 실패·복구를 검사했다. 동일 카드의 실패/복구 높이 차이는 2px 미만, preview stage 16:9 및 가로 넘침 없음. 확장 상세는 독립 높이를 유지한다. 플랫폼별 실제 메타데이터 행 개수 차이를 임의 빈 행이나 고정 높이로 맞추지 않았다. 기존 CHZZK HLS 브라우저 재생·resize/view/reorder 유지, 녹화 통계/버튼/이력, 다운로드 pause/resume/quality/file, 저장 설정 검사를 추가 실행했다. 수정 전은 사용자 첨부 로그/화면이며 재현한 TLS 실패 코드와 수정 후 실제 프레임을 작업 산출물에 보관했다.

## 참고 이슈

[148개 이슈 대조표](reference-issue-audit.md). 53개 댓글 스레드의 134개 댓글과 관련 PR 152개의 설명·변경 파일·패치를 수집했다. Qt·Nuitka·자체 fragment 엔진을 그대로 복사하지 않았다. 추가 재현/실기가 필요한 E 항목은 완료로 표시하지 않는다.

## 검증 명령

- backend: python -m pytest -q (로컬에서는 격리 DB/.env와 FFmpeg PATH를 설정하는 work/run_tests.py 사용)
- PHROLOVA_TEST_LARGE_MEDIA=1 python -m pytest tests/test_media_inspection.py::test_real_large_ts -q: 3GiB 초과 실제 TS 생성·검사 1 passed
- python -m ruff check --select E9,F63,F7,F82 backend
- python -m compileall -q backend/app backend/run.py
- frontend: npm run build (tsc -b + Vite)
- frontend/tests/preview_platform_regressions.py
- frontend/tests/preview_proxy_playback.py
- frontend/tests/platform_integration.py
- frontend/tests/live_details_layout.py
- frontend/tests/recording_repair.py
- frontend/tests/download_redesign.py
- frontend/tests/recording_finalization.py
- frontend/tests/settings_consistency.py

브라우저 테스트는 합성 API·실제 JPEG/HLS 미디어로 사용자 DB/녹화와 분리했다. 실제 공개 방송 프레임 검증도 별도로 실행했다. 2026-10-12 최종 전체 백엔드는 786 passed, 6 skipped, 4 subtests passed였다. 프록시 종료·만료·byte range·HTTPX 진단 로그 마스킹도 별도 검증한다. TypeScript/Vite 빌드, Ruff 오류 검사 및 compileall도 통과했다. 320/1440px × 그리드/목록에서 실제 백엔드 프록시 master → variant → TS 응답을 Hls.js로 디코딩하고 재생 시간 증가를 확인했다.

## 환경별 결과와 남은 검증

- 로컬 Windows 10.0.26100: 공개 CIME/SOOP 프레임 및 실제 FFmpeg/FFprobe 회귀·브라우저 검증 수행. Windows 10 실기는 수행하지 않았다.
- GitHub CI: Windows runner, Ubuntu x64, Ubuntu ARM64의 독립 전체 회귀 및 frontend build job을 구성했다. 실행 결과는 PR 체크에서 확인한다.
- Termux Native aarch64 및 proot: 경로/환경 분기 회귀만 수행. 실제 Android 장치 검증은 수행하지 않았다.
- 네트워크 저장매체 무응답, 수십 GB 장시간 녹화, 자연 CDN 장애/메모리 장시간 부하는 미검증이다.
- CHZZK/YouTube는 기존 JSON url 필드를 유지하되 값은 서버의 불투명한 프록시 경로다. 원본 서명 URL은 브라우저에 반환하지 않는다. CIME/SOOP 프레임 API도 서명 URL·쿠키를 반환하지 않는다. 프록시 재생 검증은 실제 합성 HLS를 사용했고 모든 실제 CDN/인증 방송의 장시간 재생을 검증한 것은 아니다.
- 독립 frontend ESLint 설정/명령은 기존 저장소에 없다. TypeScript 검사·실제 브라우저 테스트를 실행했다.
