"""Removed platforms must not run or overwrite existing user data."""

from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.platforms import router
from app.core.config import Settings
from app.engine.base import Platform
from app.engine.conductor import Conductor
from app.engine.vod import NonRetryableDownloadError, VodEngine
from app.store.repositories import ChannelRepository


def test_unsupported_saved_channel_is_ignored_without_deletion():
    repo = ChannelRepository()
    for platform in ("twitcasting", "x_spaces", "chzzk", "youtube"):
        repo.upsert(f"{platform}:legacy", platform, "legacy", True)
    before = repo.list_all()

    conductor = Conductor(channel_repo=repo)

    assert set(conductor._channels) == {"chzzk:legacy", "youtube:legacy"}
    assert repo.list_all() == before
    conductor.add_channel("new", platform=Platform.CHZZK)
    assert any(record["platform"] == "twitcasting" for record in repo.list_all())


def test_removed_platform_requests_are_rejected():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    response = client.post("/api/platforms/channels", json={
        "platform": "twitcasting", "channel_id": "legacy", "auto_record": False,
    })
    assert response.status_code == 400
    assert client.put("/api/platforms/settings/twitcasting", json={}).status_code == 404
    assert client.get("/api/archive/twitcasting/legacy").status_code == 404
    with pytest.raises(ValueError):
        Platform("twitcasting")


def test_old_environment_keys_are_ignored(tmp_path):
    path = tmp_path / ".env"
    content = "TWITCASTING_CLIENT_ID=old\nTWITCASTING_CLIENT_SECRET=old\nTWITCASTING_COOKIE_FILE=old.txt\n"
    path.write_text(content, encoding="utf-8")

    settings = Settings(_env_file=path)

    assert not any("twitcasting" in key for key in settings.model_dump())
    assert path.read_text(encoding="utf-8") == content


@pytest.mark.asyncio
@pytest.mark.parametrize("host", ["twitcasting.tv", "www.twitcasting.tv", "TWITCASTING.TV"])
async def test_removed_media_is_rejected_before_extraction(host):
    engine = VodEngine()
    url = f"https://{host}/legacy/movie/1"
    for operation in (engine.get_video_info, engine.download):
        with pytest.raises(NonRetryableDownloadError):
            await operation(url)
    assert engine._tasks == {}


@pytest.mark.parametrize("url", [
    "https://chzzk.naver.com/video/1", "https://www.youtube.com/watch?v=abcdefghijk",
    "https://example.com/video",
    "https://twitcasting.tv.example.com/video",
])
def test_other_media_urls_remain_supported(url):
    VodEngine._validate_media_url(url)


@pytest.mark.asyncio
@pytest.mark.parametrize('url',['https://twitcasting.tv/legacy/movie/1','https://x.com/i/spaces/old'])
async def test_old_download_history_is_preserved_but_cannot_restart(url):
    repo = Mock()
    record = {"task_id": "legacy", "url": url, "state": "completed"}
    repo.list_all.return_value = [record]
    engine = VodEngine(repo=repo)

    assert engine._tasks["legacy"].url == record["url"]
    with pytest.raises(NonRetryableDownloadError):
        await engine.retry_download("legacy")
    repo.delete.assert_not_called()
    repo.replace_all.assert_not_called()
