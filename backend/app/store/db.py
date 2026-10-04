"""
Rookery: SQLite 연결 관리

JSON 파일 여러 개로 흩어져 있던 영속 상태를 단일 DB 파일로 통합한다.
sqlite3는 Python 표준 라이브러리이므로 단일 exe 빌드나 리눅스 설치에
새로운 요구사항을 추가하지 않는다.

동시성:
    커넥션 하나를 프로세스 전역에서 공유하고 RLock으로 보호한다.
    VOD 다운로드의 yt-dlp 진행률 콜백이 워커 스레드에서 실행되므로
    check_same_thread=False가 필요하다.

내구성:
    WAL 모드 + synchronous=NORMAL. 녹화 중 전원이 꺼져도 DB가 깨지지 않고,
    JSON 전체 재작성(수백 KB)보다 쓰기 비용이 훨씬 작다.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional, Sequence

from app.core.config import resolve_data_dir
from app.core.logger import logger
from app.store.schema import LATEST_VERSION, apply_migrations

DB_FILENAME = "rookery.db"
# Rookery로 이름을 바꾸기 전에 쓰던 파일명.
LEGACY_DB_FILENAME = "signal_recorder.db"


class Database:
    """SQLite 커넥션 래퍼.

    사용법:
        db = Database(path)
        db.connect()
        with db.transaction() as conn:
            conn.execute(...)
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.RLock()

    @property
    def path(self) -> Path:
        return self._path

    # ── 라이프사이클 ────────────────────────────────────

    def connect(self) -> sqlite3.Connection:
        """커넥션을 열고 스키마를 최신 버전으로 맞춘다."""
        with self._lock:
            if self._conn is not None:
                return self._conn

            self._path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(
                self._path,
                check_same_thread=False,
                isolation_level=None,  # 트랜잭션을 명시적으로 제어한다
                timeout=10.0,
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.execute("PRAGMA foreign_keys = ON")
            # 다른 스레드가 쓰기 중이면 즉시 실패하지 않고 대기한다.
            conn.execute("PRAGMA busy_timeout = 10000")

            self._conn = conn

            applied = apply_migrations(conn)
            if applied:
                logger.info(
                    f"🗃️ DB 스키마 마이그레이션 적용: {applied}건 (v{LATEST_VERSION})"
                )
            logger.info(f"🗃️ 저장소 연결: {self._path}")
            return conn

    def close(self) -> None:
        """커넥션을 닫는다."""
        with self._lock:
            if self._conn is None:
                return
            try:
                # WAL 파일을 본 DB로 합쳐 두면 백업/복사가 단순해진다.
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception as e:
                logger.warning(f"WAL 체크포인트 실패: {e}")
            try:
                self._conn.close()
            finally:
                self._conn = None
            logger.info("🗃️ 저장소 연결 종료.")

    # ── 실행 헬퍼 ───────────────────────────────────────

    def _require(self) -> sqlite3.Connection:
        if self._conn is None:
            return self.connect()
        return self._conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """쓰기 트랜잭션. 예외 발생 시 롤백한다."""
        conn = self._require()
        with self._lock:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            else:
                conn.execute("COMMIT")

    def execute(self, sql: str, params: Sequence[Any] = ()) -> None:
        """단일 쓰기 문을 실행한다."""
        with self.transaction() as conn:
            conn.execute(sql, params)

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        """조회 결과를 리스트로 반환한다."""
        conn = self._require()
        with self._lock:
            return conn.execute(sql, params).fetchall()

    def query_one(self, sql: str, params: Sequence[Any] = ()) -> Optional[sqlite3.Row]:
        """첫 행을 반환한다. 없으면 None."""
        conn = self._require()
        with self._lock:
            return conn.execute(sql, params).fetchone()

    # ── meta 테이블 ─────────────────────────────────────

    def get_meta(self, key: str) -> Optional[str]:
        row = self.query_one("SELECT value FROM meta WHERE key = ?", (key,))
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


# ── 프로세스 전역 인스턴스 ───────────────────────────────

_database: Optional[Database] = None
_database_lock = threading.Lock()


def _resolve_db_path(data_dir: Path) -> Path:
    """사용할 DB 경로를 정하고, 구버전 파일이 있으면 새 이름으로 옮긴다.

    backend/data/는 gitignore 대상이라 DB는 사용자 로컬에만 존재한다.
    파일명 상수만 바꾸면 빈 DB가 새로 생겨서 채널 목록·녹화 이력·태그가
    통째로 사라진 것처럼 보인다.
    """
    new_path = data_dir / DB_FILENAME
    old_path = data_dir / LEGACY_DB_FILENAME

    if new_path.exists() or not old_path.exists():
        return new_path

    try:
        # WAL/SHM은 본체 파일명에 묶여 있다. 함께 옮겨야 비정상 종료 직전의
        # 트랜잭션이 보존된다.
        for suffix in ("", "-wal", "-shm"):
            src = old_path.with_name(old_path.name + suffix)
            if src.exists():
                src.rename(new_path.with_name(new_path.name + suffix))
        logger.info(f"기존 DB를 이관했습니다: {LEGACY_DB_FILENAME} → {DB_FILENAME}")
        return new_path
    except OSError as e:
        # 이관에 실패했는데 새 빈 DB를 만들면 데이터가 사라진 것처럼 보인다.
        # 그것이 최악이므로 옛 파일을 그대로 쓴다.
        logger.error(f"DB 이관 실패 ({e}). 기존 파일을 그대로 사용합니다: {LEGACY_DB_FILENAME}")
        return old_path


def get_database() -> Database:
    """전역 Database 인스턴스를 반환한다 (없으면 생성 및 연결).

    호출 전에 구버전 DB 파일명을 확인해 필요하면 이관한다.
    """
    global _database
    with _database_lock:
        if _database is None:
            _database = Database(_resolve_db_path(resolve_data_dir()))
            _database.connect()
        return _database


def set_database(db: Optional[Database]) -> None:
    """전역 인스턴스를 교체한다. 테스트에서 임시 DB를 주입할 때 사용한다."""
    global _database
    with _database_lock:
        _database = db


def close_database() -> None:
    """전역 인스턴스를 닫는다."""
    global _database
    with _database_lock:
        if _database is not None:
            _database.close()
            _database = None
