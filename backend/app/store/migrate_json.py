"""
Rookery: 기존 JSON 파일 → SQLite 일회성 이관

v1.2.0 이전 버전은 상태를 data/*.json 여러 개에 나눠 저장했다.
업그레이드한 사용자가 채널 목록이나 이력을 잃지 않도록 첫 실행 때 한 번만 옮긴다.

원칙:
    - 이미 이관했으면 다시 하지 않는다 (meta 테이블에 기록).
    - 대상 테이블에 데이터가 있으면 건너뛴다 (덮어쓰기 금지).
    - 원본 JSON은 삭제하지 않고 .migrated 접미사로 보관한다.
      한 파일이 실패해도 나머지는 계속 진행한다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from app.core.logger import logger
from app.store.db import Database
from app.store.repositories import (
    ChannelRepository,
    LiveHistoryRepository,
    NotificationRepository,
    TagRepository,
    VodRepository,
)

MIGRATION_FLAG = "json_migrated_at"


def _read_json(path: Path) -> Any:
    """JSON 파일을 읽는다. 없거나 깨졌으면 None."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"이관 대상 파일을 읽지 못했습니다 ({path.name}): {e}")
        return None


def _archive(path: Path) -> None:
    """이관이 끝난 원본을 .migrated로 보관한다 (삭제하지 않는다)."""
    try:
        target = path.with_suffix(path.suffix + ".migrated")
        if target.exists():
            target.unlink()
        path.rename(target)
    except Exception as e:
        logger.warning(f"원본 파일 보관 실패 ({path.name}): {e}")


def _table_is_empty(db: Database, table: str) -> bool:
    row = db.query_one(f"SELECT 1 FROM {table} LIMIT 1")  # noqa: S608 — 내부 상수만 사용
    return row is None


def _migrate_channels(db: Database, data_dir: Path) -> int:
    path = data_dir / "channels.json"
    data = _read_json(path)
    if not isinstance(data, dict):
        return 0
    if not _table_is_empty(db, "channels"):
        logger.info("channels 테이블에 이미 데이터가 있어 JSON 이관을 건너뜁니다.")
        return 0

    repo = ChannelRepository(db)
    count = 0
    for key, config in data.items():
        if not isinstance(config, dict):
            continue
        # 레거시 키(':' 없음)는 Chzzk 채널이었다.
        if ":" in key:
            platform = config.get("platform", "chzzk")
            channel_id = config.get("channel_id", key.split(":", 1)[-1])
            composite_key = key
        else:
            platform = "chzzk"
            channel_id = key
            composite_key = f"chzzk:{key}"

        repo.upsert(
            composite_key=composite_key,
            platform=platform,
            channel_id=channel_id,
            auto_record=bool(config.get("auto_record", True)),
            tags=config.get("tags") or [],
        )
        repo.update_capture(
            composite_key=composite_key,
            captured_m3u8_url=config.get("captured_m3u8_url"),
            captured_m3u8_at=config.get("captured_m3u8_at"),
            master_url=config.get("master_url"),
            master_url_captured_at=config.get("master_url_captured_at"),
            master_url_file=config.get("master_url_file"),
        )
        count += 1

    _archive(path)
    return count


def _migrate_live_history(db: Database, data_dir: Path) -> int:
    path = data_dir / "live_history.json"
    data = _read_json(path)
    if not isinstance(data, list):
        return 0
    if not _table_is_empty(db, "live_history"):
        return 0

    repo = LiveHistoryRepository(db)
    count = 0
    for entry in data:
        if not isinstance(entry, dict):
            continue
        repo.add_session(entry)
        count += 1

    _archive(path)
    return count


def _migrate_vod_history(db: Database, data_dir: Path) -> int:
    path = data_dir / "vod_history.json"
    data = _read_json(path)
    if not isinstance(data, (dict, list)):
        return 0
    if not _table_is_empty(db, "vod_tasks"):
        return 0

    repo = VodRepository(db)
    count = 0
    # 구버전은 {task_id: {...}} 형태, 더 오래된 버전은 [{...}] 형태였다.
    items = data.items() if isinstance(data, dict) else (
        (rec.get("task_id", ""), rec) for rec in data if isinstance(rec, dict)
    )
    for task_id, record in items:
        if not task_id or not isinstance(record, dict):
            continue
        repo.upsert(task_id, record)
        count += 1

    _archive(path)
    return count


def _migrate_tags(db: Database, data_dir: Path) -> int:
    path = data_dir / "user_preferences.json"
    data = _read_json(path)
    if not isinstance(data, dict):
        return 0
    if not _table_is_empty(db, "tags"):
        return 0

    repo = TagRepository(db)
    count = 0
    for name in data.get("tags") or []:
        if isinstance(name, str) and name.strip():
            repo.add(name)
            count += 1

    _archive(path)
    return count


def _migrate_pending_notifications(db: Database, data_dir: Path) -> int:
    path = data_dir / "pending_notifications.json"
    data = _read_json(path)
    if not isinstance(data, list) or not data:
        if path.exists():
            _archive(path)
        return 0
    if not _table_is_empty(db, "pending_notifications"):
        return 0

    valid = [n for n in data if isinstance(n, dict) and n.get("id")]
    NotificationRepository(db).replace_all(valid)
    _archive(path)
    return len(valid)


#: (표시 이름, 이관 함수) — 하나가 실패해도 나머지는 계속 진행한다.
_STEPS: list[tuple[str, Callable[[Database, Path], int]]] = [
    ("채널 목록", _migrate_channels),
    ("녹화 이력", _migrate_live_history),
    ("VOD 이력", _migrate_vod_history),
    ("태그", _migrate_tags),
    ("대기 알림", _migrate_pending_notifications),
]


def migrate_json_files(db: Database, data_dir: Path) -> dict[str, int]:
    """레거시 JSON 파일을 SQLite로 옮긴다. 이미 수행했으면 아무것도 하지 않는다.

    Returns:
        {단계 이름: 이관된 항목 수}
    """
    if db.get_meta(MIGRATION_FLAG):
        return {}

    results: dict[str, int] = {}
    for label, step in _STEPS:
        try:
            results[label] = step(db, data_dir)
        except Exception as e:
            # 한 종류가 실패해도 나머지는 살린다. 원본 JSON은 그대로 남는다.
            logger.error(f"{label} 이관 실패: {e}")
            results[label] = 0

    migrated = {k: v for k, v in results.items() if v}
    if migrated:
        summary = ", ".join(f"{k} {v}건" for k, v in migrated.items())
        logger.info(f"🗃️ 기존 데이터를 저장소로 이관했습니다: {summary}")
        logger.info("🗃️ 원본 JSON은 '.migrated' 접미사로 보관되어 있습니다.")

    from datetime import datetime

    db.set_meta(MIGRATION_FLAG, datetime.now().isoformat())
    return results
