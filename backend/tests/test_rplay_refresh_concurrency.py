import json
import threading
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from app.core.config import get_settings
from app.engine import rplay


@pytest.mark.parametrize("count", [12, 16, 24])
def test_expired_requests_share_rotated_session(monkeypatch, tmp_path, count):
    old = dict(accessToken="OLD-ACCESS-TOKEN-123456", refreshToken="OLD-REFRESH-TOKEN-123456",
               requestorOid="a" * 24, loginType="rplay")
    new = dict(old, accessToken="NEW-ACCESS-TOKEN-123456", refreshToken="NEW-REFRESH-TOKEN-123456")
    path = tmp_path / "session.json"
    path.write_text(json.dumps(old), encoding="utf-8")
    monkeypatch.setattr(get_settings(), "rplay_session_file", str(path))
    calls = []
    original = httpx.Client

    def route(request):
        calls.append(request)
        assert request.headers["refresh-token"] == old["refreshToken"]
        return httpx.Response(200, json=new)

    monkeypatch.setattr(httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(route), **kw))
    barrier = threading.Barrier(count)

    def refresh(_):
        barrier.wait(timeout=10)
        return rplay.refresh_session_token(dict(old))

    with ThreadPoolExecutor(max_workers=count) as pool:
        futures = [pool.submit(refresh, i) for i in range(count)]
        assert [f.result(timeout=15) for f in futures] == [new] * count
    assert len(calls) == 1
    assert json.loads(path.read_text(encoding="utf-8")) == new


def test_refresh_uses_latest_rotated_refresh_token(monkeypatch):
    current = dict(accessToken="expired-current", refreshToken="rotated", requestorOid="a" * 24)
    monkeypatch.setattr(rplay, "read_session", lambda: current)
    monkeypatch.setattr(rplay, "session_expired", lambda _: True)
    seen = []
    monkeypatch.setattr(rplay, "_refresh_session_token", lambda session: seen.append(session) or session)
    assert rplay.refresh_session_token(dict(current, refreshToken="stale")) == current
    assert seen == [current]


def test_account_change_does_not_refresh_old_account(monkeypatch):
    from yt_dlp.utils import ExtractorError
    current = dict(accessToken="current", requestorOid="b" * 24)
    monkeypatch.setattr(rplay, "read_session", lambda: current)
    def unexpected(_):
        pytest.fail("Old account must not be refreshed or persisted")
    monkeypatch.setattr(rplay, "_refresh_session_token", unexpected)
    with pytest.raises(ExtractorError, match="계정이 변경"):
        rplay.refresh_session_token(dict(accessToken="old", requestorOid="a" * 24))
