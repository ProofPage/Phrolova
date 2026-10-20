import pytest
from app.engine.episode_sites import parse_episode_url, site_for_url
from app.engine.aniwolf import parse_aniwolf_url, load_aniwolf_catalog, extract_aniwolf_episode
from app.engine.aniweek import parse_aniweek_url, load_aniweek_catalog, extract_aniweek_episode


def test_aniwolf_recognition_and_parsing():
    assert site_for_url("https://aniwolf.com/%EC%95%BC%EC%83%9D%EC%9D%98_%EB%9D%BC%EC%8A%A4%ED%8A%B8_%EB%B3%B4%EC%8A%A4%EA%B0%80_%EB%82%98%ED%83%80%EB%82%AC%EB%8B%A4!_2%EA%B8%B0") == "aniwolf"
    
    route_work = parse_episode_url("https://aniwolf.com/%EC%95%BC%EC%83%9D%EC%9D%98_%EB%9D%BC%EC%8A%A4%ED%8A%B8_%EB%B3%B4%EC%8A%A4%EA%B0%80_%EB%82%98%ED%83%80%EB%82%AC%EB%8B%A4!_2%EA%B8%B0")
    assert route_work["site"] == "aniwolf"
    assert route_work["collection"] is True

    route_ep = parse_episode_url("https://aniwolf.com/%EC%95%BC%EC%83%9D%EC%9D%98_%EB%9D%BC%EC%8A%A4%ED%8A%B8_%EB%B3%B4%EC%8A%A4%EA%B0%80_%EB%82%98%ED%83%80%EB%82%AC%EB%8B%A4!_2%EA%B8%B0/1%ED%99%94")
    assert route_ep["site"] == "aniwolf"
    assert route_ep["collection"] is False
    assert route_ep["episode"] == "1화"


def test_aniweek_recognition_and_parsing():
    assert site_for_url("https://aniweek.com/c/%EB%A7%88%EB%B2%95%EC%86%8C%EB%85%80%20%EB%A6%AC%EB%A6%AC%EC%BB%AC%20%EB%82%98%EB%85%B8%ED%95%98") == "aniweek"

    route_c = parse_episode_url("https://aniweek.com/c/%EB%A7%88%EB%B2%95%EC%86%8C%EB%85%80%20%EB%A6%AC%EB%A6%AC%EC%BB%AC%20%EB%82%98%EB%85%B8%ED%95%98")
    assert route_c["site"] == "aniweek"
    assert route_c["collection"] is True

    route_e = parse_episode_url("https://aniweek.com/e/%EB%A7%88%EB%B2%95%EC%86%8C%EB%85%80%20%EB%A6%AC%EB%A6%AC%EC%BB%AC%20%EB%82%98%EB%85%B8%ED%95%98%201%ED%99%94")
    assert route_e["site"] == "aniweek"
    assert route_e["collection"] is False
