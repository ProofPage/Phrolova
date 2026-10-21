"""짭플릭스(zzap208.com) 영화·드라마·예능·애니 카탈로그 및 VOD 스트림 파서."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlsplit, urljoin

from app.core.http import USER_AGENT
from app.core.logger import get_media_logger
from app.engine.episode_sites import Document, EpisodeSiteError, SITES, SiteClient, checked_url

logger = get_media_logger('zzapflix')

CATEGORY_NAMES = {
    1: '영화',
    2: '드라마',
    39: '숏드',
    3: '예능',
    4: '애니',
}


def parse_zzapflix_url(value: str) -> dict:
    """Parse zzapflix URLs (e.g. https://zzap208.com/vodview.php?id=123692&idd=1)."""
    value = checked_url(value, SITES['zzapflix']['hosts'])
    parts = urlsplit(value)
    path = parts.path
    qs = parse_qs(parts.query)

    if 'vodview.php' in path or 'vodview' in path:
        work_id = qs.get('id', [None])[0]
        if not work_id:
            raise EpisodeSiteError('짭플릭스 작품 ID(id)가 누락되었습니다.')
        idd = qs.get('idd', [None])[0]
        is_collection = (idd is None)
        return {
            'site': 'zzapflix',
            'work': work_id,
            'episode': idd if idd is not None else '0',
            'url': value,
            'collection': is_collection,
        }

    if 'vodlist.php' in path or 'vodlist' in path:
        type_id = qs.get('type_id_1', [None])[0]
        cat_name = CATEGORY_NAMES.get(int(type_id)) if type_id and type_id.isdigit() else '전체'
        return {
            'site': 'zzapflix',
            'work': f'category_{type_id or "all"}',
            'episode': None,
            'category': type_id,
            'category_name': cat_name,
            'url': value,
            'collection': True,
        }

    match = re.search(r'/vodview/(\d+)(?:/(\d+))?', path)
    if match:
        work_id, ep_id = match.groups()
        return {
            'site': 'zzapflix',
            'work': work_id,
            'episode': ep_id or '0',
            'url': value,
            'collection': ep_id is None,
        }

    raise EpisodeSiteError('지원하는 짭플릭스(zzapflix) 주소를 입력하세요. (예: /vodview.php?id=123692)')


def load_zzapflix_catalog(url: str, client=None) -> dict:
    """Load episode list for a zzapflix title."""
    route = parse_zzapflix_url(url)
    own = client is None
    client = client or SiteClient()
    try:
        final, body = client.request(route['url'], SITES['zzapflix']['hosts'])
        target = parse_zzapflix_url(final)
        if target['work'] != route['work']:
            raise EpisodeSiteError('이동된 짭플릭스 작품 ID가 다릅니다.')
        doc = Document(body).root
        titles = doc.find('title')
        episodes = {}
        for link in doc.find('a', href=None):
            try:
                ep = parse_zzapflix_url(urljoin(final, link.attrs['href']))
            except EpisodeSiteError:
                continue
            if ep['work'] == route['work'] and not ep['collection'] and link.text.strip():
                episodes[ep['episode']] = dict(id=ep['episode'], number=None,
                    name=link.text.strip(), title=link.text.strip(), url=ep['url'], available=True)
        if not titles or not titles[0].text.strip() or not episodes:
            raise EpisodeSiteError('짭플릭스의 실제 작품·회차 목록을 확인할 수 없습니다.')
        return dict(id=route['work'], title=titles[0].text.strip(), episodes=list(episodes.values()))
    finally:
        if own:
            client.close()


def extract_zzapflix_episode(route: dict, client=None) -> dict:
    """Extract playback URL from zzapflix episode page."""
    view_url = route.get('url')
    if not view_url:
        raise EpisodeSiteError('실제 짭플릭스 회차 주소가 필요합니다.')
    parsed = parse_zzapflix_url(view_url)
    if parsed['collection'] or parsed['work'] != route['work'] or parsed['episode'] != route.get('episode'):
        raise EpisodeSiteError('짭플릭스 작품·회차 주소가 일치하지 않습니다.')
    own = client is None
    client = client or SiteClient()
    try:
        final, body = client.request(view_url, SITES['zzapflix']['hosts'])
        target = parse_zzapflix_url(final)
        if target['work'] != parsed['work'] or target['episode'] != parsed['episode']:
            raise EpisodeSiteError('이동된 짭플릭스 작품·회차가 다릅니다.')
        players = []
        for frame in Document(body).root.find('iframe', src=None):
            try:
                players.append(checked_url(urljoin(final, frame.attrs['src']), SITES['zzapflix']['players']))
            except EpisodeSiteError:
                continue
        if len(players) != 1:
            raise EpisodeSiteError('짭플릭스의 실제 본편 플레이어를 확인할 수 없습니다.')
        return dict(site='zzapflix', work=parsed['work'], episode=parsed['episode'],
            stream_url=players[0], is_embed=True, referer=final,
            headers={'User-Agent': USER_AGENT, 'Referer': final})
    finally:
        if own:
            client.close()
