from unittest.mock import AsyncMock

import pytest

from app.api import lilac


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["ohli24", "moeni", "aniwolf", "aniweek", "zzapflix"])
async def test_provider_ids_are_never_invented_or_resolved_on_another_provider(source, monkeypatch):
    query = AsyncMock(side_effect=AssertionError("unrelated provider lookup"))
    monkeypatch.setattr(lilac, "_anilist_query", query)
    result = await lilac.get_anime_stream(title="Blue Box", mal_id=123, source=source)
    assert result["success"] is False
    assert result["stream_url"] is None
    assert result["source"] == source
    query.assert_not_awaited()


@pytest.mark.asyncio
async def test_mismatched_episode_url_is_rejected_before_network(monkeypatch):
    from app.engine import episode_sites
    extract = AsyncMock(side_effect=AssertionError("must not contact another provider"))
    monkeypatch.setattr(episode_sites, "extract_episode", extract)
    result = await lilac.get_anime_stream(source="moeni",
        source_url="https://tvhot2.com/drama/12384/406786806")
    assert result["success"] is False
    extract.assert_not_called()


def test_upcoming_metadata_is_not_reported_as_finished():
    result = lilac._format_anilist_media({"id": 123, "status": "NOT_YET_RELEASED"})
    assert result["status"] == "Not yet aired"
