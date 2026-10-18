"""PopkonTV web API, scoped account cookies and Streamlink live transport."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlsplit
from urllib.request import Request

import httpx
from Cryptodome.Cipher import AES
from Cryptodome.Util.Padding import pad, unpad

from app.core.config import get_settings
from app.core.http import USER_AGENT
from app.engine.base import LiveStatus
from app.engine.platform_auth import platform_cookie_jar
from app.engine.recording_errors import RecordingError

ORIGIN = "https://www.popkontv.com"
HOSTS = {"www.popkontv.com", "popkontv.com"}
MEDIA_HOSTS = {"live-popkontv.hscdn.com", "vod2.popkontv.hscdn.com"}
PARTNER = "P-00001"
IDENTIFIER = r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}"
PARTNER_RE = r"P-[0-9]{5}"
_web_config = None
_web_lock = threading.Lock()


def _parts(value):
    raw = str(value or "").strip()
    if re.search(r"[\x00-\x20\\]", raw):
        raise ValueError
    parts = urlsplit(raw)
    if (
        parts.scheme not in ("http", "https")
        or parts.hostname not in HOSTS
        or parts.username is not None
        or parts.password is not None
        or parts.port not in (None, 443 if parts.scheme == "https" else 80)
    ):
        raise ValueError
    return parts


def normalize_popkontv_channel_id(value: str) -> str:
    try:
        raw = str(value or "").strip()
        if "://" in raw:
            parts = _parts(raw)
            if parts.path.rstrip("/") != "/live/view":
                raise ValueError
            query = parse_qsl(parts.query, keep_blank_values=True)
            ids = [v for k, v in query if k == "castId"]
            partners = [v for k, v in query if k == "partnerCode"]
            if len(ids) != 1 or len(partners) > 1:
                raise ValueError
            raw = ids[0] + "@" + (partners[0] if partners else PARTNER)
        elif "@" not in raw:
            raw += "@" + PARTNER
        match = re.fullmatch(
            "(" + IDENTIFIER + ")@(" + PARTNER_RE + ")", raw, re.IGNORECASE
        )
        if not match:
            raise ValueError
        return match[1].lower() + "@" + match[2].upper()
    except ValueError:
        raise ValueError(
            "올바른 팝콘티비 방송 링크 또는 채널ID@파트너코드를 입력하세요."
        ) from None


def popkontv_live_url(value):
    cid, partner = normalize_popkontv_channel_id(value).split("@")
    return ORIGIN + "/live/view?" + urlencode({"castId": cid, "partnerCode": partner})


def parse_popkontv_video_url(value):
    try:
        parts = _parts(value)
        match = re.fullmatch(r"/(vod|clip)/([0-9]{1,20})/?", unquote(parts.path))
        if not match or int(match[2]) <= 0:
            raise ValueError
        identifier = str(int(match[2]))
        return {
            "kind": match[1],
            "id": identifier,
            "url": ORIGIN + "/" + match[1] + "/" + identifier,
        }
    except ValueError:
        raise ValueError(
            "올바른 팝콘티비 다시보기 또는 클립 링크를 입력하세요."
        ) from None


def popkontv_headers(referer=ORIGIN + "/"):
    return {"User-Agent": USER_AGENT, "Origin": ORIGIN, "Referer": referer}


def valid_media_url(value):
    try:
        if (
            not isinstance(value, str)
            or value != value.strip()
            or re.search(r"[\x00-\x1f\x7f\\]", value)
        ):
            return False
        parts = urlsplit(value)
        return (
            parts.scheme == "https"
            and parts.hostname in MEDIA_HOSTS
            and parts.port in (None, 443)
            and parts.username is None
            and parts.password is None
            and not parts.fragment
        )
    except (ValueError, TypeError):
        return False


def _cookie_cipher(passphrase, salt):
    key = b""
    previous = b""
    while len(key) < 48:
        previous = hashlib.md5(previous + passphrase.encode() + salt).digest()
        key += previous
    return AES.new(key[:32], AES.MODE_CBC, key[32:48])


def encode_account_cookie(value, passphrase):
    salt = os.urandom(8)
    data = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(
        b"Salted__" + salt + _cookie_cipher(passphrase, salt).encrypt(pad(data, 16))
    ).decode("ascii")


def _decode_account_cookie(value, passphrase):
    """Decode the site's CryptoJS/OpenSSL cookie serialization, only for imported account cookies."""
    try:
        if not isinstance(value, str) or not 1 <= len(value) <= 65536:
            raise ValueError
        raw = base64.b64decode(unquote(value), validate=True)
        if not raw.startswith(b"Salted__") or len(raw) < 32:
            raise ValueError
        return json.loads(
            unpad(_cookie_cipher(passphrase, raw[8:16]).decrypt(raw[16:]), 16)
        )
    except (ValueError, UnicodeError, RecursionError):
        raise RecordingError(
            "popkontv_cookie",
            "팝콘티비 로그인 쿠키를 읽지 못했습니다. 공식 사이트에서 다시 내보내 등록하세요.",
        ) from None


def popkontv_account(jar):
    request = Request(ORIGIN + "/")
    jar.add_cookie_header(request)
    cookies = SimpleCookie()
    cookies.load(request.get_header("Cookie", ""))
    if "auth-tk" not in cookies:
        return {}, None
    token = _decode_account_cookie(
        cookies["auth-tk"].value,
        "SECRET_PSID12__SECRET_PSID12_SECRET_PSID12__SECRET_PSID12",
    )
    user = (
        _decode_account_cookie(cookies["user"].value, "SECRET_PSID1")
        if "user" in cookies
        else None
    )
    if (
        not isinstance(token, str)
        or not token
        or len(token) > 16384
        or re.search(r"[\x00-\x20\x7f]", token)
        or not isinstance(user, dict)
        or not re.fullmatch(IDENTIFIER, str(user.get("signId", "")))
        or not re.fullmatch(PARTNER_RE, str(user.get("partnerCode", "")))
    ):
        raise RecordingError(
            "popkontv_cookie",
            "팝콘티비 로그인 쿠키가 올바르지 않습니다. 사이트에서 다시 로그인한 뒤 등록하세요.",
        )
    return {"Authorization": "Bearer " + token}, {
        "signId": user["signId"],
        "partnerCode": user["partnerCode"],
        "adult_verified": str(user.get("isAdultCheck")) == "1",
    }


def response_data(payload, success=("S2000",)):
    if not isinstance(payload, dict) or not isinstance(payload.get("statusCd"), str):
        raise RecordingError(
            "popkontv_response", "팝콘티비 응답 형식이 변경되었습니다."
        )
    code = payload["statusCd"]
    message = str(payload.get("statusMsg") or "")
    if code in success:
        if not isinstance(payload.get("data"), dict):
            raise RecordingError(
                "popkontv_response", "팝콘티비 방송·영상 정보를 확인할 수 없습니다."
            )
        return payload["data"]
    if code == "E4004":
        raise RecordingError(
            "popkontv_not_found",
            "팝콘티비 방송이나 영상을 찾을 수 없습니다. 링크와 공개 상태를 확인하세요.",
        )
    if code == "L000A" or any(
        word in message
        for word in ("로그인", "성인", "본인인증", "휴대폰 인증", "토큰", "token")
    ):
        raise RecordingError(
            "popkontv_authentication",
            "팝콘티비 로그인 또는 본인인증이 필요합니다. 공식 사이트에서 인증한 계정의 쿠키를 설정 → 인증에 등록하세요.",
        )
    if code == "L000E":
        raise RecordingError(
            "popkontv_maintenance",
            "팝콘티비 서비스 점검 중입니다. 잠시 후 다시 시도하세요.",
            retryable=True,
        )
    raise RecordingError(
        "popkontv_access",
        "팝콘티비 재생이 허용되지 않았습니다. 시청 권한과 쿠키 상태를 확인하세요.",
    )


def _post(client, path, body, headers=None):
    try:
        response = client.post(ORIGIN + "/api/proxy" + path, json=body, headers=headers)
        if response.status_code == 429:
            raise RecordingError(
                "popkontv_rate_limit",
                "팝콘티비 요청 한도에 도달했습니다.",
                retryable=True,
            )
        if response.status_code == 401:
            raise RecordingError(
                "popkontv_session_expired",
                "팝콘티비 로그인 세션이 만료되었습니다.",
            )
        if response.status_code == 403:
            raise RecordingError(
                "popkontv_authentication",
                "팝콘티비 로그인 쿠키와 시청 권한을 확인하세요.",
            )
        if response.status_code != 400:
            response.raise_for_status()
        return response.json()
    except httpx.HTTPError:
        raise RecordingError(
            "popkontv_connection",
            "팝콘티비 서버에 연결하지 못했습니다. 잠시 후 다시 시도하세요.",
            retryable=True,
        ) from None
    except ValueError:
        raise RecordingError(
            "popkontv_response", "팝콘티비 응답을 읽지 못했습니다."
        ) from None


def public_web_config(client, referer, *, require_version=True, page_html=None):
    """Read literal public client/version constants from the website; never evaluate its JavaScript."""
    global _web_config
    with _web_lock:
        if _web_config and time.monotonic() - _web_config[0] < 3600:
            return _web_config[1]

        def get(path):
            if path != referer and not re.fullmatch(
                r"/_next/static/chunks/[A-Za-z0-9_./%\[\]-]+\.js", path
            ):
                raise RecordingError(
                    "popkontv_response", "팝콘티비 웹 설정 경로가 올바르지 않습니다."
                )
            response = client.get(path if path == referer else ORIGIN + path)
            response.raise_for_status()
            if len(response.content) > 4 * 1024 * 1024:
                raise RecordingError(
                    "popkontv_response", "팝콘티비 웹 설정이 너무 큽니다."
                )
            return response.text

        try:
            page = page_html if page_html is not None else get(referer)
            scripts = re.findall(
                r'<script[^>]*src=["\'](/_next/static/chunks/[^"\']+\.js)["\']', page
            )
            app = next(p for p in scripts if "/pages/_app-" in p)
            text = get(app)
            key = re.search(
                r'PW:""\.concat\([A-Za-z_$][\w$]*\.w\.CLIENT," ([A-Za-z0-9+/=]+)"\)',
                text,
            )
            if not key:
                raise ValueError
            if not require_version:
                return {"ClientKey": "Client " + key[1]}
            version = None
            for path in scripts:
                if path == app or any(
                    part in path
                    for part in ("framework-", "polyfills-", "webpack-", "/main-")
                ):
                    continue
                text = get(path)
                if "BROADCAST.CAST_WATCH_ON_OFF" not in text:
                    continue
                for match in re.finditer(
                    r'\b([A-Za-z_$][\w$]*)="([0-9]+\.[0-9]+\.[0-9]+)"', text
                ):
                    if re.search(r"\bversion:" + re.escape(match[1]) + r"\b", text):
                        version = match[2]
                        break
                if version:
                    break
            if not version:
                raise ValueError
            config = {"ClientKey": "Client " + key[1], "version": version}
            _web_config = (time.monotonic(), config)
            return config
        except (ValueError, StopIteration, httpx.HTTPError):
            raise RecordingError(
                "popkontv_response",
                "팝콘티비 웹 재생 설정을 읽지 못했습니다. 사이트 형식을 확인하세요.",
            ) from None


def _put(cache, key, value):
    cache.pop(key, None)
    while len(cache) >= 128:
        cache.pop(next(iter(cache)))
    cache[key] = (time.monotonic(), value)


class PopkonTVLiveEngine:
    def __init__(self):
        self._cache = {}
        self._room_passwords = {}

    def set_room_password(self, channel_id, password):
        from pydantic import SecretStr

        channel = normalize_popkontv_channel_id(channel_id)
        if password:
            self._room_passwords[channel] = SecretStr(password)
        else:
            self._room_passwords.pop(channel, None)

    def get_stream_url(self, channel_id):
        return popkontv_live_url(channel_id)

    async def _metadata(self, channel_id, *, refresh=False):
        channel = normalize_popkontv_channel_id(channel_id)
        cached = self._cache.get(channel)
        if not refresh and cached and time.monotonic() - cached[0] < 8:
            return cached[1]
        cid, partner = channel.split("@")

        def fetch():
            with httpx.Client(
                timeout=15,
                follow_redirects=False,
                headers=popkontv_headers(self.get_stream_url(channel)),
            ) as client:
                data = response_data(
                    _post(
                        client,
                        "/broadcast/v1.1/mcinfo",
                        {
                            "castId": cid,
                            "castPartnerCode": partner,
                            "partnerCode": PARTNER,
                        },
                    )
                )
            if (
                str(data.get("mc_signId", "")).lower() != cid
                or data.get("mc_partnerCode") != partner
            ):
                raise RecordingError(
                    "popkontv_response",
                    "팝콘티비 방송자와 파트너 식별 정보가 다릅니다.",
                )
            return data

        data = await asyncio.to_thread(fetch)
        _put(self._cache, channel, data)
        return data

    async def check_live_status(self, channel_id) -> LiveStatus:
        channel = normalize_popkontv_channel_id(channel_id)
        data = await self._metadata(channel)
        stamp = str(data.get("mc_castStartDate") or "")
        started = None
        if stamp:
            try:
                started = (
                    datetime.strptime(stamp, "%Y%m%d%H%M%S")
                    .replace(tzinfo=timezone(timedelta(hours=9)))
                    .isoformat()
                )
            except ValueError:
                raise RecordingError(
                    "popkontv_response", "팝콘티비 방송 시작 시각이 올바르지 않습니다."
                ) from None
        viewers = data.get("mc_watchCnt")
        try:
            viewers = max(0, int(viewers)) if not isinstance(viewers, bool) else 0
        except (TypeError, ValueError):
            viewers = 0
        return LiveStatus(
            channel_id=channel,
            is_live=bool(started),
            channel_name=data.get("mc_nickName") or channel,
            title=data.get("mc_pTitle") or "",
            category=str(data.get("mc_category") or ""),
            viewer_count=viewers if started else 0,
            thumbnail_url=data.get("mc_pFileName") or "",
            profile_image_url=data.get("mc_pFileName") or "",
            live_started_at=started,
        )

    async def _streams(self, channel_id):
        channel = normalize_popkontv_channel_id(channel_id)
        cid, partner = channel.split("@")
        # Each connection uses the current broadcast and freshly imported login.
        # A watch grant from the previous broadcast/account is not reusable.
        metadata = await self._metadata(channel, refresh=True)
        if not metadata.get("mc_castStartDate"):
            return []
        if not get_settings().popkontv_use_playback_response:
            if (str(metadata.get("mc_isPrivate", "0")) not in ("0", "False", "false")
                    and channel not in self._room_passwords):
                raise RecordingError(
                    "popkontv_password",
                    "비밀번호로 보호된 팝콘티비 방송입니다. 서버 재생 응답 기준 옵션을 확인하세요.",
                )
            if (
                str(metadata.get("castType", "0")) != "0"
                or str(metadata.get("accountType", "0")) != "0"
            ):
                raise RecordingError(
                    "popkontv_paid",
                    "팝콘티비 유료·회원전용 방송입니다. 서버 재생 응답 기준 옵션을 확인하세요.",
                )
        page = self.get_stream_url(channel)
        headers = popkontv_headers(page)

        def resolve():
            from app.engine.popkontv_session import authorized_popkontv_request

            jar = platform_cookie_jar("popkontv")
            with httpx.Client(
                timeout=15, follow_redirects=False, headers=headers, cookies=jar
            ) as client:
                config = public_web_config(client, page)
                def watch(auth, user):
                    if str(metadata.get("isAdult")) == "1" and not (
                        user and user["adult_verified"]
                    ):
                        raise RecordingError(
                            "popkontv_authentication",
                            "팝콘티비 성인 인증 계정의 쿠키가 필요합니다. 설정 → 인증에 등록하세요.",
                        )
                    password = self._room_passwords.get(channel)
                    body = {
                        "androidStore": 0,
                        "castCode": cid + "-" + str(metadata["mc_castStartDate"]),
                        "castPartnerCode": partner,
                        "castSignId": cid,
                        "castType": metadata["castType"],
                        "commandType": 0,
                        "exePath": 5,
                        "partnerCode": user["partnerCode"] if user else PARTNER,
                        "password": password.get_secret_value() if password else "",
                        "version": config["version"],
                    }
                    if user:
                        body.update(signId=user["signId"], isSecret=0)
                    path = "/broadcast/v2/castwatchonoff" + ("" if user else "guest")
                    payload = _post(
                        client, path, body,
                        headers={**auth, "ClientKey": config["ClientKey"]},
                    )
                    if payload.get("statusCd") == "L0001" and any(
                        word in str(payload.get("statusMsg", "")).lower()
                        for word in ("비밀번호", "password")
                    ):
                        raise RecordingError(
                            "popkontv_password",
                            "팝콘티비 방송 비밀번호를 채널 녹화 설정에서 확인하세요.",
                        )
                    return response_data(payload, ("L0000",))

                result = authorized_popkontv_request(
                    watch, jar, page, client=client, config=config,
                )
            url = result.get("castHlsUrl")
            identity = f'/{cid}_{partner}_{metadata["mc_castStartDate"]}/'
            if not valid_media_url(url) or identity not in unquote(urlsplit(url).path):
                raise RecordingError(
                    "popkontv_stream",
                    "팝콘티비 재생 서버 또는 방송 식별 정보가 다릅니다.",
                )
            from streamlink import Streamlink
            from streamlink.stream.hls import HLSStream

            session = Streamlink(plugins_builtin=False)
            session.set_option("http-timeout", 15)
            from app.engine.streamlink_support import configure_streamlink_session
            configure_streamlink_session(session, "popkontv", url)

            def redirect_guard(response, *args, **kwargs):
                if response.is_redirect and not valid_media_url(
                    urljoin(response.url, response.headers.get("Location", ""))
                ):
                    raise RecordingError(
                        "popkontv_stream",
                        "팝콘티비 재생 서버의 이동 주소가 허용되지 않습니다.",
                    )

            session.http.hooks["response"].append(redirect_guard)
            try:
                streams = HLSStream.parse_variant_playlist(
                    session, url, headers=headers
                )
                variants = []
                for name, stream in streams.items():
                    if name in ("best", "worst", "audio", "audio_only"):
                        continue
                    target = stream.to_url()
                    if not valid_media_url(target):
                        raise RecordingError(
                            "popkontv_stream",
                            "팝콘티비 화질별 재생 서버가 허용되지 않습니다.",
                        )
                    match = re.fullmatch(r"(\d+)p(?:(\d+(?:\.\d+)?))?", name)
                    info = next(
                        (
                            p.stream_info
                            for p in getattr(
                                getattr(stream, "multivariant", None), "playlists", []
                            )
                            if p.uri == target
                        ),
                        None,
                    )
                    size = getattr(info, "resolution", None)
                    variants.append(
                        {
                            "value": name,
                            "label": name if match else "원본 · HLS",
                            "url": target,
                            "height": getattr(size, "height", None)
                            or (int(match[1]) if match else None),
                            "width": getattr(size, "width", None),
                            "fps": getattr(info, "framerate", None)
                            or (float(match[2]) if match and match[2] else None),
                            "bitrate": getattr(info, "bandwidth", None),
                        }
                    )
                if not variants:
                    raise RecordingError(
                        "popkontv_stream",
                        "팝콘티비 HLS 화질 정보를 확인할 수 없습니다.",
                    )
                return variants
            finally:
                session.http.close()

        variants = await asyncio.to_thread(resolve)
        return [dict(v) for v in variants]

    async def get_qualities(self, channel_id):
        return [
            {k: v for k, v in item.items() if k != "url"}
            for item in sorted(
                await self._streams(channel_id),
                key=lambda v: (v["height"] or 0, v["fps"] or 0),
                reverse=True,
            )
        ]

    async def resolve_stream(self, channel_id, quality="best"):
        variants = await self._streams(channel_id)
        if not variants:
            raise ValueError("팝콘티비 채널이 오프라인입니다.")
        chosen = next((v for v in variants if v["value"] == quality), None)
        if chosen is None:
            if quality not in ("best", "worst"):
                raise RecordingError(
                    "popkontv_quality",
                    "선택한 팝콘티비 화질이 없습니다. 화질 목록을 새로 조회하세요.",
                )
            chosen = (min if quality == "worst" else max)(
                variants,
                key=lambda v: (v["height"] or 0, v["fps"] or 0, v["bitrate"] or 0),
            )
        return chosen["url"], popkontv_headers(self.get_stream_url(channel_id)), None

    async def get_preview_url(self, channel_id):
        return (await self.resolve_stream(channel_id, "best"))[0]
