import sqlite3

import pytest

from app.store import db


def test_failed_migration_closes_connection_and_retries_initialization(tmp_path, monkeypatch):
    database = db.Database(tmp_path / "recovery.db")
    migrate = db.apply_migrations
    connections = []

    def fail_once(connection):
        connections.append(connection)
        if len(connections) == 1:
            raise sqlite3.OperationalError("migration interrupted")
        return migrate(connection)

    monkeypatch.setattr(db, "apply_migrations", fail_once)
    with pytest.raises(sqlite3.OperationalError, match="migration interrupted"):
        database.connect()
    assert database._conn is None
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connections[0].execute("SELECT 1")
    try:
        recovered = database.connect()
        assert recovered is not connections[0]
        assert len(connections) == 2
        assert recovered.execute("SELECT 1").fetchone()[0] == 1
    finally:
        database.close()
