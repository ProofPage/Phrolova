"""OHLI365's public catalog and ordinary MegaPlay HLS delivery."""
from __future__ import annotations

import base64
import json
import math
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from Cryptodome.Cipher import AES
from Cryptodome.Util.Padding import unpad

from app.core.http import USER_AGENT
from app.core.logger import get_platform_logger
from app.engine.episode_sites import Document, EpisodeSiteError, SITES, checked_url, _rows, validate_hls

UUID = re.compile(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', re.I)
PLAYER_PATH = re.compile(r'/stream/ani/[1-9][0-9]*/[0-9]+(?:\.[0-9]+)?/(?:sub|dub)')
ASSET_FILE = re.compile(r'(?:master|index-[A-Za-z0-9_-]+)\.m3u8|(?:seg|init|key)[A-Za-z0-9_-]*\.[a-z0-9]{1,8}')
PLAYER_ORIGIN = 'https://megaplay.buzz'
MEDIA_HEADERS = {'User-Agent': USER_AGENT, 'Referer': PLAYER_ORIGIN+'/', 'Origin': PLAYER_ORIGIN}
# Public URL-metadata encoding used by e1-player.min.js v1.8.112.
# The application reads JSON and decodes metadata; it never evaluates player scripts.
METADATA_KEY = b'i?LMTAx0Q6,:}50U'.ljust(32, b'\0')
METADATA_IV = b"W0;27ToaUpl_P%'c"
logger = get_platform_logger('ohli365', 'vod')


class _Playlists:
    """Resolve advertised asset paths on the checked issuing server, without contacting rotating CDN aliases."""
    def __init__(self, client, media):
        self.client = client
        self.parts = urlsplit(media)
        match = re.fullmatch(r'(/anime/[a-f0-9]{32}/[a-f0-9]{32}/)master\.m3u8', self.parts.path)
        if not match:
            raise EpisodeSiteError('애니365 영상 식별 경로가 변경되었습니다.')
        self.prefix = match[1]
        self.data = {}

    def _resource(self, value, address):
        parts = urlsplit(urljoin(address, value))
        # Foreign aliases contribute only an asset path; they are never requested.
        if not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}',parts.hostname or ''):
            raise EpisodeSiteError('애니365 영상 조각 주소 형식이 변경되었습니다.')
        checked_url(urlunsplit(parts), (parts.hostname,))
        filename = parts.path.removeprefix(self.prefix)
        if (not parts.path.startswith(self.prefix) or parts.query or parts.fragment
                or not ASSET_FILE.fullmatch(filename)):
            raise EpisodeSiteError('애니365 영상 조각의 회차 식별 정보가 다릅니다.')
        return urlunsplit(('https', self.parts.netloc, parts.path, '', ''))

    def request(self, url, domains, **kwargs):
        final, text = self.client.request(url, domains, **kwargs)
        if urlsplit(final).netloc != self.parts.netloc:
            raise EpisodeSiteError('애니365 재생 서버 주소가 변경되었습니다.')
        if isinstance(text, str) and text.lstrip().startswith('#EXTM3U'):
            lines = []
            for raw in text.splitlines():
                line = raw.strip()
                if line.startswith('#'):
                    line = re.sub(r'URI="([^"]+)"', lambda m:'URI="'+self._resource(m[1],final)+'"',line)
                elif line:
                    line = self._resource(line, final)
                lines.append(line)
            text = '\n'.join(lines)+'\n'
            self.data[final] = text
        return final, text


def parse_ohli365_url(value):
    value = checked_url(value, SITES['ohli365']['hosts'])
    parts = urlsplit(value)
    if parts.path not in ('', '/'):
        raise EpisodeSiteError('애니365 작품 링크를 입력하세요.')
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    titles = [v for k,v in pairs if k == 'title']
    episodes = [v for k,v in pairs if k == 'episode']
    if (len(titles) != 1 or not UUID.fullmatch(titles[0]) or len(episodes) > 1
            or episodes and episodes[0] != 'movie' and not UUID.fullmatch(episodes[0])):
        raise EpisodeSiteError('애니365 작품·회차 ID를 확인하세요.')
    work = titles[0].lower()
    episode = episodes[0].lower() if episodes else None
    query = {'title': work}
    if episode is not None:
        query['episode'] = episode
    return dict(site='ohli365', work=work, episode=episode, collection=episode is None,
                url=f'https://{parts.hostname}/?'+urlencode(query))


def _detail(html, work):
    decoder = json.JSONDecoder()
    chunks = []
    for script in Document(html).root.find('script'):
        for match in re.finditer(r'\bself\.__next_f\.push\(', script.text):
            try:
                value, end = decoder.raw_decode(script.text, match.end())
                if not script.text[end:].lstrip().startswith(')'):
                    continue
                if isinstance(value, list) and len(value) == 2 and value[0] == 1 and isinstance(value[1], str):
                    chunks.append(value[1])
            except (ValueError, RecursionError):
                raise EpisodeSiteError('애니365 작품 데이터 형식이 변경되었습니다.') from None
    flight = ''.join(chunks)
    found = []
    for match in re.finditer(r'(?:^|\n)[0-9a-f]+:(?=[\[{])', flight):
        try:
            record, _ = decoder.raw_decode(flight, match.end())
        except (ValueError, RecursionError):
            continue
        stack = [record]
        while stack:
            value = stack.pop()
            if isinstance(value, dict):
                anime = value.get('anime')
                if isinstance(anime, dict) and anime.get('id') == work and isinstance(value.get('episodes'), list):
                    if value not in found:
                        found.append(value)
                stack.extend(value.values())
            elif isinstance(value, list):
                stack.extend(value)
    if len(found) != 1:
        raise EpisodeSiteError('애니365 작품 정보·회차 목록을 확인할 수 없습니다.')
    data = found[0]
    anime = data['anime']
    if not isinstance(anime.get('title'), str) or not anime['title'].strip() or anime.get('mediaType') not in ('tv', 'movie'):
        raise EpisodeSiteError('애니365 작품 제목·종류가 올바르지 않습니다.')
    if anime.get('isDemo') is True:
        raise EpisodeSiteError('아직 공개 재생 영상이 준비되지 않은 작품입니다.')
    return data


def _catalog(route, client):
    origin = 'https://' + urlsplit(route['url']).hostname
    address = origin+'/?'+urlencode({'title':route['work']})
    final, html = client.request(address, SITES['ohli365']['hosts'])
    target = parse_ohli365_url(final)
    if target['work'] != route['work'] or target['episode'] is not None:
        raise EpisodeSiteError('이동된 애니365 작품 ID가 다릅니다.')
    data = _detail(html, route['work'])
    anime = data['anime']
    if len(data['episodes']) > 10000:
        raise EpisodeSiteError('애니365 회차 목록이 너무 큽니다.')
    rows, entries = [], {}
    if anime['mediaType'] == 'movie':
        entries['movie'] = {'id': route['work'], 'title': anime['title']}
        rows.append(dict(id='movie', title=anime['title'].strip(), number=None, season=1,
                         url=address+'&episode=movie', available=True))
    else:
        for entry in data['episodes']:
            if not isinstance(entry, dict) or not isinstance(entry.get('id'), str) or not UUID.fullmatch(entry['id']):
                raise EpisodeSiteError('애니365 회차 ID가 올바르지 않습니다.')
            identifier = entry['id'].lower()
            number, season = entry.get('number'), entry.get('season', 1)
            if (isinstance(number, bool) or not isinstance(number, (int,float)) or not math.isfinite(number)
                    or not 0 <= number < 1000000 or type(season) is not int or not 0 <= season < 1000):
                raise EpisodeSiteError('애니365 회차 번호가 올바르지 않습니다.')
            label = entry.get('title')
            if not isinstance(label, str) or not label.strip() or identifier in entries:
                raise EpisodeSiteError('애니365 회차 제목·중복 ID를 확인하세요.')
            entries[identifier] = entry
            prefix = f'{season}기 ' if season > 1 else ''
            title = f'{prefix}{number:g}화 · {label.strip()}'
            rows.append(dict(id=identifier, title=title, number=number, season=season,
                             url=address+'&episode='+identifier, available=entry.get('playable') is not False))
    if route['episode'] is not None:
        rows = [row for row in rows if row['id'] == route['episode']]
        if not rows:
            raise EpisodeSiteError('애니365 작품에 등록되지 않은 회차입니다.')
    catalog = dict(source='ohli365', id=route['work'], title=anime['title'].strip(),
                   url=route['url'], incomplete=False,
                   episodes=sorted(_rows(rows), key=lambda r:(r['season'],r['number'] or 0,r['id'])))
    return catalog, entries


def load_ohli365_catalog(route, client):
    return _catalog(route, client)[0]


def _source_metadata(data):
    if not isinstance(data, dict):
        raise EpisodeSiteError('애니365 외부 플레이어 응답이 올바르지 않습니다.')
    encrypted = data.get('enc')
    if not isinstance(encrypted, str) or not 1 <= len(encrypted) <= 65536 or not re.fullmatch(r'[A-Za-z0-9_-]+={0,2}', encrypted):
        raise EpisodeSiteError('애니365 외부 재생 주소 형식이 변경되었습니다.')
    try:
        raw = base64.urlsafe_b64decode(encrypted+'='*(-len(encrypted)%4))
        result = json.loads(unpad(AES.new(METADATA_KEY, AES.MODE_CBC, METADATA_IV).decrypt(raw),16))
        if not isinstance(result, dict) or not isinstance(result.get('file'), str):
            raise ValueError
        return checked_url(result['file'], SITES['ohli365']['media'], subdomains=True)
    except (ValueError, UnicodeError, RecursionError):
        raise EpisodeSiteError('애니365 외부 재생 주소를 읽지 못했습니다. 플레이어 형식을 확인하세요.') from None


def _subtitles(data, media, client):
    result = {}
    tracks = data.get('tracks') or []
    if not isinstance(tracks, list) or len(tracks) > 32:
        raise EpisodeSiteError('애니365 자막 목록을 확인할 수 없습니다.')
    identity = re.search(r'/anime/([a-f0-9]{32}/[a-f0-9]{32})/', urlsplit(media).path)
    if not identity:
        raise EpisodeSiteError('애니365 영상 경로의 식별 정보가 다릅니다.')
    languages = {'eng':'en','kor':'ko','ara':'ar','fre':'fr','ger':'de','ita':'it','rus':'ru',
                 'Brazil_por':'pt-BR','Latin_America_spa':'es-419','Spain_spa':'es-ES'}
    labels = {'english':'en','korean':'ko','arabic':'ar','french':'fr','german':'de',
              'italian':'it','russian':'ru','japanese':'ja', 'portuguese (brazil)':'pt-BR',
              'spanish (latin america)':'es-419','spanish (spain)':'es-ES'}
    for track in tracks:
        if not isinstance(track, dict):
            raise EpisodeSiteError('애니365 자막 항목이 올바르지 않습니다.')
        if track.get('kind') != 'captions':
            continue
        url = checked_url(track.get('file'), SITES['ohli365']['media'], subdomains=True)
        match = re.fullmatch(r'/anime/'+identity[1]+r'/subtitles/(?:track_[0-9]+_([A-Za-z_]+)|[a-f0-9]{32})\.vtt',
                             urlsplit(url).path)
        if not match:
            raise EpisodeSiteError('애니365 자막의 회차 식별 정보가 다릅니다.')
        lang = (languages.get(match[1], 'und-'+match[1].lower().replace('_','-')) if match[1]
                else labels.get(str(track.get('label', '')).strip().casefold(), 'und'))
        try:
            _, text = client.request(url, SITES['ohli365']['media'], subdomains=True,
                                     referer=PLAYER_ORIGIN+'/', headers={'Origin':PLAYER_ORIGIN})
            if not text.lstrip().startswith('WEBVTT') or ' --> ' not in text:
                raise EpisodeSiteError('정상 VTT 자막이 아닙니다.')
            result.setdefault(lang, []).append({'ext':'vtt', 'data':text})
        except EpisodeSiteError:
            logger.warning('애니365 자막을 불러오지 못했습니다. 언어=%s',lang)
    return result


def extract_ohli365_episode(route, client):
    if route['collection']:
        raise EpisodeSiteError('작품의 회차 목록에서 내려받을 회차를 선택하세요.')
    catalog, entries = _catalog(route, client)
    episode = catalog['episodes'][0]
    if not episode['available']:
        raise EpisodeSiteError('아직 공개 재생 파일이 준비되지 않은 회차입니다.')
    origin = 'https://' + urlsplit(route['url']).hostname
    body = {'animeId':route['work']} if route['episode'] == 'movie' else {'episodeId':route['episode']}
    _, playback = client.json(origin+'/api/home/playback', (urlsplit(origin).hostname,),
        referer=origin+'/?'+urlencode({'title':route['work']}), json_body=body, headers={'Origin':origin})
    expected_id = route['work'] if route['episode'] == 'movie' else route['episode']
    if (not isinstance(playback, dict) or playback.get('profileId') not in (None, 'public')
            or playback.get('responseId') != 'megaplay:'+expected_id
            or route['episode'] != 'movie' and playback.get('episodeId') != route['episode']):
        raise EpisodeSiteError('애니365 공개 회차 재생 식별 정보가 다릅니다.')
    if playback.get('sourceType') != 'iframe':
        raise EpisodeSiteError('애니365의 이 재생 제공자는 아직 지원하지 않습니다.')
    player = checked_url(playback.get('sourceUrl'), SITES['ohli365']['players'])
    parts = urlsplit(player)
    if not PLAYER_PATH.fullmatch(parts.path) or parts.query or parts.fragment:
        raise EpisodeSiteError('애니365 외부 플레이어 경로가 변경되었습니다.')
    final, html = client.request(player, SITES['ohli365']['players'], referer=route['url'])
    if urlsplit(final).path != parts.path:
        raise EpisodeSiteError('애니365 외부 플레이어 회차가 다릅니다.')
    players = Document(html).root.find(id='megaplay-player')
    if len(players) != 1 or not re.fullmatch(r'[1-9][0-9]*',players[0].attrs.get('data-id','')):
        raise EpisodeSiteError('애니365 외부 플레이어 ID를 확인할 수 없습니다.')
    identifier = players[0].attrs['data-id']
    _, data = client.json(PLAYER_ORIGIN+'/stream/getSources?'+urlencode({'id':identifier,'platform':'OTHER'}),
        SITES['ohli365']['players'], referer=final, headers={'X-Requested-With':'XMLHttpRequest'})
    media = _source_metadata(data)
    playlists = _Playlists(client, media)
    media, manifest = validate_hls(playlists, media, PLAYER_ORIGIN+'/', SITES['ohli365']['media'],
                                   headers={'Origin':PLAYER_ORIGIN})
    subtitles = _subtitles(data, media, client)
    entry = entries[route['episode']]
    duration = entry.get('duration')
    if isinstance(duration, bool) or not isinstance(duration,(int,float)) or not math.isfinite(duration) or duration <= 0:
        duration = None
    title = catalog['title'] if catalog['title'] == episode['title'] else catalog['title']+' · '+episode['title']
    return dict(id=route['work']+'-'+route['episode'], title=title,
                series=catalog['title'], episode=episode['title'], episode_number=episode['number'],
                duration=duration, webpage_url=route['url'], uploader='애니365', subtitles=subtitles,
                url=media, manifest=manifest, is_live=False, http_headers=dict(MEDIA_HEADERS),
                _ohli365_playlists=playlists.data)
