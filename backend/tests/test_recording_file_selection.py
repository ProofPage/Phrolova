from types import SimpleNamespace
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api import recordings


def test_source_and_output_file_routes_are_distinct(tmp_path, monkeypatch):
    source, result = tmp_path/"source.ts", tmp_path/"output.mkv"
    source.write_bytes(b"original")
    result.write_bytes(b"converted")
    job = {"state":"completed", "output_path":str(result), "source_paths":[str(source)]}
    monkeypatch.setattr(recordings, "manager", lambda: SimpleNamespace(get=lambda _: job))
    app=FastAPI();app.include_router(recordings.router)
    with TestClient(app) as client:
        assert client.get("/api/recordings/job/file").content == b"converted"
        assert client.get("/api/recordings/job/file?source=true").content == b"original"
        source.unlink()
        assert client.get("/api/recordings/job/file?source=true").status_code == 404
        assert client.get("/api/recordings/job/file").content == b"converted"
