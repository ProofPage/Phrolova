"""Server-authorized playback, fresh account/broadcast state and saved policy."""

import json
from http.cookiejar import CookieJar
from types import SimpleNamespace

import pytest
from streamlink.stream.hls import HLSStream

from app.core.config import Settings, get_settings
from app.engine import popkontv as pop
from app.engine.recording_errors import RecordingError
from tests.test_popkontv import CHANNEL, MEDIA, META, account_jar, mock_api


@pytest.fixture
def media_parser(monkeypatch):
    calls = []
    monkeypatch.setattr(pop, "platform_cookie_jar", lambda _: CookieJar())

    def parse(session, url, **kwargs):
        calls.append((url, kwargs))
        assert "Authorization" not in kwargs["headers"]
        assert "ClientKey" not in kwargs["headers"]
        return {"720p": SimpleNamespace(to_url=lambda: url.replace("index", "720"))}

    monkeypatch.setattr(HLSStream, "parse_variant_playlist", parse)
    return calls


def test_server_playback_policy_is_enabled_by_default(monkeypatch):
    monkeypatch.delenv("POPKONTV_USE_PLAYBACK_RESPONSE", raising=False)
    assert Settings(_env_file=None).popkontv_use_playback_response is True


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["mc_isPrivate", "castType", "accountType"])
@pytest.mark.parametrize("authenticated", [False, True])
async def test_broadcast_type_does_not_override_server_grant(
    monkeypatch, media_parser, field, authenticated
):
    get_settings().popkontv_use_playback_response = True
    calls = mock_api(monkeypatch, metadata={**META, field: 1})
    if authenticated:
        monkeypatch.setattr(pop, "platform_cookie_jar", lambda _: account_jar())
    result = await pop.PopkonTVLiveEngine().resolve_stream(CHANNEL)
    assert result[0] == MEDIA.replace("index", "720")
    watch = calls[-1]
    assert watch.url.path.endswith("/castwatchonoff" + ("" if authenticated else "guest"))
    body = json.loads(watch.content)
    assert body["castType"] == (1 if field == "castType" else META["castType"])
    assert body["exePath"] == 5
    assert body["password"] == ""
    assert len(media_parser) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["mc_isPrivate", "castType", "accountType"])
async def test_server_denial_is_not_overridden_by_the_enabled_policy(
    monkeypatch, media_parser, field
):
    get_settings().popkontv_use_playback_response = True
    mock_api(
        monkeypatch, metadata={**META, field: 1},
        grant={"statusCd": "L0001", "statusMsg": "로그인 후 이용하실 수 있습니다.",
               "data": {"castHlsUrl": MEDIA}},
    )
    with pytest.raises(RecordingError, match="로그인"):
        await pop.PopkonTVLiveEngine().resolve_stream(CHANNEL)
    assert media_parser == []


@pytest.mark.asyncio
async def test_connection_rereads_login_after_guest_grant(monkeypatch, media_parser):
    calls = mock_api(monkeypatch)
    engine = pop.PopkonTVLiveEngine()
    await engine.resolve_stream(CHANNEL)
    assert calls[-1].url.path.endswith("/castwatchonoffguest")
    monkeypatch.setattr(pop, "platform_cookie_jar", lambda _: account_jar())
    await engine.resolve_stream(CHANNEL)
    assert calls[-1].url.path.endswith("/castwatchonoff")
    assert calls[-1].headers["authorization"] == "Bearer fixture-token"
    assert len(media_parser) == 2


@pytest.mark.asyncio
async def test_connection_rereads_broadcast_start(monkeypatch, media_parser):
    metadata = dict(META)
    calls = mock_api(monkeypatch, metadata=metadata)
    engine = pop.PopkonTVLiveEngine()
    await engine.resolve_stream(CHANNEL)
    metadata["mc_castStartDate"] = "20261018103500"
    with pytest.raises(RecordingError, match="식별"):
        # The old grant must not be reused for the restarted broadcast.
        await engine.resolve_stream(CHANNEL)
    assert json.loads(calls[-1].content)["castCode"] == "fixture-20261018103500"
    assert len(media_parser) == 1


@pytest.mark.parametrize("enabled", [False, True])
def test_playback_policy_settings_roundtrip(api_client, tmp_path, enabled):
    response = api_client.put(
        "/api/settings/live",
        json={"max_record_retries": 3, "popkontv_use_playback_response": enabled},
    )
    assert response.status_code == 200, response.text
    assert response.json()["settings"]["popkontv_use_playback_response"] is enabled
    assert api_client.get("/api/settings").json()["popkontv_use_playback_response"] is enabled
    assert Settings(_env_file=tmp_path / ".env").popkontv_use_playback_response is enabled


@pytest.mark.asyncio
@pytest.mark.parametrize("policy", [False, True])
async def test_private_room_sends_the_entered_password(monkeypatch, media_parser, policy):
    get_settings().popkontv_use_playback_response = policy
    calls = mock_api(monkeypatch, metadata={**META, "mc_isPrivate": 1})
    engine = pop.PopkonTVLiveEngine()
    engine.set_room_password(CHANNEL, "room-1234")
    await engine.resolve_stream(CHANNEL)
    assert json.loads(calls[-1].content)["password"] == "room-1234"
    assert "room-1234" not in repr(engine._room_passwords)


@pytest.mark.asyncio
async def test_wrong_password_is_actionable_without_login_retry(monkeypatch, media_parser):
    mock_api(monkeypatch, metadata={**META, "mc_isPrivate": 1}, grant={
        "statusCd": "L0001", "statusMsg": "비밀번호가 일치하지 않습니다.", "data": {},
    })
    engine = pop.PopkonTVLiveEngine()
    engine.set_room_password(CHANNEL, "wrong-password")
    with pytest.raises(RecordingError) as error:
        await engine.resolve_stream(CHANNEL)
    assert error.value.code == "popkontv_password"
    assert "wrong-password" not in str(error.value)
    assert media_parser == []
