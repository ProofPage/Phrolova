"""Toonday movie pages and their advertised standard HLS rendition."""
import re
from urllib.parse import parse_qs, urljoin, urlsplit

from app.core.http import USER_AGENT
from app.engine.episode_sites import Document, EpisodeSiteError, SITES, checked_url, validate_hls, _rows


def parse_toonday_url(value):
    value = checked_url(value, SITES['toonday']['hosts'])
    parts = urlsplit(value)
    match = re.fullmatch(r'/movie/([1-9]\d*)(?:/([1-9]\d*))?/?', parts.path)
    if not match:
        raise EpisodeSiteError('툰데이 영화 작품 또는 본편 주소를 입력하세요.')
    work, episode = match.groups()
    return dict(site='toonday', work=work, episode=episode, collection=episode is None,
                url=f'https://{parts.hostname}/movie/{work}' + (f'/{episode}' if episode else ''))


def _page(route, client):
    final, body = client.request(route['url'], SITES['toonday']['hosts'])
    target = parse_toonday_url(final)
    if target['work'] != route['work'] or route['episode'] and target['episode'] != route['episode']:
        raise EpisodeSiteError('이동된 툰데이 작품·회차가 다릅니다.')
    return final, Document(body).root


def _catalog(route, final, doc):
    cards = doc.find(cls='movie-info-copy')
    titles = cards[0].find('h5') if len(cards) == 1 else []
    if len(titles) != 1 or not titles[0].text.strip():
        raise EpisodeSiteError('툰데이 작품 제목을 확인할 수 없습니다.')
    episodes = {}
    lists = doc.find(id='chapter_list')
    if len(lists) != 1:
        raise EpisodeSiteError('툰데이 본편 목록을 확인할 수 없습니다.')
    for link in lists[0].find('a', href=None):
        ep = parse_toonday_url(urljoin(final, link.attrs['href']))
        labels = link.find('strong')
        if ep['work'] != route['work'] or not ep['episode'] or not labels:
            continue
        if route['episode'] and route['episode'] != ep['episode']:
            continue
        episodes[ep['episode']] = dict(id=ep['episode'], title=labels[0].text.strip(),
            url=ep['url'], number=None, available=True)
    if not episodes:
        raise EpisodeSiteError('툰데이 목록에 요청한 본편이 없습니다.')
    return dict(source='toonday', id=route['work'], title=titles[0].text.strip(), url=route['url'],
                episodes=_rows(list(episodes.values())), incomplete=False)


def load_toonday_catalog(route, client):
    return _catalog(route, *_page(route, client))


def extract_toonday_episode(route, client):
    if route['collection']:
        raise EpisodeSiteError('작품 목록에서 내려받을 본편을 선택하세요.')
    final, doc = _page(route, client)
    catalog = _catalog(route, final, doc)
    sections = doc.find(cls='movie-player')
    frames = sections[0].find('iframe', src=None) if len(sections) == 1 else []
    if len(frames) != 1:
        raise EpisodeSiteError('툰데이 본편 플레이어를 확인할 수 없습니다.')
    player = checked_url(urljoin(final, frames[0].attrs['src']), SITES['toonday']['players'])
    urls = parse_qs(urlsplit(player).query).get('m3u8', [])
    if len(urls) != 1:
        raise EpisodeSiteError('툰데이 재생목록 구성이 변경되었습니다.')
    media = checked_url(urls[0], ('cdn.datv.kr',))
    media, manifest = validate_hls(client, media, player, SITES['toonday']['media'])
    keys = set(re.findall(r'^#EXT-X-KEY:[^\r\n]*URI="([^"]+)"', manifest, re.M))
    for key in keys:
        key_url = checked_url(urljoin(media, key), SITES['toonday']['hosts'])
        if not re.fullmatch(r'/getkey/[a-f0-9]{32}', urlsplit(key_url).path):
            raise EpisodeSiteError('툰데이 영상 키 경로가 변경되었습니다.')
        _, data = client.request(key_url, SITES['toonday']['hosts'], referer=player, binary=True)
        if len(data) != 16:
            raise EpisodeSiteError('툰데이 서버가 표준 HLS 키를 제공하지 않습니다.')
    episode = catalog['episodes'][0]
    return dict(id=route['work']+'-'+episode['id'], title=catalog['title'], series=catalog['title'],
        episode=episode['title'], episode_number=None, webpage_url=final, uploader='툰데이',
        url=media, manifest=manifest, subtitles={}, is_live=False,
        http_headers={'User-Agent': USER_AGENT, 'Referer': player,
                      'Origin': 'https://'+urlsplit(player).hostname})
