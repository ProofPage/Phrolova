"""Unit tests for LilacAnime API router."""

from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_lilac_home_endpoint_structure(client):
    """Test /api/lilac/home structure and fallback handling."""
    with patch("app.api.lilac._fetch_cached", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = {"data": [{"mal_id": 1, "title": "Cowboy Bebop"}]}
        resp = client.get("/api/lilac/home")
        assert resp.status_code == 200
        data = resp.json()
        assert "season" in data
        assert "top" in data
        assert isinstance(data["season"], list)
        assert isinstance(data["top"], list)
        assert data["season"][0]["title"] == "Cowboy Bebop"


def test_lilac_schedule_endpoint(client):
    """Test /api/lilac/schedule endpoint."""
    with patch("app.api.lilac._fetch_cached", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = {"data": [{"mal_id": 2, "title": "Attack on Titan"}]}
        resp = client.get("/api/lilac/schedule?day=monday")
        assert resp.status_code == 200
        data = resp.json()
        assert "schedule" in data
        assert isinstance(data["schedule"], list)
        assert data["schedule"][0]["title"] == "Attack on Titan"


def test_lilac_search_endpoint(client):
    """Test /api/lilac/search endpoint with pagination and params."""
    with patch("app.api.lilac._fetch_cached", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = {
            "data": [{"mal_id": 20, "title": "Naruto"}],
            "pagination": {"has_next_page": True},
        }
        resp = client.get("/api/lilac/search?q=Naruto&limit=5")
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert "pagination" in data
        assert data["results"][0]["title"] == "Naruto"


def test_lilac_skip_times_fallback(client):
    """Test /api/lilac/skip-times endpoint returns graceful structure."""
    resp = client.get("/api/lilac/skip-times/21/1?duration=1420")
    assert resp.status_code == 200
    data = resp.json()
    assert "found" in data
    assert "results" in data
    assert isinstance(data["results"], list)

