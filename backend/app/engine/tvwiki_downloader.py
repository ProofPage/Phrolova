"""Retry advertised TVWiki HLS resources on their issuing media server."""
from urllib.parse import urlsplit, urlunsplit

import yt_dlp
from yt_dlp.networking import Request
from yt_dlp.networking.exceptions import HTTPError

from app.engine.episode_sites import SITES, checked_url, EpisodeSiteError


class TVWikiYoutubeDL(yt_dlp.YoutubeDL):
    def __init__(self, *args, **kwargs):
        self._tvwiki_origin = None
        self._tvwiki_resources = set()
        self._tvwiki_failed_hosts = set()
        super().__init__(*args, **kwargs)

    def process_ie_result(self, ie_result, *args, **kwargs):
        delivery = ie_result.get('_tvwiki_delivery')
        if isinstance(delivery, dict):
            origin, resources = delivery.get('origin'), delivery.get('resources')
            try:
                checked_url(origin, SITES['tvwiki']['media'], subdomains=True)
                parts = urlsplit(origin)
                if parts.path not in ('', '/') or parts.query or parts.fragment:
                    raise EpisodeSiteError('영상 원본 서버 주소가 올바르지 않습니다.')
                if not isinstance(resources, list) or len(resources) > 10000:
                    raise EpisodeSiteError('영상 조각 목록이 올바르지 않습니다.')
                allowed = {Request(checked_url(url, SITES['tvwiki']['media'], subdomains=True)).url for url in resources}
            except (ValueError, TypeError):
                raise ValueError('티비위키 원본 서버·영상 조각 정보를 확인할 수 없습니다.') from None
            self._tvwiki_origin = urlunsplit((parts.scheme, parts.netloc, '', '', ''))
            self._tvwiki_resources = allowed
        return super().process_ie_result(ie_result, *args, **kwargs)

    def urlopen(self, request):
        if not isinstance(request, Request):
            return super().urlopen(request)
        parts = urlsplit(request.url)
        alternate = None
        if (request.method == 'GET' and request.data is None and self._tvwiki_origin
                and request.url in self._tvwiki_resources
                and parts.netloc != urlsplit(self._tvwiki_origin).netloc):
            alternate = request.copy()
            alternate.url = self._tvwiki_origin + urlunsplit(('', '', parts.path, parts.query, ''))
            alternate.headers = {key:value for key,value in request.headers.items()
                                 if key.lower() not in ('cookie', 'authorization', 'host')}
        if alternate is not None and parts.hostname in self._tvwiki_failed_hosts:
            return super().urlopen(alternate)
        try:
            return super().urlopen(request)
        except HTTPError as error:
            if alternate is None or error.status not in (403, 404, 410, 500, 502, 503, 504):
                raise
            error.close()
            if parts.hostname not in self._tvwiki_failed_hosts:
                self.to_screen('티비위키 CDN 조각 연결 실패 · 해당 영상의 원본 서버로 재시도합니다.')
                self._tvwiki_failed_hosts.add(parts.hostname)
            return super().urlopen(alternate)
