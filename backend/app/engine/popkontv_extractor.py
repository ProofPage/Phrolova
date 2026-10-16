"""PopkonTV VOD/clip metadata on Phrolova's existing yt-dlp queue."""

import json
from urllib.parse import urlsplit

from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.utils import ExtractorError, int_or_none, unified_strdate

from app.engine.popkontv import (
    ORIGIN,
    PARTNER,
    parse_popkontv_video_url,
    popkontv_account,
    popkontv_headers,
    response_data,
    valid_media_url,
)
from app.engine.recording_errors import RecordingError


class PopkonTVIE(InfoExtractor):
    IE_NAME = "popkontv"
    _VALID_URL = (
        r"https?://(?:www\.)?popkontv\.com/(?P<kind>vod|clip)/(?P<id>[0-9]+)(?:[/?#]|$)"
    )

    def _metadata(self, route):
        try:
            auth, user = popkontv_account(self._downloader.cookiejar)
            body = {
                "idx": int(route["id"]),
                "partnerCode": user["partnerCode"] if user else PARTNER,
                "signId": user["signId"] if user else "",
            }
            payload = self._download_json(
                ORIGIN + "/api/proxy/vod/v1/detail",
                route["id"],
                data=json.dumps(body).encode(),
                headers={
                    **popkontv_headers(route["url"]),
                    **auth,
                    "Content-Type": "application/json",
                },
                note="팝콘티비 영상 정보를 확인합니다",
                expected_status=400,
            )
            item = response_data(payload)
            if str(item.get("isAdult")) == "1" and not (
                user and user["adult_verified"]
            ):
                raise RecordingError(
                    "popkontv_authentication",
                    "팝콘티비 성인 인증 계정의 로그인이 필요합니다. 인증 쿠키를 등록하세요.",
                )
            if str(item.get("locType")) == "1":
                raise RecordingError(
                    "popkontv_access",
                    "팝콘티비에서 이 영상의 재생을 허용하지 않았습니다.",
                )
            if str(item.get("pk_code")) != route["id"]:
                raise RecordingError(
                    "popkontv_response", "팝콘티비 영상 식별 정보가 다릅니다."
                )
            if (str(item.get("groupCode")) == "20") != (route["kind"] == "clip"):
                raise RecordingError(
                    "popkontv_response",
                    "팝콘티비 다시보기·클립 종류와 링크가 다릅니다.",
                )
            if not valid_media_url(item.get("vodAddress")):
                raise RecordingError(
                    "popkontv_access",
                    "팝콘티비 영상 주소가 제공되지 않거나 재생 서버가 허용되지 않습니다. 로그인과 시청 권한을 확인하세요.",
                )
            return item
        except RecordingError as error:
            raise ExtractorError(str(error), expected=True) from None

    def _real_extract(self, url):
        try:
            route = parse_popkontv_video_url(url)
        except ValueError as error:
            raise ExtractorError(str(error), expected=True) from None
        item = self._metadata(route)
        media = item["vodAddress"]
        headers = popkontv_headers(route["url"])
        path = urlsplit(media).path.lower()
        if path.endswith(".m3u8"):
            formats = self._extract_m3u8_formats(
                media, route["id"], "mp4", entry_protocol="m3u8_native", headers=headers
            )
            if any(not valid_media_url(f.get("url")) for f in formats):
                raise ExtractorError(
                    "팝콘티비 화질별 재생 서버가 허용되지 않습니다.", expected=True
                )
        elif path.endswith(".mp4"):
            formats = [
                {
                    "url": media,
                    "format_id": "source",
                    "ext": "mp4",
                    "http_headers": headers,
                }
            ]
        else:
            raise ExtractorError(
                "팝콘티비 영상 형식을 지원하지 않습니다.", expected=True
            )
        return {
            "id": route["kind"] + "-" + route["id"],
            "title": item.get("vodTitle") or "팝콘티비 " + route["id"],
            "webpage_url": route["url"],
            "original_url": route["url"],
            "is_live": False,
            "formats": formats,
            "http_headers": headers,
            "uploader": item.get("nickName"),
            "channel_id": item.get("cast_signid"),
            "thumbnail": item.get("vodPoster"),
            "channel_thumbnail": item.get("cast_pFileName"),
            "view_count": int_or_none(item.get("viewCnt")),
            "like_count": int_or_none(item.get("goodCnt")),
            "upload_date": unified_strdate(item.get("rdate")),
            "age_limit": 19 if str(item.get("isAdult")) == "1" else 0,
        }
