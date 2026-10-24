import pytest
from unittest.mock import Mock
from app.engine.episode_sites import EpisodeSiteError
from app.core.episode_domains import numbered_site_for_host
from app.engine.episode_sites import parse_episode_url, site_for_url
from app.engine.zzapflix import (
    parse_zzapflix_url,
    load_zzapflix_catalog,
    extract_zzapflix_episode,
    CATEGORY_NAMES,
)


def test_zzapflix_domain_and_site_recognition():
    assert numbered_site_for_host("zzap208.com") == "zzapflix"
    assert numbered_site_for_host("zzap999.com") == "zzapflix"
    assert site_for_url("https://zzap208.com/vodview.php?id=123692") == "zzapflix"


def test_zzapflix_url_parsing():
    # 1. Detail view URL
    route_view = parse_episode_url("https://zzap208.com/vodview.php?id=123692")
    assert route_view["site"] == "zzapflix"
    assert route_view["work"] == "123692"
    assert route_view["collection"] is True

    # 2. Episode view URL
    route_ep = parse_episode_url("https://zzap208.com/vodview.php?id=123692&idd=2")
    assert route_ep["site"] == "zzapflix"
    assert route_ep["work"] == "123692"
    assert route_ep["episode"] == "2"
    assert route_ep["collection"] is False

    # 3. Category URL (Type 1 Movie, Type 2 Drama, Type 39 Short, Type 3 Variety, Type 4 Anime)
    for type_id, name in CATEGORY_NAMES.items():
        route_cat = parse_episode_url(f"https://zzap208.com/vodlist.php?type_id_1={type_id}&order_type=")
        assert route_cat["site"] == "zzapflix"
        assert route_cat["category"] == str(type_id)
        assert route_cat["category_name"] == name


def test_zzapflix_catalog_and_stream_resolution():
    url = "https://zzap208.com/vodview.php?id=123692"
    episode_url = url + "&idd=1"
    client = Mock()
    client.request.return_value = (url, f'<title>Actual work</title><a href="{episode_url}">2화</a>')
    catalog = load_zzapflix_catalog(url, client)
    assert catalog["id"] == "123692"
    assert len(catalog["episodes"]) > 0

    route = parse_zzapflix_url("https://zzap208.com/vodview.php?id=123692&idd=1")
    client.request.return_value = (episode_url,
        '<iframe src="https://ckp2.wiselife.blog/player.php?id=123692&idd=1"></iframe>')
    stream = extract_zzapflix_episode(route, client)
    assert stream["site"] == "zzapflix"
    assert "wiselife.blog" in stream["stream_url"]
    assert stream["is_embed"] is True


def test_missing_page_never_produces_invented_episode_or_player():
    url = "https://zzap208.com/vodview.php?id=123692&idd=1"
    client = Mock()
    client.request.return_value = (url, "<title>Unavailable</title>")
    with pytest.raises(EpisodeSiteError):
        load_zzapflix_catalog(url, client)
    with pytest.raises(EpisodeSiteError):
        extract_zzapflix_episode(parse_zzapflix_url(url), client)
    client.request.side_effect = EpisodeSiteError("blocked", status=403)
    with pytest.raises(EpisodeSiteError):
        extract_zzapflix_episode(parse_zzapflix_url(url), client)
