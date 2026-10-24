"""Authorized Berriz replay downloads; DRM is never enabled."""
from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.utils import ExtractorError

from app.engine.berriz import API, HEADERS


class BerrizIE(InfoExtractor):
    _VALID_URL = r'https?://berriz\.in/(?:[a-z]{2}(?:-[A-Z]{2})?/)?[^/]+/live/replay/(?P<id>[a-fA-F0-9-]{36})/?(?:[?#].*)?$'

    def _real_extract(self, url):
        media_id = self._match_id(url)
        payload = self._download_json(API + f"/medias/live/replay/{media_id}/playback_info",
                                      media_id, headers=HEADERS, query={"languageCode": "ko"})
        if payload.get("code") != "0000":
            raise ExtractorError("베리즈 다시보기의 시청 권한을 확인하세요.", expected=True)
        replay = payload.get("data", {}).get("replay", {})
        if replay.get("isDrm") is not False or replay.get("drmInfo"):
            raise ExtractorError("베리즈 DRM 다시보기는 지원하지 않습니다.", expected=True)
        media = replay.get("hls", {}).get("playbackUrl")
        from urllib.parse import urlsplit
        parsed = urlsplit(media or "")
        if (parsed.scheme != "https" or parsed.hostname != "statics.berriz.in"
                or parsed.username or parsed.password or parsed.port not in (None, 443)
                or not parsed.path.endswith(".m3u8") or any(c in media for c in "\r\n\\")):
            raise ExtractorError("베리즈 HLS 재생 주소를 확인하지 못했습니다.", expected=True)
        formats = self._extract_m3u8_formats(media, media_id, "mp4", headers=HEADERS)
        return {"id": media_id, "title": media_id, "duration": replay.get("duration"),
                "formats": formats, "http_headers": dict(HEADERS)}
