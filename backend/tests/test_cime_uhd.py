"""CIME's authorized UHD flow, measured fMP4 dimensions and native 4K capture."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import gzip
import json
from pathlib import Path
import shutil
import struct
import subprocess

import httpx
import pytest
import requests

from app.core.config import get_settings
from app.engine import cime
from app.engine.platform_auth import PlatformAuthenticationError
from tests.test_new_platforms import local_hls


CHANNEL = "1067321"
PAGE = "https://ci.me/@alice/live"
UHD = f"https://view.ci.me/uhd/{CHANNEL}/s0/ingest/channel-{CHANNEL}/playlist.m3u8"
STANDARD = "https://cdn.example/master.m3u8"
MASTER = """#EXTM3U
#EXT-X-STREAM-INF:RESOLUTION=1920x1080,BANDWIDTH=8000000,FRAME-RATE=60
full.m3u8
#EXT-X-STREAM-INF:RESOLUTION=1280x720,BANDWIDTH=3000000,FRAME-RATE=60
hd.m3u8
"""
MEDIA = """#EXTM3U
#EXT-X-TARGETDURATION:1
#EXT-X-MAP:URI="init.mp4"
#EXTINF:1,
segment.m4s
"""
SIGNED = {"CloudFront-Policy": "policy-PRIVATE", "CloudFront-Signature": "signature-PRIVATE",
          "CloudFront-Key-Pair-Id": "key-PRIVATE"}


def box(kind, data):
    return struct.pack(">I4s", len(data) + 8, kind) + data


def initialization(width=3840, height=2160, *, version=0, handler=b"vide"):
    header = bytearray(96 if version == 1 else 84)
    header[0] = version
    header[-8:] = struct.pack(">II", width << 16, height << 16)
    return box(b"ftyp", b"isom") + box(b"moov", box(b"trak",
        box(b"tkhd", header) + box(b"mdia", box(b"hdlr", b"\0" * 8 + handler))))


@pytest.fixture
def api(monkeypatch, tmp_path):
    cookie = tmp_path / "cime.txt"
    cookie.write_text("# Netscape HTTP Cookie File\n.ci.me\tTRUE\t/\tTRUE\t0\tsession-id\taccount-PRIVATE\n")
    monkeypatch.setattr(get_settings(), "cime_cookie_file", str(cookie))
    calls = []
    state = {"grant_status": 200, "allowed": True, "media": MEDIA, "init": initialization(), "init_headers": {}}

    def respond(request):
        calls.append(request)
        if request.url.host == "ci.me" and request.url.path.startswith("/json/"):
            authenticated = "account-PRIVATE" in request.headers.get("cookie", "")
            allowed = authenticated and state["allowed"]
            return httpx.Response(200, json={"bodyData": {"live": {
                "state": "ACTIVE", "id": "1006180", "channel": {"id": CHANNEL, "name": "Fixture"},
                "playback": {"url": STANDARD, "urlUhd": UHD if allowed else None,
                             "uhdActive": True, "canWatchUhd": allowed, "uhdFps": 60 if allowed else None},
            }}})
        if request.url.path == "/api/app/streams/sign-cookie":
            assert request.method == "POST"
            assert json.loads(request.content) == {"type": "UHD", "channelId": CHANNEL}
            assert "account-PRIVATE" in request.headers.get("cookie", "")
            return httpx.Response(state["grant_status"], json={"code": state["grant_status"], "data": {
                "expiresAt": "2099-01-01T00:00:00Z", "ttlSec": 900, "refreshAfterSec": 540,
                "cookiePath": f"/uhd/{CHANNEL}", "cookies": None,
            }}, headers=[("set-cookie", f"{name}={value}; Domain=.ci.me; Path=/uhd/{CHANNEL}; Secure; HttpOnly")
                         for name, value in SIGNED.items()])
        if request.url.host == "view.ci.me":
            assert "account-PRIVATE" not in request.headers.get("cookie", "")
            assert all(value in request.headers.get("cookie", "") for value in SIGNED.values())
            if request.url.path.endswith("init.mp4"):
                return httpx.Response(200, content=state["init"], headers=state["init_headers"])
            return httpx.Response(200, text=state["media"])
        if request.url.host == "cdn.example":
            assert "cookie" not in request.headers
            return httpx.Response(200, text=MASTER)
        raise AssertionError(f"Unexpected request: {request.url.host}{request.url.path}")

    original_async, original_sync = httpx.AsyncClient, httpx.Client
    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: original_async(*a, **kw, transport=transport))
    monkeypatch.setattr(httpx, "Client", lambda *a, **kw: original_sync(*a, **kw, transport=transport))
    return calls, state


@pytest.mark.asyncio
async def test_public_cache_does_not_hide_authorized_uhd(api):
    calls, _ = api
    engine = cime.CimeLiveEngine()
    assert (await engine.check_live_status("alice"))["is_live"]
    qualities = await engine.get_qualities("alice")
    assert [item["value"] for item in qualities] == ["2160p60", "1080p60", "720p60"]
    assert qualities[0]["width"] == 3840
    spec = await engine.resolve_stream_spec("alice", "2160p60")
    assert (spec["width"], spec["height"], spec["fps"]) == (3840, 2160, 60)
    assert spec["url"] == UHD and spec["video_index"] is None
    assert "account-PRIVATE" not in spec["cookies"]
    assert all(value in spec["cookies"] for value in SIGNED.values())
    assert not any("cookie" == key.lower() for key in spec["headers"])
    assert (await engine.resolve_stream_spec("alice", "best"))["height"] == 2160
    assert (await engine.resolve_stream_spec("alice", "1080p60"))["height"] == 1080
    assert await engine.get_preview_url("alice") == STANDARD
    metadata_calls = [call for call in calls if call.url.path.startswith("/json/")]
    assert len(metadata_calls) == 2
    assert "cookie" not in metadata_calls[0].headers
    assert "account-PRIVATE" in metadata_calls[1].headers["cookie"]
    assert len([call for call in calls if call.method == "POST"]) == 1


@pytest.mark.asyncio
async def test_preview_cache_invalidation_rechecks_uhd_permissions(api):
    calls, state = api
    engine = cime.CimeLiveEngine()
    assert (await engine.resolve_stream_spec("alice", "best"))["height"] == 2160
    state["allowed"] = False
    engine._metadata_cache.pop("alice", None)
    with pytest.raises(PlatformAuthenticationError, match="시청 권한"):
        await engine.resolve_stream_spec("alice", "2160p60")
    assert len([call for call in calls if call.method == "POST"]) == 1


@pytest.mark.asyncio
async def test_missing_cookie_keeps_standard_but_rejects_explicit_uhd(api, monkeypatch):
    calls, _ = api
    monkeypatch.setattr(get_settings(), "cime_cookie_file", None)
    engine = cime.CimeLiveEngine()
    assert (await engine.get_qualities("alice"))[0]["height"] == 1080
    assert (await engine.resolve_stream_spec("alice", "best"))["height"] == 1080
    with pytest.raises(PlatformAuthenticationError, match="로그인"):
        await engine.resolve_stream_spec("alice", "2160p60")
    assert not any(call.method == "POST" or call.url.host == "view.ci.me" for call in calls)


@pytest.mark.asyncio
async def test_denied_account_never_requests_a_uhd_grant(api):
    calls, state = api
    state["allowed"] = False
    with pytest.raises(PlatformAuthenticationError, match="시청 권한"):
        await cime.CimeLiveEngine().resolve_stream_spec("alice", "2160p60")
    assert not any(call.method == "POST" or call.url.host == "view.ci.me" for call in calls)


@pytest.mark.asyncio
async def test_denied_uhd_grant_is_not_retried_or_downgraded(api):
    calls, state = api
    state["grant_status"] = 403
    with pytest.raises(PlatformAuthenticationError) as caught:
        await cime.CimeLiveEngine().resolve_stream_spec("alice", "2160p60")
    assert "PRIVATE" not in str(caught.value)
    assert len([call for call in calls if call.method == "POST"]) == 1
    assert not any(call.url.host == "view.ci.me" for call in calls)


@pytest.mark.asyncio
async def test_compressed_initialization_is_decoded_once(api):
    _, state = api
    state["init"] = gzip.compress(initialization())
    state["init_headers"] = {"content-encoding": "gzip"}
    spec = await cime.CimeLiveEngine().resolve_stream_spec("alice", "2160p60")
    assert (spec["width"], spec["height"]) == (3840, 2160)


@pytest.mark.asyncio
@pytest.mark.parametrize("contents", [b"not-an-mp4", initialization()[:-1], b"x" * (1024 * 1024 + 1)],
                         ids=["invalid", "truncated", "oversized"])
async def test_invalid_initialization_does_not_invent_a_4k_quality(api, contents):
    _, state = api
    state["init"] = contents
    with pytest.raises(ValueError):
        await cime.CimeLiveEngine().resolve_stream_spec("alice", "2160p60")


@pytest.mark.asyncio
async def test_signed_cookies_never_follow_an_init_uri_to_another_host(api):
    calls, state = api
    state["media"] = MEDIA.replace("init.mp4", "https://evil.example/init.mp4")
    with pytest.raises(ValueError, match="범위"):
        await cime.CimeLiveEngine().resolve_stream_spec("alice", "2160p60")
    assert not any(call.url.host == "evil.example" for call in calls)


@pytest.mark.parametrize("version", [0, 1])
def test_init_dimensions_are_measured_not_assumed(version):
    assert cime.cime_init_dimensions(initialization(2560, 1440, version=version)) == (2560, 1440)
    with pytest.raises(ValueError):
        cime.cime_init_dimensions(initialization(handler=b"soun"))


@pytest.mark.parametrize("url", [
    "http://view.ci.me/uhd/1067321/init.mp4",
    "https://view.ci.me.evil/uhd/1067321/init.mp4",
    "https://user@view.ci.me/uhd/1067321/init.mp4",
    "https://view.ci.me:8443/uhd/1067321/init.mp4",
    "https://view.ci.me/uhd/other/init.mp4",
    "https://view.ci.me\\@evil.example/uhd/1067321/init.mp4",
])
def test_uhd_auth_rejects_non_media_origins(url):
    assert cime.CimeUhdAuth.for_url(url, PAGE) is None


def test_parallel_media_requests_refresh_once_before_grant_expiry(api, monkeypatch):
    calls, _ = api
    clock = [1000.0]
    monkeypatch.setattr(cime.time, "monotonic", lambda: clock[0])
    auth = cime.CimeUhdAuth.for_url(UHD, PAGE)

    def prepare(_):
        return requests.Request("GET", UHD, auth=auth).prepare().headers["Cookie"]

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert all("signature-PRIVATE" in header for header in pool.map(prepare, range(8)))
        assert len([call for call in calls if call.method == "POST"]) == 1
        clock[0] += 541
        list(pool.map(prepare, range(8)))
    assert len([call for call in calls if call.method == "POST"]) == 2
    for url in ("https://evil.example/segment.m4s", UHD.replace("/1067321/", "/999/")):
        prepared = requests.Request("GET", url, auth=auth).prepare()
        assert "Cookie" not in prepared.headers
    assert len([call for call in calls if call.method == "POST"]) == 2


def test_streamlink_uses_renewable_scoped_uhd_auth(api, monkeypatch):
    from app.engine.pipeline import YtdlpLivePipeline
    import streamlink
    calls, state = api
    state["media"] = MEDIA + "#EXT-X-ENDLIST\n"
    original = streamlink.Streamlink

    def session(*args, **kwargs):
        instance = original(*args, **kwargs)
        def get(url, **options):
            prepared = requests.Request("GET", url, auth=instance.http.auth).prepare()
            assert "account-PRIVATE" not in prepared.headers.get("Cookie", "")
            assert "signature-PRIVATE" in prepared.headers["Cookie"]
            response = requests.Response()
            response.status_code = 200
            response.url = url
            response._content = MEDIA.encode()
            return response
        monkeypatch.setattr(instance.http, "get", get)
        return instance

    monkeypatch.setattr(streamlink, "Streamlink", session)
    instance, stream = YtdlpLivePipeline._create_streamlink_stream(
        UHD, {}, "CloudFront-Policy=stale-PRIVATE; session-id=account-PRIVATE", 0, False, "2160p60", PAGE)
    try:
        assert isinstance(instance.http.auth, cime.CimeUhdAuth)
        assert stream.to_url() == UHD
        assert len([call for call in calls if call.method == "POST"]) == 1
        for url in (UHD.replace("https://", "http://"), UHD.replace("/1067321/", "/999/")):
            prepared = instance.http.prepare_request(requests.Request("GET", url))
            assert "Cookie" not in prepared.headers
    finally:
        instance.http.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("output_format", ["mkv", "mp4"])
async def test_real_single_fmp4_4k_capture_and_finalization(local_hls, monkeypatch, output_format):
    from app.engine.media_inspection import probe_media
    from app.engine.pipeline import YtdlpLivePipeline
    from app.engine.recording_finalizer import RecordingFinalizer
    from tests.test_recording_finalization import channel, terminal

    base, directory = local_hls
    folder = directory / "uhd"
    folder.mkdir()
    subprocess.run([shutil.which("ffmpeg"), "-y", "-v", "error", "-f", "lavfi", "-i",
                    "color=c=blue:size=3840x2160:rate=5", "-f", "lavfi", "-i",
                    "sine=frequency=1000:sample_rate=48000", "-t", "3", "-c:v", "libx264",
                    "-preset", "ultrafast", "-c:a", "aac", "-g", "5", "-f", "hls",
                    "-hls_time", "1", "-hls_list_size", "0", "-hls_segment_type", "fmp4",
                    str(folder / "playlist.m3u8")], check=True, cwd=folder)
    monkeypatch.setattr(get_settings(), "cime_cookie_file", None)
    engine = cime.CimeLiveEngine()
    original_request = engine._request
    media_url = base + "/uhd/playlist.m3u8"

    async def request(url, **kwargs):
        if url.startswith(cime.CIME_ORIGIN + "/json/"):
            return httpx.Response(200, json={"bodyData": {"live": {
                "state": "ACTIVE", "playback": {"url": media_url, "uhdFps": 5}
            }}}, request=httpx.Request("GET", url)), {}
        response, cookies = await original_request(url, **kwargs)
        if url == media_url:
            # The adapter sees an active live; the native receiver gets a finite
            # three-second fixture so the real capture can finish deterministically.
            response = httpx.Response(200, text=response.text.replace("#EXT-X-ENDLIST", ""),
                                      request=httpx.Request("GET", url))
        return response, cookies

    monkeypatch.setattr(engine, "_request", request)
    qualities = await engine.get_qualities("fixture")
    assert [(item["width"], item["height"], item["fps"]) for item in qualities] == [(3840, 2160, 5)]
    pipeline = YtdlpLivePipeline("fixture")
    manager = RecordingFinalizer()
    try:
        await pipeline.start_recording(stream_obj="https://ci.me/@fixture/live", quality="2160p5",
                                       output_dir=str(directory / "capture"),
                                       source_resolver=lambda quality: pipeline._resolve_stream_spec(engine, "fixture", quality))
        await asyncio.wait_for(asyncio.shield(pipeline._feeder_task), 30)
        await pipeline.stop_recording()
        assert pipeline.state.value == "completed" and pipeline.capture_format == "fmp4"
        assert pipeline.get_status()["recording_resolution"] == {"width": 3840, "height": 2160, "fps": 5}
        captured = probe_media(pipeline.output_path)
        assert captured["streams"] == {"video", "audio"}
        assert next(track for track in captured["tracks"] if track["codec_type"] == "video")["height"] == 2160
        original = Path(pipeline.output_path).read_bytes()
        job_id = manager.register_capture("cime:fixture", pipeline, channel("cime"),
                                          {"output_format": output_format, "keep_source_ts": True})
        await manager.capture_finished(job_id, pipeline)
        job = await terminal(manager, job_id)
        assert job["state"] == "completed", job
        output = probe_media(job["output_path"])
        assert output["streams"] == {"video", "audio"}
        assert next(track for track in output["tracks"] if track["codec_type"] == "video")["width"] == 3840
        assert Path(job["output_path"]).suffix == "." + output_format
        assert Path(pipeline.output_path).read_bytes() == original
        assert not list(Path(pipeline.output_path).parent.glob("*.ts"))
    finally:
        await pipeline.stop_recording()
        await manager.close()
