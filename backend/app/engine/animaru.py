"""Animaru's public reader API and its ordinary HLS player."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import math
import re
from urllib.parse import urljoin, urlsplit

from app.core.http import USER_AGENT
from app.core.logger import get_platform_logger
from app.engine.episode_sites import Document, EpisodeSiteError, SITES, checked_url, _rows, validate_hls

API = 'https://api.storagewebtoon.store'
READER = API + '/api/v1/reader/v1/works/'
PLAYER_PATH = re.compile(r'/api/v1/v1/anime/player/([1-9]\d*)')
PATH = re.compile(r'/contents?/([1-9]\d*)(?:/((?:0|[1-9]\d*)(?:\.\d+)?))?/?')
logger = get_platform_logger('animaru', 'vod')


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise EpisodeSiteError('애니마루 회차 번호가 올바르지 않습니다.')
    text = str(value)
    if len(text) > 32 or not re.fullmatch(r'(?:0|[1-9]\d*)(?:\.\d+)?', text):
        raise EpisodeSiteError('애니마루 회차 번호가 올바르지 않습니다.')
    try:
        number = Decimal(text)
        if not number.is_finite() or not 0 <= number < 1000000:
            raise InvalidOperation
        canonical = format(number, 'f')
        return canonical.rstrip('0').rstrip('.') if '.' in canonical else canonical
    except InvalidOperation:
        raise EpisodeSiteError('애니마루 회차 번호가 올바르지 않습니다.') from None


def parse_animaru_url(value):
    value = checked_url(value, SITES['animaru']['hosts'])
    parts = urlsplit(value)
    match = PATH.fullmatch(parts.path)
    if not match:
        raise EpisodeSiteError('애니마루 작품 또는 회차 주소를 입력하세요.')
    work, episode = match.groups()
    episode = _number(episode) if episode is not None else None
    return dict(site='animaru', work=work, episode=episode, collection=episode is None,
                url=f'https://{parts.hostname}/content/{work}' + (f'/{episode}' if episode is not None else ''))


def _work(route, client):
    final, data = client.json(READER+route['work'], SITES['animaru']['api'],
                              referer=route['url'], headers={'Origin':'https://'+urlsplit(route['url']).hostname})
    if urlsplit(final).path != urlsplit(READER+route['work']).path:
        raise EpisodeSiteError('애니마루 작품 API 주소가 변경되었습니다.')
    if not isinstance(data, dict) or data.get('ok') is not True or not isinstance(data.get('item'), dict):
        raise EpisodeSiteError('애니마루 작품 정보를 확인할 수 없습니다.')
    item = data['item']
    if str(item.get('id')) != route['work'] or item.get('media_type') != 'ANIME':
        raise EpisodeSiteError('애니마루 작품 ID 또는 콘텐츠 종류가 다릅니다.')
    if item.get('adult') is True:
        raise EpisodeSiteError('시청 권한 확인이 필요한 애니마루 콘텐츠입니다.')
    title, episodes = item.get('title'), data.get('episodes')
    if not isinstance(title, str) or not title.strip() or not isinstance(episodes, list) or not 1 <= len(episodes) <= 10000:
        raise EpisodeSiteError('애니마루 작품 제목·회차 목록을 확인할 수 없습니다.')
    return item, episodes


def _catalog(route, item, episodes):
    rows, entries, identities = {}, {}, {}
    for episode in episodes:
        if not isinstance(episode, dict) or not re.fullmatch(r'[1-9]\d*', str(episode.get('id'))):
            raise EpisodeSiteError('애니마루 회차 ID가 올바르지 않습니다.')
        number = _number(episode.get('number'))
        identifier = str(episode['id'])
        if identifier in identities and identities[identifier] != number:
            raise EpisodeSiteError('애니마루 회차 ID가 중복되어 있습니다.')
        identities[identifier] = number
        label = episode.get('title')
        if label is None or label == '':
            label = number+'화'
        if not isinstance(label, str):
            raise EpisodeSiteError('애니마루 회차 제목이 올바르지 않습니다.')
        label = label.strip()
        if re.fullmatch(r'\d+(?:\.\d+)?', label):
            label += '화'
        if not label:
            label = number+'화'
        player = episode.get('embed_url')
        if player is not None and not isinstance(player, str):
            raise EpisodeSiteError('애니마루 회차 재생 주소가 올바르지 않습니다.')
        row = dict(id=number, title=label, number=float(number),
                   url=f'https://{urlsplit(route["url"]).hostname}/content/{route["work"]}/{number}',
                   available=bool(player) and episode.get('ready') is not False)
        if number in entries and entries[number] != episode:
            raise EpisodeSiteError('애니마루 회차 번호가 중복되어 있습니다.')
        rows[number], entries[number] = row, episode
    total = item.get('episode_count')
    incomplete = type(total) is int and total > len(rows)
    if route['episode'] is not None:
        rows = {key:row for key,row in rows.items() if key == route['episode']}
        if not rows:
            raise EpisodeSiteError('애니마루에 등록되지 않은 회차입니다.')
    return dict(source='animaru', id=route['work'], title=item['title'].strip(), url=route['url'],
                episodes=_rows(list(rows.values())), incomplete=incomplete if route['collection'] else False), entries


def load_animaru_catalog(route, client):
    return _catalog(route, *_work(route, client))[0]


def extract_animaru_episode(route, client):
    if route['collection']:
        raise EpisodeSiteError('작품의 회차 목록에서 내려받을 회차를 선택하세요.')
    catalog, entries = _catalog(route, *_work(route, client))
    episode, entry = catalog['episodes'][0], entries[route['episode']]
    if not episode['available']:
        raise EpisodeSiteError('아직 재생 파일이 준비되지 않은 애니마루 회차입니다.')
    player = checked_url(entry['embed_url'], SITES['animaru']['api'])
    parts = urlsplit(player)
    match = PLAYER_PATH.fullmatch(parts.path)
    if not match or parts.query or parts.fragment:
        raise EpisodeSiteError('애니마루 플레이어 경로가 변경되었습니다.')
    final, html = client.request(player, SITES['animaru']['api'], referer=route['url'])
    if urlsplit(final).path != parts.path:
        raise EpisodeSiteError('애니마루 회차 플레이어 ID가 다릅니다.')
    doc = Document(html).root
    if len(doc.find('video', id='player')) != 1:
        raise EpisodeSiteError('애니마루 본편 플레이어를 확인할 수 없습니다.')
    urls = [value for script in doc.find('script') for _,value in re.findall(
        r'''\bvar\s+s\s*=\s*(['"])(https://[^'"\\\s]+)\1\s*;''', script.text)]
    if len(urls) != 1:
        raise EpisodeSiteError('애니마루 본편 HLS 주소를 확인할 수 없습니다.')
    media = checked_url(urls[0], SITES['animaru']['api'])
    if (urlsplit(media).path != f'/api/v1/v1/anime/playlist/{match[1]}/index.m3u8'
            or urlsplit(media).query or urlsplit(media).fragment):
        raise EpisodeSiteError('애니마루 재생목록의 회차 ID가 다릅니다.')
    media, manifest = validate_hls(client, media, final, SITES['animaru']['media'])
    keys = set(re.findall(r'^#EXT-X-KEY:[^\r\n]*\bURI="([^"]+)"', manifest, re.M))
    if len(keys) > 16:
        raise EpisodeSiteError('애니마루 영상 키 정보가 너무 많습니다.')
    for key in keys:
        _, data = client.request(urljoin(media,key), SITES['animaru']['media'], referer=final,
                                 subdomains=True, binary=True, prefix_bytes=17)
        if not isinstance(data, bytes) or len(data) != 16:
            raise EpisodeSiteError('애니마루 재생 서버가 표준 HLS 키를 제공하지 않습니다.')
    subtitles = {}
    tracks = [value for script in doc.find('script') for _,value in re.findall(
        r'''\btr\.src\s*=\s*(['"])(https://[^'"\\\s]+)\1\s*;''', script.text)]
    if len(tracks) > 1:
        raise EpisodeSiteError('애니마루 자막 식별 정보가 중복되어 있습니다.')
    for track in tracks:
        track = checked_url(track, SITES['animaru']['media'], subdomains=True)
        if not re.fullmatch(r'/ani/'+route['work']+'/'+str(entry['id'])+r'/[A-Za-z0-9_.-]+\.vtt',urlsplit(track).path):
            raise EpisodeSiteError('애니마루 자막의 작품·회차 ID가 다릅니다.')
        try:
            _, text = client.request(track, SITES['animaru']['media'], referer=final, subdomains=True)
            if not text.lstrip().startswith('WEBVTT') or ' --> ' not in text:
                raise EpisodeSiteError('정상 VTT 자막이 아닙니다.')
            subtitles['ko'] = [{'ext':'vtt','data':text}]
        except EpisodeSiteError:
            logger.warning('애니마루 자막을 불러오지 못해 영상만 다운로드합니다.')
    duration = sum(float(value) for value in re.findall(r'^#EXTINF:(\d+(?:\.\d+)?),',manifest,re.M)) or None
    if duration is not None and (not math.isfinite(duration) or duration <= 0):
        raise EpisodeSiteError('애니마루 영상 길이를 확인할 수 없습니다.')
    title = episode['title'] if episode['title'].startswith(catalog['title']) else f'{catalog["title"]} · {episode["title"]}'
    return dict(id=route['work']+'-'+str(entry['id']), title=title, series=catalog['title'],
                episode=episode['title'], episode_number=episode['number'], duration=duration,
                webpage_url=route['url'], uploader='애니마루', url=media, manifest=manifest,
                subtitles=subtitles, is_live=False,
                http_headers={'User-Agent':USER_AGENT, 'Referer':final, 'Origin':API})
