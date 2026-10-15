"""회차 추출만 맡고 전송·재시도·검사는 기존 yt-dlp 파이프라인에 맡긴다."""
from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.utils import ExtractorError

from app.engine.episode_sites import EpisodeSiteError, SiteClient, extract_episode


class EpisodeSiteIE(InfoExtractor):
    IE_NAME = 'phrolova:episodes'
    _VALID_URL = r'https://(?:anilife(?:01|1)\.tv/content/\d+/(?:[A-Za-z0-9_-]+|\d+\.\d+)|linkani\.tv/watch/\d+/a\d+/k\d+/?|tvwiki54\.net/(?:movie|kor_movie|drama|ent|sisa|world|ott_ent|short_drama|ani_movie|animation|old_ent|old_drama)/[1-9]\d*/[1-9]\d*/?|(?:www\.)?ohli24\.net/\d+/[^/?#]+\.html)(?:[?#].*)?$'

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
        formats, manifest_subtitles = self._parse_m3u8_formats_and_subtitles(
            item.pop('manifest'), item['url'], ext='mp4', entry_protocol='m3u8_native',
            m3u8_id='hls', headers=item['http_headers'], video_id=item['id'])
        if not formats:
            raise ExtractorError('회차 영상에서 사용 가능한 화질을 찾지 못했습니다.', expected=True)
        for fmt in formats:
            fmt['http_headers'] = item['http_headers']
        item['subtitles'] = self._merge_subtitles(manifest_subtitles, item['subtitles'])
        item['formats'] = formats
        item.pop('url')
        return item
