"""Bilibili 단축 주소를 검증된 동영상 경로로 한정해서 해석한다."""
from urllib.parse import urljoin, urlsplit

import httpx

from app.core.http import USER_AGENT


async def resolve_bilibili_video_url(value: str) -> str:
    from app.engine.bilibili import canonical_bilibili_video_url

    url = canonical_bilibili_video_url(value)
    if urlsplit(url).hostname != 'b23.tv':
        return url
    # 단축 주소가 내부 주소나 다른 서비스로 이동해도 추출기로 넘기지 않는다.
    async with httpx.AsyncClient(timeout=12, follow_redirects=False,
                                  headers={'User-Agent': USER_AGENT}) as client:
        for _ in range(4):
            async with client.stream('GET', url) as response:
                if not response.is_redirect:
                    response.raise_for_status()
                    raise ValueError('Bilibili 단축 주소의 동영상 이동 경로를 확인하지 못했습니다.')
                target = urljoin(url, response.headers.get('location', ''))
                url = canonical_bilibili_video_url(target)
            if urlsplit(url).hostname != 'b23.tv':
                return url
    raise ValueError('Bilibili 단축 주소의 이동 횟수를 초과했습니다.')
