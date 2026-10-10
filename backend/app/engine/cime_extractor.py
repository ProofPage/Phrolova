"""yt-dlp adapter for CIME's verified public watch-page JSON routes.

Registered per YoutubeDL instance by Phrolova. The existing VOD engine owns
queuing, retries, pause/cancel, merging, file inspection and persisted history.
"""
from __future__ import annotations

from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.utils import ExtractorError, float_or_none, parse_iso8601

from app.engine.cime import (CIME_ORIGIN, _http_url, cime_headers,
                             extract_cime_body_data, parse_cime_video_url,
                             permission_required, playback_url)

CIME_AUTH_MESSAGE = "씨미 로그인이 필요하거나 이 콘텐츠의 시청 권한이 없습니다."


def _error_status(error: Exception) -> int | None:
    cause = getattr(error, "cause", None)
    return getattr(cause, "status", None) or getattr(cause, "code", None)


class CimeIE(InfoExtractor):
    IE_NAME = "cime"
    _VALID_URL = r"https?://(?:www\.)?ci\.me/(?:@(?P<slug>[A-Za-z0-9_][A-Za-z0-9_.-]{0,99})/vods/|clips/)(?P<id>\d+)(?:[/?#]|$)"
    _TESTS = [{"url": "https://ci.me/@hebi/vods/73611", "only_matching": True},
              {"url": "https://ci.me/clips/31404", "only_matching": True}]

    def _router(self, route: dict) -> dict:
        path = f"/@{route['slug']}/vods/{route['id']}" if route["kind"] == "vod" else f"/clips/{route['id']}"
        try:
            data = self._download_json(CIME_ORIGIN + "/json" + path, route["id"],
                                       headers=cime_headers(route["url"]),
                                       note="씨미 영상 정보를 확인합니다", errnote="씨미 영상 정보를 가져오지 못했습니다")
        except ExtractorError as error:
            status = _error_status(error)
            if status in (401, 403):
                raise ExtractorError(CIME_AUTH_MESSAGE, expected=True, cause=error.cause) from None
            if status == 404:
                raise ExtractorError("씨미 영상을 찾을 수 없습니다.", expected=True) from None
            raise ExtractorError("씨미 영상 정보를 가져오지 못했습니다.", expected=True) from None
        body = extract_cime_body_data(data)
        if route["kind"] == "vod":
            item = body.get("vod")
        else:
            item = next((clip for clip in body.get("clips") or []
                         if isinstance(clip, dict) and str(clip.get("id")) == route["id"]), None)
        if permission_required(body, item if isinstance(item, dict) else {}):
            raise ExtractorError(CIME_AUTH_MESSAGE, expected=True)
        if not isinstance(item, dict):
            raise ExtractorError("씨미 영상을 찾을 수 없습니다.", expected=True)
        return item

    def _real_extract(self, url: str) -> dict:
        route = parse_cime_video_url(url)
        if route is None:
            raise ExtractorError("올바른 씨미 다시보기 또는 클립 링크를 입력하세요.", expected=True)
        item = self._router(route)
        media = playback_url(item)
        if not media:
            if item.get("viewAccess") or item.get("isAdult"):
                raise ExtractorError(CIME_AUTH_MESSAGE, expected=True)
            raise ExtractorError("씨미 영상의 재생 정보를 찾을 수 없습니다.", expected=True)
        headers = cime_headers(route["url"])
        if ".m3u8" in media.split("?", 1)[0].lower():
            try:
                formats = self._extract_m3u8_formats(media, route["id"], "mp4", entry_protocol="m3u8_native",
                                                     m3u8_id="hls", headers=headers,
                                                     note="씨미 재생 목록을 확인합니다",
                                                     errnote="씨미 재생 목록을 가져오지 못했습니다")
            except ExtractorError as error:
                if _error_status(error) in (401, 403):
                    raise ExtractorError(CIME_AUTH_MESSAGE, expected=True, cause=error.cause) from None
                raise ExtractorError("씨미 재생 목록을 가져오지 못했습니다.", expected=True) from None
        else:
            # Clips currently expose a ready MP4, without reliable dimensions
            # in the router response. Keep 'source' instead of inventing 1080p.
            formats = [{"url": media, "format_id": "source", "ext": "mp4", "http_headers": headers}]
        if not formats:
            raise ExtractorError("씨미 영상에서 다운로드 가능한 화질을 찾지 못했습니다.", expected=True)
        channel = item.get("channel") if isinstance(item.get("channel"), dict) else {}
        category = item.get("category") if isinstance(item.get("category"), dict) else {}
        tags = [str(tag.get("displayName") or tag.get("name")) for tag in item.get("tags") or []
                if isinstance(tag, dict) and (tag.get("displayName") or tag.get("name"))]
        return {"id": route["id"], "title": str(item.get("title") or f"씨미 영상 {route['id']}"),
                "webpage_url": route["url"], "original_url": route["url"],
                "channel": str(channel.get("name") or route["slug"]),
                "uploader": str(channel.get("name") or route["slug"]),
                "channel_id": str(channel.get("slug") or route["slug"]),
                "channel_url": f"{CIME_ORIGIN}/@{channel.get('slug') or route['slug']}" if channel.get("slug") or route["slug"] else None,
                "thumbnail": _http_url(item.get("imageUrl")) or _http_url(item.get("coverImageUrl")),
                "duration": float_or_none(item.get("duration"), scale=1000),
                "timestamp": parse_iso8601(item.get("openedAt") or item.get("createdAt")),
                "age_limit": 19 if item.get("isAdult") else 0,
                "categories": [category["name"]] if category.get("name") else [], "tags": tags,
                "formats": formats, "http_headers": headers, "is_live": False}
