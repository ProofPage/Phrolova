"""Observed public MissAV player and ordinary MPEG-TS HLS delivery."""
import re
from urllib.parse import urlsplit, urljoin

from yt_dlp.utils import decode_packed_codes

from app.engine.episode_sites import Document, EpisodeSiteError, checked_url
from app.core.http import USER_AGENT

SITE_HOSTS = ('missav123.com', 'www.missav123.com')
MEDIA_HOSTS = ('surrit.com',)


def parse_missav_url(value):
    value = checked_url(value, SITE_HOSTS, allow_ad_path=True)
    parts = urlsplit(value)
    match = re.fullmatch(r'/ko/([a-zA-Z0-9_-]+)/?', parts.path)
    if not match:
        raise EpisodeSiteError('MissAV 개별 영상 주소(/ko/{slug})를 입력하세요.')
    slug = match[1]
    return dict(site='missav', work=slug, episode=slug, collection=False,
                url=f'https://missav123.com/ko/{slug}')


def main_playlist(html):
    """Decode data substitution only; never execute packed JavaScript.

    Match the exact `source` assignment, not numbered quality variables,
    thumbnail videos, advertisements, or guessed playlist filenames.
    """
    sources = set()
    for script in Document(html).root.find('script'):
        text = script.text
        if 'eval(function(p,a,c,k,e,' not in text:
            continue
        try:
            text = decode_packed_codes(text)
        except (AttributeError, ValueError, IndexError, TypeError):
            continue
        # The observed unpacker output retains escaped quote delimiters.
        for match in re.finditer(r"(?:^|;)\s*source\s*=\s*\\?'([^'\\\s]+)\\?'\s*;", text):
            value = checked_url(match[1], MEDIA_HOSTS)
            parts = urlsplit(value)
            if parts.query or parts.fragment or not re.fullmatch(
                    r'/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/playlist\.m3u8',
                    parts.path):
                raise EpisodeSiteError('MissAV 본편 재생목록 경로를 확인할 수 없습니다.')
            sources.add(value)
    if len(sources) != 1:
        raise EpisodeSiteError('MissAV 본편 플레이어 설정을 확인할 수 없습니다.')
    return sources.pop()


def resource_url(value, identity, kind):
    value = checked_url(value, MEDIA_HOSTS)
    p = urlsplit(value)
    suffix = {'master': r'playlist\.m3u8', 'variant': r'\d+p/video\.m3u8',
              'segment': r'\d+p/video\d+\.jpeg'}.get(kind)
    if (not suffix or p.query or p.fragment or not re.fullmatch(
            '/' + re.escape(identity) + '/' + suffix, p.path)):
        raise EpisodeSiteError('MissAV 본편 리소스 경로를 확인할 수 없습니다.')
    return value


def extract_missav_episode(route, client):
    def same_page(value):
        if parse_missav_url(value)['url'] != route['url']:
            raise EpisodeSiteError('MissAV 요청한 영상과 이동한 영상이 다릅니다.')
        return value
    final, html = client.request(route['url'], SITE_HOSTS, validator=same_page)
    address = main_playlist(html)
    identity = urlsplit(address).path.split('/')[1]
    resources, playlists = {}, {}

    def load(url, kind):
        resource_url(url, identity, kind)
        _, text = client.request(url, MEDIA_HOSTS, referer=final,
                                 validator=lambda u: resource_url(u, identity, kind))
        if not text.startswith('#EXTM3U'):
            raise EpisodeSiteError('MissAV 정상 HLS 재생목록이 아닙니다.')
        # No observed encryption or ad-interstitial protocol. Fail closed.
        if re.search(r'^#.*(?:KEY:|URI=|CUE|DATERANGE|SCTE|BYTERANGE)', text, re.M | re.I):
            raise EpisodeSiteError('MissAV 광고·암호화 또는 지원하지 않는 재생목록입니다.')
        refs = [urljoin(url, x.strip()) for x in text.splitlines() if x.strip() and not x.startswith('#')]
        if not refs or len(refs) > 10000:
            raise EpisodeSiteError('MissAV 비어 있거나 너무 큰 재생목록입니다.')
        resources[url], playlists[url] = kind, text
        for ref in refs:
            resource_url(ref, identity, 'variant' if kind == 'master' else 'segment')
        if kind == 'master':
            if '#EXT-X-STREAM-INF:' not in text or len(refs) > 16:
                raise EpisodeSiteError('MissAV 화질 재생목록을 확인할 수 없습니다.')
            for ref in set(refs):
                load(ref, 'variant')
        else:
            if '#EXT-X-ENDLIST' not in text or '#EXT-X-STREAM-INF:' in text:
                raise EpisodeSiteError('MissAV 종료된 본편 영상이 아닙니다.')
            resources.update(dict.fromkeys(refs, 'segment'))
        return text

    manifest = load(address, 'master')
    doc = Document(html).root
    titles = doc.find('meta', property='og:title')
    title = titles[0].attrs.get('content', '').strip() if titles else ''
    title = title or next((n.text.strip() for n in doc.find('title') if n.text.strip()), '')
    if not title:
        raise EpisodeSiteError('MissAV 영상 제목을 확인할 수 없습니다.')
    return dict(id=route['episode'], title=title, site='missav', url=address,
                webpage_url=route['url'], manifest=manifest, subtitles={},
                http_headers={'User-Agent': USER_AGENT, 'Referer': final},
                _missav_delivery=dict(identity=identity, resources=resources,
                                      playlists=playlists, referer=final))
