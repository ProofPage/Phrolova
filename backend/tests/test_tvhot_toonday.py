from unittest.mock import Mock
import pytest
from app.engine.episode_sites import parse_episode_url, load_catalog, extract_episode, EpisodeSiteError
from app.engine.platform_media import canonical_platform_video


@pytest.mark.parametrize("site,path", [
    ("tvhot2", "drama/12384/406786806"), ("toonday1", "movie/40452/340758")])
def test_routes(site, path):
    url = f"https://{site}.com/{path}"
    assert canonical_platform_video(url) == url
    assert not parse_episode_url(url)["collection"]
    with pytest.raises(EpisodeSiteError):
        parse_episode_url(url.replace(".com", ".com.evil"))


def test_toonday_real_page_shape_and_standard_key():
    url = "https://toonday1.com/movie/40452/340758"
    player = "https://player-v2.bcbc.red.datv.kr/?m3u8=https://cdn.datv.kr/m3u8/test.m3u8"
    page = (f'<section class="movie-player"><iframe src="{player}"></iframe></section>'
        '<div class="movie-info-copy"><h5>Movie</h5></div>'
        '<div id="chapter_list"><a href="/movie/40452/340758"><strong>본편</strong></a></div>')
    manifest = ('#EXTM3U\n#EXT-X-TARGETDURATION:6\n#EXT-X-KEY:METHOD=AES-128,'
        'URI="https://toonday1.com/getkey/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"\n'
        '#EXTINF:6,\nhttps://cdn-bm.pongping.top/videos/a.png\n#EXT-X-ENDLIST\n')
    client = Mock()
    client.request.side_effect = [(url, page), (url, page),
        ("https://cdn.datv.kr/m3u8/test.m3u8", manifest), ("key", b"0"*16)]
    assert load_catalog(url, client)["episodes"][0]["title"] == "본편"
    assert extract_episode(url, client)["manifest"] == manifest


def test_tvhot_catalog_filters_to_requested_episode():
    url = "https://tvhot2.com/drama/12384/406786806"
    client = Mock()
    client.request.return_value = (url, f'<title>작품 다시보기 - 티비핫</title>'
        f'<iframe id="view_iframe"></iframe><a class="title" href="{url}">6화</a>'
        '<a class="title" href="/drama/12384/406786648">5화</a>')
    catalog = load_catalog(url, client)
    assert catalog["source"] == "tvhot"
    assert len(catalog["episodes"]) == 1 and catalog["episodes"][0]["number"] == 6
