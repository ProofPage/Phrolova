"""Program release checks must not download or install a program update."""
from unittest.mock import Mock

import httpx
import pytest

from app.engine import updater


@pytest.mark.asyncio
async def test_startup_only_checks_release_metadata(monkeypatch):
    service = updater.UpdaterService()
    requests = []

    def response(request):
        requests.append(str(request.url))
        return httpx.Response(200, json={"tag_name": "v99.0.0"})

    client = httpx.AsyncClient
    monkeypatch.setattr(updater.httpx, "AsyncClient", lambda **kwargs: client(
        transport=httpx.MockTransport(response), **kwargs))

    async def sleep(delay):
        if delay == service._CHECK_INTERVAL:
            service._running = False

    launch = Mock(side_effect=AssertionError("Program updates must not launch installers"))
    monkeypatch.setattr("subprocess.Popen", launch)
    monkeypatch.setattr(updater.asyncio, "sleep", sleep)
    service._running = True
    await service._update_loop()
    assert requests == [updater.GITHUB_API_URL]
    assert service.get_cached_info()["has_update"]
    assert "auto_update" not in service.get_cached_info()
    launch.assert_not_called()
