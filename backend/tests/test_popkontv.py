"""PopkonTV identity, API grants, authentication scope and media integrations."""

import asyncio
import base64
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
import requests
from Cryptodome.Cipher import AES
from Cryptodome.Util.Padding import pad
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.engine import popkontv as pop
from app.engine.base import Platform, PlatformEngine
from app.engine.conductor import Conductor
from app.engine.platform_auth import platform_cookie_jar
from app.engine.platform_media import (
    canonical_platform_video,
    media_platform,
    platform_ydl,
)
from app.engine.popkontv_extractor import PopkonTVIE
from app.engine.preview_proxy import PreviewProxy
from app.engine.recording_errors import RecordingError
from tests.test_new_platforms import local_hls as _local_hls

local_hls = _local_hls

CHANNEL = "fixture@P-00117"
PAGE = pop.popkontv_live_url(CHANNEL)
MEDIA = "https://live-popkontv.hscdn.com/cast/fixture_P-00117_20261016100624/index.m3u8"
META = {
    "mc_signId": "fixture",
    "mc_partnerCode": "P-00117",
    "mc_castStartDate": "20261016100624",
    "mc_watchCnt": 123,
    "mc_nickName": "테스트",
    "mc_pTitle": "방송",
    "mc_isPrivate": 0,
    "castType": 0,
    "accountType": 0,
}


@pytest.mark.parametrize(
    "value",
    [
        CHANNEL,
        "FIXTURE@p-00117",
        PAGE,
        PAGE + "&from=home",
        "http://popkontv.com:80/live/view?castId=fixture&partnerCode=P-00117",
    ],
)
def test_live_partner_identity_roundtrip(value):
    assert pop.normalize_popkontv_channel_id(value) == CHANNEL
    assert pop.normalize_popkontv_channel_id(pop.popkontv_live_url(value)) == CHANNEL
    assert pop.normalize_popkontv_channel_id("fixture") == "fixture@P-00001"


@pytest.mark.parametrize(
    "value",
    [
        "",
        PAGE + "&castId=other",
        PAGE + "&partnerCode=P-00001",
        PAGE.replace(".com/", ".com.evil/"),
        PAGE.replace("www.", "u:p@www."),
        PAGE.replace(".com/", ".com:444/"),
        PAGE.replace("/live/view", "/vod/1"),
        PAGE.replace("https:", "file:"),
        "fixture\nother",
        "f@P-12",
    ],
)
def test_bad_live_identity(value):
    with pytest.raises(ValueError):
        pop.normalize_popkontv_channel_id(value)


@pytest.mark.parametrize("kind", ["vod", "clip"])
def test_video_url_canonical_and_extractor(kind):
    url = f"http://popkontv.com/{kind}/00023501/?share=1#top"
    assert canonical_platform_video(url) == f"https://www.popkontv.com/{kind}/23501"
    assert media_platform(url) == "popkontv"
    with platform_ydl(url, {"quiet": True}) as ydl:
        assert isinstance(ydl._ies["PopkonTV"], PopkonTVIE)


@pytest.mark.parametrize(
    "value",
    [
        "https://www.popkontv.com/vod/0",
        "https://www.popkontv.com/clip/-1",
        "https://www.popkontv.com/clip/1/extra",
        "https://www.popkontv.com.evil/vod/2",
        "https://user@www.popkontv.com/vod/2",
        "https://www.popkontv.com:123/vod/2",
    ],
)
def test_invalid_video_url(value):
    with pytest.raises(ValueError):
        pop.parse_popkontv_video_url(value)


def mock_api(monkeypatch, metadata=None, grant=None, status=200):
    calls = []
    original = httpx.Client

    def route(request):
        calls.append(request)
        if request.url.path.endswith("/mcinfo"):
            return httpx.Response(
                200,
                json={
                    "statusCd": "S2000",
                    "data": META if metadata is None else metadata,
                },
            )
        return httpx.Response(
            status, json=grant or {"statusCd": "L0000", "data": {"castHlsUrl": MEDIA}}
        )

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kw: original(transport=httpx.MockTransport(route), **kw),
    )
    monkeypatch.setattr(
        pop,
        "public_web_config",
        lambda *a: {"ClientKey": "Client public-fixture", "version": "4.6.2"},
    )
    return calls


@pytest.mark.asyncio
async def test_metadata_cache_kst_and_schema(monkeypatch):
    calls = mock_api(monkeypatch)
    engine = pop.PopkonTVLiveEngine()
    status = await engine.check_live_status(CHANNEL)
    assert (
        status["is_live"]
        and status["viewer_count"] == 123
        and status["live_started_at"] == "2026-10-16T10:06:24+09:00"
    )
    assert (await engine.check_live_status(CHANNEL)) == status and len(calls) == 1
    assert json.loads(calls[0].content)["castPartnerCode"] == "P-00117"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("mc_signId", "other"),
        ("mc_partnerCode", "P-00001"),
        ("mc_castStartDate", "bad"),
    ],
)
async def test_mismatched_metadata_is_not_offline(monkeypatch, field, value):
    data = {**META, field: value}
    mock_api(monkeypatch, metadata=data)
    with pytest.raises(RecordingError):
        await pop.PopkonTVLiveEngine().check_live_status(CHANNEL)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value", [("mc_isPrivate", 1), ("castType", 1), ("accountType", 1)]
)
async def test_no_automatic_password_or_paid_view(monkeypatch, field, value):
    calls = mock_api(monkeypatch, metadata={**META, field: value})
    with pytest.raises(RecordingError):
        await pop.PopkonTVLiveEngine().get_qualities(CHANNEL)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_http_200_denial_never_uses_media_url(monkeypatch):
    from streamlink.stream.hls import HLSStream

    calls = mock_api(
        monkeypatch,
        grant={
            "statusCd": "L0001",
            "statusMsg": "로그인 후 이용",
            "data": {"castHlsUrl": MEDIA},
        },
    )
    parse = Mock()
    monkeypatch.setattr(HLSStream, "parse_variant_playlist", parse)
    with pytest.raises(RecordingError) as caught:
        await pop.PopkonTVLiveEngine().get_qualities(CHANNEL)
    assert caught.value.code == "popkontv_authentication" and not caught.value.retryable
    assert len(calls) == 2 and calls[1].url.path.endswith("castwatchonoffguest")
    parse.assert_not_called()


@pytest.mark.parametrize(
    "code,expected,retryable",
    [
        ("E4004", "not_found", False),
        ("L000A", "authentication", False),
        ("L000E", "maintenance", True),
        ("OTHER", "access", False),
    ],
)
def test_status_errors(code, expected, retryable):
    with pytest.raises(RecordingError) as caught:
        pop.response_data({"statusCd": code, "data": {}})
    assert (
        caught.value.code == "popkontv_" + expected
        and caught.value.retryable is retryable
    )


def encrypt_cookie(value, passphrase):
    salt = b"12345678"
    key = b""
    previous = b""
    while len(key) < 48:
        previous = hashlib.md5(previous + passphrase.encode() + salt).digest()
        key += previous
    cipher = AES.new(key[:32], AES.MODE_CBC, key[32:48]).encrypt(
        pad(json.dumps(value).encode(), 16)
    )
    return base64.b64encode(b"Salted__" + salt + cipher).decode()


def account_jar(domain=".popkontv.com"):
    jar = requests.cookies.RequestsCookieJar()
    jar.set(
        "auth-tk",
        encrypt_cookie(
            "fixture-token", "SECRET_PSID12__SECRET_PSID12_SECRET_PSID12__SECRET_PSID12"
        ),
        domain=domain,
        path="/",
        secure=True,
    )
    jar.set(
        "user",
        encrypt_cookie({"signId": "viewer", "partnerCode": "P-00001"}, "SECRET_PSID1"),
        domain=domain,
        path="/",
        secure=True,
    )
    return jar


def test_own_cookie_decode_and_domain_scope():
    assert pop.popkontv_account(account_jar()) == (
        {"Authorization": "Bearer fixture-token"},
        {"signId": "viewer", "partnerCode": "P-00001", "adult_verified": False},
    )
    assert pop.popkontv_account(account_jar(".evil.example")) == ({}, None)
    session = requests.Session()
    session.cookies.update(account_jar())
    assert (
        "Cookie" not in session.prepare_request(requests.Request("GET", MEDIA)).headers
    )
    with pytest.raises(RecordingError):
        pop._decode_account_cookie("invalid", "password")
    session.close()


@pytest.mark.asyncio
async def test_authenticated_api_qualities_do_not_leak_account_to_cdn(monkeypatch):
    from streamlink.stream.hls import HLSStream

    calls = mock_api(monkeypatch)
    seen = []
    monkeypatch.setattr(pop, "platform_cookie_jar", lambda p: account_jar())

    def parse(session, url, **kw):
        seen.append(kw["headers"])
        assert "Authorization" not in kw["headers"] and "ClientKey" not in kw["headers"]
        return {
            f"{h}p": SimpleNamespace(to_url=lambda h=h: MEDIA.replace("index", str(h)))
            for h in (720, 1080)
        }

    monkeypatch.setattr(HLSStream, "parse_variant_playlist", parse)
    engine = pop.PopkonTVLiveEngine()
    qualities = await engine.get_qualities(CHANNEL)
    assert [q["value"] for q in qualities] == [
        "1080p",
        "720p",
    ] and "url" not in qualities[0]
    assert (
        calls[1].url.path.endswith("/castwatchonoff")
        and calls[1].headers["authorization"] == "Bearer fixture-token"
    )
    assert json.loads(calls[1].content)["signId"] == "viewer"
    assert "1080" in (await engine.resolve_stream(CHANNEL))[0]
    assert "720" in (await engine.resolve_stream(CHANNEL, "worst"))[0]
    with pytest.raises(RecordingError):
        await engine.resolve_stream(CHANNEL, "2160p")
    assert len(calls) == 2 and len(seen) == 1


def test_dynamic_public_config_literals_no_evaluation(monkeypatch):
    monkeypatch.setattr(pop, "_web_config", None)

    def route(request):
        if request.url.path == "/live/view":
            body = '<script src="/_next/static/chunks/pages/_app-a.js"></script><script src="/_next/static/chunks/site-b.js"></script>'
        elif "_app" in request.url.path:
            body = 'PW:"".concat(o.w.CLIENT," public123=")'
        else:
            body = 'BROADCAST.CAST_WATCH_ON_OFF;nn="4.6.2";version:nn'
        return httpx.Response(200, text=body)

    with httpx.Client(transport=httpx.MockTransport(route)) as client:
        assert pop.public_web_config(client, PAGE) == {
            "ClientKey": "Client public123=",
            "version": "4.6.2",
        }


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/a",
        "http://live-popkontv.hscdn.com/a",
        "https://live-popkontv.hscdn.com.evil/a",
        "https://user@vod2.popkontv.hscdn.com/a",
        "https://vod2.popkontv.hscdn.com:444/a",
        None,
    ],
)
def test_cdn_boundary(url):
    assert not pop.valid_media_url(url)


@pytest.mark.parametrize("kind,group", [("vod", "1"), ("clip", "20")])
def test_extractor_native_mp4_and_api_only_auth(monkeypatch, kind, group):
    with platform_ydl(
        "https://www.popkontv.com/" + kind + "/23501", {"quiet": True}
    ) as ydl:
        ie = PopkonTVIE(ydl)
        calls = []

        def metadata(url, vid, **kw):
            calls.append((url, kw))
            return {
                "statusCd": "S2000",
                "data": {
                    "pk_code": "23501",
                    "groupCode": group,
                    "isAdult": "0",
                    "vodTitle": "테스트",
                    "vodAddress": "https://vod2.popkontv.hscdn.com/video.mp4",
                },
            }

        monkeypatch.setattr(ie, "_download_json", metadata)
        info = ie._real_extract("https://www.popkontv.com/" + kind + "/23501")
        assert (
            info["formats"][0]["format_id"] == "source"
            and "height" not in info["formats"][0]
        )
        assert "Authorization" not in info["http_headers"] and calls[0][0].endswith(
            "/vod/v1/detail"
        )


def test_platform_registration_cookie_crud_and_capabilities(monkeypatch, tmp_path):
    import app.main
    from app.api import platforms, stream, vod

    conductor = Conductor()
    service = SimpleNamespace(
        _conductor=conductor,
        add_platform_channel=Mock(return_value={"status": "added"}),
    )
    monkeypatch.setattr(app.main, "get_recorder_service", lambda: service)
    monkeypatch.setattr(platforms, "_COOKIE_SAVE_PATH", tmp_path / "platform.txt")
    app = FastAPI()
    app.include_router(platforms.router)
    app.include_router(vod.router)
    with TestClient(app) as client:
        result = client.post(
            "/api/platforms/channels",
            json={
                "platform": "popkontv",
                "channel_id": PAGE,
                "recording_quality": "720p",
            },
        )
        assert (
            result.status_code == 200
            and service.add_platform_channel.call_args.kwargs["channel_id"] == CHANNEL
        )
        assert client.get("/api/platforms/status").json()["popkontv"]["enabled"]
        sources = [
            s["id"] for s in client.get("/api/vod/capabilities").json()["sources"]
        ]
        assert (
            len(sources) == 18 and "popkontv" in sources and "pandalive" not in sources
        )
        cookies = b"# Netscape HTTP Cookie File\n.popkontv.com\tTRUE\t/\tTRUE\t0\tfixture\tSECRET\n.evil.example\tTRUE\t/\tTRUE\t0\tfixture\tOTHER\n"
        result = client.post(
            "/api/platforms/popkontv/cookie", files={"file": ("cookies.txt", cookies)}
        )
        assert (
            result.status_code == 200
            and result.json()["valid"]
            and "SECRET" not in result.text
        )
        assert all("popkontv.com" in c.domain for c in platform_cookie_jar("popkontv"))
        assert client.delete("/api/platforms/popkontv/cookie").status_code == 200
    assert isinstance(conductor._get_engine(Platform.POPKONTV), pop.PopkonTVLiveEngine)
    assert isinstance(pop.PopkonTVLiveEngine(), PlatformEngine)
    assert stream._to_composite_key("popkontv:" + CHANNEL) == "popkontv:" + CHANNEL


def test_preview_urls_opaque_scoped_and_no_api_bearer():
    proxy = PreviewProxy()
    token = proxy.register("popkontv:" + CHANNEL, "popkontv", MEDIA)
    body = proxy.rewrite(proxy.nodes[token], "#EXTM3U\npart.ts?token=SECRET\n")
    assert "SECRET" not in body and "/api/stream/preview-media/" in body
    assert not proxy.allowed("https://evil.example/a", {""}, "popkontv")


@pytest.mark.asyncio
async def test_preview_fetch_scoped_headers_cookies_and_redirects(monkeypatch):
    calls = []
    original = httpx.AsyncClient

    def route(request):
        calls.append(request)
        if request.url.path.endswith(".m3u8"):
            return httpx.Response(
                200, text="#EXTM3U\n#EXTINF:2,\npart.ts?token=SECRET\n"
            )
        return httpx.Response(200, content=b"transport")

    monkeypatch.setattr(
        "app.engine.preview_proxy.platform_cookie_jar", lambda _: account_jar()
    )
    monkeypatch.setattr("app.engine.preview_proxy.preview_ca_bundle", lambda: True)
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: original(transport=httpx.MockTransport(route), **kw),
    )
    proxy = PreviewProxy()
    token = proxy.register("popkontv:" + CHANNEL, "popkontv", MEDIA)
    data, _kind, status, _ = await proxy.fetch(token)
    assert status == 200 and b"SECRET" not in data
    child = data.decode().splitlines()[-1].split("/")[-2]
    assert (await proxy.fetch(child))[0] == b"transport"
    assert all(
        r.headers["referer"] == PAGE and r.headers["origin"] == pop.ORIGIN
        for r in calls
    )
    assert all(
        not any(h in r.headers for h in ("authorization", "cookie", "clientkey"))
        for r in calls
    )


def test_preview_auth_error_keeps_reason_and_unknown_error_is_redacted(monkeypatch):
    import app.main
    from app.api import stream

    service = SimpleNamespace(
        get_live_preview_url=AsyncMock(
            side_effect=RecordingError(
                "popkontv_authentication", "팝콘티비 로그인이 필요합니다."
            )
        )
    )
    monkeypatch.setattr(app.main, "get_recorder_service", lambda: service)
    app = FastAPI()
    app.include_router(stream.router)
    with TestClient(app) as client:
        result = client.get("/api/stream/preview/popkontv:" + CHANNEL)
        assert result.status_code == 403 and "로그인" in result.json()["detail"]
        service.get_live_preview_url.side_effect = RuntimeError(
            "https://cdn.example/live?token=PRIVATE"
        )
        result = client.get("/api/stream/preview/popkontv:" + CHANNEL)
        assert result.status_code == 502 and "PRIVATE" not in result.text


@pytest.mark.parametrize(
    "change",
    [
        {"isAdult": "1"},
        {"locType": "1"},
        {"pk_code": "999"},
        {"groupCode": "20"},
        {"vodAddress": "https://evil.example/video.mp4"},
    ],
)
def test_restricted_and_mismatched_vod_cannot_play(monkeypatch, change):
    from yt_dlp.utils import ExtractorError

    with platform_ydl("https://www.popkontv.com/vod/23501", {"quiet": True}) as ydl:
        ie = PopkonTVIE(ydl)
        data = {
            "pk_code": "23501",
            "groupCode": "1",
            "isAdult": "0",
            "locType": "0",
            "vodAddress": "https://vod2.popkontv.hscdn.com/video.mp4",
            **change,
        }
        monkeypatch.setattr(
            ie, "_download_json", lambda *a, **kw: {"statusCd": "S2000", "data": data}
        )
        with pytest.raises(ExtractorError):
            ie._real_extract("https://www.popkontv.com/vod/23501")


@pytest.mark.asyncio
async def test_adult_cookie_requires_verified_flag_before_watch(monkeypatch):
    calls = mock_api(monkeypatch, metadata={**META, "isAdult": "1"})
    monkeypatch.setattr(pop, "platform_cookie_jar", lambda _: account_jar())
    with pytest.raises(RecordingError) as caught:
        await pop.PopkonTVLiveEngine().get_qualities(CHANNEL)
    assert caught.value.code == "popkontv_authentication" and len(calls) == 1


def test_video_media_path_allows_real_unicode_spaces_but_not_controls():
    assert pop.valid_media_url(
        "https://vod2.popkontv.hscdn.com/CAST_VOD/테스트 영상.mp4"
    )
    assert not pop.valid_media_url("\nhttps://vod2.popkontv.hscdn.com/video.mp4")


@pytest.mark.asyncio
async def test_actual_streamlink_manifest_resolution(local_hls, monkeypatch):
    base, directory = local_hls
    folder = directory / "fixture_P-00117_20261016100624"
    folder.mkdir()
    manifest = (directory / "master.m3u8").read_text()
    for height in (1080, 720, 480):
        manifest = manifest.replace(
            f"{height}/index.m3u8", f"{base}/{height}/index.m3u8"
        )
    (folder / "index.m3u8").write_text(manifest)
    mock_api(
        monkeypatch,
        grant={
            "statusCd": "L0000",
            "data": {"castHlsUrl": base + "/" + folder.name + "/index.m3u8"},
        },
    )
    # Only this local HTTP fixture replaces the production HTTPS/CDN boundary.
    monkeypatch.setattr(
        pop,
        "valid_media_url",
        lambda url: isinstance(url, str) and url.startswith(base + "/"),
    )
    engine = pop.PopkonTVLiveEngine()
    qualities = await engine.get_qualities(CHANNEL)
    assert [q["height"] for q in qualities] == [1080, 720, 480]
    assert qualities[0]["width"] == 1920 and qualities[0]["fps"] == 5
    assert (await engine.resolve_stream(CHANNEL, "720p"))[0] == base + "/720/index.m3u8"


@pytest.mark.asyncio
async def test_live_transport_and_finalizer(local_hls, monkeypatch):
    from app.engine.media_inspection import probe_media
    from app.engine.pipeline import YtdlpLivePipeline
    from app.engine.recording_finalizer import RecordingFinalizer
    from tests.test_recording_finalization import terminal

    base, directory = local_hls
    engine = pop.PopkonTVLiveEngine()
    monkeypatch.setattr(
        engine,
        "_streams",
        AsyncMock(
            return_value=[
                {
                    "value": "720p",
                    "url": base + "/720/index.m3u8",
                    "height": 720,
                    "fps": 5,
                    "bitrate": 1,
                }
            ]
        ),
    )
    pipeline = YtdlpLivePipeline(CHANNEL)
    manager = RecordingFinalizer()
    try:
        await pipeline.start_recording(
            stream_obj=PAGE,
            output_dir=str(directory / "popkon"),
            quality="720p",
            source_resolver=lambda q: engine.resolve_stream(CHANNEL, q),
        )
        await asyncio.wait_for(asyncio.shield(pipeline._feeder_task), 15)
        await pipeline.stop_recording()
        job_id = manager.register_capture(
            "popkontv:" + CHANNEL,
            pipeline,
            SimpleNamespace(
                platform=Platform.POPKONTV, channel_id=CHANNEL, channel_name="PopkonTV"
            ),
            {"output_format": "mkv", "keep_source_ts": True},
        )
        await manager.capture_finished(job_id, pipeline)
        job = await terminal(manager, job_id)
        assert job["state"] == "completed" and job["inspection_state"] == "passed"
        assert probe_media(job["output_path"])["streams"] == {"video", "audio"}
    finally:
        await pipeline.stop_recording()
        await manager.close()
