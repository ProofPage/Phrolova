"""Berriz community live monitoring; only server-authorized, non-DRM HLS."""
import re
from urllib.parse import urlsplit

import httpx

from app.core.http import USER_AGENT
from app.engine.base import LiveStatus
from app.engine.platform_auth import get_platform_cookies
from app.engine.recording_errors import RecordingError

API = "https://svc-api.berriz.in/service/v1"
HEADERS = {"User-Agent": USER_AGENT, "Referer": "https://berriz.in/", "Origin": "https://berriz.in"}


def normalize_berriz_channel_id(value):
    raw = value.strip()
    if "://" in raw:
        try:
            url = urlsplit(raw)
            if (url.scheme not in ("https", "http") or url.hostname != "berriz.in"
                    or url.username or url.password or url.port):
                raise ValueError()
            match = re.fullmatch(r"/(?:[a-z]{2}(?:-[A-Z]{2})?/)?([A-Za-z0-9_-]+)(?:/live)?/?", url.path)
            if not match:
                raise ValueError()
            raw = match[1]
        except ValueError:
            raise ValueError("베리즈 커뮤니티 ID 또는 커뮤니티 링크를 입력하세요.") from None
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", raw) or raw.lower() in ("main", "ko", "en", "web"):
        raise ValueError("베리즈 커뮤니티 ID 또는 커뮤니티 링크를 입력하세요.")
    return raw.lower()


class BerrizLiveEngine:
    async def _api(self, path):
        url = API + path
        try:
            async with httpx.AsyncClient(timeout=12, follow_redirects=False) as client:
                response = await client.get(url, params={"languageCode": "ko"}, headers=HEADERS,
                                            cookies=get_platform_cookies("berriz", url))
            if response.status_code in (401, 403):
                raise RecordingError("authentication", "베리즈 시청 권한을 확인하세요. 설정에서 로그인 쿠키를 등록하세요.")
            if response.status_code == 429:
                raise RecordingError("berriz_rate_limit", "베리즈 요청 한도에 도달했습니다.", retryable=True)
            response.raise_for_status()
            payload = response.json()
            if payload.get("code") != "0000" or not isinstance(payload.get("data"), dict):
                raise RecordingError("berriz_access", "베리즈에서 방송 정보 접근을 허용하지 않았습니다.")
            return payload["data"]
        except (httpx.HTTPError, ValueError):
            raise RecordingError("berriz_connection", "베리즈 방송 정보를 확인하지 못했습니다.", retryable=True) from None

    async def canonical_channel_id(self, value):
        key = normalize_berriz_channel_id(value)
        if key.isdigit():
            await self._api(f"/community/{key}/medias/live/on-air")
            return str(int(key))
        data = await self._api("/community/id/" + key)
        if not isinstance(data.get("communityId"), int):
            raise RecordingError("berriz_response", "베리즈 커뮤니티 정보를 확인하지 못했습니다.")
        return str(data["communityId"])

    def get_stream_url(self, channel_id):
        # Registered channels use the stable numeric community ID.
        return "https://berriz.in/ko/" + normalize_berriz_channel_id(channel_id) + "/live/"

    async def _live(self, channel_id):
        cid = normalize_berriz_channel_id(channel_id)
        if not cid.isdigit():
            cid = await self.canonical_channel_id(cid)
        data = await self._api(f"/community/{cid}/medias/live/on-air")
        contents = data.get("contents")
        if not isinstance(contents, list):
            raise RecordingError("berriz_response", "베리즈 라이브 목록 형식이 올바르지 않습니다.")
        return cid, contents[0] if contents else None

    async def check_live_status(self, channel_id):
        cid, item = await self._live(channel_id)
        media = item["media"] if item else {}
        artists = item.get("communityArtists", []) if item else []
        return LiveStatus(channel_id=cid, is_live=bool(item), channel_name=", ".join(
            artist["name"] for artist in artists) or cid, title=media.get("title", ""),
            category="Berriz", thumbnail_url=media.get("thumbnailUrl", ""),
            profile_image_url=artists[0].get("imageUrl", "") if artists else "", viewer_count=0)

    async def _playback(self, channel_id):
        _, item = await self._live(channel_id)
        if not item:
            raise RecordingError("broadcast_ended", "베리즈 방송이 종료되었습니다.")
        media_id = item["media"]["mediaId"]
        if not re.fullmatch(r"[a-fA-F0-9-]{36}", media_id):
            raise RecordingError("berriz_response", "베리즈 방송 ID 형식이 올바르지 않습니다.")
        data = await self._api(f"/medias/live/{media_id}/playback_info")
        live = data.get("live")
        if not isinstance(live, dict) or live.get("isDrm") is not False or live.get("drmInfo"):
            raise RecordingError("drm", "베리즈 DRM 방송은 녹화를 지원하지 않습니다.")
        return live.get("hls") or {}

    async def get_qualities(self, channel_id):
        hls = await self._playback(channel_id)
        return [{"value": "best", "label": "Source"}] + [
            {"value": f'{item["height"]}p', "label": f'{item["height"]}p', "height": item["height"]}
            for item in hls.get("adaptationSet", []) if isinstance(item.get("height"), int)]

    async def resolve_stream(self, channel_id, quality="best"):
        hls = await self._playback(channel_id)
        media = hls.get("playbackUrl")
        if quality not in ("best", "worst"):
            selected = next((item for item in hls.get("adaptationSet", [])
                             if f'{item.get("height")}p' == quality), None)
            if not selected:
                raise RecordingError("quality_unavailable", "베리즈에서 선택한 화질을 제공하지 않습니다.")
            media = selected.get("playbackUrl")
        elif quality == "worst" and hls.get("adaptationSet"):
            media = min(hls["adaptationSet"], key=lambda item: item["height"]).get("playbackUrl")
        try:
            url = urlsplit(media)
            if (url.scheme != "https" or url.hostname != "statics.berriz.in" or url.username
                    or url.password or url.port not in (None, 443) or not url.path.endswith(".m3u8")
                    or any(char in media for char in "\r\n\\")):
                raise ValueError()
        except (TypeError, ValueError):
            raise RecordingError("berriz_stream", "베리즈에서 지원하는 비DRM HLS 주소를 제공하지 않았습니다.") from None
        return media, dict(HEADERS), None

    async def get_preview_url(self, channel_id):
        return (await self.resolve_stream(channel_id))[0]
