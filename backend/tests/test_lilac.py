"""Unit tests for Anime Hub API router."""

from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture
def client(monkeypatch):
    media = {"id": 101, "idMal": 202, "title": {"english": "Live catalog fixture"}}
    monkeypatch.setattr("app.api.lilac._anilist_query", AsyncMock(return_value={
        "seasonMedia": {"media": [media]}, "topMedia": {"media": [media]},
        "Page": {"media": [media], "airingSchedules": [{"media": media}]},
    }))
    return TestClient(app)


def test_anime_home_endpoint_structure(client):
    """Test /api/lilac/home structure and fallback handling."""
    resp = client.get("/api/lilac/home")
    assert resp.status_code == 200
    data = resp.json()
    assert "season" in data
    assert "top" in data
    assert isinstance(data["season"], list)
    assert isinstance(data["top"], list)
    assert len(data["season"]) > 0


def test_anime_schedule_endpoint(client):
    """Test /api/lilac/schedule endpoint."""
    resp = client.get("/api/lilac/schedule?day=monday")
    assert resp.status_code == 200
    data = resp.json()
    assert "schedule" in data
    assert isinstance(data["schedule"], list)
    assert len(data["schedule"]) > 0


def test_anime_search_endpoint(client):
    """Test /api/lilac/search endpoint with pagination and params."""
    resp = client.get("/api/lilac/search?q=Naruto&limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert "results" in data
    assert "pagination" in data
    assert isinstance(data["results"], list)
    assert len(data["results"]) > 0


def test_anime_skip_times_fallback(client):
    """Test /api/lilac/skip-times endpoint returns graceful structure."""
    resp = client.get("/api/lilac/skip-times/21/1?duration=1420")
    assert resp.status_code == 200
    data = resp.json()
    assert "found" in data
    assert "results" in data
    assert isinstance(data["results"], list)


