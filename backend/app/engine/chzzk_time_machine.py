"""Resolve a Chzzk live time-machine HLS stream for Streamlink."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

from app.core.http import USER_AGENT, get_http_client

LIVE_DETAIL_URL = "https://api.chzzk.naver.com/service/v3/channels/{channel_id}/live-detail"
TIME_MACHINE_URL = "https://api.chzzk.naver.com/service/v1/live/{live_id}/playback/time-machine"
MAX_TIME_OFFSET_SECONDS = 86400
_TRUSTED_MEDIA_SUFFIXES = (".navercdn.com", ".pstatic.net", ".akamaized.net")


class TimeMachineUnavailableError(RuntimeError):
    """Raised when Chzzk does not provide a usable time-machine HLS stream."""


@dataclass(frozen=True)
class TimeMachineStream:
    url: str
    headers: dict[str, str]
    live_start_index: int | None
    master_url: str | None = None
    cdn: str = "default"
    warning: str | None = None


def _is_trusted_media_url(url: str) -> bool:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    try:
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and port in (None, 443)
        and not parsed.username
        and not parsed.password
        and (any(host.endswith(suffix) for suffix in _TRUSTED_MEDIA_SUFFIXES))
    )


def _media_path(media_items: list[object], cdn: str = "default") -> str:
    candidates: list[tuple[bool, bool, str]] = []
    for item in media_items:
        if isinstance(item, dict):
            media_id = item.get("mediaId", "")
            protocol = item.get("protocol", "")
            path = item.get("path", "")
        elif isinstance(item, (list, tuple)) and len(item) >= 3:
            media_id, protocol, path = item[:3]
        else:
            continue
        if isinstance(path, str) and path and (
            str(media_id).upper() == "HLS" or str(protocol).upper() == "HLS"
        ):
            candidates.append((str(media_id).upper() == "LLHLS", str(media_id).upper() == "HLS", path))

    # Choose only URLs actually returned by the platform; signed live URLs
    # cannot be changed with the VOD host replacement rule.
    candidates.sort(key=lambda candidate: (cdn == 'akamai' and (urlsplit(candidate[2]).hostname or '').endswith('.akamaized.net'), not (urlsplit(candidate[2]).hostname or '').endswith('.akamaized.net'), candidate[0], candidate[1]), reverse=True)
    for _, _, path in candidates:
        if _is_trusted_media_url(path):
            return path
    raise TimeMachineUnavailableError("Chzzk did not return a supported HLS CDN URL.")


def _parse_attributes(value: str) -> dict[str, str]:
    return {
        key: item.strip('"')
        for key, item in re.findall(r'([A-Z0-9-]+)=((?:"[^"]*")|[^,]*)', value)
    }


def _select_variant(master_text: str, master_url: str, quality: str) -> tuple[str, bool]:
    lines = [line.strip() for line in master_text.splitlines()]
    variants: list[tuple[int, float, int, str]] = []
    for index, line in enumerate(lines):
        if not line.startswith("#EXT-X-STREAM-INF:"):
            continue
        attributes = _parse_attributes(line.partition(":")[2])
        uri = next(
            (candidate for candidate in lines[index + 1:] if candidate and not candidate.startswith("#")),
            "",
        )
        if not uri:
            continue
        if not uri.startswith("https://"):
            uri = urljoin(master_url, uri)
        if not _is_trusted_media_url(uri):
            continue
        resolution = re.search(r"\d+x(\d+)", attributes.get("RESOLUTION", ""))
        height = int(resolution.group(1)) if resolution else 0
        bandwidth = int(attributes.get("AVERAGE-BANDWIDTH") or attributes.get("BANDWIDTH") or 0)
        fps = float(attributes.get("FRAME-RATE") or 0)
        variants.append((height, fps, bandwidth, uri))

    if not variants:
        if "#EXTINF:" in master_text:
            return master_url, False
        raise TimeMachineUnavailableError("The Chzzk HLS master playlist has no usable variants.")

    requested = re.fullmatch(r"(\d+)p([\d.]+)?", quality)
    max_height = int(requested[1]) if requested else None
    candidates = variants
    if max_height is not None:
        within_limit = [variant for variant in variants if 0 < variant[0] <= max_height]
        if within_limit:
            candidates = within_limit
    if requested and requested[2]:
        exact = [variant for variant in candidates if variant[0] == max_height
                 and abs(variant[1] - float(requested[2])) < 0.1]
        candidates = exact or candidates
    selected = (min if quality == "worst" else max)(
        candidates, key=lambda variant: (variant[0], variant[1], variant[2]))
    return selected[3], True


def _start_index(playlist_text: str, offset_seconds: int) -> int | None:
    durations = [
        float(match.group(1))
        for match in re.finditer(r"^#EXTINF:([0-9]+(?:\.[0-9]+)?)", playlist_text, re.MULTILINE)
    ]
    if not durations:
        return None

    if offset_seconds <= 0:
        return 0
    covered = 0.0
    for index, duration in enumerate(durations):
        covered += duration
        if covered >= offset_seconds:
            return min(index + 1, len(durations) - 1)
    raise TimeMachineUnavailableError(
        "The requested stream start offset is beyond the available time-machine playlist."
    )


async def _get_playlist_text(client: httpx.AsyncClient, url: str, headers: dict[str, str]) -> str:
    """Fetch a CDN playlist without leaking its signed URL in raised errors."""
    for attempt in range(3):
        try:
            response = await client.get(url, headers=headers, timeout=30.0)
            response.raise_for_status()
            return response.text
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            retryable = status_code in (408, 425, 429) or status_code >= 500
            if not retryable or attempt == 2:
                raise TimeMachineUnavailableError(
                    f"Chzzk HLS playlist request failed (HTTP {status_code})."
                ) from None
        except httpx.HTTPError as exc:
            if attempt == 2:
                raise TimeMachineUnavailableError(
                    f"Chzzk HLS playlist request failed ({type(exc).__name__})."
                ) from None
        await asyncio.sleep(attempt + 1)
    raise TimeMachineUnavailableError("Chzzk HLS playlist request failed after retries.")


async def resolve_time_machine_stream(
    channel_id: str,
    quality: str,
    offset_seconds: int,
    cookie_header: str | None = None,
    cdn: str = "default",
) -> TimeMachineStream:
    """Resolve the selected live HLS variant and start offset using Chzzk's API."""
    if not channel_id or not channel_id.strip():
        raise TimeMachineUnavailableError("A Chzzk channel ID is required.")
    offset_seconds = max(0, min(MAX_TIME_OFFSET_SECONDS, int(offset_seconds)))
    api_headers = {
        "User-Agent": USER_AGENT,
        "Origin": "https://chzzk.naver.com",
        "Referer": "https://chzzk.naver.com/",
    }
    if cookie_header:
        api_headers["Cookie"] = cookie_header

    client = get_http_client()
    last_error: Exception | None = None
    content: dict = {}
    for attempt in range(3):
        try:
            detail_response = await client.get(
                LIVE_DETAIL_URL.format(channel_id=channel_id),
                headers=api_headers,
                timeout=20.0,
            )
            detail_response.raise_for_status()
            detail = detail_response.json().get("content") or {}
            if detail.get("status") != "OPEN":
                raise TimeMachineUnavailableError("The Chzzk channel is no longer live.")
            live_id = detail.get("liveId")
            if not live_id:
                raise TimeMachineUnavailableError("Chzzk did not return a live ID.")

            response = await client.get(
                TIME_MACHINE_URL.format(live_id=live_id),
                headers=api_headers,
                timeout=20.0,
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("code") != 200:
                raise TimeMachineUnavailableError(
                    str(payload.get("message") or "Chzzk time-machine API returned an error.")
                )
            content = payload.get("content") or {}
            break
        except TimeMachineUnavailableError:
            raise
        except (httpx.HTTPError, ValueError, TypeError, AttributeError, KeyError) as exc:
            last_error = exc
            if attempt < 2:
                await asyncio.sleep(attempt + 1)
    else:
        raise TimeMachineUnavailableError(f"Chzzk time-machine request failed: {last_error}")

    playback = content.get("playback") or {}
    master_url = _media_path(playback.get("media") or [], cdn)
    cdn_headers = {
        "User-Agent": USER_AGENT,
        "Origin": "https://chzzk.naver.com",
        "Referer": "https://chzzk.naver.com/",
    }
    master_text = await _get_playlist_text(client, master_url, cdn_headers)
    selected_url, has_variant = _select_variant(master_text, master_url, quality)

    if has_variant:
        playlist_text = await _get_playlist_text(client, selected_url, cdn_headers)
    else:
        playlist_text = master_text

    live_start_index = _start_index(playlist_text, offset_seconds)
    if live_start_index is None:
        raise TimeMachineUnavailableError(
            "The time-machine playlist has no segment durations for the requested offset."
        )

    return TimeMachineStream(
        url=selected_url,
        headers=cdn_headers,
        live_start_index=live_start_index,
        master_url=master_url,
        cdn="akamai" if (urlsplit(master_url).hostname or "").endswith(".akamaized.net") else "default",
        warning=_cdn_warning(master_url, cdn),
    )


def _cdn_warning(url, requested):
    if requested == 'akamai' and not (urlsplit(url).hostname or '').endswith('.akamaized.net'):
        return '이 방송은 Akamai CDN을 제공하지 않아 기본 CDN으로 연결했습니다.'
    return None


async def resolve_live_cdn_stream(channel_id, quality, cookie_header=None, cdn='default'):
    """Select a trusted HLS URL from the current live-detail API."""
    import json
    headers={'User-Agent': USER_AGENT, 'Origin':'https://chzzk.naver.com', 'Referer':'https://chzzk.naver.com/'}
    if cookie_header:headers['Cookie']=cookie_header
    response=await get_http_client().get(LIVE_DETAIL_URL.format(channel_id=channel_id),headers=headers,timeout=20)
    response.raise_for_status()
    detail=response.json().get('content') or {}
    if detail.get('status') != 'OPEN':raise TimeMachineUnavailableError('치지직 방송이 종료되었습니다.')
    playback=json.loads(detail.get('livePlaybackJson') or '{}')
    url=_media_path(playback.get('media') or [],cdn)
    headers.pop('Cookie',None)
    return TimeMachineStream(url,headers,None,url,'akamai' if (urlsplit(url).hostname or '').endswith('.akamaized.net') else 'default',_cdn_warning(url,cdn))
