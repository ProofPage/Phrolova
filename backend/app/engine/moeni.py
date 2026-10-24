"""모에니(moeni.net) 작품 카탈로그 및 HLS 스트림 파서."""
from __future__ import annotations

import base64
import hashlib
import json
import math
import re
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit

from Cryptodome.Cipher import AES
from Cryptodome.Util.Padding import unpad

from app.core.http import USER_AGENT
from app.core.logger import get_media_logger
from app.engine.episode_sites import EpisodeSiteError, SITES, checked_url, _rows, validate_hls
from app.engine.tls_compat import enable_tls_compat

logger = get_media_logger('moeni')

PATH = re.compile(r'/([1-9]\d*)(?:/([1-9]\d*(?:\.\d+)?))?/?')


def _b64_fix_decode(s: str) -> bytes:
    s = s.strip()
    s += '=' * (-len(s) % 4)
    return base64.b64decode(s)


def _sha256_hex(val: str) -> str:
    return hashlib.sha256(val.encode('utf-8')).hexdigest()


def _moeni_decrypt(raw_enc: str, secret_key_source: str, ua: str, is_nested_b64: bool = False) -> str:
    try:
        if is_nested_b64:
            raw_enc = _b64_fix_decode(raw_enc).decode('utf-8')
        text = raw_enc.replace('d0s1l2', '//').replace('/p0p1', '+')

        kst = timezone(timedelta(hours=9))
        day = str(datetime.now(kst).day)
        secret = 'Moeni108oo'

        key_str = _sha256_hex(secret_key_source + ua[-7:] + secret + day + day)[:32]
        iv_str = _sha256_hex('Moeni')[:16]

        cipher_bytes = _b64_fix_decode(text)
        cipher = AES.new(key_str.encode('utf-8'), AES.MODE_CBC, iv_str.encode('utf-8'))
        decrypted_padded = cipher.decrypt(cipher_bytes)
        decrypted = unpad(decrypted_padded, AES.block_size).decode('utf-8')
        return decrypted[1:]
    except Exception as error:
        raise EpisodeSiteError('모에니 데이터 복호화에 실패했습니다.') from error


def parse_moeni_url(value: str) -> dict:
    value = checked_url(value, SITES['moeni']['hosts'])
    parts = urlsplit(value)
    path = parts.path.rstrip('/')
    if not path:
        raise EpisodeSiteError('모에니 메인 주소입니다. 다운로드할 개별 작품 주소(/{id}) 또는 회차 주소(/{id}/{number})를 입력하세요.')
    match = PATH.fullmatch(parts.path)
    if not match:
        raise EpisodeSiteError('올바른 모에니 작품 또는 회차 주소를 입력하세요.')
    work, episode = match.groups()
    return dict(site='moeni', work=work, episode=episode,
                url=f'https://{parts.hostname}/{work}' + (f'/{episode}' if episode else ''),
                collection=episode is None)


def _ensure_tls_compat(client):
    http = getattr(client, 'http', client)
    for host in ('moeni.net', 'api.moeni.net', 'api.modumo.bid', 'video.modumo.bid'):
        try:
            enable_tls_compat(http, host)
        except Exception:
            pass


def _fetch_meta(route, client):
    _ensure_tls_compat(client)
    api_url = f'https://api.moeni.net/web/{route["work"]}'
    final, data = client.json(api_url, ('api.moeni.net',), referer=route['url'],
                              headers={'Origin': 'https://moeni.net'})
    if not isinstance(data, dict) or str(data.get('id')) != route['work']:
        raise EpisodeSiteError('모에니 작품 정보를 확인할 수 없습니다.')
    title = str(data.get('title') or '').strip()
    path_name = str(data.get('path') or '').strip()
    if not title:
        raise EpisodeSiteError('모에니 작품 제목을 확인할 수 없습니다.')
    return data, title, path_name


def _fetch_episodes(route, client, path_name):
    _ensure_tls_compat(client)
    list_url = f'https://api.modumo.bid/v1/list/{route["work"]}'
    final, enc_text = client.request(list_url, ('api.modumo.bid',), referer=route['url'],
                                     headers={'Origin': 'https://moeni.net'})
    decrypted_str = _moeni_decrypt(enc_text, path_name, USER_AGENT)
    try:
        categories = json.loads(decrypted_str)
    except ValueError as error:
        raise EpisodeSiteError('모에니 회차 목록 형식이 올바르지 않습니다.') from error

    if not isinstance(categories, list) or not categories:
        raise EpisodeSiteError('모에니 회차 목록을 확인할 수 없습니다.')

    raw_episodes = []
    for cat in categories:
        if isinstance(cat, dict) and isinstance(cat.get('list'), list):
            raw_episodes.extend(cat['list'])

    if not raw_episodes:
        raise EpisodeSiteError('모에니에 등록된 회차가 없습니다.')
    return raw_episodes


def _catalog(route, client):
    meta, title, path_name = _fetch_meta(route, client)
    raw_episodes = _fetch_episodes(route, client, path_name)

    rows, entries = {}, {}
    for idx, item in enumerate(raw_episodes, start=1):
        if not isinstance(item, dict):
            continue
        ep_title = str(item.get('title') or '').strip()
        ep_value = str(item.get('value') or '').strip()
        if not ep_title or not ep_value:
            continue

        num_match = re.search(r'(\d+(?:\.\d+)?)화', ep_title)
        num = float(num_match.group(1)) if num_match else float(idx)
        key = str(int(num)) if num.is_integer() else str(num)

        row = dict(
            id=key,
            title=ep_title,
            number=num,
            url=f'https://{urlsplit(route["url"]).hostname}/{route["work"]}/{key}',
            available=True,
        )
        item['key'] = key
        item['number'] = num
        rows[key] = row
        entries[key] = item

    if route['episode'] is not None:
        target_key = route['episode']
        filtered_rows = {k: v for k, v in rows.items() if k == target_key or str(v['number']) == str(target_key)}
        if not filtered_rows:
            raise EpisodeSiteError('모에니에 등록되지 않은 회차입니다.')
        rows = filtered_rows

    catalog = dict(
        source='moeni',
        id=route['work'],
        title=title,
        url=route['url'],
        episodes=_rows(list(rows.values())),
        incomplete=False,
    )
    return catalog, entries, meta


def load_moeni_catalog(route, client):
    return _catalog(route, client)[0]


def extract_moeni_episode(route, client):
    _ensure_tls_compat(client)
    catalog, entries, meta = _catalog(route, client)
    if len(catalog['episodes']) != 1:
        raise EpisodeSiteError('작품의 회차 목록에서 내려받을 회차를 선택하세요.')

    episode_row = catalog['episodes'][0]
    key = str(episode_row['id'])
    entry = entries.get(key)
    if not entry or not entry.get('value'):
        raise EpisodeSiteError('모에니 회차 식별 정보를 확인할 수 없습니다.')

    ep_value = entry['value']
    ep_title = entry.get('title') or episode_row['title']

    play_url = 'https://api.modumo.bid/v1/play'
    final, enc_play = client.request(
        play_url,
        ('api.modumo.bid',),
        form={'id': ep_value},
        referer=route['url'],
        headers={'Origin': 'https://moeni.net'},
    )

    dec_play_str = _moeni_decrypt(enc_play, ep_title, USER_AGENT, is_nested_b64=True)
    try:
        play_data = json.loads(dec_play_str)
    except ValueError as error:
        raise EpisodeSiteError('모에니 재생 데이터 형식이 올바르지 않습니다.') from error

    if not isinstance(play_data, dict) or not play_data.get('pl'):
        raise EpisodeSiteError('모에니 영상 재생목록을 확인할 수 없습니다.')

    pl_raw = _b64_fix_decode(play_data['pl']).decode('utf-8')
    ser_list = play_data.get('ser') or ['video']

    lines = [line for line in pl_raw.splitlines() if not line.startswith('#EXT-X-KEY')]
    mod_lines = []
    seg_idx = 0
    first_seg_url = None
    for line in lines:
        s_line = line.strip()
        if not s_line or s_line.startswith('#'):
            mod_lines.append(s_line)
        else:
            ser = ser_list[seg_idx % len(ser_list)]
            seg_url = f'https://{ser}.modumo.bid/vod/{s_line}'
            if first_seg_url is None:
                first_seg_url = seg_url
            mod_lines.append(seg_url)
            seg_idx += 1

    if not seg_idx or first_seg_url is None:
        raise EpisodeSiteError('모에니 영상 세그먼트 목록이 비어 있습니다.')

    manifest = '\n'.join(mod_lines)
    if not manifest.lstrip().startswith('#EXTM3U'):
        raise EpisodeSiteError('정상 HLS 재생목록이 아닙니다.')
    if re.search(r'^\s*#(?:EXT-X-(?:CUE|DATERANGE|SESSION-KEY)\b|(?:EXT(?:-X|-OATCLS)?-)?SCTE-?35\b|(?:EXT-X-)?(?:VAST|INTERSTITIAL)\b)', manifest, re.I | re.M):
        raise EpisodeSiteError('광고 구간 또는 보호된 재생목록은 지원하지 않습니다.')

    # 첫 세그먼트 유효성 및 TS 스트림 검증
    _, seg_head = client.request(first_seg_url, SITES['moeni']['media'], referer=route['url'],
                                 subdomains=True, binary=True, prefix_bytes=188)
    if not seg_head or seg_head[0] != 0x47:
        raise EpisodeSiteError('모에니 영상 세그먼트 스트림을 확인할 수 없습니다.')

    duration = sum(float(value) for value in re.findall(r'^#EXTINF:(\d+(?:\.\d+)?),', manifest, re.M)) or None
    if duration is not None and (not math.isfinite(duration) or duration <= 0):
        raise EpisodeSiteError('모에니 영상 길이를 확인할 수 없습니다.')

    full_title = ep_title if ep_title.startswith(catalog['title']) else f'{catalog["title"]} · {ep_title}'
    dummy_media_url = first_seg_url.rsplit('/', 1)[0] + '/playlist.m3u8'
    return dict(
        id=f'{route["work"]}-{key}',
        title=full_title,
        series=catalog['title'],
        episode=episode_row['title'],
        episode_number=episode_row.get('number'),
        duration=duration,
        webpage_url=route['url'],
        uploader='모에니',
        url=dummy_media_url,
        manifest=manifest,
        subtitles={},
        is_live=False,
        http_headers={'User-Agent': USER_AGENT, 'Referer': 'https://moeni.net/', 'Origin': 'https://moeni.net'},
    )
