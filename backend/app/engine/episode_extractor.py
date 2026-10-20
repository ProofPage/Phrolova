"""회차 추출만 맡고 전송·재시도·검사는 기존 yt-dlp 파이프라인에 맡긴다."""
from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.utils import ExtractorError

from app.core.episode_domains import NUMBERED_SITE_HOSTS
from app.engine.episode_sites import EpisodeSiteError, SiteClient, extract_episode, parse_episode_url


class EpisodeSiteIE(InfoExtractor):
    IE_NAME = 'phrolova:episodes'
    _VALID_URL = (
        rf'https://(?:{NUMBERED_SITE_HOSTS["anilife"].pattern}/content/\d+/(?:[A-Za-z0-9_-]+|\d+\.\d+)'
        r'|linkani\.tv/watch/\d+/a\d+/k\d+/?'
        rf'|{NUMBERED_SITE_HOSTS["tvwiki"].pattern}/(?:movie|kor_movie|drama|ent|sisa|world|ott_ent|short_drama|ani_movie|animation|old_ent|old_drama)/[1-9]\d*/[1-9]\d*/?'
        rf'|{NUMBERED_SITE_HOSTS["animaru"].pattern}/contents?/[1-9]\d*/(?:0|[1-9]\d*)(?:\.\d+)?/?'
        r'|(?:www\.)?moeni\.net/[1-9]\d*/[1-9]\d*(?:\.\d+)?/?'
        r'|(?:www\.)?reanime\.to/watch/[a-zA-Z0-9_-]+(?:\?ep=\d+)?/?'
        r'|(?:(?:v2|www)\.)?ohli365\.org/\?title=[0-9a-f-]+&episode=(?:[0-9a-f-]+|movie)'
        r'|(?:(?:ani|www)\.)?ohli24\.(?:net|com)/(?:(?:\d+/[^/?#]+\.html)|(?:[ce]/[^/?#]+)))(?:[?#].*)?$'
    )

    @classmethod
    def suitable(cls, url):
        # Use the same parsed hostname and path checks as catalog/preparation.
        try:
            route = parse_episode_url(url)
            return not route['collection'] or route['site'] == 'ohli24'
        except EpisodeSiteError:
            return False

    def _real_extract(self, url):
        client = SiteClient()
        try:
            item = extract_episode(url, client)
            # 정상 플레이어 발급 응답의 세션을 같은 작업의 조각 전송에도 유지한다.
            for cookie in client.http.cookies.jar:
                self._downloader.cookiejar.set_cookie(cookie)
        except EpisodeSiteError as error:
            raise ExtractorError(str(error), expected=True) from None
        finally:
            client.close()
        if 'manifest' not in item:
            # A direct MP4 has already passed the site adapter's bounded probe.
            direct = {key: item.pop(key) for key in ('url', 'ext', 'format_id') if key in item}
            direct['http_headers'] = item['http_headers']
            item['formats'] = [direct]
            return item
        checked_playlists = item.pop('_ohli365_playlists', None)
        formats, manifest_subtitles = self._parse_m3u8_formats_and_subtitles(
            item.pop('manifest'), item['url'], ext='mp4', entry_protocol='m3u8_native',
            m3u8_id='hls', headers=item['http_headers'], video_id=item['id'])
        if not formats:
            raise ExtractorError('회차 영상에서 사용 가능한 화질을 찾지 못했습니다.', expected=True)
        for fmt in formats:
            fmt['http_headers'] = item['http_headers']
            if checked_playlists is not None:
                body = checked_playlists.get(fmt['url'])
                if not isinstance(body, str) or '#EXT-X-ENDLIST' not in body:
                    raise ExtractorError('애니365 화질의 검증된 재생목록이 없습니다.', expected=True)
                fmt['hls_media_playlist_data'] = body
        item['subtitles'] = self._merge_subtitles(manifest_subtitles, item['subtitles'])
        item['formats'] = formats
        item.pop('url')
        return item
