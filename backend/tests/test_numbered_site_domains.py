"""Domain rotation through catalog, authentication and the existing VOD queue."""
import json
from urllib.parse import urlsplit

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.episode_domains import numbered_site_for_host
from app.core.logger import get_media_logger
from app.engine.episode_extractor import EpisodeSiteIE
from app.engine.episode_sites import (
    EpisodeSiteError, SITES, SiteClient, extract_episode, load_catalog, parse_episode_url,
)
from app.engine.platform_media import canonical_platform_video, media_platform
from app.engine.vod_preparation import canonical_prepared_url
from tests.test_animaru import fixture_client as animaru_fixture
from tests.test_episode_sites import FixtureClient
from tests.test_tvwiki import fixture_client as tvwiki_fixture


SOURCES = [
    ('animaru', 'animaru1.com', 'animaru2.com', '/content/42', '/content/42/1.5'),
    ('tvwiki', 'tvwiki54.net', 'tvwiki55.net', '/drama/42', '/drama/42/11'),
    ('anilife', 'anilife01.tv', 'anilife02.tv', '/content/1', '/content/1/one'),
]


@pytest.mark.parametrize('site,old,host,work,episode', SOURCES)
@pytest.mark.parametrize('number', ['0', '1', '02', '209', '123456'])
def test_new_numbers_preserve_host_in_routing_preparation_and_logging(site, old, host, work, episode, number):
    host = site + number + '.' + host.rsplit('.', 1)[1]
    for path, collection in ((work, True), (episode, False)):
        url = 'https://' + host + path
        route = parse_episode_url(url + '?ref=tracking#top')
        assert route['url'] == url and route['collection'] is collection
        assert route['site'] == media_platform(url) == numbered_site_for_host(host) == site
        assert get_media_logger(url).name == 'phrolova.' + site
        assert EpisodeSiteIE.suitable(url) is not collection
        if not collection:
            assert canonical_platform_video(url) == canonical_prepared_url(url, site) == url
    upper = 'https://' + host.upper() + ':443' + episode
    assert parse_episode_url(upper)['url'] == 'https://' + host + episode


@pytest.mark.parametrize('site,old,host,work,episode', SOURCES)
@pytest.mark.parametrize('authority', [
    '{host}.evil.example', 'evil.{host}', '{host}@evil.example', '{host}:444',
    'u:p@{host}', '@{host}', 'u@{host}', ':@{host}', '{host}.', '{host}%2eevil.example', '{site}.com',
])
def test_url_authority_boundaries(site, old, host, work, episode, authority):
    url = 'https://' + authority.format(host=host, site=site) + episode
    with pytest.raises(EpisodeSiteError):
        parse_episode_url(url)
    assert not EpisodeSiteIE.suitable(url)


@pytest.mark.parametrize('host', [
    'tvwiki55.com', 'tvchak209.net', 'animaru2.tv', 'anilife02.net',
    'tvwiki55.network', 'tvwiki５５.net', 'anilife٠٢.tv', 'tvwiki55.net\n',
    'tvwiki' + '1' * 58 + '.net',
])
def test_host_family_is_exact_and_ascii(host):
    assert numbered_site_for_host(host) is None
    assert media_platform('https://' + host.replace('\n', '%0a') + '/') == 'external'


def rotated_fixture(site, old, host):
    if site == 'animaru':
        client, _ = animaru_fixture()
    elif site == 'tvwiki':
        client = tvwiki_fixture()
    else:
        origin = 'https://' + old
        client = FixtureClient({
            origin + '/content/1': 'page', origin + '/content/1/one': 'page',
            origin + '/api/anime/1': json.dumps({'item': {'id': 1, 'title': 'Work', 'episodes': [
                {'key': 'one', 'title': 'One', 'number': 1, 'sourceType': 'anilife',
                 'playbackUrl': '/api/playback/1/one'}]}}),
            origin + '/api/playback/session': json.dumps({'token': 'guest-proof', 'expiresAt': 2000000000}),
            origin + '/api/playback/1/one': json.dumps({'videoUrl': 'https://aniplayer1.site/master.m3u8'}),
            'https://aniplayer1.site/master.m3u8': '#EXTM3U\n#EXTINF:3,\nseg.ts\n#EXT-X-ENDLIST',
        })
    client.routes = {url.replace(old, host): body.replace(old, host) if isinstance(body, str) else body
                     for url, body in client.routes.items()}
    return client


@pytest.mark.parametrize('site,old,host,work,episode', SOURCES)
def test_catalog_and_player_requests_use_the_supplied_domain(site, old, host, work, episode):
    client = rotated_fixture(site, old, host)
    origin = 'https://' + host
    catalog = load_catalog(origin + work, client)
    assert catalog['url'] == origin + work
    assert all(urlsplit(row['url']).hostname == host for row in catalog['episodes'])
    item = extract_episode(origin + episode, client)
    assert urlsplit(item['webpage_url']).hostname == host
    assert all(urlsplit(url).hostname != old for url, _ in client.calls)
    if site in ('animaru', 'tvwiki'):
        assert any(opts.get('headers', {}).get('Origin') == origin for _, opts in client.calls)
    if site == 'anilife':
        proof = next((url, opts) for url, opts in client.calls if url.endswith('/playback/1/one'))
        assert urlsplit(proof[0]).hostname == host
        assert proof[1]['headers']['X-Anilife-Playback'] == 'guest-proof'


@pytest.mark.parametrize('site,old,host,work,episode', SOURCES[1:])
def test_catalog_uses_final_host_after_website_rotation(site, old, host, work, episode):
    client = rotated_fixture(site, old, host)
    origin = 'https://' + host
    client.routes['https://' + old + work] = (origin + work, client.routes[origin + work])
    catalog = load_catalog('https://' + old + work, client)
    assert catalog['url'] == origin + work
    assert all(urlsplit(row['url']).hostname == host for row in catalog['episodes'])


@pytest.mark.parametrize('site,old,host,work,episode', SOURCES)
@pytest.mark.parametrize('destination', ['same_family', 'lookalike', 'credentials', 'http', 'other_family'])
def test_each_website_redirect_is_checked_before_sending(site, old, host, work, episode, destination, monkeypatch):
    target = {
        'same_family': 'https://' + host + work,
        'lookalike': 'https://' + host + '.evil.example' + work,
        'credentials': 'https://u:p@' + host + work,
        'http': 'http://' + host + work,
        'other_family': 'https://' + ('tvwiki99.net' if site != 'tvwiki' else 'anilife99.tv') + work,
    }[destination]
    calls = []
    def handle(request):
        calls.append(request)
        return (httpx.Response(302, headers={'Location': target}) if request.url.host == old else
                httpx.Response(200, text='page'))
    client = SiteClient()
    client.http.close()
    client.http = httpx.Client(transport=httpx.MockTransport(handle))
    try:
        if destination == 'same_family':
            assert client.request('https://' + old + work, SITES[site]['hosts'],
                headers={'Origin': 'https://' + old, 'X-Playback-Proof': 'issuer-only'})[0] == target
            assert [r.url.host for r in calls] == [old, host]
            assert calls[0].headers['X-Playback-Proof'] == 'issuer-only'
            assert 'X-Playback-Proof' not in calls[1].headers and 'Origin' not in calls[1].headers
        else:
            with pytest.raises(EpisodeSiteError):
                client.request('https://' + old + work, SITES[site]['hosts'])
            assert len(calls) == 1
    finally:
        client.close()


@pytest.mark.parametrize('site,old,host,work,episode', SOURCES[1:])
def test_session_api_does_not_forward_proofs_or_body_to_another_number(site, old, host, work, episode):
    fixture = rotated_fixture(site, old, host)
    protected = '/api/create_session.php' if site == 'tvwiki' else '/api/playback/1/one'
    calls = []
    def handle(request):
        calls.append(request)
        if request.url.path == protected:
            return httpx.Response(307, headers={'Location': 'https://' + old + protected})
        return httpx.Response(200, text=fixture.routes[str(request.url)])
    client = SiteClient()
    client.http.close()
    client.http = httpx.Client(transport=httpx.MockTransport(handle))
    try:
        with pytest.raises(EpisodeSiteError):
            extract_episode('https://' + host + episode, client)
        assert all(request.url.host != old for request in calls)
        assert any(request.url.path == protected for request in calls)
    finally:
        client.close()


def test_removed_platform_is_not_supported_and_cookie_file_is_preserved(tmp_path):
    from app.api import platforms
    path = tmp_path / 'cookies.txt'
    path.write_text('existing user file', encoding='utf-8')
    app = FastAPI()
    app.include_router(platforms.router)
    url = 'https://tvchak209.com/index.php/vod/play/id/123703/sid/1/nid/1.html'
    assert numbered_site_for_host('tvchak209.com') is None
    assert media_platform(url) == 'external'
    assert not EpisodeSiteIE.suitable(url)
    with pytest.raises(EpisodeSiteError):
        parse_episode_url(url)
    with TestClient(app) as api:
        assert api.get('/api/platforms/tvchak/cookie').status_code == 400
        assert api.delete('/api/platforms/tvchak/cookie').status_code == 400
    assert path.read_text(encoding='utf-8') == 'existing user file'
