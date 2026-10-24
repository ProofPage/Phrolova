"""The observed CHZZK SEA playback -> advertised AES HLS -> cookie-key flow."""

import io
import json
import subprocess
from http.cookiejar import Cookie
from urllib.parse import parse_qs, urlsplit

import pytest
import yt_dlp
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from yt_dlp.networking import Request, Response
from yt_dlp.networking.exceptions import HTTPError
from yt_dlp.utils import DownloadError

from app.engine.chzzk_cdn import ChzzkCdnYoutubeDL
from app.engine.platform_media import platform_ydl


PAGE = "https://chzzk.naver.com/video/123"
PLAYBACK = "https://play.vod.naver.com/v3/playback/fixture-video"
MASTER = "https://resources-rmcnmv.akamaized.net/fixture/master.m3u8"
KEY_URL = "https://api.chzzk.naver.com/service/v1/encryption/videos/fixture-video/aes_key"
KEY = b"fixture-key-1234"
MPD = f"""<MPD xmlns="urn:mpeg:dash:schema:mpd:2011"
 xmlns:naver="urn:naver:vod:2020" xmlns:sea="urn:mpeg:dash:schema:sea:2012">
 <Period><AdaptationSet naver:m3u="{MASTER}">
 <Representation id="test"><ContentProtection schemeIdUri="urn:mpeg:dash:sea:2012">
 <sea:SegmentEncryption encryptionSystemUrn="urn:mpeg:dash:sea:aes128-cbc:2013"/>
 <sea:CryptoPeriod keyUriTemplate="{KEY_URL}"/>
 </ContentProtection></Representation></AdaptationSet></Period></MPD>"""
METADATA = {"content": {
    "encryptionType": "AES", "vodStatus": "ABR_HLS",
    "videoId": "fixture-video", "inKey": "fixture-playback-key",
    "videoTitle": "authorized AES recording", "duration": 1,
    "membershipBenefitType": "NONE",
    "channel": {"channelName": "fixture", "channelId": "fixture-channel"},
}}


@pytest.fixture
def playback(monkeypatch):
    requests = []
    assets = {
        "https://api.chzzk.naver.com/service/v3/videos/123": json.dumps(METADATA).encode(),
        PLAYBACK: MPD.encode(),
        MASTER: (
            '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=128000,RESOLUTION=160x90,'
            'FRAME-RATE=10,CODECS="avc1.4d400c,mp4a.40.2"\nmedia.m3u8\n'
        ).encode(),
        MASTER.replace("master", "media"): (
            '#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXT-X-MEDIA-SEQUENCE:0\n'
            f'#EXT-X-KEY:METHOD=AES-128,URI="{KEY_URL}"\n'
            '#EXTINF:1,\nsegment.ts\n#EXT-X-ENDLIST\n'
        ).encode(),
        KEY_URL: KEY,
    }

    def send(self, request):
        request = Request(request) if isinstance(request, str) else request
        parts = urlsplit(request.url)
        address = f"{parts.scheme}://{parts.netloc}{parts.path}"
        cookie = self.cookiejar.get_cookie_header(request.url)
        requests.append((address, cookie, parse_qs(parts.query)))
        if address == KEY_URL and not cookie:
            raise HTTPError(Response(io.BytesIO(b""), request.url, {}, status=403))
        assert address in assets, address
        return Response(io.BytesIO(assets[address]), request.url, {})

    monkeypatch.setattr(yt_dlp.YoutubeDL, "urlopen", send)
    return assets, requests


def authorize(ydl):
    ydl.cookiejar.set_cookie(Cookie(
        version=0, name="NID_AUT", value="fixture-account", port=None,
        port_specified=False, domain=".naver.com", domain_specified=True,
        domain_initial_dot=True, path="/", path_specified=True, secure=True,
        expires=None, discard=True, comment=None, comment_url=None, rest={},
    ))


def test_metadata_and_selected_qualities_use_advertised_aes_hls(playback):
    _, requests = playback
    with platform_ydl(PAGE, {"quiet": True}) as ydl:
        info = ydl.extract_info(PAGE, download=False)
    assert info["title"] == METADATA["content"]["videoTitle"]
    assert info["height"] == 90
    assert all(item["protocol"] == "m3u8_native" for item in info["formats"])
    assert any(address == PLAYBACK and query["key"] == ["fixture-playback-key"]
               for address, _, query in requests)
    assert sum("/service/v3/videos/" in address for address, _, _ in requests) == 1
    assert not any("fixture-account" in str(item) for item in info["formats"])


@pytest.mark.parametrize("authorized", [False, True])
def test_native_aes_key_uses_scoped_account_cookie_and_preserves_media(
    playback, tmp_path, authorized,
):
    assets, requests = playback
    plain = tmp_path / "original.ts"
    subprocess.run([
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=10",
        "-f", "lavfi", "-i", "sine=frequency=440", "-t", "1",
        "-c:v", "libx264", "-threads", "1", "-c:a", "aac", "-f", "mpegts", str(plain),
    ], check=True, timeout=30)
    original = plain.read_bytes()
    assets[MASTER.replace("master.m3u8", "segment.ts")] = AES.new(
        KEY, AES.MODE_CBC, bytes(16),
    ).encrypt(pad(original, 16))
    output = tmp_path / "download.ts"
    with ChzzkCdnYoutubeDL({
        "quiet": True, "noprogress": True, "fixup": "never",
        "hls_prefer_native": True, "outtmpl": str(output), "format": "best",
        "skip_unavailable_fragments": False, "retries": 0, "fragment_retries": 0,
    }) as ydl:
        if authorized:
            authorize(ydl)
            ydl.extract_info(PAGE, download=True)
        else:
            with pytest.raises(DownloadError):
                ydl.extract_info(PAGE, download=True)
    if authorized:
        assert output.read_bytes() == original
    assert any(address == KEY_URL for address, _, _ in requests)
    assert all(not cookie for address, cookie, _ in requests if "akamaized.net" in address)


@pytest.mark.parametrize("replacement", [
    "urn:mpeg:dash:sea:unsupported:2026",
    "urn:mpeg:dash:mp4protection:2011",
])
def test_other_protection_is_not_treated_as_supported_aes(playback, replacement):
    assets, _ = playback
    assets[PLAYBACK] = MPD.replace("urn:mpeg:dash:sea:aes128-cbc:2013", replacement).encode()
    with ChzzkCdnYoutubeDL({"quiet": True}) as ydl, pytest.raises(DownloadError):
        ydl.extract_info(PAGE, download=False)
