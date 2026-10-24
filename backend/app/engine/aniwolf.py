"""애니울프(aniwolf.com) 작품 카탈로그 및 스트림 파서."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import unquote, urlsplit

from app.core.http import USER_AGENT
from app.core.logger import get_media_logger
from app.engine.episode_sites import EpisodeSiteError, SITES, checked_url, SiteClient
from app.engine.tls_compat import enable_tls_compat

logger = get_media_logger('aniwolf')


def parse_aniwolf_url(value: str) -> dict:
    """Parse aniwolf URLs (e.g. https://aniwolf.com/작품제목 or /작품제목/1화)."""
    value = checked_url(value, SITES['aniwolf']['hosts'])
    parts = urlsplit(value)
    path = unquote(parts.path).strip('/')

    if not path:
        raise EpisodeSiteError('애니울프 메인 주소입니다. 작품 상세 주소를 입력하세요.')

    segments = [s for s in path.split('/') if s]
    if len(segments) == 1:
        work = segments[0]
        return {
            'site': 'aniwolf',
            'work': work,
            'episode': None,
            'url': f'https://aniwolf.com/{work}',
            'collection': True,
        }
    elif len(segments) >= 2:
        work = segments[0]
        ep = segments[1]
        return {
            'site': 'aniwolf',
            'work': work,
            'episode': ep,
            'url': f'https://aniwolf.com/{work}/{ep}',
            'collection': False,
        }

    raise EpisodeSiteError('지원하지 않는 애니울프 주소 형식입니다.')


def load_aniwolf_catalog(url: str, client: Optional[SiteClient] = None) -> dict:
    """Load episode list from aniwolf work page."""
    route = parse_aniwolf_url(url)
    work = route['work']
    work_url = f'https://aniwolf.com/{work}'

    own = client is None
    c = client or SiteClient()
    try:
        enable_tls_compat(c.http, 'aniwolf.com')
        final, body = c.request(work_url, SITES['aniwolf']['hosts'])
        
        # Parse episode links
        ep_links = re.findall(r'href="([^"]+/' + re.escape(work) + r'/([^"]+))"[^>]*>\s*([^<]+)\s*</a>', body)
        episodes = []
        for full_href, ep_slug, ep_title in ep_links:
            ep_slug_decoded = unquote(ep_slug).strip()
            ep_title_clean = ep_title.strip()
            m_num = re.search(r'(\d+)', ep_slug_decoded)
            ep_num = int(m_num.group(1)) if m_num else 1
            episodes.append({
                'id': ep_slug_decoded,
                'number': ep_num,
                'name': ep_title_clean,
                'url': full_href if full_href.startswith('http') else f'https://aniwolf.com/{work}/{ep_slug}',
                'available': True,
            })

        # Reverse if newest first
        if len(episodes) > 1 and episodes[0]['number'] > episodes[-1]['number']:
            episodes.reverse()

        return {
            'id': work,
            'title': unquote(work).replace('_', ' '),
            'episodes': episodes,
        }
    finally:
        if own:
            c.close()


def extract_aniwolf_episode(route: dict, client: Optional[SiteClient] = None) -> dict:
    """Extract playback cdndania player URL from aniwolf episode page."""
    ep_url = route['url']
    own = client is None
    c = client or SiteClient()
    try:
        enable_tls_compat(c.http, 'aniwolf.com')
        final, body = c.request(ep_url, SITES['aniwolf']['hosts'], referer='https://aniwolf.com/')

        # Find iframe player (cdndania.com or michealcdn.com)
        m_iframe = re.search(r'<iframe[^>]*src="([^"]*(?:cdndania|michealcdn)\.com/video/[^"]+)"', body)
        if not m_iframe:
            # Fallback any video iframe
            m_iframe = re.search(r'<iframe[^>]*src="([^"]*(?:cdndania|michealcdn)[^"]*)"', body)

        if not m_iframe:
            raise EpisodeSiteError('애니울프 영상 플레이어(cdndania) 링크를 확인할 수 없습니다.')

        player_url = m_iframe.group(1)
        if player_url.startswith('//'):
            player_url = 'https:' + player_url

        return {
            'site': 'aniwolf',
            'work': route['work'],
            'episode': route.get('episode') or '1',
            'stream_url': player_url,
            'is_embed': True,
            'referer': ep_url,
            'headers': {
                'User-Agent': USER_AGENT,
                'Referer': 'https://aniwolf.com/',
            },
        }
    finally:
        if own:
            c.close()
