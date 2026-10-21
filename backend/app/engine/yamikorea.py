"""YamiKorea public single-video pages; no listing or advertising extraction."""
import re
from urllib.parse import quote, unquote, urljoin, urlsplit

from app.core.http import USER_AGENT
from app.engine.episode_sites import Document, EpisodeSiteError, SITES, checked_url


def parse_yamikorea_url(value):
    value = checked_url(value, SITES['yamikorea']['hosts'])
    parts = urlsplit(value)
    path = unquote(parts.path)
    match = re.fullmatch(r'/videos/([^/]+)/?', path)
    if not match or match[1] in ('.', '..') or any(c in path for c in '?#%'):
        raise EpisodeSiteError('YamiKorea 개별 영상 주소(/videos/{slug}/)를 입력하세요.')
    slug = match[1]
    return dict(site='yamikorea', work=slug, episode=slug, collection=False,
                url=f'https://ym-05.com/videos/{quote(slug, safe="-_")}/')


def _media_url(value):
    value = checked_url(value, ('media.ym-05.com',))
    path = unquote(urlsplit(value).path)
    if not re.fullmatch(r'/data/file/videos/[^/]+\.mp4', path) or any(
            part in ('.', '..') for part in path.split('/')):
        raise EpisodeSiteError('YamiKorea 본편 MP4 주소를 확인할 수 없습니다.')
    return value


def extract_yamikorea_episode(route, client):
    final, html = client.request(route['url'], SITES['yamikorea']['hosts'])
    if parse_yamikorea_url(final)['url'] != route['url']:
        raise EpisodeSiteError('요청한 YamiKorea 영상과 이동한 영상이 다릅니다.')
    doc = Document(html).root
    sources = set()
    for video in doc.find('video'):
        for node in [video, *video.find('source')]:
            value = node.attrs.get('src')
            if not value:
                continue
            # Only native video sources in the observed main-media directory.
            try:
                sources.add(_media_url(urljoin(final, value)))
            except EpisodeSiteError:
                continue
    if len(sources) != 1:
        raise EpisodeSiteError('YamiKorea 본편 영상을 확인할 수 없습니다. 사이트 접속 상태를 확인하세요.')
    media = sources.pop()
    resolved, prefix = client.request(media, ('media.ym-05.com',), referer=final,
                                      binary=True, prefix_bytes=32,
                                      headers={'Range': 'bytes=0-31'})
    if _media_url(resolved) != media or not isinstance(prefix, bytes) or len(prefix) < 12 or prefix[4:8] != b'ftyp':
        raise EpisodeSiteError('YamiKorea MP4 응답을 확인할 수 없습니다.')
    titles = doc.find('meta', property='og:title')
    title = titles[0].attrs.get('content', '').strip() if titles else ''
    if not title:
        title = next((node.text.strip() for node in doc.find('title') if node.text.strip()), '')
    if not title:
        raise EpisodeSiteError('YamiKorea 영상 제목을 확인할 수 없습니다.')
    return dict(id=route['episode'], title=title, url=media, ext='mp4', format_id='original',
                site='yamikorea', webpage_url=route['url'], subtitles={},
                http_headers={'User-Agent': USER_AGENT, 'Referer': final})
