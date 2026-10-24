# 저장소 (SQLite)

v2.0.0부터 영속 상태를 SQLite 파일 하나로 통합했다.

## 위치

| 실행 방식 | 경로 |
|-----------|------|
| `.exe` (PyInstaller) | `<exe 폴더>/data/phrolova.db` |
| 개발 환경 | `backend/data/phrolova.db` |
| Docker | `/app/backend/data/phrolova.db` (`./data` 볼륨에 마운트) |

`sqlite3`는 Python 표준 라이브러리이므로 단일 exe 빌드나 리눅스 설치에
추가 요구사항이 생기지 않는다.

WAL 모드로 동작하므로 실행 중에는 `phrolova.db-wal`,
`phrolova.db-shm` 파일이 함께 존재한다. 앱을 정상 종료하면
WAL이 본 파일로 합쳐지므로, **백업은 앱을 종료한 뒤 `.db` 파일 하나만
복사하면 된다.**

## 테이블

| 테이블 | 용도 | 이전 파일 |
|--------|------|-----------|
| `channels` | 감시 채널, 자동 녹화·화질·출력 형식 설정 | `channels.json` |
| `app_settings` | 녹화 완료 후 저장 형식·원본 보관·변환 동시 실행 수 | — |
| `recording_jobs` | TS 원본·후처리 상태·최종 파일·검사·재시도 | — |
| `live_history` | 녹화 완료 세션 이력 | `live_history.json` |
| `live_detections` | 라이브 감지 날짜 (하루 1회) | *메모리 전용이라 재시작 시 소실됐음* |
| `vod_tasks` | VOD 다운로드 작업 이력 | `vod_history.json` |
| `tags` | 사용자 정의 태그 목록 | `user_preferences.json` |
| `pending_notifications` | 아직 전송하지 못한 Discord 알림 | `pending_notifications.json` |
| `meta` | 마이그레이션 수행 여부 등 내부 상태 | — |

## 기존 데이터 이관

업그레이드 후 **첫 실행 때 한 번만** 자동으로 수행된다.

- 대상 테이블이 비어 있을 때만 옮긴다. 이미 데이터가 있으면 덮어쓰지 않는다.
- 원본 JSON은 **삭제하지 않고** `.migrated` 접미사를 붙여 보관한다.
  (예: `channels.json` → `channels.json.migrated`)
- 한 파일이 깨져 있어도 나머지 파일은 계속 이관한다.
- 완료되면 `meta` 테이블에 기록되어 다시 실행되지 않는다.

레거시 채널 키(`:` 없는 구버전 Chzzk 키)는 이관 과정에서
`chzzk:<채널ID>` 형식으로 자동 변환된다.

브랜드 DB 이전은 `rookery.db`, 그 다음 `signal_recorder.db`를 탐지합니다. 새 `phrolova.db`가 이미 있으면 덮어쓰지 않습니다. SQLite 백업 API는 커밋된 WAL을 포함한 일관된 복사본을 만들고 무결성을 검사합니다. 열린 원본이나 WAL/SHM의 이름을 바꾸지 않습니다. 실패하면 원본 DB를 계속 사용하며 오류를 기록합니다.

원본 DB는 복구용으로 보존합니다. 새 버전에서 추가된 데이터까지 이전 버전으로 가져가려면 앱을 정상 종료한 뒤 SQLite backup으로 새 DB를 레거시 이름의 별도 복사본으로 백업하세요. 원본이나 새 DB를 삭제하지 마세요. 중단된 임시 `.phrolova-migration-*` 파일은 게시되지 않으므로 재실행은 원본에서 다시 시작합니다.

## 스키마 버전 관리

`PRAGMA user_version`으로 관리한다. 새 마이그레이션은
`app/store/schema.py`의 `MIGRATIONS` 리스트에 `(버전, DDL)` 항목을
**append만** 한다. 이미 배포된 항목은 수정하지 않는다 —
사용자의 DB는 되돌릴 수 없기 때문이다.

## 코드 구조

```
app/store/
├── db.py            # 커넥션 관리, 트랜잭션, 전역 인스턴스
├── schema.py        # DDL 및 스키마 버전 마이그레이션
├── repositories.py  # 도메인별 SQL (Channel / LiveHistory / Vod / Tag / Notification)
└── migrate_json.py  # 레거시 JSON 일회성 이관
```

엔진/서비스 계층은 SQL을 직접 다루지 않고 레포지토리만 호출한다.
레포지토리는 모두 동기 메서드다 — SQLite 쓰기는 마이크로초 단위라
이벤트 루프를 막지 않으며, 기존 JSON 전체 재작성보다 오히려 빠르다.

## 테스트

`tests/conftest.py`의 `isolated_database` 픽스처가 모든 테스트에
임시 DB를 주입한다. 테스트가 실제 사용자 DB를 건드릴 일은 없다.
