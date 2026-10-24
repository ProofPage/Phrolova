"""Authorized AES-128 HLS: initialization contexts and native capture bytes."""

import threading
from collections import OrderedDict
from datetime import timedelta
from types import SimpleNamespace

import pytest
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from streamlink import Streamlink
from streamlink.stream.hls.m3u8 import parse_m3u8

from app.engine.chzzk_continuity import ChzzkContinuityWriter, SourcePath
from app.engine.chzzk_stream import ChzzkHLSStream
from tests.test_chzzk_continuity import CDN, INITIALIZATION, MEDIA, START, box


KEYS = {
    "https://cdn.example/first.key": b"0123456789abcdef",
    "https://cdn.example/second.key": b"fedcba9876543210",
}


def encrypted(data, key, iv):
    return AES.new(key, AES.MODE_CBC, iv).encrypt(pad(data, 16))


def encrypt_playlist(path):
    """Encrypt the local TS fixture with rotating keys; return original bytes."""
    playlist = parse_m3u8(path.read_text())
    segments = iter(playlist.segments)
    original = bytearray()
    lines = []
    for line in path.read_text().splitlines():
        if line and not line.startswith("#"):
            segment = next(segments)
            media = path.parent / segment.uri
            data = media.read_bytes()
            original.extend(data)
            key = (segment.num + 1).to_bytes(16, "big")
            name = f"capture-{segment.num}.key"
            (path.parent / name).write_bytes(key)
            media.write_bytes(encrypted(data, key, segment.num.to_bytes(16, "big")))
            lines.append(f'#EXT-X-KEY:METHOD=AES-128,URI="{name}?token=key%2F{segment.num}"')
        lines.append(line)
    path.write_text("\n".join(lines) + "\n")
    return bytes(original)


@pytest.mark.parametrize(
    "change", ["key", "iv", "sequence_iv", "clear_to_encrypted", "encrypted_to_clear"]
)
def test_initialization_cache_uses_the_advertised_encryption_context(change):
    writer = object.__new__(ChzzkContinuityWriter)
    writer.cache_lock = threading.Lock()
    writer.keys = OrderedDict()
    writer.maps = OrderedDict()
    writer.passthrough_encrypted = False
    calls = []
    first, second = KEYS
    expected = [INITIALIZATION, INITIALIZATION + box(b"free", b"new context")]
    for index, initialization in enumerate(expected):
        key_uri = second if change == "key" and index else first
        iv = (index + 1 if change in ("iv", "sequence_iv") else 1).to_bytes(16, "big")
        clear = (
            change == "clear_to_encrypted" and index == 0
            or change == "encrypted_to_clear" and index == 1
        )
        tag = '#EXT-X-KEY:METHOD=NONE' if clear else (
            f'#EXT-X-KEY:METHOD=AES-128,URI="{key_uri}"'
            + ("" if change == "sequence_iv" else f",IV=0x{iv.hex()}")
        )
        playlist = parse_m3u8(
            "#EXTM3U\n#EXT-X-TARGETDURATION:4\n"
            f"#EXT-X-MEDIA-SEQUENCE:{index + 1}\n{tag}\n"
            '#EXT-X-MAP:URI="init.mp4"\n#EXTINF:4,\nsegment.m4v\n',
            base_uri="https://cdn.example/list.m3u8",
        )
        body = initialization if clear else encrypted(initialization, KEYS[key_uri], iv)

        def fetch(url, byterange=None):
            calls.append(url)
            return KEYS[url] if url in KEYS else body

        writer.http_bytes = fetch
        located = SimpleNamespace(map=playlist.segments[0].map, num=index + 1)
        assert writer.load_map(located) == initialization
        before = len(calls)
        assert writer.load_map(located) == initialization
        assert len(calls) == before
    assert calls.count("https://cdn.example/init.mp4") == 2


def test_equivalent_identity_key_formats_share_initialization_cache():
    writer = object.__new__(ChzzkContinuityWriter)
    writer.cache_lock = threading.Lock()
    writer.keys = OrderedDict()
    writer.maps = OrderedDict()
    writer.passthrough_encrypted = False
    iv = (1).to_bytes(16, "big")
    key_uri = next(iter(KEYS))
    calls = []

    def fetch(url, byterange=None):
        calls.append(url)
        return KEYS[url] if url in KEYS else encrypted(INITIALIZATION, KEYS[key_uri], iv)

    writer.http_bytes = fetch
    for attributes in ("", ',KEYFORMAT="identity",KEYFORMATVERSIONS="1"'):
        playlist = parse_m3u8(
            "#EXTM3U\n#EXT-X-TARGETDURATION:4\n"
            f'#EXT-X-KEY:METHOD=AES-128,URI="{key_uri}",IV=0x{iv.hex()}{attributes}\n'
            '#EXT-X-MAP:URI="init.mp4"\n#EXTINF:4,\nsegment.m4v\n',
            base_uri="https://cdn.example/list.m3u8",
        )
        assert writer.load_map(SimpleNamespace(map=playlist.segments[0].map, num=1)) == INITIALIZATION
    assert calls.count("https://cdn.example/init.mp4") == 1


@pytest.mark.parametrize("mode", ["hls", "llhls"])
@pytest.mark.parametrize("container", ["ts", "fmp4"])
@pytest.mark.parametrize("explicit_iv", [False, True])
def test_native_encrypted_capture_preserves_original_media(
    tmp_path, mode, container, explicit_iv
):
    with CDN() as cdn:
        directory = "/primary/1080p/"
        first_sequence = 101
        lines = [
            "#EXTM3U", "#EXT-X-VERSION:7", "#EXT-X-TARGETDURATION:4",
            f"#EXT-X-MEDIA-SEQUENCE:{first_sequence}",
        ]
        if mode == "llhls":
            lines.append("#EXT-X-PART-INF:PART-TARGET=1")
        if container == "fmp4":
            map_key = b"0123456789abcdef"
            map_iv = (17).to_bytes(16, "big")
            lines.extend([
                '#EXT-X-KEY:METHOD=AES-128,URI="init.key?token=map%2Ftoken",'
                f"IV=0x{map_iv.hex()}",
                '#EXT-X-MAP:URI="init.mp4"',
            ])
            cdn.assets[directory + "init.key"] = map_key
            cdn.assets[directory + "init.mp4"] = encrypted(INITIALIZATION, map_key, map_iv)
            media = MEDIA
        else:
            media = [b"\x47" + bytes([index]) * 187 for index in range(4)]
        for index, data in enumerate(media):
            key = bytes([index + 1]) * 16
            number = first_sequence + index
            iv = (7 if explicit_iv else number).to_bytes(16, "big")
            lines.append(
                f'#EXT-X-KEY:METHOD=AES-128,URI="{index}.key?token=key%2F{index}"'
                + (f",IV=0x{iv.hex()}" if explicit_iv else "")
            )
            lines.extend([
                "#EXT-X-PROGRAM-DATE-TIME:" + (START + timedelta(seconds=4 * index)).isoformat(),
                "#EXTINF:4,", f"{index}.m4v",
            ])
            cdn.assets[directory + f"{index}.key"] = key
            cdn.assets[directory + f"{index}.m4v"] = encrypted(data, key, iv)
        lines.append("#EXT-X-ENDLIST")
        cdn.assets[directory + "list.m3u8"] = "\n".join(lines).encode()
        url = cdn.url("primary")
        session = Streamlink(plugins_builtin=False)
        session.set_option("hls-live-edge", 1)
        session.set_option("stream-segment-threads", 2)
        try:
            paths = [SourcePath(url, mode=mode, cdn="korean")]
            stream = ChzzkHLSStream(
                session, url, "fixture", live_id=1, source_paths=paths,
                source_mode=mode, buffer_dir=str(tmp_path),
            )
            stream.continuity.provider = lambda: (1, paths, False)
            reader = stream.open()
            output = bytearray()
            try:
                while chunk := reader.read(65536):
                    output.extend(chunk)
            finally:
                reader.close()
        finally:
            session.http.close()
        expected = (INITIALIZATION if container == "fmp4" else b"") + b"".join(media)
        assert bytes(output) == expected
        for index in range(4):
            assert any(
                query == directory + f"{index}.key?token=key%2F{index}"
                for query in cdn.queries
            )
