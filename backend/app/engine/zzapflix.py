"""짭플릭스(zzap208.com) 영화·드라마·예능·애니 카탈로그 및 VOD 스트림 파서."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlsplit

from app.core.http import USER_AGENT
from app.core.logger import get_media_logger
from app.engine.episode_sites import EpisodeSiteError, SITES, checked_url

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
    work_id = route['work']

    # Standard episode schema
    episodes = [
        {
            'id': f'{work_id}_0',
            'number': 1,
            'name': '1화',
            'url': f'https://zzap208.com/vodview.php?id={work_id}&idd=0',
            'available': True,
        }
    ]

    return {
        'id': work_id,
        'title': f'짭플릭스 작품 #{work_id}',
        'episodes': episodes,
    }


def extract_zzapflix_episode(route: dict, client=None) -> dict:
    """Extract playback URL from zzapflix episode page."""
    work_id = route['work']
    idd = route.get('episode') or '0'
    view_url = f'https://zzap208.com/vodview.php?id={work_id}&idd={idd}'

    # Wiselife blog embed player
    player_url = f'https://ckp2.wiselife.blog/player.php?id={work_id}&idd={idd}'

    return {
        'site': 'zzapflix',
        'work': work_id,
        'episode': idd,
        'stream_url': player_url,
        'is_embed': True,
        'referer': view_url,
        'headers': {
            'User-Agent': USER_AGENT,
            'Referer': 'https://zzap208.com/',
        },
    }
