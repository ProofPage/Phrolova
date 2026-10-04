"""
공용 pytest 픽스처.

두 가지를 격리한다:
  1. 저장소 — 전역 SQLite 싱글턴을 임시 DB로 교체한다.
  2. .env — 설정 API 테스트가 개발자의 실제 .env를 덮어쓰지 않게 한다.

둘 다 프로세스 전역 상태라 격리하지 않으면 테스트가 실사용 파일을 건드린다.
"""

import pytest

import app.core.utils as core_utils
from app.core.config import get_settings
from app.store.db import Database, set_database


@pytest.fixture(autouse=True)
def isolated_database(tmp_path_factory):
    """테스트마다 빈 임시 DB를 전역 저장소로 주입한다."""
    db_path = tmp_path_factory.mktemp("store") / "test.db"
    database = Database(db_path)
    database.connect()
    set_database(database)

    yield database

    database.close()
    set_database(None)


@pytest.fixture(autouse=True)
def isolated_env_file(tmp_path, monkeypatch):
    """.env 쓰기를 임시 파일로 돌린다.

    설정 API는 변경을 .env에 영속화하는데, 격리하지 않으면 테스트를 한 번
    돌리는 것만으로 사용자의 실제 설정(토큰, 경로 등)이 덮어써진다.
    """
    monkeypatch.setattr(core_utils, "_get_env_path", lambda: tmp_path / ".env")
    yield


@pytest.fixture(autouse=True)
def restore_settings():
    """테스트가 바꾼 Settings 싱글턴 값을 원래대로 되돌린다.

    get_settings()는 lru_cache라 프로세스 전역에서 같은 인스턴스를 공유하므로,
    한 테스트의 변경이 다음 테스트로 새어나간다.
    """
    settings = get_settings()
    snapshot = settings.model_dump()

    yield

    for key, value in snapshot.items():
        try:
            setattr(settings, key, value)
        except (AttributeError, ValueError):
            # 계산된 속성 등 되돌릴 수 없는 항목은 건너뛴다.
            pass
