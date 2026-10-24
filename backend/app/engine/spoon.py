"""Korean Spoon public live audio, using server-issued HLS grants."""
import re
from urllib.parse import urljoin, urlsplit

import httpx
from requests.auth import AuthBase

from app.core.http import USER_AGENT
from app.engine.base import LiveStatus
from app.engine.recording_errors import RecordingError

ORIGIN = "https://www.spooncast.net"
GATEWAY = "https://kr-gw.spooncast.net"
API = "https://kr-api.spooncast.net"
HEADERS = {"User-Agent": USER_AGENT, "Origin": ORIGIN, "Referer": ORIGIN + "/"}


def normalize_spoon_channel_id(value: str) -> str:
    raw = value.strip()
    if "://" in raw:
        try:
            url = urlsplit(raw)
            if (url.scheme not in ("https", "http")
                    or url.hostname not in ("www.spooncast.net", "spooncast.net")
                    or url.username or url.password or url.port):
                raise ValueError()
            match = re.fullmatch(r"/kr/channel/([1-9][0-9]*)(?:/tab/(?:home|casts|live-history|posts|follower-posts))?/?", url.path)
            if match:
                return match[1]
            match = re.fullmatch(r"/kr/live/(@[A-Za-z0-9_.-]+|[1-9][0-9]*)/?", url.path)
            if not match:
                raise ValueError()
            raw = match[1]
            if raw.isdigit():
                return "live:" + raw
        except ValueError:
            raise ValueError("스푼 채널 링크 또는 채널 ID를 확인하세요.") from None
    if re.fullmatch(r"[1-9][0-9]*|@[A-Za-z0-9_.-]{1,100}|live:[1-9][0-9]*", raw):
        return raw
    raise ValueError("스푼 채널 링크 또는 채널 ID를 확인하세요.")


def media_allowed(value: str) -> bool:
    try:
        url = urlsplit(value)
        return (url.scheme == "https" and url.hostname == "kr-hana-live.spooncast.net"
                and not url.username and not url.password and url.port in (None, 443)
                and url.path.startswith("/cast/") and not any(c in value for c in "\r\n\\"))
    except (TypeError, ValueError):
        return False


def configure_media_session(session):
    delegate = session.http.auth

    class MediaAuth(AuthBase):
        def __call__(self, request):
            if not media_allowed(request.url):
                raise RecordingError("spoon_stream", "스푼 재생 서버 주소가 허용되지 않습니다.")
            return delegate(request) if delegate else request

    def guard(response, *args, **kwargs):
        if response.is_redirect and not media_allowed(urljoin(response.url, response.headers.get("Location", ""))):
            raise RecordingError("spoon_stream", "스푼 재생 서버 이동 주소가 허용되지 않습니다.")

    session.http.auth = MediaAuth()
    session.http.hooks["response"].append(guard)


class SpoonLiveEngine:
    async def _api(self, base, path, params=None):
        try:
            async with httpx.AsyncClient(timeout=12, follow_redirects=False, headers=HEADERS) as client:
                response = await client.get(base + path, params=params)
            if response.status_code in (401, 403):
                raise RecordingError("spoon_access", "스푼에서 공개 재생을 허용하지 않는 방송입니다.")
            if response.status_code == 404:
                raise RecordingError("spoon_not_found", "스푼 채널 또는 방송을 찾지 못했습니다.")
            if response.status_code == 429:
                raise RecordingError("spoon_rate_limit", "스푼 요청 한도에 도달했습니다.", retryable=True)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError()
            return data
        except (httpx.HTTPError, ValueError):
            raise RecordingError("spoon_connection", "스푼 방송 정보를 확인하지 못했습니다.", retryable=True) from None

    async def canonical_channel_id(self, value):
        cid = normalize_spoon_channel_id(value)
        if cid.startswith("@"):
            data = await self._api(GATEWAY, "/search/user", {"keyword": cid[1:], "page_size": 10, "v": 2})
            matches = [user for user in data.get("results", [])
                       if user.get("tag") == cid[1:] and isinstance(user.get("id"), int)]
            if len(matches) != 1:
                raise RecordingError("spoon_not_found", "스푼의 정확한 채널 ID를 찾지 못했습니다. 채널 링크를 입력하세요.")
            return str(matches[0]["id"])
        if cid.startswith("live:"):
            data = await self._api(API, "/lives/" + cid[5:] + "/")
            try:
                return str(int(data["results"][0]["author"]["id"]))
            except (KeyError, IndexError, TypeError, ValueError):
                raise RecordingError("spoon_response", "스푼 방송의 채널 정보를 확인하지 못했습니다.") from None
        return cid

    def get_stream_url(self, channel_id):
        return ORIGIN + "/kr/channel/" + normalize_spoon_channel_id(channel_id)

    async def _live(self, channel_id):
        cid = await self.canonical_channel_id(channel_id)
        data = await self._api(GATEWAY, "/channels/" + cid)
        try:
            channel = data["result"]["channel"]
            if str(channel["id"]) != cid:
                raise ValueError()
            live_id = channel["currentLiveId"]
            if live_id is None:
                return cid, channel, None
            data = await self._api(API, f"/lives/{int(live_id)}/")
            live = data["results"][0]
            if str(live["author"]["id"]) != cid or live["id"] != live_id:
                raise ValueError()
            return cid, channel, live if live["status"] == 1 and live.get("closed") is None else None
        except (KeyError, IndexError, TypeError, ValueError):
            raise RecordingError("spoon_response", "스푼 방송 정보 형식이 올바르지 않습니다.") from None

    async def check_live_status(self, channel_id) -> LiveStatus:
        cid, channel, live = await self._live(channel_id)
        return LiveStatus(channel_id=cid, is_live=live is not None,
                          channel_name=channel.get("nickname") or cid,
                          profile_image_url=channel.get("profileUrl") or "",
                          title=live.get("title", "") if live else "", category="Audio",
                          viewer_count=live.get("member_count", 0) if live else 0,
                          thumbnail_url=live.get("img_url", "") if live else "",
                          live_started_at=live.get("created") if live else None)

    async def get_qualities(self, channel_id):
        _, _, live = await self._live(channel_id)
        return [{"value": "best", "label": "Source audio"}] if live else []

    async def resolve_stream(self, channel_id, quality="best"):
        _, _, live = await self._live(channel_id)
        if live is None:
            raise RecordingError("broadcast_ended", "스푼 방송이 종료되었습니다.")
        # Never use the unsigned `url` or the short preview endpoint.
        media = live.get("url_hls")
        if not media_allowed(media) or not urlsplit(media).path.endswith(".m3u8"):
            raise RecordingError("spoon_access", "스푼에서 허용된 원본 오디오 주소를 제공하지 않았습니다.")
        return media, dict(HEADERS), None

    async def get_preview_url(self, channel_id):
        return (await self.resolve_stream(channel_id))[0]
