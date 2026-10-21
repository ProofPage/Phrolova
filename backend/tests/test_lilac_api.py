import pytest
from unittest.mock import AsyncMock
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_lilac_home_endpoint(monkeypatch):
    from app.api import lilac
    media = {"id": 101, "idMal": 202, "title": {"english": "Live metadata"}}
    query = AsyncMock(return_value={"seasonMedia": {"media": [media]}, "topMedia": {"media": [media]}})
    monkeypatch.setattr(lilac, "_anilist_query", query)
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

    res_wolf = client.get("/api/lilac/home?source=aniwolf")
    assert res_wolf.status_code == 200
    assert "season" in res_wolf.json()

    res_week = client.get("/api/lilac/home?source=aniweek")
    assert res_week.status_code == 200
    assert "season" in res_week.json()
    assert query.await_count == 4
    for response in (res, res_zzap, res_wolf, res_week):
        assert response.json()["season"][0]["mal_id"] == 202
        assert response.json()["availability_verified"] is False


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
    assert data_zzap.get("success") is False
    assert "stream_url" in data_zzap

