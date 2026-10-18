"""Use CHZZK's advertised AES HLS, not an unsupported SEA DASH download."""

from urllib.parse import urlsplit

from yt_dlp.extractor.chzzk import CHZZKVideoIE as UpstreamCHZZKVideoIE
from yt_dlp.utils import ExtractorError

from app.engine.chzzk_time_machine import _is_trusted_media_url


class CHZZKVideoIE(UpstreamCHZZKVideoIE):
    # Keep the upstream IE key so a per-instance registration replaces only
    # CHZZK VOD extraction, including metadata/quality discovery.
    def _real_extract(self, url):
        self._aes_video = False
        return super()._real_extract(url)

    def _download_json(self, url_or_request, video_id, *args, **kwargs):
        result = super()._download_json(url_or_request, video_id, *args, **kwargs)
        if url_or_request == f"https://api.chzzk.naver.com/service/v3/videos/{video_id}":
            self._aes_video = (result.get("content") or {}).get("encryptionType") == "AES"
        return result

    def _extract_mpd_formats_and_subtitles(self, mpd_url, video_id, *args, **kwargs):
        if not self._aes_video:
            return super()._extract_mpd_formats_and_subtitles(mpd_url, video_id, *args, **kwargs)
        # The official player uses this playback endpoint for encryptionType=AES.
        # The returned namespaced m3u attribute is the platform's HLS URL; do
        # not synthesize CDN paths or try to remove DASH protection metadata.
        playback_id = urlsplit(mpd_url).path.rsplit("/", 1)[-1]
        mpd = self._download_xml(
            f"https://play.vod.naver.com/v3/playback/{playback_id}",
            video_id,
            query={**kwargs.get("query", {}), "sid": "2099", "devt": "html5_pc"},
            headers={"Accept": "application/xml", "Referer": "https://chzzk.naver.com/"},
        )
        ns = {"mpd": "urn:mpeg:dash:schema:mpd:2011",
              "sea": "urn:mpeg:dash:schema:sea:2012"}
        formats, subtitles = [], {}
        playlists = set()
        for adaptation in mpd.findall(".//mpd:AdaptationSet", ns):
            encryption = adaptation.findall(".//sea:SegmentEncryption", ns)
            if not encryption or any(
                item.get("encryptionSystemUrn") != "urn:mpeg:dash:sea:aes128-cbc:2013"
                for item in encryption
            ):
                continue
            advertised = adaptation.get("{urn:naver:vod:2020}m3u")
            urls = [advertised] if advertised else [
                item.get("{urn:naver:vod:2020}m3u")
                for item in adaptation.findall("mpd:Representation", ns)
            ]
            for url in urls:
                if not url or url in playlists or not _is_trusted_media_url(url):
                    continue
                playlists.add(url)
                found, subs = self._extract_m3u8_formats_and_subtitles(
                    url, video_id, "mp4", "m3u8_native", m3u8_id="hls-aes",
                    headers={"Referer": "https://chzzk.naver.com/"},
                )
                formats.extend(found)
                self._merge_subtitles(subs, target=subtitles)
        if not formats:
            raise ExtractorError(
                "치지직이 지원되는 AES-128 HLS 재생 주소를 제공하지 않았습니다.",
                expected=True, video_id=video_id,
            )
        # The cookie jar authenticates the key API on api.chzzk.naver.com.
        # Never put Naver Cookie headers or AES keys into format metadata.
        return formats, subtitles
