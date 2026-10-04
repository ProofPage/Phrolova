"""
Rookery: SQLite 스키마 정의 및 마이그레이션

스키마 버전은 SQLite의 `PRAGMA user_version`으로 관리한다.
새 버전을 추가할 때는 MIGRATIONS에 (버전, DDL) 항목을 append 하기만 하면 되며,
기존 항목은 절대 수정하지 않는다. (이미 배포된 DB가 되돌아갈 수 없기 때문)
"""

from __future__ import annotations

import sqlite3

#: 순차 적용되는 마이그레이션. (target_version, SQL) 형태이며 버전은 1부터 시작한다.
MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
        -- 감시 대상 채널
        CREATE TABLE IF NOT EXISTS channels (
            composite_key           TEXT PRIMARY KEY,
            platform                TEXT NOT NULL,
            channel_id              TEXT NOT NULL,
            auto_record             INTEGER NOT NULL DEFAULT 1,
            tags                    TEXT NOT NULL DEFAULT '[]',
            captured_m3u8_url       TEXT,
            captured_m3u8_at        TEXT,
            master_url              TEXT,
            master_url_captured_at  TEXT,
            master_url_file         TEXT,
            created_at              TEXT NOT NULL DEFAULT (datetime('now'))
        );

        -- 녹화 완료 세션 이력
        CREATE TABLE IF NOT EXISTS live_history (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            composite_key       TEXT NOT NULL,
            platform            TEXT NOT NULL,
            channel_id          TEXT NOT NULL,
            channel_name        TEXT,
            started_at          TEXT,
            ended_at            TEXT NOT NULL,
            duration_seconds    REAL NOT NULL DEFAULT 0,
            file_size_bytes     INTEGER NOT NULL DEFAULT 0,
            output_path         TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_live_history_key ON live_history(composite_key);
        CREATE INDEX IF NOT EXISTS idx_live_history_ended ON live_history(ended_at);

        -- 라이브 감지 이력 (하루 1회 카운트).
        -- 기존에는 메모리에만 있어 재시작할 때마다 통계가 초기화됐다.
        CREATE TABLE IF NOT EXISTS live_detections (
            composite_key   TEXT NOT NULL,
            detected_on     TEXT NOT NULL,
            PRIMARY KEY (composite_key, detected_on)
        );

        -- VOD 다운로드 작업 이력
        CREATE TABLE IF NOT EXISTS vod_tasks (
            task_id         TEXT PRIMARY KEY,
            url             TEXT NOT NULL,
            title           TEXT,
            quality         TEXT,
            state           TEXT NOT NULL,
            progress        REAL NOT NULL DEFAULT 0,
            output_path     TEXT,
            error_message   TEXT,
            created_at      TEXT,
            started_at      TEXT,
            completed_at    TEXT,
            payload         TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_vod_tasks_created ON vod_tasks(created_at);

        -- 사용자 정의 태그
        CREATE TABLE IF NOT EXISTS tags (
            name        TEXT PRIMARY KEY,
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );

        -- 아직 전송하지 못한 알림
        CREATE TABLE IF NOT EXISTS pending_notifications (
            id              TEXT PRIMARY KEY,
            kind            TEXT NOT NULL,
            title           TEXT NOT NULL,
            description     TEXT NOT NULL DEFAULT '',
            color           TEXT NOT NULL DEFAULT 'green',
            fields          TEXT NOT NULL DEFAULT '{}',
            created_at      REAL NOT NULL,
            attempts        INTEGER NOT NULL DEFAULT 0,
            next_attempt_at REAL NOT NULL DEFAULT 0
        );

        -- 마이그레이션 수행 여부 등 내부 상태
        CREATE TABLE IF NOT EXISTS meta (
            key     TEXT PRIMARY KEY,
            value   TEXT NOT NULL
        );
        """,
    ),
    (
        2,
        """
        -- 채팅 로그(.jsonl) 조회용 파생 인덱스.
        --
        -- 원본 파일은 그대로 두고 줄 수와 체크포인트 바이트 위치만 캐시한다.
        -- 이게 없으면 목록 화면이 열릴 때마다 모든 로그를 끝까지 읽어야 하고,
        -- 페이지 한 장을 넘기려고 파일 전체를 파싱해야 했다.
        --
        -- 언제든 버려도 되는 데이터다. 행이 없거나 파일과 어긋나면
        -- 그 파일만 다시 훑어서 채운다.
        CREATE TABLE IF NOT EXISTS chat_file_index (
            path            TEXT PRIMARY KEY,
            message_count   INTEGER NOT NULL DEFAULT 0,
            offsets         TEXT NOT NULL DEFAULT '[]',
            scanned_bytes   INTEGER NOT NULL DEFAULT 0
        );
        """,
    ),
]

#: 코드가 기대하는 최신 스키마 버전.
LATEST_VERSION = MIGRATIONS[-1][0] if MIGRATIONS else 0


def apply_migrations(conn: sqlite3.Connection) -> int:
    """현재 DB 버전부터 최신까지 순차 적용하고 적용된 개수를 반환한다."""
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    applied = 0

    for version, sql in MIGRATIONS:
        if version <= current:
            continue
        conn.executescript(sql)
        # PRAGMA는 파라미터 바인딩을 지원하지 않지만, version은 코드 내 정수 상수다.
        conn.execute(f"PRAGMA user_version = {int(version)}")
        conn.commit()
        applied += 1

    return applied
