import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_lilac_home_endpoint():
    res = client.get("/api/lilac/home?source=ohli24")
    assert res.status_code == 200
    data = res.json()
    assert "season" in data
    assert "top" in data
    assert len(data["season"]) > 0

    res_zzap = client.get("/api/lilac/home?source=zzapflix")
    assert res_zzap.status_code == 200
    data_zzap = res_zzap.json()
    assert "season" in data_zzap
    assert len(data_zzap["season"]) > 0


def test_lilac_schedule_endpoint():
    res = client.get("/api/lilac/schedule")
    assert res.status_code == 200
    data = res.json()
    assert "schedule" in data


def test_lilac_search_endpoint():
    res = client.get("/api/lilac/search?q=")
    assert res.status_code == 200
    data = res.json()
    assert "results" in data


def test_setup_open_folder_endpoint():
    res_get = client.get("/api/setup/open-folder?path=vod")
    assert res_get.status_code == 200
    assert "path" in res_get.json()

    res_post = client.post("/api/setup/open-folder?path=vod")
    assert res_post.status_code == 200
    assert "path" in res_post.json()


def test_lilac_stream_endpoint():
    res = client.get("/api/lilac/stream?source=ohli24&anime_id=123&ep=1")
    assert res.status_code == 200
    data = res.json()
    assert "stream_url" in data

    res_zzap = client.get("/api/lilac/stream?source=zzapflix&mal_id=123692&episode=1")
    assert res_zzap.status_code == 200
    data_zzap = res_zzap.json()
    assert data_zzap.get("success") is True
    assert "stream_url" in data_zzap

