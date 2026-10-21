from unittest.mock import Mock
import base64
import json

import pytest

from app.engine.episode_sites import EpisodeSiteError, parse_episode_url, load_catalog, extract_episode
from app.engine.platform_media import media_platform, canonical_platform_video

WORK = "https://tvroom42.org/video/work-2026"
EP = WORK + "/episode-1"
PLAYER = "https://player-v2.pongping.top/player/v3/test"
MEDIA = "https://player.pongping.top/stream/m3u8/test"


def key_envelope():
    return base64.b64encode(json.dumps({
        "encrypted_key": base64.b64encode(b"AAAAxxDDDDxxBBBBxxCCCCxx").decode(),
        "rule": {"segments_count": 4, "segment_sizes": [4, 4, 4, 4], "noise_length": 2,
                 "permutation": [0, 3, 1, 2], "key_length": 16}
    }).encode())


def test_public_player_key_envelope():
    from app.engine.tvroom import decode_player_key
    assert decode_player_key(key_envelope()) == b"AAAABBBBCCCCDDDD"
    for malformed in (b"not base64", b"e30=", b"x" * 5000):
        with pytest.raises(EpisodeSiteError):
            decode_player_key(malformed)


def test_routing_and_collection_require_selection():
    assert media_platform(EP) == "tvroom"
    assert parse_episode_url(WORK)["collection"]
    assert canonical_platform_video(EP) == EP
    with pytest.raises(ValueError):
        canonical_platform_video(WORK)


@pytest.mark.parametrize("url", ["https://tvroom42.org.evil/video/a/b",
    "https://tvroom42.org/video/%2Fbad/e", "https://tvroom42.org/video/a/%5Cbad",
    "https://tvroom42.org/video/a/b/c", "https://tvroom42.org/video/영화"])
def test_invalid_urls_are_rejected(url):
    with pytest.raises(EpisodeSiteError):
        parse_episode_url(url)


def test_collection_redirect_is_preserved_and_player_is_parsed_without_js():
    client = Mock()
    page = (f"<title>작품 - 티비룸</title><a class='episode-item' href='{EP}'>제01회</a>"
            f"<iframe id='view_iframe' src='{PLAYER}'></iframe>")
    manifest = ('#EXTM3U\n#EXT-X-TARGETDURATION:8\n#EXT-X-KEY:METHOD=AES-128,'
                'URI="https://player.pongping.top/stream/key/test"\n'
                '#EXTINF:8,\nhttps://cdn-bm.pongping.top/videos/segment.png\n#EXT-X-ENDLIST\n')
    client.request.side_effect = [(EP, page), (EP, page),
        (PLAYER, f"<div id='player' data-m3u8='{MEDIA}'></div>"), (MEDIA, manifest),
        ("https://player.pongping.top/stream/key/test", key_envelope())]
    catalog = load_catalog(WORK, client)
    assert catalog["episodes"][0]["url"] == EP
    result = extract_episode(EP, client)
    assert result["manifest"] == manifest and result["url"] == MEDIA
    assert result["http_headers"]["Referer"] == PLAYER
    assert bytes.fromhex(result["hls_aes"]["key"]) == b"AAAABBBBCCCCDDDD"


def test_redirect_cannot_replace_requested_work():
    client = Mock()
    client.request.return_value = ("https://tvroom42.org/video/other/e", "<title>Other</title>")
    with pytest.raises(EpisodeSiteError, match="다릅니다"):
        load_catalog(WORK, client)
