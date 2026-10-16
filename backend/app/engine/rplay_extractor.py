"""Download only media explicitly granted by RPLAY's content API."""
from urllib.parse import urlsplit

from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.utils import ExtractorError, float_or_none, int_or_none, unified_timestamp

from app.engine.rplay import ORIGIN, canonical_rplay_video_url, valid_media_url, video_metadata


class RplayIE(InfoExtractor):
    IE_NAME = 'rplay'
    _VALID_URL = r'https?://(?:www\.)?rplay\.live/play/(?P<id>[a-fA-F0-9]{24})(?:[/?#]|$)'

    def _real_extract(self, url):
        canonical = canonical_rplay_video_url(url)
        item = video_metadata(canonical)
        oid = item['_id']
        media = item['canView']['url']
        headers = {'Origin': ORIGIN, 'Referer': canonical}
        path = urlsplit(media).path.lower()
        if path.endswith('.m3u8') or path.startswith('/content/hlsstream'):
            formats = self._extract_m3u8_formats(media, oid, 'mp4', entry_protocol='m3u8_native', headers=headers)
        elif path.endswith('.mpd'):
            formats = self._extract_mpd_formats(media, oid, headers=headers)
        elif path.endswith('.mp4'):
            formats = [{'url': media, 'format_id': 'source', 'ext': 'mp4', 'http_headers': headers}]
            streams = item.get('streamables') or []
            video = next((s for s in streams if isinstance(s, dict) and str(s.get('type', '')).startswith('video/')), {})
            formats[0].update(width=int_or_none(video.get('width')), height=int_or_none(video.get('height')))
        else:
            raise ExtractorError('알플레이 재생 형식을 지원하지 않습니다.', expected=True)
        if not formats or any(not valid_media_url(f.get('url')) or f.get('has_drm') for f in formats):
            raise ExtractorError('알플레이 재생 주소 또는 보호 방식을 지원하지 않습니다.', expected=True)
        # Never put API headers, the account identity, or session data in returned media info.
        creator = item.get('creatorInfo') if isinstance(item.get('creatorInfo'), dict) else {}
        return {'id': oid, 'title': item.get('title') or f'RPLAY {oid}', 'webpage_url': canonical,
                'original_url': canonical, 'is_live': False, 'formats': formats, 'http_headers': headers,
                'duration': float_or_none(item.get('length')), 'uploader': item.get('nickname') or creator.get('nickname'),
                'thumbnail': f'https://pb3.rplay.live/thumbnail/{oid}',
                'channel_id': item.get('creatorOid'), 'timestamp': unified_timestamp(item.get('publishedAt')),
                'view_count': int_or_none(item.get('views')), 'age_limit': 19 if item.get('isAdultContent') else 0}
