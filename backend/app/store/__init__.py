"""
Rookery: 영속 저장소

JSON 파일 여러 개에 흩어져 있던 상태(채널 목록, 녹화/VOD 이력, 태그,
미전송 알림)를 단일 SQLite 파일로 통합한다.

sqlite3는 Python 표준 라이브러리이므로 배포 요구사항이 늘지 않는다.
"""

from app.store.db import Database, close_database, get_database, set_database
from app.store.migrate_json import migrate_json_files
from app.store.repositories import (
    ChannelRepository,
    ChatIndexRepository,
    LiveHistoryRepository,
    NotificationRepository,
    TagRepository,
    VodRepository,
)

__all__ = [
    "Database",
    "get_database",
    "set_database",
    "close_database",
    "migrate_json_files",
    "ChannelRepository",
    "ChatIndexRepository",
    "LiveHistoryRepository",
    "NotificationRepository",
    "TagRepository",
    "VodRepository",
]
