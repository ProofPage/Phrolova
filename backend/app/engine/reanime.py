"""Re:ANIME (reanime.to) 작품 카탈로그 및 에피소드 파서."""
from __future__ import annotations

import json
import re
import subprocess
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from app.core.http import USER_AGENT
from app.core.logger import get_media_logger
from app.engine.episode_sites import EpisodeSiteError, SITES, checked_url, _rows

logger = get_media_logger('reanime')

ANIME_PATH = re.compile(r'/anime/([a-zA-Z0-9_-]+)/?')
WATCH_PATH = re.compile(r'/watch/([a-zA-Z0-9_-]+)/?')


def parse_reanime_url(value: str) -> dict:
    value = checked_url(value, SITES['reanime']['hosts'])
    parts = urlsplit(value)
    path = parts.path.rstrip('/')
    if not path or path in ('/home', '/search', '/schedule', '/community', '/settings'):
        raise EpisodeSiteError('Re:ANIME 메인 주소입니다. 다운로드할 개별 작품 주소(/anime/{slug}) 또는 회차 주소(/watch/{slug}?ep={n})를 입력하세요.')

    anime_m = ANIME_PATH.fullmatch(parts.path)
    if anime_m:
        slug = anime_m.group(1)
        return dict(
            site='reanime',
            work=slug,
            episode=None,
            url=f'https://{parts.hostname}/watch/{slug}',
            collection=True,
        )

    watch_m = WATCH_PATH.fullmatch(parts.path)
    if watch_m:
        slug = watch_m.group(1)
        qs = parse_qs(parts.query)
        ep = qs.get('ep', [None])[0]
        url = f'https://{parts.hostname}/watch/{slug}' + (f'?ep={ep}' if ep else '')
        return dict(
            site='reanime',
            work=slug,
            episode=ep,
            url=url,
            collection=ep is None,
        )

    raise EpisodeSiteError('올바른 Re:ANIME 작품 또는 회차 주소를 입력하세요.')


def _parse_svelte_data(html: str) -> tuple[dict, list[dict]]:
    scripts = re.findall(r'<script[^>]*>([\s\S]*?)</script>', html)
    target_script = None
    for s in scripts:
        if 'episodes:' in s and 'anime_id:' in s:
            target_script = s
            break
    if not target_script:
        raise EpisodeSiteError('Re:ANIME 작품 데이터를 페이지에서 찾을 수 없습니다.')

    runner = f"""
    const text = {json.dumps(target_script)};
    const pos = text.indexOf('data: [');
    if (pos === -1) process.exit(1);
    const sub = text.substring(pos + 6);
    const end = sub.lastIndexOf(']');
    const arr = (new Function('return ' + sub.substring(0, end + 1)))();
    for (const item of arr) {{
        if (item && item.data && item.data.anime) {{
            console.log(JSON.stringify(item.data));
            process.exit(0);
        }}
    }}
    process.exit(1);
    """
    try:
        proc = subprocess.run(['node', '-'], input=runner, capture_output=True, text=True, encoding='utf-8', timeout=15)
        if not proc.stdout.strip().startswith('{'):
            raise ValueError(proc.stderr)
        data = json.loads(proc.stdout)
    except Exception as error:
        raise EpisodeSiteError('Re:ANIME 데이터 파싱에 실패했습니다.') from error

    anime = data.get('anime') or {}
    episodes = data.get('episodes') or []
    return anime, episodes


def _catalog(route, client):
    target_url = f'https://{urlsplit(route["url"]).hostname}/watch/{route["work"]}'
    final, html = client.request(target_url, SITES['reanime']['hosts'], referer=route['url'])

    anime, raw_episodes = _parse_svelte_data(html)
    title_dict = anime.get('title') or {}
    title = (
        title_dict.get('english')
        or title_dict.get('romaji')
        or title_dict.get('native')
        or anime.get('title')
        or route['work']
    ).strip()

    rows = {}
    for idx, ep in enumerate(raw_episodes, start=1):
        if not isinstance(ep, dict):
            continue
        num = ep.get('number') if ep.get('number') is not None else ep.get('episode_number', idx)
        key = str(num)
        ep_title = ep.get('title') or f'Episode {num}'
        row = dict(
            id=key,
            title=f'Episode {num}' if ep_title == f'Episode {num}' else f'{num}화 · {ep_title}',
            number=float(num),
            url=f'https://{urlsplit(final).hostname}/watch/{route["work"]}?ep={key}',
            available=ep.get('playable') is not False,
        )
        rows[key] = row

    if route['episode'] is not None:
        target_key = str(route['episode'])
        filtered_rows = {k: v for k, v in rows.items() if k == target_key or str(int(v['number'])) == target_key}
        if not filtered_rows:
            raise EpisodeSiteError('Re:ANIME에 등록되지 않은 회차입니다.')
        rows = filtered_rows

    catalog = dict(
        source='reanime',
        id=route['work'],
        title=title,
        url=route['url'],
        episodes=_rows(list(rows.values())),
        incomplete=False,
        anilist_id=anime.get('anilist_id'),
        mal_id=anime.get('mal_id'),
    )
    return catalog, rows, anime


def load_reanime_catalog(route, client):
    return _catalog(route, client)[0]


def extract_reanime_episode(route, client):
    catalog, rows, anime = _catalog(route, client)
    if len(catalog['episodes']) != 1:
        raise EpisodeSiteError('작품의 회차 목록에서 내려받을 회차를 선택하세요.')

    episode_row = catalog['episodes'][0]
    ep_num = int(episode_row['number'])
    anilist_id = anime.get('anilist_id') or catalog.get('anilist_id')
    mal_id = anime.get('mal_id') or catalog.get('mal_id')

    if not anilist_id:
        raise EpisodeSiteError('Re:ANIME 작품 식별 번호를 확인할 수 없습니다.')

    api_url = f'https://reanime.to/api/flix/{anilist_id}/{ep_num}'
    if mal_id:
        api_url += f'?mal={mal_id}'

    final, payload = client.json(
        api_url,
        SITES['reanime']['hosts'],
        referer=route['url'],
        headers={'Origin': 'https://reanime.to'},
    )

    if not isinstance(payload, dict) or not payload.get('success') or not payload.get('servers'):
        raise EpisodeSiteError('Re:ANIME 재생 서버 목록을 가져올 수 없습니다.')

    servers = payload['servers']
    # HD-2 sub 우선, 없으면 HD-1 sub
    chosen_server = next(
        (s for s in servers if s.get('dataType') == 'sub' and s.get('serverName') == 'HD-2'),
        next(
            (s for s in servers if s.get('dataType') == 'sub'),
            servers[0]
        )
    )

    player_url = chosen_server.get('dataLink')
    if not player_url:
        raise EpisodeSiteError('Re:ANIME 플레이어 링크를 확인할 수 없습니다.')

    title = episode_row['title']
    full_title = title if title.startswith(catalog['title']) else f'{catalog["title"]} · {title}'

    return dict(
        id=f'{route["work"]}-{ep_num}',
        title=full_title,
        series=catalog['title'],
        episode=episode_row['title'],
        episode_number=episode_row.get('number'),
        webpage_url=route['url'],
        uploader='Re:ANIME',
        url=player_url,
        subtitles={},
        is_live=False,
        http_headers={'User-Agent': USER_AGENT, 'Referer': 'https://reanime.to/'},
    )
