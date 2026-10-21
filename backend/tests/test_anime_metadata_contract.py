"""Regression checks for catalog seasons and distinct provider IDs."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api import lilac


@pytest.mark.parametrize(
    ("month", "season"),
    [(1, "WINTER"), (3, "WINTER"), (4, "SPRING"), (6, "SPRING"),
     (7, "SUMMER"), (9, "SUMMER"), (10, "FALL"), (12, "FALL")],
)
def test_anilist_season_boundaries(monkeypatch, month, season):
    monkeypatch.setattr(lilac.time, "gmtime", lambda: SimpleNamespace(tm_year=2026, tm_mon=month))
    assert lilac._current_season() == (season, 2026)


@pytest.mark.asyncio
async def test_mal_detail_never_looks_up_anilist_id(monkeypatch):
    query = AsyncMock(return_value={"Media": {"id": 154587, "idMal": 52991,
                                             "title": {"english": "Frieren"}}})
    monkeypatch.setattr(lilac, "_anilist_query", query)
    result = await lilac.get_anime_detail(52991, id_type="mal")
    assert result["anime"]["anilist_id"] == 154587
    assert query.call_count == 1
    args = query.call_args.args
    assert "Media(idMal: $idMal," in args[0]
    assert args[1] == {"idMal": 52991}


@pytest.mark.asyncio
async def test_missing_mal_detail_does_not_switch_id_namespace(monkeypatch):
    query = AsyncMock(return_value={})
    monkeypatch.setattr(lilac, "_anilist_query", query)
    assert await lilac.get_anime_detail(52991, id_type="mal") == {"anime": {}}
    assert query.call_count == 1
