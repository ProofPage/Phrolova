"""
test_store.py
SQLite 저장소의 스키마 마이그레이션, 레포지토리 동작, JSON 이관 테스트.

가장 중요한 계약: 기존 사용자의 JSON 데이터를 잃지 않는다.
"""

import json

import pytest

from app.store.db import (
    DB_FILENAME,
    LEGACY_DB_FILENAME,
    Database,
    _resolve_db_path,
)
from app.store.migrate_json import MIGRATION_FLAG, migrate_json_files
from app.store.repositories import (
    ChannelRepository,
    LiveHistoryRepository,
    NotificationRepository,
    TagRepository,
    VodRepository,
)
from app.store.schema import LATEST_VERSION


@pytest.fixture
def db(tmp_path):
    """임시 파일 기반 DB (WAL 동작까지 실제와 동일하게 검증)."""
    database = Database(tmp_path / "test.db")
    database.connect()
    yield database
    database.close()


class TestSchema:
    def test_migrations_bring_db_to_latest(self, db):
        version = db.query_one("PRAGMA user_version")[0]
        assert version == LATEST_VERSION

    def test_migrations_are_idempotent(self, tmp_path):
        path = tmp_path / "idem.db"
        first = Database(path)
        first.connect()
        first.close()

        second = Database(path)
        second.connect()
        try:
            assert second.query_one("PRAGMA user_version")[0] == LATEST_VERSION
        finally:
            second.close()

    def test_wal_mode_enabled(self, db):
        mode = db.query_one("PRAGMA journal_mode")[0]
        assert mode.lower() == "wal"

    def test_transaction_rolls_back_on_error(self, db):
        repo = TagRepository(db)
        repo.add("살아남는태그")

        with pytest.raises(RuntimeError):
            with db.transaction() as conn:
                conn.execute("INSERT INTO tags (name) VALUES (?)", ("사라질태그",))
                raise RuntimeError("의도적 실패")

        assert repo.list_all() == ["살아남는태그"]


class TestChannelRepository:
    def test_upsert_and_list(self, db):
        repo = ChannelRepository(db)
        repo.upsert("chzzk:abc", "chzzk", "abc", auto_record=True, tags=["게임"])

        channels = repo.list_all()
        assert len(channels) == 1
        assert channels[0]["composite_key"] == "chzzk:abc"
        assert channels[0]["auto_record"] is True
        assert channels[0]["tags"] == ["게임"]

    def test_upsert_preserves_capture_columns(self, db):
        """재등록해도 캡처된 Master URL이 날아가면 안 된다."""
        repo = ChannelRepository(db)
        repo.upsert("x_spaces:user", "x_spaces", "user", auto_record=True)
        repo.update_capture(
            "x_spaces:user",
            captured_m3u8_url="https://m3u8",
            captured_m3u8_at="2026-01-01T00:00:00",
            master_url="https://master",
            master_url_captured_at="2026-01-01T00:00:00",
            master_url_file="C:/urls/a.txt",
        )

        repo.upsert("x_spaces:user", "x_spaces", "user", auto_record=False)

        channel = repo.list_all()[0]
        assert channel["master_url"] == "https://master"
        assert channel["auto_record"] is False

    def test_set_auto_record_and_tags(self, db):
        repo = ChannelRepository(db)
        repo.upsert("chzzk:abc", "chzzk", "abc", auto_record=True)

        repo.set_auto_record("chzzk:abc", False)
        repo.set_tags("chzzk:abc", ["버튜버", "저챗"])

        channel = repo.list_all()[0]
        assert channel["auto_record"] is False
        assert channel["tags"] == ["버튜버", "저챗"]

    def test_remove_tag_everywhere(self, db):
        repo = ChannelRepository(db)
        repo.upsert("chzzk:a", "chzzk", "a", auto_record=True, tags=["게임", "저챗"])
        repo.upsert("chzzk:b", "chzzk", "b", auto_record=True, tags=["저챗"])
        repo.upsert("chzzk:c", "chzzk", "c", auto_record=True, tags=["음악"])

        changed = repo.remove_tag_everywhere("저챗")

        assert changed == 2
        by_key = {c["composite_key"]: c["tags"] for c in repo.list_all()}
        assert by_key["chzzk:a"] == ["게임"]
        assert by_key["chzzk:b"] == []
        assert by_key["chzzk:c"] == ["음악"]

    def test_delete(self, db):
        repo = ChannelRepository(db)
        repo.upsert("chzzk:abc", "chzzk", "abc", auto_record=True)
        repo.delete("chzzk:abc")
        assert repo.list_all() == []


class TestLiveHistoryRepository:
    def test_add_and_list_sessions(self, db):
        repo = LiveHistoryRepository(db)
        repo.add_session(
            {
                "composite_key": "chzzk:abc",
                "platform": "chzzk",
                "channel_id": "abc",
                "channel_name": "테스트 채널",
                "started_at": "2026-01-01T10:00:00",
                "ended_at": "2026-01-01T12:00:00",
                "duration_seconds": 7200,
                "file_size_bytes": 1024,
                "output_path": "C:/rec/a.ts",
            }
        )

        sessions = repo.list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["channel_name"] == "테스트 채널"
        assert sessions[0]["duration_seconds"] == 7200

    def test_detection_is_counted_once_per_day(self, db):
        repo = LiveHistoryRepository(db)
        repo.record_detection("chzzk:abc", day="2026-01-01")
        repo.record_detection("chzzk:abc", day="2026-01-01")
        repo.record_detection("chzzk:abc", day="2026-01-02")

        counts = repo.detection_counts(days=36500)
        assert counts["chzzk:abc"] == 2

    def test_detection_counts_respect_window(self, db):
        repo = LiveHistoryRepository(db)
        repo.record_detection("chzzk:abc", day="2000-01-01")

        assert repo.detection_counts(days=30) == {}


class TestVodRepository:
    def test_upsert_roundtrip_with_extra_fields(self, db):
        repo = VodRepository(db)
        repo.upsert(
            "task-1",
            {
                "url": "https://chzzk.naver.com/video/1",
                "title": "테스트 VOD",
                "quality": "best",
                "state": "completed",
                "progress": 100.0,
                "output_path": "C:/vod/a.mp4",
                "created_at": "2026-01-01T00:00:00",
                # 스키마에 없는 필드는 payload로 보존되어야 한다.
                "expected_part_file": "C:/vod/a.mp4.part",
            },
        )

        records = repo.list_all()
        assert len(records) == 1
        assert records[0]["title"] == "테스트 VOD"
        assert records[0]["expected_part_file"] == "C:/vod/a.mp4.part"

    def test_upsert_updates_existing(self, db):
        repo = VodRepository(db)
        repo.upsert("t", {"url": "u", "state": "downloading", "progress": 10.0})
        repo.upsert("t", {"url": "u", "state": "completed", "progress": 100.0})

        records = repo.list_all()
        assert len(records) == 1
        assert records[0]["state"] == "completed"
        assert records[0]["progress"] == 100.0

    def test_replace_all(self, db):
        repo = VodRepository(db)
        repo.upsert("old", {"url": "u", "state": "completed"})
        repo.replace_all({"new": {"url": "u2", "state": "downloading"}})

        records = repo.list_all()
        assert [r["task_id"] for r in records] == ["new"]


class TestOrdering:
    """created_at은 초 단위라 정렬 기준으로 쓸 수 없다 — 삽입 순서를 지켜야 한다."""

    def test_tags_keep_insertion_order(self, db):
        repo = TagRepository(db)
        # 알파벳/가나다 역순으로 넣어도 넣은 순서 그대로 나와야 한다.
        for name in ["음악", "게임", "스페이스", "저챗"]:
            repo.add(name)

        assert repo.list_all() == ["음악", "게임", "스페이스", "저챗"]

    def test_channels_keep_insertion_order(self, db):
        repo = ChannelRepository(db)
        for cid in ["zzz", "aaa", "mmm"]:
            repo.upsert(f"chzzk:{cid}", "chzzk", cid, auto_record=True)

        keys = [c["composite_key"] for c in repo.list_all()]
        assert keys == ["chzzk:zzz", "chzzk:aaa", "chzzk:mmm"]

    def test_channel_update_does_not_change_order(self, db):
        """설정을 바꿔도 목록에서의 자리가 바뀌면 안 된다."""
        repo = ChannelRepository(db)
        for cid in ["a", "b", "c"]:
            repo.upsert(f"chzzk:{cid}", "chzzk", cid, auto_record=True)

        repo.upsert("chzzk:a", "chzzk", "a", auto_record=False)
        repo.set_tags("chzzk:a", ["변경"])

        keys = [c["composite_key"] for c in repo.list_all()]
        assert keys == ["chzzk:a", "chzzk:b", "chzzk:c"]


class TestNotificationRepository:
    def test_replace_and_list(self, db):
        repo = NotificationRepository(db)
        repo.replace_all(
            [
                {
                    "id": "abc123",
                    "kind": "recording_started",
                    "title": "🎬 녹화 시작",
                    "description": "설명",
                    "color": "green",
                    "fields": {"화질": "best"},
                    "created_at": 1000.0,
                    "attempts": 2,
                    "next_attempt_at": 1005.0,
                }
            ]
        )

        items = repo.list_all()
        assert len(items) == 1
        assert items[0]["fields"] == {"화질": "best"}
        assert items[0]["attempts"] == 2

    def test_clear(self, db):
        repo = NotificationRepository(db)
        repo.replace_all([{"id": "x", "kind": "system", "title": "t", "created_at": 1.0}])
        repo.clear()
        assert repo.list_all() == []


class TestJsonMigration:
    def _write(self, data_dir, name, payload):
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / name).write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )

    def test_migrates_all_legacy_files(self, db, tmp_path):
        data_dir = tmp_path / "data"
        self._write(
            data_dir,
            "channels.json",
            {
                "chzzk:abc": {
                    "platform": "chzzk",
                    "channel_id": "abc",
                    "auto_record": True,
                    "tags": ["게임"],
                },
                "x_spaces:someone": {
                    "platform": "x_spaces",
                    "channel_id": "someone",
                    "auto_record": False,
                    "master_url": "https://master",
                },
            },
        )
        self._write(
            data_dir,
            "live_history.json",
            [{"composite_key": "chzzk:abc", "channel_id": "abc", "ended_at": "2026-01-01T00:00:00"}],
        )
        self._write(data_dir, "vod_history.json", {"t1": {"url": "u", "state": "completed"}})
        self._write(data_dir, "user_preferences.json", {"tags": ["게임", "음악"]})

        results = migrate_json_files(db, data_dir)

        assert results["채널 목록"] == 2
        assert results["녹화 이력"] == 1
        assert results["VOD 이력"] == 1
        assert results["태그"] == 2

        channels = {c["composite_key"]: c for c in ChannelRepository(db).list_all()}
        assert channels["chzzk:abc"]["tags"] == ["게임"]
        assert channels["x_spaces:someone"]["master_url"] == "https://master"
        assert channels["x_spaces:someone"]["auto_record"] is False
        assert TagRepository(db).list_all() == ["게임", "음악"]

    def test_legacy_keys_without_platform_prefix(self, db, tmp_path):
        """':' 없는 구버전 키는 chzzk 채널로 이관되어야 한다."""
        data_dir = tmp_path / "data"
        self._write(data_dir, "channels.json", {"oldchannel": {"auto_record": True}})

        migrate_json_files(db, data_dir)

        channels = ChannelRepository(db).list_all()
        assert channels[0]["composite_key"] == "chzzk:oldchannel"
        assert channels[0]["platform"] == "chzzk"
        assert channels[0]["channel_id"] == "oldchannel"

    def test_originals_are_archived_not_deleted(self, db, tmp_path):
        data_dir = tmp_path / "data"
        self._write(data_dir, "channels.json", {"chzzk:abc": {"auto_record": True}})

        migrate_json_files(db, data_dir)

        assert not (data_dir / "channels.json").exists()
        assert (data_dir / "channels.json.migrated").exists()

    def test_runs_only_once(self, db, tmp_path):
        data_dir = tmp_path / "data"
        self._write(data_dir, "channels.json", {"chzzk:abc": {"auto_record": True}})

        migrate_json_files(db, data_dir)
        assert db.get_meta(MIGRATION_FLAG) is not None

        # 두 번째 호출은 아무 일도 하지 않는다.
        assert migrate_json_files(db, data_dir) == {}
        assert len(ChannelRepository(db).list_all()) == 1

    def test_does_not_overwrite_existing_rows(self, db, tmp_path):
        """DB에 이미 채널이 있으면 JSON이 덮어쓰지 않는다."""
        ChannelRepository(db).upsert("chzzk:existing", "chzzk", "existing", auto_record=True)

        data_dir = tmp_path / "data"
        self._write(data_dir, "channels.json", {"chzzk:fromjson": {"auto_record": True}})

        results = migrate_json_files(db, data_dir)

        assert results["채널 목록"] == 0
        keys = [c["composite_key"] for c in ChannelRepository(db).list_all()]
        assert keys == ["chzzk:existing"]

    def test_corrupt_file_does_not_block_others(self, db, tmp_path):
        """한 파일이 깨져도 나머지는 이관되어야 한다."""
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "channels.json").write_text("{ 깨진 JSON", encoding="utf-8")
        self._write(data_dir, "user_preferences.json", {"tags": ["살아있음"]})

        results = migrate_json_files(db, data_dir)

        assert results["채널 목록"] == 0
        assert results["태그"] == 1
        assert TagRepository(db).list_all() == ["살아있음"]

    def test_missing_files_are_fine(self, db, tmp_path):
        assert migrate_json_files(db, tmp_path / "nonexistent") == {
            "채널 목록": 0,
            "녹화 이력": 0,
            "VOD 이력": 0,
            "태그": 0,
            "대기 알림": 0,
        }
class TestDbFilenameMigration:
    """Rookery 리네이밍 시 구버전 DB 파일을 잃지 않는지 검증한다.

    backend/data/는 gitignore 대상이라 DB는 사용자 로컬에만 있다.
    이관에 실패하면 빈 DB가 생겨 채널 목록과 이력이 사라진 것처럼 보인다.
    """

    def test_renames_legacy_file(self, tmp_path):
        (tmp_path / LEGACY_DB_FILENAME).write_bytes(b"sqlite")

        result = _resolve_db_path(tmp_path)

        assert result == tmp_path / DB_FILENAME
        assert result.exists()
        assert not (tmp_path / LEGACY_DB_FILENAME).exists()

    def test_moves_wal_and_shm_together(self, tmp_path):
        """WAL은 본체 파일명에 묶여 있어 같이 옮기지 않으면 트랜잭션을 잃는다."""
        (tmp_path / LEGACY_DB_FILENAME).write_bytes(b"sqlite")
        (tmp_path / f"{LEGACY_DB_FILENAME}-wal").write_bytes(b"wal")
        (tmp_path / f"{LEGACY_DB_FILENAME}-shm").write_bytes(b"shm")

        _resolve_db_path(tmp_path)

        assert (tmp_path / f"{DB_FILENAME}-wal").read_bytes() == b"wal"
        assert (tmp_path / f"{DB_FILENAME}-shm").read_bytes() == b"shm"
        assert not (tmp_path / f"{LEGACY_DB_FILENAME}-wal").exists()

    def test_keeps_existing_new_file(self, tmp_path):
        """이미 새 이름 DB가 있으면 구버전을 덮어쓰지 않는다."""
        (tmp_path / DB_FILENAME).write_bytes(b"new")
        (tmp_path / LEGACY_DB_FILENAME).write_bytes(b"old")

        result = _resolve_db_path(tmp_path)

        assert result.read_bytes() == b"new"
        assert (tmp_path / LEGACY_DB_FILENAME).read_bytes() == b"old"

    def test_fresh_install(self, tmp_path):
        result = _resolve_db_path(tmp_path)

        assert result == tmp_path / DB_FILENAME
        assert not result.exists()

    def test_migrated_db_keeps_rows(self, tmp_path):
        """이관 후에도 실제 데이터를 읽을 수 있어야 한다."""
        legacy = Database(tmp_path / LEGACY_DB_FILENAME)
        legacy.connect()
        ChannelRepository(legacy).upsert("chzzk:abc", "chzzk", "abc", auto_record=True)
        legacy.close()

        migrated = Database(_resolve_db_path(tmp_path))
        migrated.connect()
        rows = ChannelRepository(migrated).list_all()
        migrated.close()

        assert [r["composite_key"] for r in rows] == ["chzzk:abc"]
