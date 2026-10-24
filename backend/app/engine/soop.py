"""숲 라이브 모니터링 및 스트림 추출 엔진."""
import asyncio
import re
import time
from typing import Optional
from urllib.parse import urlsplit

import httpx

from app.core.logger import logger
from app.engine.base import LiveStatus
from app.engine.platform_auth import platform_cookie_jar

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
HOSTS = (
    "play.sooplive.com",
    "sooplive.com",
    "www.sooplive.com",
    "play.sooplive.co.kr",
    "sooplive.co.kr",
    "afreecatv.com",
    "play.afreecatv.com",
)


def normalize_soop_channel_id(value: str) -> str:
    """숲 방송 주소 또는 아이디에서 채널 ID(BJID)를 추출한다."""
    raw = value.strip()
    if re.fullmatch(r"[A-Za-z0-9_]{3,30}", raw):
        return raw.lower()
    parsed = urlsplit(raw if "://" in raw else "https://" + raw)
    match = re.fullmatch(r"/([A-Za-z0-9_]{3,30})(?:/[0-9]+)?/?", parsed.path)
    if (parsed.scheme not in ("http", "https") or parsed.hostname not in HOSTS
            or parsed.username or parsed.password or parsed.port or not match):
        raise ValueError("올바른 숲 채널 ID 또는 방송 링크를 입력하세요.")
    return match[1].lower()


class SoopLiveEngine:
    def __init__(self):
        self._cache: dict[str, tuple[float, LiveStatus]] = {}

    def get_stream_url(self, channel_id: str) -> str:
        cid = normalize_soop_channel_id(channel_id)
        return f"https://play.sooplive.com/{cid}"

    async def check_live_status(self, channel_id: str) -> LiveStatus:
        """숲 라이브 상태를 확인한다."""
        cid = normalize_soop_channel_id(channel_id)
        cached = self._cache.get(cid)
        if cached and time.monotonic() - cached[0] < 5:
            return cached[1]

        headers = {
            "User-Agent": USER_AGENT,
            "Referer": f"https://play.sooplive.com/{cid}",
            "Origin": "https://play.sooplive.com",
        }
        cookies = platform_cookie_jar("soop")

        channel_name = cid
        profile_image = ""
        is_live = False
        title = ""
        category = "SOOP"
        viewer_count = 0
        thumbnail_url = ""
        live_started_at = None

        # 1. 채널 기본 정보 조회 (chapi.sooplive.co.kr)
        station_url = f"https://chapi.sooplive.co.kr/api/{cid}/station"
        try:
            async with httpx.AsyncClient(timeout=8, headers=headers, cookies=cookies) as client:
                st_resp = await client.get(station_url)
                if st_resp.status_code == 515:
                    raise ValueError("숲 채널이 존재하지 않습니다.")
                st_resp.raise_for_status()
                if st_resp.status_code == 200:
                    data = st_resp.json()
                    if not isinstance(data.get("station"), dict) or "broad" not in data:
                        raise RuntimeError("숲 채널 응답 형식이 올바르지 않습니다.")
                    station = data.get("station") or {}
                    channel_name = station.get("user_nick") or channel_name
                    p_img = data.get("profile_image") or ""
                    if p_img.startswith("//"):
                        profile_image = "https:" + p_img
                    elif p_img.startswith("http"):
                        profile_image = p_img

                    broad = data.get("broad")
                    if isinstance(broad, dict):
                        is_live = True
                        title = broad.get("broad_title") or title
                        viewer_count = int(broad.get("current_sum_viewer") or 0)
                        bno = str(broad.get("broad_no") or "")
                        if bno:
                            thumbnail_url = f"https://liveimg.sooplive.co.kr/m/{bno}"
        except Exception as e:
            logger.debug(f"[SOOP] station API 호출 실패 ({cid}): {e}")
            raise RuntimeError("숲 채널 정보를 확인할 수 없습니다.") from e

        # 2. 실시간 라이브 플레이어 API (player_live_api.php)
        api_url = "https://live.sooplive.com/afreeca/player_live_api.php"
        data = {
            "bid": cid,
            "type": "live",
            "mode": "landing",
            "player_type": "html5",
            "stream_type": "common",
            "from_api": "0",
        }
        try:
            async with httpx.AsyncClient(timeout=8, headers=headers, cookies=cookies) as client:
                resp = await client.post(api_url, data=data)
                if resp.status_code == 200:
                    payload = resp.json().get("CHANNEL") or {}
                    if payload.get("RESULT") == 1:
                        is_live = True
                        channel_name = payload.get("BJNICK") or channel_name
                        title = payload.get("TITLE") or title
                        tags = payload.get("CATEGORY_TAGS") or []
                        if tags:
                            category = tags[0]
                        bno = str(payload.get("BNO") or "")
                        if bno:
                            thumbnail_url = f"https://liveimg.sooplive.co.kr/m/{bno}"
                    elif payload.get("RESULT") == 0:
                        is_live = False
                    else:
                        raise RuntimeError("숲 방송 상태를 확인할 수 없습니다.")
        except Exception as e:
            logger.debug(f"[SOOP] player_live_api 호출 실패 ({cid}): {e}")

        status = LiveStatus(
            channel_id=cid,
            is_live=is_live,
            channel_name=channel_name,
            title=title or (f"{channel_name} 라이브 방송" if is_live else ""),
            category=category,
            viewer_count=viewer_count,
            thumbnail_url=thumbnail_url,
            profile_image_url=profile_image or thumbnail_url,
            live_started_at=live_started_at,
        )
        self._cache[cid] = (time.monotonic(), status)
        return status

    async def get_qualities(self, channel_id: str) -> list[dict]:
        """스트림 화질 목록을 반환한다."""
        return [
            {"value": "best", "label": "최고 화질 (Source)", "height": 1080},
            {"value": "1080p", "label": "1080p", "height": 1080},
            {"value": "720p", "label": "720p", "height": 720},
            {"value": "540p", "label": "540p", "height": 540},
            {"value": "360p", "label": "360p", "height": 360},
            {"value": "worst", "label": "낮은 화질 (Worst)", "height": 360},
        ]

    async def resolve_stream(self, channel_id: str, quality: str = "best") -> tuple[str, dict[str, str], Optional[str]]:
        """라이브 스트림 URL과 필수 헤더를 반환한다."""
        cid = normalize_soop_channel_id(channel_id)
        live_url = f"https://play.sooplive.com/{cid}"

        def _get_hls_url():
            import streamlink
            session = streamlink.session.Streamlink()
            session.set_option("http-timeout", 15)
            session.set_option("no-plugin-cache", True)
            session.set_option("webbrowser", False)
            session.http.cookies.update(platform_cookie_jar("soop"))
            try:
                streams = session.streams(live_url)
                if not streams:
                    raise RuntimeError("숲 생방송 스트림을 찾을 수 없습니다. 방송이 진행 중인지 확인하세요.")
                if quality not in streams:
                    raise ValueError("선택한 숲 방송 화질을 사용할 수 없습니다.")
                return streams[quality].to_url()
            finally:
                session.http.close()

        stream_url = await asyncio.to_thread(_get_hls_url)
        headers = {
            "User-Agent": USER_AGENT,
            "Referer": live_url,
            "Origin": "https://play.sooplive.com",
        }
        return stream_url, headers, None

    async def get_preview_url(self, channel_id: str) -> str:
        return (await self.resolve_stream(channel_id))[0]
