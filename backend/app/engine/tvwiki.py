"""TVWiki catalogs and its public guest-player flow; no JavaScript execution."""
from __future__ import annotations

import base64
import json
import math
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from Cryptodome.Cipher import AES
from Cryptodome.Util.Padding import unpad

from app.core.http import USER_AGENT
from app.engine.episode_sites import Document, EpisodeSiteError, SITES, checked_url, _rows, validate_hls

CATEGORIES = ('movie', 'kor_movie', 'drama', 'ent', 'sisa', 'world', 'ott_ent',
              'short_drama', 'ani_movie', 'animation', 'old_ent', 'old_drama')
PATH = re.compile(r'/(' + '|'.join(CATEGORIES) + r')/([1-9]\d*)(?:/([1-9]\d*))?/?')


def parse_tvwiki_url(value):
    value = checked_url(value, SITES['tvwiki']['hosts'])
    parts = urlsplit(value)
    match = PATH.fullmatch(parts.path)
    if not match:
        raise EpisodeSiteError('티비위키 작품 또는 회차 주소를 입력하세요.')
    category, work, episode = match.groups()
    return dict(site='tvwiki', category=category, work=work, episode=episode,
                url=f'https://{parts.hostname}/{category}/{work}' + (f'/{episode}' if episode else ''),
                collection=episode is None)


def _page(route, client):
    final, body = client.request(route['url'], SITES['tvwiki']['hosts'])
    target = parse_tvwiki_url(final)
    if any(target[key] != route[key] for key in ('category', 'work', 'episode')):
        raise EpisodeSiteError('이동된 티비위키 작품·회차 ID가 다릅니다.')
    return final, body, Document(body).root


def _catalog(route, final, body, doc):
    titles = doc.find('title')
    title = re.sub(r'\s+다시보기\s*-\s*티비위키\s*$', '', titles[0].text).strip() if titles else ''
    if not title:
        raise EpisodeSiteError('티비위키 작품 제목을 확인할 수 없습니다.')
    has_player = bool(doc.find('iframe', id='view_iframe'))
    episodes = {}
    for link in doc.find('a', cls='ep-link', href=None):
        label = link.text.strip()
        if not label:
            continue
        address = urljoin(final, link.attrs['href'])
        episode = parse_tvwiki_url(address)
        if any(episode[key] != route[key] for key in ('category', 'work')):
            continue
        if not episode['episode']:
            continue
        number = re.search(r'(\d+(?:\.\d+)?)\s*(?:화|회)(?:\s|$)', label)
        is_current = episode['episode'] == route['episode']
        available = has_player if is_current else True
        episodes[episode['episode']] = dict(id=episode['episode'], title=label,
            url=episode['url'], number=float(number[1]) if number else None, available=available)
    total = re.search(r'\btotalEpisodes\s*:\s*(\d+)', body)
    incomplete = bool(total and int(total[1]) > len(episodes))
    if route['episode']:
        episodes = {key: row for key, row in episodes.items() if key == route['episode']}
        if not episodes:
            raise EpisodeSiteError('티비위키 목록에서 요청한 회차를 찾지 못했습니다.')
    return dict(source='tvwiki', id=route['category']+'-'+route['work'], title=title,
                url=parse_tvwiki_url(final)['url'], episodes=_rows(list(episodes.values())),
                incomplete=incomplete if route['collection'] else False)


def load_tvwiki_catalog(route, client):
    return _catalog(route, *_page(route, client))


def _hex(value, *, sizes=None, maximum=32768):
    if not isinstance(value, str) or len(value) > maximum or not re.fullmatch(r'(?:[a-fA-F0-9]{2})+', value):
        raise EpisodeSiteError('티비위키 플레이어 설정 형식이 변경되었습니다.')
    data = bytes.fromhex(value)
    if sizes and len(data) not in sizes:
        raise EpisodeSiteError('티비위키 플레이어 설정 길이가 올바르지 않습니다.')
    return data


def _decrypt(key, iv, data):
    try:
        return unpad(AES.new(key, AES.MODE_CBC, iv).decrypt(data), AES.block_size)
    except ValueError:
        raise EpisodeSiteError('티비위키 플레이어 설정을 읽지 못했습니다. 다시 조회하세요.') from None


def _player_config(client, player, html):
    seeds = re.findall(r'window\.(_[A-Za-z0-9_]+)\s*=\s*\{\s*k:\s*"([a-fA-F0-9]+)"\s*,\s*t:\s*"([a-fA-F0-9]+)"\s*,\s*b:\s*\[\s*\]\s*\}', html)
    if len(seeds) != 1:
        raise EpisodeSiteError('티비위키 플레이어 설정을 확인할 수 없습니다.')
    name, key_part, token = seeds[0]
    host = urlsplit(player).hostname
    origin = 'https://' + host
    first = _hex(key_part, sizes=(16, 24, 32))
    if not 1 <= len(token) <= 512:
        raise EpisodeSiteError('티비위키 플레이어 세션을 확인할 수 없습니다.')
    _, shared = client.json(origin+'/api/key-share.php', (host,), referer=player,
                            json_body={'token': token}, headers={'Origin': origin})
    if not isinstance(shared, dict) or shared.get('ok') is not True:
        raise EpisodeSiteError('티비위키 플레이어 세션이 만료되었습니다. 다시 조회하세요.')
    second = _hex(shared.get('k2'), sizes=(len(first),))
    key = bytes(a ^ b for a, b in zip(first, second))
    blocks = re.findall(re.escape(name)+r'\.b\.push\(\{c:"([A-Za-z0-9+/=]+)",v:"([a-fA-F0-9]+)"\}\)', html)
    if not 1 <= len(blocks) <= 8:
        raise EpisodeSiteError('티비위키 플레이어 설정 블록이 변경되었습니다.')
    configs, scripts = [], []
    for data, iv in blocks:
        if len(data) > 2*1024*1024:
            raise EpisodeSiteError('티비위키 플레이어 설정이 너무 큽니다.')
        try:
            script = _decrypt(key, _hex(iv, sizes=(16,)), base64.b64decode(data, validate=True)).decode('utf-8')
        except (ValueError, UnicodeError):
            raise EpisodeSiteError('티비위키 플레이어 설정을 읽지 못했습니다.') from None
        scripts.append(script)
        match = re.search(r'\bconst\s+ART_CONFIG\s*=\s*(\{[\s\S]*?\n\s*\});', script)
        if match:
            configs.append(match[1])
    if len(configs) != 1:
        raise EpisodeSiteError('티비위키 본편 플레이어 설정을 확인할 수 없습니다.')
    config = {}
    for field in ('wrappedKey', 'wrapNonce', 'wrapSession', 'wrapIssuedAt', 'wrapSignature', 'urlPayload'):
        values = re.findall(r'\b'+field+r'\s*:\s*("(?:[^"\\]|\\.)*"|[0-9]+)\s*[,\n}]', configs[0])
        if len(values) != 1:
            raise EpisodeSiteError('티비위키 본편 재생 설정이 변경되었습니다.')
        config[field] = json.loads(values[0])
    for field in ('wrapNonce', 'wrapSession', 'wrapSignature'):
        if not isinstance(config[field], str) or not re.fullmatch(r'[A-Za-z0-9._~-]{1,1024}', config[field]):
            raise EpisodeSiteError('티비위키 본편 재생 세션이 올바르지 않습니다.')
    if not isinstance(config['wrapIssuedAt'], int) or config['wrapIssuedAt'] <= 0:
        raise EpisodeSiteError('티비위키 재생 세션 발급 시간을 확인할 수 없습니다.')
    _, wrap = client.json(origin+'/wrap_key.php', (host,), referer=player,
        json_body={'n':config['wrapNonce'], 'sid':config['wrapSession'], 'iat':str(config['wrapIssuedAt']), 'sig':config['wrapSignature']},
        headers={'Origin':origin})
    if not isinstance(wrap, dict) or any(not isinstance(wrap.get(k), str) for k in 'abcd'):
        raise EpisodeSiteError('티비위키 재생 주소 발급 응답을 확인할 수 없습니다.')
    material = _decrypt(_hex(wrap['a']+wrap['b'], sizes=(16,24,32)),
                        _hex(wrap['c']+wrap['d'], sizes=(16,)), _hex(config['wrappedKey']))
    if len(material) != 32:
        raise EpisodeSiteError('티비위키 재생 주소 설정 길이가 변경되었습니다.')
    try:
        playback = _decrypt(material[:16], material[16:], _hex(config['urlPayload'])).decode('utf-8')
        direct = re.findall(r'\bdirectPayload\s*:\s*("[a-fA-F0-9]+")\s*[,\n}]', configs[0])
        if not direct:
            return playback
        if len(direct) != 1:
            raise EpisodeSiteError('티비위키 기본 HLS 재생 주소를 확인할 수 없습니다.')
        native = _decrypt(material[:16], material[16:], _hex(json.loads(direct[0]))).decode('utf-8')
    except UnicodeError:
        raise EpisodeSiteError('티비위키 재생 주소를 읽지 못했습니다.') from None
    checked_url(native, SITES['tvwiki']['media'], subdomains=True)
    constants = {}
    for name in ('CAST_CONTENT_ID', 'CAST_AUTH_TOKEN', 'CAST_TIMESTAMP', 'CAST_REGISTER_URL'):
        values = [value for script in scripts for value in re.findall(
            r'window\.'+name+r'\s*=\s*("[^"\r\n]*"|[0-9]+)\s*;', script)]
        if len(values) != 1:
            raise EpisodeSiteError('티비위키 기본 HLS 세션 정보를 확인할 수 없습니다.')
        constants[name] = json.loads(values[0])
    register_host = constants['CAST_REGISTER_URL']
    if register_host != urlsplit(native).hostname:
        raise EpisodeSiteError('티비위키 기본 HLS 세션 발급 호스트가 다릅니다.')
    for name in ('CAST_CONTENT_ID', 'CAST_AUTH_TOKEN'):
        if not isinstance(constants[name], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,1024}', constants[name]):
            raise EpisodeSiteError('티비위키 기본 HLS 세션 형식이 변경되었습니다.')
    if not isinstance(constants['CAST_TIMESTAMP'], int) or constants['CAST_TIMESTAMP'] <= 0:
        raise EpisodeSiteError('티비위키 기본 HLS 세션 시간을 확인할 수 없습니다.')
    # Use the ordinary native/casting rendition advertised by the player.
    # Its standard AES-128 keys need no browser-only key decoder or site code.
    _, registered = client.json('https://'+register_host+'/v/cast-register', (register_host,), referer=player,
        json_body={'c':constants['CAST_CONTENT_ID'], 'auth':constants['CAST_AUTH_TOKEN'], 't':constants['CAST_TIMESTAMP']},
        headers={'Origin':origin})
    if not isinstance(registered, dict) or registered.get('ok') is not True:
        raise EpisodeSiteError('티비위키 기본 HLS 재생 세션을 등록하지 못했습니다. 다시 조회하세요.')
    return native


def extract_tvwiki_episode(route, client):
    if route['collection']:
        raise EpisodeSiteError('작품의 회차 목록에서 내려받을 회차를 선택하세요.')
    final, body, doc = _page(route, client)
    catalog = _catalog(route, final, body, doc)
    frames = doc.find('iframe', id='view_iframe')
    if len(frames) != 1:
        raise EpisodeSiteError('아직 본편 영상이 준비되지 않았거나 재생할 수 없는 회차입니다.')
    raw = frames[0].attrs.get('data-session1', '')
    try:
        if len(raw) > 32768:
            raise ValueError
        data = json.loads(raw)
        if (not isinstance(data, dict) or str(data.get('idx')) != route['episode']
                or set(data)-{'idx','s','vtt','option','srt','src','t','p','encrypted'}
                or any(not isinstance(v, (str,int,type(None))) or isinstance(v,bool) for v in data.values())):
            raise ValueError
    except (TypeError, ValueError):
        raise EpisodeSiteError('티비위키 회차 재생 식별 정보가 변경되었습니다.') from None
    origin = 'https://' + urlsplit(final).hostname
    _, session = client.json(origin+'/api/create_session.php', (urlsplit(final).hostname,),
                             referer=final, json_body=data, headers={'Origin':origin})
    if not isinstance(session, dict) or session.get('success') is not True:
        raise EpisodeSiteError('티비위키 재생 세션을 발급하지 못했습니다. 다시 조회하세요.')
    player = urljoin(final, session.get('player_url') or '')
    checked_url(player, SITES['tvwiki']['players'], subdomains=True)
    parts = urlsplit(player)
    if not re.fullmatch(r'/v/[A-Za-z0-9_-]{1,128}', parts.path):
        raise EpisodeSiteError('티비위키 플레이어 경로가 변경되었습니다.')
    query = dict(parse_qsl(parts.query))
    for field in ('t','sig'):
        value = session.get(field)
        if not isinstance(value, (str,int)) or isinstance(value,bool) or not re.fullmatch(r'[A-Za-z0-9._~-]{1,1024}',str(value)):
            raise EpisodeSiteError('티비위키 플레이어 세션 응답이 올바르지 않습니다.')
        query[field] = str(value)
    player = urlunsplit(parts._replace(query=urlencode(query)))
    player_final, html = client.request(player, SITES['tvwiki']['players'], referer=final, subdomains=True)
    if urlsplit(player_final).path != parts.path:
        raise EpisodeSiteError('티비위키 본편 플레이어 주소가 변경되었습니다.')
    media = _player_config(client, player_final, html)
    media, manifest = validate_hls(client, media, player_final, SITES['tvwiki']['media'])
    key = re.search(r'^#EXT-X-KEY:[^\r\n]*\bURI="([^"]+)"', manifest, re.M)
    if key:
        _, key_data = client.request(urljoin(media,key[1]), SITES['tvwiki']['media'],
                                     referer=player_final, subdomains=True, binary=True)
        if not isinstance(key_data, bytes) or len(key_data) != 16:
            raise EpisodeSiteError('티비위키 재생 서버가 표준 HLS 키를 제공하지 않습니다. 이 재생 형식은 지원되지 않습니다.')
    episode = catalog['episodes'][0]
    durations = re.findall(r'^#EXTINF:(\d+(?:\.\d+)?),', manifest, re.M)
    duration = sum(float(value) for value in durations) if durations else None
    if duration is not None and (not math.isfinite(duration) or duration <= 0):
        raise EpisodeSiteError('티비위키 영상 길이를 확인할 수 없습니다.')
    resources = []
    for line in manifest.splitlines():
        refs = re.findall(r'URI="([^"]+)"', line) if line.startswith('#') else [line.strip()] if line.strip() else []
        resources.extend(urljoin(media, reference) for reference in refs)
    return dict(id=catalog['id']+'-'+episode['id'], title=episode['title'], series=catalog['title'],
                episode=episode['title'], episode_number=episode['number'], webpage_url=final,
                duration=duration,
                uploader='티비위키', url=media, manifest=manifest, subtitles={}, is_live=False,
                _tvwiki_delivery={'origin':'https://'+urlsplit(media).netloc, 'resources':resources},
                http_headers={'User-Agent':USER_AGENT, 'Referer':player_final, 'Origin':'https://'+urlsplit(player_final).hostname})
