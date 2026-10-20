"""애니위크(aniweek.com) 작품 카탈로그 및 스트림 파서."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote, unquote, urlsplit

from app.core.http import USER_AGENT
from app.core.logger import get_media_logger
from app.engine.episode_sites import EpisodeSiteError, SITES, checked_url, SiteClient
from app.engine.tls_compat import enable_tls_compat

logger = get_media_logger('aniweek')


def parse_aniweek_url(value: str) -> dict:
    """Parse aniweek URLs (e.g. https://aniweek.com/c/작품명 or /e/회차명)."""
    value = checked_url(value, SITES['aniweek']['hosts'])
    parts = urlsplit(value)
    path = parts.path

    match_c = re.fullmatch(r'/c/([^/?#]+)/?', path)
    if match_c:
        work = unquote(match_c.group(1)).strip()
        return {
            'site': 'aniweek',
            'work': work,
            'episode': None,
            'url': f'https://aniweek.com/c/{quote(work)}',
            'collection': True,
        }

    match_e = re.fullmatch(r'/e/([^/?#]+)/?', path)
    if match_e:
        ep_slug = unquote(match_e.group(1)).strip()
        return {
            'site': 'aniweek',
            'work': ep_slug,
            'episode': ep_slug,
            'url': f'https://aniweek.com/e/{quote(ep_slug)}',
            'collection': False,
        }

    raise EpisodeSiteError('지원하는 애니위크(aniweek) 주소를 입력하세요. (예: /c/{작품명} 또는 /e/{회차명})')


def load_aniweek_catalog(url: str, client: Optional[SiteClient] = None) -> dict:
    """Load episode list from aniweek /c/ page using Inertia SSR JSON."""
    route = parse_aniweek_url(url)
    work = route['work']
    work_url = f'https://aniweek.com/c/{quote(work)}'

    own = client is None
    c = client or SiteClient()
    try:
        enable_tls_compat(c.http, 'aniweek.com')
        final, body = c.request(work_url, SITES['aniweek']['hosts'], referer='https://aniweek.com/')

        # Extract Inertia page props
        m_app = re.search(r'<script data-page="app" type="application/json">(.*?)</script>', body, re.DOTALL)
        episodes = []
        title = work

        if m_app:
            try:
                page_data = json.loads(m_app.group(1))
                props = page_data.get('props', {})
                content = props.get('content') or {}
                if content.get('title'):
                    title = content['title']

                ep_list = props.get('episodes', {}).get('data', [])
                for idx, ep_item in enumerate(ep_list):
                    ep_name = ep_item.get('title') or f'{idx + 1}화'
                    body_obj = ep_item.get('body') or {}
                    raw_player_url = body_obj.get('url') or ''
                    m_num = re.search(r'(\d+)', ep_name)
                    ep_num = int(m_num.group(1)) if m_num else idx + 1

                    episodes.append({
                        'id': str(ep_item.get('id') or idx),
                        'number': ep_num,
                        'name': ep_name,
                        'url': f'https://aniweek.com/e/{quote(work + " " + ep_name)}',
                        'player_url': raw_player_url,
                        'available': True,
                    })
            except Exception as e:
                logger.debug(f'Aniweek Inertia parsing failed: {e}')

        # Order 1화 -> 최신화
        if len(episodes) > 1 and episodes[0]['number'] > episodes[-1]['number']:
            episodes.reverse()

        return {
            'id': work,
            'title': title,
            'episodes': episodes,
        }
    finally:
        if own:
            c.close()


def extract_aniweek_episode(route: dict, client: Optional[SiteClient] = None) -> dict:
    """Extract michealcdn / cdndania playback URL from aniweek episode page."""
    ep_url = route['url']
    own = client is None
    c = client or SiteClient()
    try:
        enable_tls_compat(c.http, 'aniweek.com')
        final, body = c.request(ep_url, SITES['aniweek']['hosts'], referer='https://aniweek.com/')

        # 1. Inertia JSON lookup
        m_app = re.search(r'<script data-page="app" type="application/json">(.*?)</script>', body, re.DOTALL)
        if m_app:
            try:
                page_data = json.loads(m_app.group(1))
                props = page_data.get('props', {})
                playing = props.get('playing') or {}
                body_obj = playing.get('body') or {}
                raw_player = body_obj.get('url')
                if raw_player:
                    return {
                        'site': 'aniweek',
                        'work': route['work'],
                        'episode': route.get('episode') or '1',
                        'stream_url': raw_player,
                        'is_embed': True,
                        'referer': ep_url,
                        'headers': {
                            'User-Agent': USER_AGENT,
                            'Referer': 'https://aniweek.com/',
                        },
                    }
            except Exception:
                pass

        # 2. Regex fallback for michealcdn / cdndania iframe
        m_player = re.search(r'(https://(?:michealcdn\.com|cdndania\.com)/video/[A-Za-z0-9]+)', body)
        if m_player:
            return {
                'site': 'aniweek',
                'work': route['work'],
                'episode': route.get('episode') or '1',
                'stream_url': m_player.group(1),
                'is_embed': True,
                'referer': ep_url,
                'headers': {
                    'User-Agent': USER_AGENT,
                    'Referer': 'https://aniweek.com/',
                },
            }

        raise EpisodeSiteError('애니위크 영상 플레이어(michealcdn) 주소를 확인할 수 없습니다.')
    finally:
        if own:
            c.close()
