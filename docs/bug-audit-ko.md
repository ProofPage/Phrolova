# Phrolova 전체 코드 검수 및 수정 보고서

검수일: 2026-10-09. 기준 커밋: `6ab47df01a7ddf4fedbba039b4f7cb17c2db1557`.
수정은 별도 작업 트리에서 수행했으며 GitHub push 및 배포는 하지 않았다.

## A. 전체 분석 결과

백엔드 API, 설정/로그, SQLite 저장소, Conductor/채널 수명주기, FFmpeg/Streamlink/yt-dlp, DASH/HLS/X Spaces, 채팅 저장/검색, 프론트엔드 API·상태·플레이어, 실행/설치 스크립트, 의존성 및 GitHub Actions를 조사했다. 정상 동작 중인 재생 방식과 API 형식을 유지하면서 재현 가능한 결함을 우선 수정했다. 모든 외부 플랫폼·운영체제의 모든 경로를 실행 검증했다는 의미는 아니다.

아래 표 기준 수정 항목 20건: Critical 0, High 5, Medium 14, Low 1. 독립 항목 묶음 기준이며 테스트나 보안 자문 개수와 다르다. 별도로 Python 의존성의 미해결 위험 1건을 기록한다. 프론트엔드 npm 감사는 기존 14건에서 0건으로 감소했다.

## B. 발견 및 수정된 문제

| # | 심각도 | 파일·함수 | 원인 / 증상 | 수정·검증 |
|---|---|---|---|---|
| 1 | Medium | `backend/app/api/stream.py::_to_composite_key` | YouTube 키가 치지직 키로 변환되어 수동 조작 실패 | youtube 접두사 보존; 회귀 테스트 |
| 2 | Medium | `backend/app/api/archive.py::clear_captured_space` | 존재하지 않는 메서드 호출로 500 및 캡처 상태 미저장 | 실제 상태 저장·브로드캐스트 호출; API 테스트 |
| 3 | High | `backend/app/engine/conductor.py::remove_channel, stop` | 채널 참조를 먼저 제거하거나 감시 종료를 기다리지 않아 녹화·채팅이 남음 | 감시 취소/대기 후 참조 유지한 채 프로세스·채팅 정리; 회귀 테스트 |
| 4 | Medium | `engine/channel.py`, `conductor.py::_start_recording, _stop_recording` | 동시 시작/중단 경쟁으로 프로세스 교체·중복 생성 | 채널별 asyncio 잠금과 상태 재검사; 중복 시작 테스트 |
| 5 | Medium | `engine/vod.py` MPD 패치 | 모듈 재로드 시 래퍼가 자신을 호출하여 재귀 오류 | 원본 함수 클로저·중복 적용 표식; 실제 별도 Python 프로세스 재로드 테스트 |
| 6 | Medium | `engine/vod.py::_run_download` | 재시도 대기 중 취소 시 CANCELLING 상태에 고착 | finally에서 상태·기록 정리; 취소/재시작 테스트 |
| 7 | Medium | `engine/vod.py::_attempt_download` | 메타데이터 조회 중 취소해도 실제 다운로드 진입 | 조회 완료 후 취소 확인·상태 저장; 모의 추출기 테스트 |
| 8 | Medium | `engine/vod.py::reorder` | 중복 ID로 큐 작업 유실 및 순서 미저장 | 중복 거부 및 순서 저장; 회귀 테스트 |
| 9 | High | `engine/vod.py` URL 검증 | 로컬 파일·비 HTTP 프로토콜 입력 허용 | HTTP(S), 호스트, 사용자정보 검증; 4종 잘못된 입력 테스트. 사설 HTTP 주소는 허용하며 완전한 SSRF 방어는 아님 |
| 10 | Medium | `engine/vod.py` X Spaces 재생 다운로드 | 중첩 재생목록 상대 URI 기준 오류 및 출력명 충돌 | urljoin, KEY/MAP URI 처리, UUID 파일명·취소 추적; 모의 재생목록 테스트 |
| 11 | High | `api/chat.py` 경로 검증 | 녹화 루트의 일반 파일이나 외부를 가리키는 심볼릭 링크 노출 가능 | jsonl/실제 파일/루트 경계 검증; 확장자·경로 테스트 |
| 12 | Medium | `api/chat.py` 메시지 파싱·페이지 읽기 | JSON scalar/잘못된 타입으로 오류, 쓰는 중인 마지막 줄이 인덱스와 불일치 | 메시지 타입 검증 및 완전한 줄만 읽기; 필터/비필터 회귀 테스트 |
| 13 | High | `core/utils.py::update_env_file`, `api/settings/media.py` | 값의 개행이 새 설정 행을 삽입하고 중복 키가 이전 값을 덮음; 쓰기 실패 시 손상 | 값 인용·키 검증·중복 갱신·멀티라인 보존·잠금·원자 교체; CRLF/실패 보존 테스트 |
| 14 | High | `app/main.py`, `core/config.py`, `frontend/vite.config.ts` | 임의 웹 출처 접근 허용 및 개발 서버 전체 인터페이스 노출 | 명시적 로컬 CORS, 쓰기 전 Origin 검사, dev loopback; 외부 출처 거부·동일 출처/CLI 테스트. 인증 기능을 대체하지 않음 |
| 15 | Medium | `core/logger.py::_SecretSafeFormatter` | 인증 쿠키·헤더·토큰 URL이 진단 로그에 포함 가능 | 출력 단계 URL/헤더/알려진 쿠키 마스킹; 비밀값 불포함 테스트 |
| 16 | Medium | `engine/pipeline/ffmpeg.py` | stderr를 읽지 않아 파이프가 차면 멈춤; ERROR를 완료로 덮음; 미디어 파이프에 q 삽입 | 동시 제한된 stderr 수집, stdout 폐기, 오류 보존, EOF 종료; 실제 자식 프로세스 300KB stderr 및 FFmpeg 테스트 |
| 17 | Medium | `engine/pipeline/ytdlp.py` | 의도적 종료 EOF를 재연결 오류로 표시; 취소된 to_thread의 늦게 열린 핸들 누수 | 종료 의도 확인 및 늦은 reader/session 정리; 취소 타이밍 회귀 테스트·실제 HLS |
| 18 | Medium | `engine/spaces_recorder.py`, `engine/x_spaces/engine.py` | stdout/stderr 파이프 적체 및 kill 이후 미수거, 파일명 제어문자 | 출력 drain/폐기, kill 후 wait, 공통 파일명 정리; 테스트·코드 검증 |
| 19 | Medium | `store/repositories.py::VodRepository.replace_all` | 개별 커밋 후 실패하면 기록 일부만 바뀜 | 단일 트랜잭션으로 upsert 및 삭제; 실패 시 전체 롤백 테스트 |
| 20 | Low | `app/main.py` SPA fallback; 프론트 `VodContext.tsx`, `api/client.ts`; lockfile | 폰트 요청이 HTML로 반환, 상태 요청 중첩, 알려진 npm 취약 버전 | 실제 정적 파일 제공, 진행 중 요청 공유·10초 타임아웃, 범위 내 lock 업데이트; 폰트 wOF2 검사·tsc/build·npm audit |

`core/utils.py::clean_filename`도 C0 제어문자를 제거한다. 변경은 기존 설정/DB/녹화 파일을 삭제하거나 초기화하지 않는다. 원본 파일의 줄바꿈 형식을 유지했다.

### 해결되지 않은 의존성 위험

현재 최신 `chzzkpy==2.2.0`이 `aiohttp==3.12.13`, `idna==3.10` 등 버전을 정확히 고정한다. pip-audit에서 이 버전에 알려진 보안 자문이 보고되었다. 강제 업데이트나 `--no-deps` 설치는 의존성 계약을 깨므로 적용하지 않았다. 상위 패키지의 수정 릴리즈 또는 검증된 포크가 필요하다. aiohttp 자문 중 서버 전용 결함은 클라이언트 사용 경로에 그대로 적용되지 않으므로 자문 개수를 실제 취약점 개수로 간주하지 않았다.

감사 대상 설치 목록에서 aiohttp 66, idna 2, pip 12개 항목이 출력되었으나 중복 자문이 포함된다. pip는 프로젝트 런타임 의존성이 아닌 설치 도구다. Termux 관리 pip를 무조건 자체 업그레이드하도록 변경하지 않았다. Python 런타임 의존성 변경은 없다.

## C. 테스트 결과

실행 환경은 Linux x86_64/Python 3.12.14다.

| 명령/검증 | 결과 |
|---|---|
| `python -m pytest -c backend/pytest.ini backend/tests -q` | 412 passed, 2 warnings, skipped 없음 |
| 새 `backend/tests/test_bug_audit.py` | 29개 회귀 테스트 통과; 최초 13개는 수정 전 모두 실패 |
| 기존 API 테스트 | 클라이언트/격리 fixture를 복구하여 이전에 건너뛴 29개를 실제 실행 |
| `python -m compileall -q backend/app backend/tests` | 통과 |
| `python -m pip check` | No broken requirements found |
| `cd frontend && npx tsc --noEmit -p tsconfig.json` | 통과 |
| `cd frontend && npm run build` | 통과; 큰 번들 경고는 남음 |
| `npm audit --json` | 알려진 취약점 0 |
| `bash -n scripts/*.sh`, `git diff --check` | 통과 |
| 로컬 FastAPI /health·SPA·API·SSE, 설정 저장 | 통과 |
| 로컬 모의 영상의 실제 yt-dlp 다운로드·취소 | 통과 |
| SIGTERM·SIGINT 종료 및 DB/환경설정 재시작 유지 | 통과 |
| 실제 Streamlink HLS→FFmpeg TS 및 MP4/MKV remux | 통과; ffprobe로 약 12초 영상 확인 |

유한 모의 HLS의 자연 EOF는 기존 라이브 재연결 정책에 따라 ERROR 상태로 분류된다. 파일 생성/미디어 검증 성공과 라이브 종료 상태를 구분했다. 실제 방송의 무단·장시간 녹화는 하지 않았다.

테스트 경고 2건은 Starlette TestClient/httpx와 discord audioop의 사용 중단 경고다. 빌드 경고는 500KB 초과 번들이다. 모두 숨기지 않았다.

새 변경 사항의 Windows, Linux ARM64, Native Termux, proot 실행 및 실제 플랫폼 인증/YouTube/X Spaces 통신은 직접 검증하지 못했다. X Spaces 상대 URI와 취소는 모의 테스트다. 프론트엔드 요청 공유는 컴파일/빌드 검증이며 실제 모바일 브라우저 자동화 검증은 하지 않았다. 이전 사용자의 Termux 설치·녹화·재생·재시작 성공은 기존 버전의 검증이고 새 패치의 기기 검증을 대신하지 않는다.

## D. 변경 파일 목록

- API: `archive.py`, `chat.py`, `settings/media.py`, `stream.py`.
- 공통: `core/config.py`, `core/logger.py`, `core/utils.py`, `app/main.py`.
- 엔진: `channel.py`, `conductor.py`, `pipeline/ffmpeg.py`, `pipeline/ytdlp.py`, `spaces_recorder.py`, `vod.py`, `x_spaces/engine.py`.
- 저장소: `store/repositories.py`.
- 테스트: `conftest.py`, `test_api_settings.py`, `test_api_stream.py`, `test_api_vod.py`, `test_download_condition.py`, `test_pipeline.py`, 새 `test_bug_audit.py`.
- 프론트: `package-lock.json`, `src/api/client.ts`, `src/contexts/VodContext.tsx`, `vite.config.ts`.
- 문서: 이 보고서.

프론트 package.json 범위는 유지했다. lockfile에서 axios 1.20.0, Vite 6.4.4, React Router 7.18.4, Rollup 4.64.3 등 호환 범위 내 업데이트를 적용했다. Node.js는 빌드에 필요하며 빌드 산출물을 FastAPI에서 제공할 때 별도 Node 서버가 필요하지 않다.

## E. 최종 평가

확인한 결함은 실제 수정하고 회귀·실행 검증했다. 전체 코드에 결함이 전혀 없다는 보장은 하지 않는다. 재생·다운로드 구조와 기존 API 계약을 유지했으며 사용자 데이터는 초기화하지 않았다.

새 버전은 Linux x86_64 로컬 운영 테스트를 통과했다. Termux에는 기존 성공 경험과 호환성을 유지하는 코드 근거가 있지만 새 버전은 조건부 지원이며 기기 재검증이 필요하다. 특히 종료 도중 Streamlink 연결 스레드는 소켓 타임아웃까지 기다릴 수 있다. Android 강제 종료·절전 정책, 발열·장시간 녹화는 이 테스트로 보장할 수 없다.

공개 서버 운영 준비 완료로 판정하지 않는다. 기본 loopback을 유지하고, 외부 공개 전 인증/프록시 접근 통제와 미해결 Python 의존성 위험을 해결해야 한다. Origin 검사는 인증을 대체하지 않으며 사설 HTTP URL 접근도 별도 배포 정책이 필요하다. GitHub에는 아직 아무 변경도 push하지 않았다.
