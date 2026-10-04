"""
Rookery: 저장소 레포지토리

각 도메인의 SQL을 한곳에 모아 엔진/서비스 계층이 SQL을 직접 다루지 않게 한다.
모든 메서드는 동기다 — SQLite 쓰기는 마이크로초 단위라 이벤트 루프를 막지 않으며,
기존 JSON 전체 재작성보다 오히려 빠르다.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Optional

from app.core.logger import logger
from app.store.db import Database, get_database


def _loads(raw: Any, default: Any) -> Any:
    """DB에 JSON 문자열로 저장된 값을 복원한다. 깨져 있으면 기본값."""
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


class ChatIndexRepository:
    """채팅 로그 파일의 줄 수·바이트 오프셋 인덱스.

    JSONL 원본에서 언제든 다시 만들 수 있는 파생 데이터다. 행이 사라지거나
    파일과 어긋나면 그 파일만 다시 훑으면 되므로 정확성에 영향이 없다.
    """

    def __init__(self, db: Optional[Database] = None) -> None:
        self._db = db or get_database()

    def get(self, path: str) -> Optional[dict]:
        row = self._db.query_one(
            "SELECT message_count, offsets, scanned_bytes FROM chat_file_index WHERE path = ?",
            (path,),
        )
        if row is None:
            return None
        return {
            "message_count": row["message_count"],
            "offsets": _loads(row["offsets"], []),
            "scanned_bytes": row["scanned_bytes"],
        }

    def save(
        self,
        path: str,
        message_count: int,
        offsets: list[int],
        scanned_bytes: int,
    ) -> None:
        self._db.execute(
            """
            INSERT INTO chat_file_index (path, message_count, offsets, scanned_bytes)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                message_count = excluded.message_count,
                offsets       = excluded.offsets,
                scanned_bytes = excluded.scanned_bytes
            """,
            (path, message_count, json.dumps(offsets), scanned_bytes),
        )


class ChannelRepository:
    """감시 채널 목록."""

    def __init__(self, db: Optional[Database] = None) -> None:
        self._db = db or get_database()

    def list_all(self) -> list[dict]:
        """등록된 모든 채널을 등록순으로 반환한다.

        created_at은 초 단위라 같은 초에 추가된 항목의 순서를 구분하지 못한다.
        rowid는 삽입 순서 그대로이고 UPSERT의 UPDATE에서도 바뀌지 않는다.
        """
        rows = self._db.query("SELECT * FROM channels ORDER BY rowid")
        return [self._to_dict(row) for row in rows]

    def upsert(
        self,
        composite_key: str,
        platform: str,
        channel_id: str,
        auto_record: bool,
        tags: Optional[list[str]] = None,
    ) -> None:
        """채널을 등록하거나 기본 정보를 갱신한다.

        캡처된 URL 계열 컬럼은 건드리지 않는다 — 재등록으로 캡처 결과가
        날아가면 안 되기 때문이다.
        """
        self._db.execute(
            """
            INSERT INTO channels (composite_key, platform, channel_id, auto_record, tags)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(composite_key) DO UPDATE SET
                platform    = excluded.platform,
                channel_id  = excluded.channel_id,
                auto_record = excluded.auto_record,
                tags        = excluded.tags
            """,
            (
                composite_key,
                platform,
                channel_id,
                1 if auto_record else 0,
                json.dumps(tags or [], ensure_ascii=False),
            ),
        )

    def delete(self, composite_key: str) -> None:
        self._db.execute("DELETE FROM channels WHERE composite_key = ?", (composite_key,))

    def set_auto_record(self, composite_key: str, value: bool) -> None:
        self._db.execute(
            "UPDATE channels SET auto_record = ? WHERE composite_key = ?",
            (1 if value else 0, composite_key),
        )

    def set_tags(self, composite_key: str, tags: list[str]) -> None:
        self._db.execute(
            "UPDATE channels SET tags = ? WHERE composite_key = ?",
            (json.dumps(tags, ensure_ascii=False), composite_key),
        )

    def remove_tag_everywhere(self, tag_name: str) -> int:
        """모든 채널에서 특정 태그를 제거하고 변경된 채널 수를 반환한다."""
        changed = 0
        with self._db.transaction() as conn:
            rows = conn.execute("SELECT composite_key, tags FROM channels").fetchall()
            for row in rows:
                tags = _loads(row["tags"], [])
                if tag_name not in tags:
                    continue
                tags = [t for t in tags if t != tag_name]
                conn.execute(
                    "UPDATE channels SET tags = ? WHERE composite_key = ?",
                    (json.dumps(tags, ensure_ascii=False), row["composite_key"]),
                )
                changed += 1
        return changed

    def update_capture(
        self,
        composite_key: str,
        captured_m3u8_url: Optional[str],
        captured_m3u8_at: Optional[str],
        master_url: Optional[str],
        master_url_captured_at: Optional[str],
        master_url_file: Optional[str],
    ) -> None:
        """X Spaces 캡처 정보를 갱신한다 (Space 종료 시 None으로 초기화)."""
        self._db.execute(
            """
            UPDATE channels SET
                captured_m3u8_url      = ?,
                captured_m3u8_at       = ?,
                master_url             = ?,
                master_url_captured_at = ?,
                master_url_file        = ?
            WHERE composite_key = ?
            """,
            (
                captured_m3u8_url,
                captured_m3u8_at,
                master_url,
                master_url_captured_at,
                master_url_file,
                composite_key,
            ),
        )

    @staticmethod
    def _to_dict(row) -> dict:
        return {
            "composite_key": row["composite_key"],
            "platform": row["platform"],
            "channel_id": row["channel_id"],
            "auto_record": bool(row["auto_record"]),
            "tags": _loads(row["tags"], []),
            "captured_m3u8_url": row["captured_m3u8_url"],
            "captured_m3u8_at": row["captured_m3u8_at"],
            "master_url": row["master_url"],
            "master_url_captured_at": row["master_url_captured_at"],
            "master_url_file": row["master_url_file"],
        }


class LiveHistoryRepository:
    """녹화 세션 이력과 라이브 감지 이력."""

    def __init__(self, db: Optional[Database] = None) -> None:
        self._db = db or get_database()

    def add_session(self, entry: dict) -> None:
        """녹화 완료 세션 한 건을 추가한다.

        기존 JSON 구현은 전체 파일을 읽고 다시 썼기 때문에 이력이 쌓일수록
        녹화 종료가 느려졌다. 여기서는 INSERT 한 번이다.
        """
        self._db.execute(
            """
            INSERT INTO live_history (
                composite_key, platform, channel_id, channel_name,
                started_at, ended_at, duration_seconds, file_size_bytes, output_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.get("composite_key", ""),
                entry.get("platform", ""),
                entry.get("channel_id", ""),
                entry.get("channel_name"),
                entry.get("started_at"),
                entry.get("ended_at") or datetime.now().isoformat(),
                float(entry.get("duration_seconds") or 0),
                int(entry.get("file_size_bytes") or 0),
                entry.get("output_path"),
            ),
        )

    def list_sessions(self, limit: Optional[int] = None) -> list[dict]:
        """녹화 이력을 오래된 순으로 반환한다 (기존 JSON 파일과 동일한 순서)."""
        sql = "SELECT * FROM live_history ORDER BY id"
        params: tuple = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        return [
            {
                "composite_key": row["composite_key"],
                "platform": row["platform"],
                "channel_id": row["channel_id"],
                "channel_name": row["channel_name"],
                "started_at": row["started_at"],
                "ended_at": row["ended_at"],
                "duration_seconds": row["duration_seconds"],
                "file_size_bytes": row["file_size_bytes"],
                "output_path": row["output_path"],
            }
            for row in self._db.query(sql, params)
        ]

    def record_detection(self, composite_key: str, day: Optional[str] = None) -> None:
        """라이브 감지를 날짜 단위로 기록한다 (같은 날 중복은 무시)."""
        day = day or datetime.now().strftime("%Y-%m-%d")
        self._db.execute(
            "INSERT OR IGNORE INTO live_detections (composite_key, detected_on) VALUES (?, ?)",
            (composite_key, day),
        )

    def detection_counts(self, days: int = 30) -> dict[str, int]:
        """최근 N일간 채널별 감지 일수를 반환한다."""
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        rows = self._db.query(
            "SELECT composite_key, COUNT(*) AS cnt FROM live_detections "
            "WHERE detected_on >= ? GROUP BY composite_key",
            (cutoff,),
        )
        return {row["composite_key"]: row["cnt"] for row in rows}


class VodRepository:
    """VOD 다운로드 작업 이력."""

    def __init__(self, db: Optional[Database] = None) -> None:
        self._db = db or get_database()

    def upsert(self, task_id: str, record: dict) -> None:
        """작업 상태를 저장한다. 스키마에 없는 필드는 payload에 JSON으로 담는다."""
        known = {
            "url",
            "title",
            "quality",
            "state",
            "progress",
            "output_path",
            "error_message",
            "created_at",
            "started_at",
            "completed_at",
        }
        payload = {k: v for k, v in record.items() if k not in known and k != "task_id"}

        self._db.execute(
            """
            INSERT INTO vod_tasks (
                task_id, url, title, quality, state, progress,
                output_path, error_message, created_at, started_at, completed_at, payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                url           = excluded.url,
                title         = excluded.title,
                quality       = excluded.quality,
                state         = excluded.state,
                progress      = excluded.progress,
                output_path   = excluded.output_path,
                error_message = excluded.error_message,
                started_at    = excluded.started_at,
                completed_at  = excluded.completed_at,
                payload       = excluded.payload
            """,
            (
                task_id,
                record.get("url", ""),
                record.get("title"),
                record.get("quality"),
                str(record.get("state", "idle")),
                float(record.get("progress") or 0),
                record.get("output_path"),
                record.get("error_message"),
                record.get("created_at"),
                record.get("started_at"),
                record.get("completed_at"),
                json.dumps(payload, ensure_ascii=False, default=str),
            ),
        )

    def replace_all(self, records: dict[str, dict]) -> None:
        """전체 작업 목록을 교체한다 (완료 작업 일괄 삭제 등에 사용)."""
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM vod_tasks")
        for task_id, record in records.items():
            self.upsert(task_id, record)

    def delete(self, task_id: str) -> None:
        self._db.execute("DELETE FROM vod_tasks WHERE task_id = ?", (task_id,))

    def list_all(self) -> list[dict]:
        """저장된 작업을 생성순으로 반환한다."""
        result: list[dict] = []
        for row in self._db.query("SELECT * FROM vod_tasks ORDER BY created_at, rowid"):
            record = {
                "task_id": row["task_id"],
                "url": row["url"],
                "title": row["title"],
                "quality": row["quality"],
                "state": row["state"],
                "progress": row["progress"],
                "output_path": row["output_path"],
                "error_message": row["error_message"],
                "created_at": row["created_at"],
                "started_at": row["started_at"],
                "completed_at": row["completed_at"],
            }
            record.update(_loads(row["payload"], {}))
            result.append(record)
        return result


class TagRepository:
    """사용자 정의 태그 목록."""

    def __init__(self, db: Optional[Database] = None) -> None:
        self._db = db or get_database()

    def list_all(self) -> list[str]:
        """태그를 추가한 순서대로 반환한다 (사용자가 정렬 순서를 인지한다)."""
        return [
            row["name"]
            for row in self._db.query("SELECT name FROM tags ORDER BY rowid")
        ]

    def add(self, name: str) -> None:
        self._db.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,))

    def delete(self, name: str) -> None:
        self._db.execute("DELETE FROM tags WHERE name = ?", (name,))


class NotificationRepository:
    """미전송 알림 큐의 영속 사본."""

    def __init__(self, db: Optional[Database] = None) -> None:
        self._db = db or get_database()

    def replace_all(self, notifications: list[dict]) -> None:
        """대기 큐 전체를 교체한다."""
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM pending_notifications")
            conn.executemany(
                """
                INSERT INTO pending_notifications (
                    id, kind, title, description, color, fields,
                    created_at, attempts, next_attempt_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        n["id"],
                        n["kind"],
                        n["title"],
                        n.get("description", ""),
                        n.get("color", "green"),
                        json.dumps(n.get("fields") or {}, ensure_ascii=False),
                        float(n.get("created_at") or 0),
                        int(n.get("attempts") or 0),
                        float(n.get("next_attempt_at") or 0),
                    )
                    for n in notifications
                ],
            )

    def list_all(self) -> list[dict]:
        return [
            {
                "id": row["id"],
                "kind": row["kind"],
                "title": row["title"],
                "description": row["description"],
                "color": row["color"],
                "fields": _loads(row["fields"], {}),
                "created_at": row["created_at"],
                "attempts": row["attempts"],
                "next_attempt_at": row["next_attempt_at"],
            }
            for row in self._db.query(
                "SELECT * FROM pending_notifications ORDER BY created_at"
            )
        ]

    def clear(self) -> None:
        self._db.execute("DELETE FROM pending_notifications")
