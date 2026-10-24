"""yt-dlp custom InfoExtractor for HearHeart (hearheart.com)."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.utils import ExtractorError, clean_html, get_element_by_attribute

from app.engine.hearheart import canonical_hearheart_video_url, hearheart_headers
from app.engine.platform_auth import PlatformAuthenticationError, platform_cookie_jar


class HearHeartIE(InfoExtractor):
    IE_NAME = "hearheart"
    _VALID_URL = r"https?://(?:www\.)?hearheart\.com/playlist/(?P<playlist_id>\d+)(?:/play/(?P<id>\d+))?"

    def _real_initialize(self):
        jar = platform_cookie_jar("hearheart")
        if jar:
            for cookie in jar:
                self._downloader.cookiejar.set_cookie(cookie)

    def _real_extract(self, url):
        canonical = canonical_hearheart_video_url(url)
        match = re.match(self._VALID_URL, canonical)
        playlist_id = match.group("playlist_id")
        content_id = match.group("id")

        headers = hearheart_headers(canonical)

        # 회차 ID 없이 플레이리스트 페이지만 전달된 경우
        if not content_id:
            return self._extract_playlist(canonical, playlist_id, headers)

        return self._extract_episode(canonical, playlist_id, content_id, headers)

    def _extract_playlist(self, url: str, playlist_id: str, headers: dict[str, str]):
        webpage = self._download_webpage(url, playlist_id, headers=headers)
        
        # 성인인증 게이트로 리다이렉트되었는지 확인
        if "성인인증 - 히어하트" in webpage or "/auth/adult-gate" in webpage:
            raise ExtractorError(
                "히어하트 성인인증 또는 로그인이 필요합니다. 설정에서 히어하트 쿠키를 등록하세요.",
                expected=True,
            )

        # 플레이리스트 내 회차 링크 추출 (순서 보존)
        episode_ids = []
        pattern = re.compile(rf"/playlist/{playlist_id}/play/(\d+)")
        for ep_id in pattern.findall(webpage):
            if ep_id not in episode_ids:
                episode_ids.append(ep_id)

        if not episode_ids:
            # 회차가 1개만 있거나 바로 첫 회차로 리다이렉트되는 경우
            first_ep_match = re.search(r"/playlist/\d+/play/(\d+)", webpage)
            if first_ep_match:
                episode_ids.append(first_ep_match.group(1))

        if not episode_ids:
            raise ExtractorError("히어하트 플레이리스트에서 회차를 찾을 수 없습니다.", expected=True)

        title = self._og_search_title(webpage, default=None) or self._html_search_regex(
            r"<title>([^<]+)</title>", webpage, "title", default=f"히어하트 플레이리스트 {playlist_id}"
        )
        title = re.sub(r"^히어하트\s*-\s*", "", title).strip()

        uploader = None
        m_creator = re.search(r'''<a[^>]+href=['"](?:https?://hearheart\.com)?/channel/(\d+)['"][^>]*>([^<]+)</a>''', webpage)
        if m_creator:
            uploader = clean_html(m_creator.group(2)).strip()
        elif " - " in title:
            parts = title.rsplit(" - ", 1)
            if len(parts) == 2 and len(parts[1].strip()) <= 30:
                uploader = parts[1].strip()
                title = parts[0].strip()

        entries = [
            self.url_result(
                f"https://hearheart.com/playlist/{playlist_id}/play/{ep_id}",
                ie=HearHeartIE.ie_key(),
                video_id=ep_id,
            )
            for ep_id in episode_ids
        ]

        return self.playlist_result(entries, playlist_id=playlist_id, playlist_title=title, playlist_uploader=uploader)

    def _extract_episode(self, url: str, playlist_id: str, content_id: str, headers: dict[str, str]):
        webpage = self._download_webpage(url, content_id, headers=headers)

        if "성인인증 - 히어하트" in webpage or "/auth/adult-gate" in webpage:
            raise ExtractorError(
                "히어하트 성인인증 또는 로그인이 필요합니다. 설정에서 히어하트 쿠키를 등록하세요.",
                expected=True,
            )

        # streamUrl 추출:
        # 1. videoPlayer 컴포넌트의 streamUrl (HTML 이스케이프 \/ 및 \u0026 정규화)
        # 2. lockedPreview 컴포넌트의 previewStreamUrl
        # 3. 직접 src 속성 또는 m3u8 주소
        stream_url = None

        m_stream = re.search(r"streamUrl\s*:\s*(?:&#039;|'|\")([^'\"&]+(?:\.m3u8|\.mp4)[^'\"]*)(?:&#039;|'|\")", webpage)
        if not m_stream:
            m_stream = re.search(r"streamUrl\s*:\s*(?:&#039;|'|\")([^'\"]+)(?:&#039;|'|\")", webpage)
        if m_stream and m_stream.group(1):
            stream_url = m_stream.group(1).replace(r"\/", "/").replace(r"\u0026", "&")

        if not stream_url:
            m_prev = re.search(r"previewStreamUrl\s*:\s*(?:&#039;|'|\")([^'\"]+)(?:&#039;|'|\")", webpage)
            if m_prev and m_prev.group(1):
                stream_url = m_prev.group(1).replace(r"\/", "/").replace(r"\u0026", "&")

        if not stream_url:
            m_src = re.search(r"""<source[^>]+src=['"]([^'"]+\.(?:m3u8|mp4)[^'"]*)['"]""", webpage)
            if m_src:
                stream_url = m_src.group(1)

        if not stream_url:
            m_direct = re.search(r"""['"](https?://[^'"]+?\.(?:m3u8|mp4)(?:\?[^'"]*)?)['"]""", webpage)
            if m_direct:
                stream_url = m_direct.group(1).replace(r"\/", "/").replace(r"\u0026", "&")

        if not stream_url or stream_url == "null":
            # 비로그인 잠금 상태인지 확인
            if "lockedPreview" in webpage or "previewStreamUrl: null" in webpage:
                raise ExtractorError(
                    "히어하트 로그인 또는 이용권 구매가 필요한 회차입니다. 설정에서 히어하트 쿠키를 등록하세요.",
                    expected=True,
                )
            raise ExtractorError("히어하트 재생 스트림 주소를 추출하지 못했습니다.", expected=True)

        stream_headers = hearheart_headers(url)

        # HLS or direct MP4 format extraction
        if ".m3u8" in stream_url:
            formats = self._extract_m3u8_formats(
                stream_url, content_id, "mp4", entry_protocol="m3u8_native", headers=stream_headers
            )
        else:
            formats = [{
                "url": stream_url,
                "format_id": "source",
                "ext": "mp4",
                "http_headers": stream_headers,
            }]

        title = self._og_search_title(webpage, default=None) or self._html_search_regex(
            r"<title>([^<]+)</title>", webpage, "title", default=f"히어하트 {content_id}"
        )
        title = re.sub(r"^히어하트\s*-\s*", "", title).strip()

        # 크리에이터 (uploader / channel) 추출
        uploader = None
        channel_id = None
        m_creator = re.search(r'''<a[^>]+href=['"](?:https?://hearheart\.com)?/channel/(\d+)['"][^>]*>([^<]+)</a>''', webpage)
        if m_creator:
            channel_id = m_creator.group(1)
            uploader = clean_html(m_creator.group(2)).strip()

        if not uploader and " - " in title:
            parts = title.rsplit(" - ", 1)
            if len(parts) == 2 and len(parts[1].strip()) <= 30:
                uploader = parts[1].strip()
                title = parts[0].strip()

        # 재생 시간 (duration) 추출
        duration = None
        m_dur = re.search(rf'''/playlist/{playlist_id}/play/{content_id}['"][^>]*>[\s\S]*?(\d+):(\d{{2}})(?::(\d{{2}}))?''', webpage)
        if not m_dur:
            m_dur = re.search(r'''(?:current-episode|desktop-current-episode)['"][^>]*>[\s\S]*?(\d+):(\d{{2}})(?::(\d{{2}}))?''', webpage)
        if not m_dur:
            m_dur = re.search(r'''/\s*(\d+):(\d{{2}})(?::(\d{{2}}))?''', webpage)

        if m_dur:
            if m_dur.group(3):
                duration = int(m_dur.group(1)) * 3600 + int(m_dur.group(2)) * 60 + int(m_dur.group(3))
            else:
                duration = int(m_dur.group(1)) * 60 + int(m_dur.group(2))

        thumbnail = self._og_search_thumbnail(webpage, default=None)
        if not thumbnail:
            m_thumb = re.search(r"""https?://images\.hearheart\.com/[^\s"'<>]+\.(?:png|jpg|webp)""", webpage)
            if m_thumb:
                thumbnail = m_thumb.group(0)

        description = self._og_search_description(webpage, default=None)

        return {
            "id": content_id,
            "title": title,
            "uploader": uploader,
            "uploader_id": channel_id,
            "channel": uploader,
            "channel_id": channel_id,
            "channel_url": f"https://hearheart.com/channel/{channel_id}" if channel_id else None,
            "duration": duration,
            "formats": formats,
            "thumbnail": thumbnail,
            "description": description,
            "http_headers": stream_headers,
            "webpage_url": url,
            "playlist_id": playlist_id,
        }
