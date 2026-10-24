# Phrolova 리브랜딩 검수 결과

작업 브랜치: `feature/phrolova-rebrand`. 기준: 게시된 v2.0.51 소스. 버전은 2.0.51 그대로 유지했습니다. 검수 완료 당시 원격 push·태그·Release는 수행하지 않았으며, 이후 사용자 승인으로 GitHub main에 반영합니다. 태그·Release는 이번 승인 범위에 포함하지 않습니다.

## 변경 및 보존

- `rookery.spec` → `phrolova.spec`; EXE 이름, FileDescription, InternalName, ProductName, OriginalFilename을 Phrolova로 변경했습니다. 버전 정보는 `backend/app/version.py`에서 가져옵니다. CompanyName·LegalCopyright·LICENSE·기여자 표기는 보존했습니다.
- Release 워크플로 빌드·Defender·해시·이름 변경 경로는 `dist/Phrolova.exe`; 최종 아티팩트는 기존 `Phrolova-버전-windows-x64.exe` 형식입니다. 아이콘, 번들 구성, FFmpeg/FFprobe 탐색은 유지했습니다.
- Windows 트레이 내부 식별자와 표시명을 Phrolova로 변경했습니다. 시작·종료 구현은 변경하지 않았습니다.
- npm package 및 lockfile 루트 이름을 phrolova로 변경하고 npm으로 lockfile을 갱신했습니다. 웹 제목은 이미 Phrolova였으며 그대로 유지합니다. UpdateModal의 Linux 안내 명령만 phrolova로 변경했습니다. 언어·테마 localStorage 키 및 기존 사용자 설정은 보존했습니다.
- Linux APP_NAME/SERVICE_NAME은 phrolova, 기본 설치 디렉터리는 별도 상수 `~/Phrolova`입니다. 명시적 INSTALL_DIR → 실행 중인 저장소 → 기존 기본 설치 디렉터리 순으로 결정합니다. 구형 디렉터리는 이동·삭제하지 않습니다.
- 새 명령 링크가 등록된 후 동일 설치본의 manage.sh를 가리키는 구형 링크만 제거합니다. 실제 파일·다른 설치본 링크는 보존합니다. 심볼릭 링크로 명령을 호출해도 실제 스크립트 경로를 해석합니다.
- systemd Description은 `Phrolova - Live Stream Recorder`. 구형 유닛의 활성화·실행 상태를 기록하고 중지한 뒤 새 유닛을 등록합니다. 등록 또는 /health 확인 실패 시 새 유닛을 복구/제거하고 이전 상태를 복원합니다. 이전 유닛 파일은 비활성 상태로 보존합니다. 경로에 공백이 있어도 unit 경로를 따옴표로 처리합니다.

## DB 이전과 복구

새 DB는 `phrolova.db`입니다. 기존 새 이름 DB가 있으면 우선 사용하며 덮어쓰지 않습니다. 없으면 `rookery.db`, 다음 `signal_recorder.db`를 탐지합니다.

기존 DB를 rename하지 않습니다. SQLite writer lock을 예약하고 읽기 연결의 backup API로 커밋된 WAL을 포함하는 일관된 임시 복사본을 생성합니다. quick_check와 파일 fsync 후 같은 디렉터리에서 hard link로 원자적·덮어쓰기 없는 게시를 수행합니다. 복사 연결과 잠금 연결을 닫고 임시 파일을 정리합니다. 원본 DB는 복구용으로 보존합니다. 실패하면 오류를 기록하고 원본 DB를 계속 사용하므로 새 빈 DB로 전환하지 않습니다. 손상된 원본은 연결 실패로 드러나며 조용히 초기화하지 않습니다.

중단된 임시 파일은 다음 실행에서 신뢰하지 않으며 원본에서 다시 복사합니다. 게시된 새 DB가 있으면 재실행 시 그대로 사용합니다. WAL/SHM 자체를 위험하게 이름 변경하지 않습니다. 채널·태그·라이브 이력·VOD 작업 payload·대기 알림·스키마 보존을 테스트했습니다.

**업데이트 전에 모든 이전 버전 서버를 정상 종료하세요.** 스냅샷 이후 옛 프로세스가 계속 쓰는 상황에서 두 버전의 DB를 동기화하는 기능은 없습니다. hard link를 지원하지 않는 공유 파일 시스템에서는 이전이 실패할 수 있으며 원본을 계속 사용하고 로그에 알립니다. 일반 Windows NTFS/Linux/Termux 내부 저장소의 실제 하드웨어 조합은 별도 검증이 필요합니다.

되돌릴 때 앱을 종료하고 새 DB까지 백업하세요. 새 버전에서 추가된 데이터가 필요하면 SQLite backup으로 레거시 이름의 별도 복사본을 만드세요. 보존된 원본은 이전 시점의 복구 자료입니다. 원본·설정·다운로드 파일을 삭제하지 않습니다.

## 레거시 문자열 분류

`git grep -n -i rookery`와 과거 제품명 검색을 전체 tracked 소스에 수행했습니다. 현재 공식 제품 식별자로 사용하는 항목은 제거했습니다. 남은 참조는 다음과 같습니다.

| 파일 | 보존 사유 |
|---|---|
| backend/app/store/db.py | 이전 DB 파일명 탐지 |
| scripts/manage.sh | 이전 설치 경로·관리 명령·서비스 탐지 |
| scripts/healthcheck.sh | 이전 설치·DB 읽기 전용 점검 |
| frontend/src/contexts/ThemeContext.tsx | 과거 기본 제목만 Phrolova로 이전; 사용자 정의 제목 보존 |
| backend/tests/test_store.py, test_rebranding.py | 실제 구형 설치·DB·서비스 호환성 테스트 |
| backend/tests/test_release_metadata.py | 구형 트레이 식별자 재도입 방지 |
| README.md, docs/storage.md, docs/termux-guide.md, docs/linux-guide.md | 기존 사용자의 이전 안내 |
| docs/CHANGELOG.md, docs/checklist.md | 과거 릴리스 실제 이름·해시·실행 기록; 역사적 사실 보존 |
| docs/compatibility-audit-ko.md, audit-evidence/* | 이전 검수의 문제·원본 로그·파일 목록 보존 |
| docs/rebranding-audit-ko.md | 이번 검색·처리 근거 |

기존 `signal-recorder`, `chzzk-recorder-pro`, `signal_recorder.db` 참조도 설치 호환성 또는 역사 기록에만 남겼습니다. 저작권 귀속은 변경하지 않았습니다.

## 실행한 검증

| 명령/검증 | 결과 |
|---|---|
| cd backend && python -m pytest tests -q | **500 passed, 2 warnings**, 실패/skip 없음 |
| 브랜드·저장소·배포 메타데이터 집중 테스트 | 45 passed |
| python -m compileall -q backend | 통과 |
| python -m pip check | No broken requirements found |
| npm install --package-lock-only --ignore-scripts --offline | 통과; 루트 이름만 변경 |
| cd frontend && npm ci | 통과, 151 packages 설치 |
| cd frontend && npx tsc --noEmit | 통과 |
| cd frontend && npm run build | 통과; backend/app/static 출력. 기존 큰 JS chunk 경고 |
| bash -n scripts/manage.sh scripts/healthcheck.sh | 통과 |
| 격리 Bash mock | 신규/구형 설치 탐지·INSTALL_DIR 우선·링크 전환·서비스 성공/실패 롤백·start/stop/restart/logs·update 자동 재시작·서비스 삭제 통과 |
| 브라우저 VOD 준비 목록 | 실제 Chromium 390/1440, 드롭·다중 입력·품질·시작·취소·재시도·정리·번역 통과 (API mock) |
| 기존 브라우저 회귀 | 필터 재정렬, 320/390/820/1024/1440 레이아웃·실제 로컬 HLS 플레이어 유지 통과 |
| scripts/audit-posix.py | 실제 Linux 서버 /health·SPA·SSE·태그 저장·로컬 VOD 다운로드/취소·설정 저장·재시작 DB/이력 유지·SIGTERM/SIGINT 통과 |
| 실제 로컬 Streamlink → FFmpeg | 12.023222초 TS 생성, MP4/MKV remux 통과 |
| git diff --check | 통과 |

유한 모의 HLS의 종료는 기존 라이브 재연결 요청 상태 `RecordingState.ERROR`를 발생시킵니다. 이는 수신·미디어 출력 검증이며 무중단 장시간 방송 검증이 아닙니다.

초기 오프라인 npm ci는 yallist 캐시 부족으로 ENOTCACHED 실패했습니다. 정상 npm ci로 재시도하여 통과했습니다. 새 테스트 작성 중 mock의 선택 인자 처리와 테스트 변수 이름 충돌을 수정했습니다. 최종 테스트 실패는 없습니다. 두 Python 경고는 기존 외부 패키지의 폐기 예정 API 경고입니다. 의존성 버전은 변경하지 않았습니다.

## 미검증과 제한

- Windows 환경이 없어 `python -m PyInstaller --clean --noconfirm phrolova.spec` 실제 Windows 빌드, PE 메타데이터·트레이·Defender 실행은 수행하지 못했습니다. 파일/버전/워크플로 경로는 자동 테스트로 검증했습니다. `dist/Phrolova.exe` 생성 성공으로 보고하지 않습니다.
- 컨테이너에 systemd PID1이 없어 실제 서비스 등록·부팅은 실행하지 않았습니다. 격리 mock으로 상태 전환/롤백과 unit 내용을 검증했습니다.
- 이번 변경의 실제 Android Termux/ARM64/Windows 장치 및 외부 CHZZK/CDN 다운로드는 미검증입니다. 이전 사용자의 Termux 성공과 구별합니다.
- API와 다운로드 엔진 변경이 없고 회귀 테스트는 통과했지만, 실제 플랫폼 인증·방송·장기 운영은 별도 확인이 필요합니다.

## 변경 파일 목록

`rookery.spec` → `phrolova.spec` 이름 변경 외에는 동일 경로에서 수정했습니다. 아래 목록 중 app의 헤더 파일은 제품 표기만 변경했습니다.

- `.env.example`
- `.github/workflows/release.yml`
- `CONTRIBUTING.md`
- `README.md`
- `backend/app/api/archive.py`
- `backend/app/api/platforms.py`
- `backend/app/api/setup.py`
- `backend/app/api/stats.py`
- `backend/app/api/stream.py`
- `backend/app/api/system.py`
- `backend/app/api/tags.py`
- `backend/app/api/vod.py`
- `backend/app/core/config.py`
- `backend/app/core/http.py`
- `backend/app/core/logger.py`
- `backend/app/core/utils.py`
- `backend/app/engine/auth.py`
- `backend/app/engine/base.py`
- `backend/app/engine/channel.py`
- `backend/app/engine/conductor.py`
- `backend/app/engine/downloader.py`
- `backend/app/engine/events.py`
- `backend/app/engine/spaces_recorder.py`
- `backend/app/engine/updater.py`
- `backend/app/engine/vod.py`
- `backend/app/engine/youtube.py`
- `backend/app/main.py`
- `backend/app/services/discord_bot/service.py`
- `backend/app/services/notifications.py`
- `backend/app/services/recorder.py`
- `backend/app/store/__init__.py`
- `backend/app/store/db.py`
- `backend/app/store/migrate_json.py`
- `backend/app/store/repositories.py`
- `backend/app/store/schema.py`
- `backend/app/version.py`
- `backend/run.py`
- `backend/tests/__init__.py`
- `backend/tests/test_config.py`
- `backend/tests/test_rebranding.py`
- `backend/tests/test_release_metadata.py`
- `backend/tests/test_store.py`
- `docs/CHANGELOG.md`
- `docs/checklist.md`
- `docs/linux-guide.md`
- `docs/rebranding-audit-ko.md`
- `docs/storage.md`
- `docs/termux-guide.md`
- `docs/test-guide.md`
- `docs/x-spaces-guide.md`
- `frontend/package-lock.json`
- `frontend/package.json`
- `frontend/src/components/ui/UpdateModal.tsx`
- `phrolova.spec`
- `scripts/healthcheck.sh`
- `scripts/manage.bat`
- `scripts/manage.sh`
