"""TVChak work/episode pages and their normal MacCMS player data."""
from __future__ import annotations

import base64
import re
from urllib.parse import unquote, urlencode, urljoin, urlsplit

from app.core.http import USER_AGENT
from app.engine.episode_sites import (
    Document, EpisodeSiteError, SITES, _assigned, _rows, checked_url, validate_hls,
)

PATH = re.compile(r'/index\.php/vod/(?:detail/id/([1-9]\d*)|play/id/([1-9]\d*)/sid/([1-9]\d*)/nid/([1-9]\d*))\.html')


def parse_tvchak_url(value):
    value = checked_url(value, SITES['tvchak']['hosts'])
    parts = urlsplit(value)
    match = PATH.fullmatch(parts.path)
    if not match:
        raise EpisodeSiteError('티비착 작품 또는 회차 주소를 입력하세요.')
    work, playing, source, number = match.groups()
    work = work or playing
    path = (f'play/id/{work}/sid/{source}/nid/{number}' if playing else f'detail/id/{work}')
    return dict(site='tvchak', work=work, source=source, number=number,
                episode=f's{source}-n{number}' if playing else None,
                url=f'https://{parts.hostname}/index.php/vod/'+path+'.html', collection=not playing)


def _page(route, client):
    final, body = client.request(route['url'], SITES['tvchak']['hosts'])
    target = parse_tvchak_url(final)
    if any(target[key] != route[key] for key in ('work', 'source', 'number')):
        raise EpisodeSiteError('이동된 티비착 작품·회차 ID가 다릅니다.')
    return final, Document(body).root


def _catalog(route, final, doc):
    headings = doc.find('h1')
    title = headings[0].text.strip() if len(headings) == 1 else ''
    if not title:
        raise EpisodeSiteError('티비착 작품 제목을 확인할 수 없습니다.')
    episodes = {}
    playlists = [playlist for container in doc.find(id='playsx')
                 for playlist in container.find('ul', cls='content_playlist')]
    for playlist in playlists:
        for link in playlist.find('a', href=None):
            label = link.text.strip()
            if not label:
                continue
            episode = parse_tvchak_url(urljoin(final, link.attrs['href']))
            if episode['work'] != route['work']:
                raise EpisodeSiteError('티비착 회차 목록에 다른 작품이 포함되어 있습니다.')
            if episode['collection']:
                continue
            # Keep distinct source IDs; never invent unlisted episode numbers.
            number = re.search(r'(\d+(?:\.\d+)?)\s*(?:화|회)(?:\s|$)', label)
            row = dict(id=episode['episode'], title=label, url=episode['url'],
                       number=float(number[1]) if number else float(episode['number']), available=True)
            previous = episodes.get(row['id'])
            if previous and previous != row:
                raise EpisodeSiteError('티비착 회차 목록의 식별 정보가 중복되었습니다.')
            episodes[row['id']] = row
    if route['episode']:
        episodes = {key: row for key, row in episodes.items() if key == route['episode']}
        if not episodes:
            raise EpisodeSiteError('티비착 목록에서 요청한 회차를 찾지 못했습니다.')
    return dict(source='tvchak', id=route['work'], title=title, url=parse_tvchak_url(final)['url'],
                episodes=_rows(list(episodes.values())), incomplete=False)


def load_tvchak_catalog(route, client):
    return _catalog(route, *_page(route, client))


def _media_url(player):
    value, encoding = player.get('url'), player.get('encrypt')
    if not isinstance(value, str) or not value or len(value) > 16384 or type(encoding) is not int:
        raise EpisodeSiteError('티비착 본편 재생 주소 형식이 변경되었습니다.')
    try:
        if encoding == 2:
            value = base64.b64decode(value, validate=True).decode('utf-8')
        elif encoding not in (0, 1):
            raise ValueError
        if encoding in (1, 2):
            value = unquote(value, errors='strict')
    except (ValueError, UnicodeError):
        raise EpisodeSiteError('티비착 본편 재생 주소를 읽지 못했습니다.') from None
    return checked_url(value, SITES['tvchak']['media'], subdomains=True)


def extract_tvchak_episode(route, client):
    if route['collection']:
        raise EpisodeSiteError('작품의 회차 목록에서 내려받을 회차를 선택하세요.')
    final, doc = _page(route, client)
    catalog = _catalog(route, final, doc)
    player = _assigned(doc, 'player_aaaa')
    if (player.get('flag') != 'play' or str(player.get('id')) != route['work']
            or str(player.get('sid')) != route['source'] or str(player.get('nid')) != route['number']):
        raise EpisodeSiteError('티비착 플레이어의 작품·회차 ID가 다릅니다.')
    if (type(player.get('trysee')) is not int or player['trysee'] != 0
            or type(player.get('points')) is not int or player['points'] != 0):
        raise EpisodeSiteError('티비착 미리보기 또는 시청 권한이 필요한 회차는 지원하지 않습니다.')
    if player.get('is_ad') or player.get('advertisement') or player.get('from') not in ('mp4', 'MP4', 'ikm3u8', 'sdm3u8', 'sdyun'):
        raise EpisodeSiteError('티비착 본편 플레이어를 확인할 수 없습니다.')
    media = _media_url(player)
    path = urlsplit(media).path.lower()
    if path.endswith('.mp4'):
        # This is the wrapper used by the site's own mp4 player. Do not load ads
        # or execute the wrapper's scripts to discover the already declared URL.
        referer = 'https://ckp2.wiselife.blog/chak/chaktt.php?' + urlencode({'url': media})
        actual, prefix = client.request(media, SITES['tvchak']['media'], referer=referer,
            subdomains=True, binary=True, prefix_bytes=4096, headers={'Range': 'bytes=0-4095'})
        if len(prefix) < 16 or prefix[4:8] != b'ftyp':
            raise EpisodeSiteError('티비착 서버에서 정상 MP4 영상을 받지 못했습니다.')
        result = dict(url=actual, ext='mp4', format_id='original')
    elif path.endswith('.m3u8'):
        referer = final
        actual, manifest = validate_hls(client, media, referer, SITES['tvchak']['media'])
        result = dict(url=actual, manifest=manifest)
    else:
        raise EpisodeSiteError('티비착의 이 재생 형식은 지원하지 않습니다.')
    episode = catalog['episodes'][0]
    title = episode['title'] if episode['title'].startswith(catalog['title']) else f'{catalog["title"]} · {episode["title"]}'
    return dict(id=catalog['id']+'-'+episode['id'], title=title, series=catalog['title'],
                episode=episode['title'], episode_number=episode['number'], webpage_url=final,
                uploader='티비착', subtitles={}, is_live=False,
                http_headers={'User-Agent': USER_AGENT, 'Referer': referer}, **result)
