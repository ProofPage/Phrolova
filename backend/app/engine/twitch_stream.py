"""Twitch advertisement state and byte-exact capture boundaries.

TTV-AB 23.0.2 (GosuDRM/TTV-AB) ad metadata signature patterns are integrated into
Streamlink's TwitchM3U8Parser for zero-ad capture precision.
"""
from collections import deque
from dataclasses import replace
import re
import threading
import time

from streamlink.plugins.twitch import TwitchHLSStream, TwitchM3U8Parser
from streamlink.exceptions import StreamError

# TTV-AB 23.0.2 comprehensive ad metadata pattern
TTV_AB_AD_METADATA_RE = re.compile(
    r'stitched-ad|X-TV-TWITCH-AD|/adsquared/|SCTE35-OUT|EXT-X-CUE-OUT'
    r'|twitch-(?:stitched-)?ad|midroll',
    re.I
)

# Monkey-patch Streamlink's Twitch DateRange parser with TTV-AB rules
_orig_is_daterange_ad = TwitchM3U8Parser._is_daterange_ad


def _ttv_ab_is_daterange_ad(daterange):
    if _orig_is_daterange_ad(daterange):
        return True
    from app.core.config import get_settings
    if not get_settings().twitch_ttv_ab_enabled:
        return False
    cls = str(getattr(daterange, "classname", "") or "")
    dr_id = str(getattr(daterange, "id", "") or "")
    if TTV_AB_AD_METADATA_RE.search(cls) or TTV_AB_AD_METADATA_RE.search(dr_id):
        return True
    attrs = getattr(daterange, "attributes", None)
    if isinstance(attrs, dict):
        for k, v in attrs.items():
            if TTV_AB_AD_METADATA_RE.search(str(k)) or TTV_AB_AD_METADATA_RE.search(str(v)):
                return True
    return False


TwitchM3U8Parser._is_daterange_ad = staticmethod(_ttv_ab_is_daterange_ad)

_orig_is_segment_ad = TwitchM3U8Parser._is_segment_ad


def _ttv_ab_is_segment_ad(self, date, title=None):
    if _orig_is_segment_ad(self, date, title):
        return True
    from app.core.config import get_settings
    if not get_settings().twitch_ttv_ab_enabled:
        return False
    if title and TTV_AB_AD_METADATA_RE.search(title):
        return True
    return False


TwitchM3U8Parser._is_segment_ad = _ttv_ab_is_segment_ad

_orig_get_segment = TwitchM3U8Parser.get_segment


def _ttv_ab_get_segment(self, uri, **data):
    segment = _orig_get_segment(self, uri, **data)
    from app.core.config import get_settings
    if get_settings().twitch_ttv_ab_enabled and not segment.ad and uri and TTV_AB_AD_METADATA_RE.search(uri):
        segment.ad = True
    return segment


TwitchM3U8Parser.get_segment = _ttv_ab_get_segment


class TwitchCaptureStream(TwitchHLSStream):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ad_active = False
        self.last_activity = time.monotonic()
        self.excluded_ads = 0
        self._written = 0
        self._read = 0
        self._latest_sequence = None
        self._boundaries = deque()
        self._boundary_lock = threading.Lock()

    def split_capture_data(self, data):
        """Called by the sole capture reader, after the buffer read completed."""
        start = self._read
        self._read += len(data)
        boundaries = []
        with self._boundary_lock:
            while self._boundaries and self._boundaries[0][0] < self._read:
                boundaries.append(self._boundaries.popleft())
        offset = 0
        reason = None
        for absolute, next_reason in boundaries:
            cut = absolute - start
            if cut > offset:
                yield reason, data[offset:cut]
            offset, reason = cut, next_reason
        if offset < len(data):
            yield reason, data[offset:]


_Reader = TwitchHLSStream.__reader__
_Worker = _Reader.__worker__
_Writer = _Reader.__writer__


class TwitchCaptureWorker(_Worker):
    def process_segments(self, playlist):
        latest = playlist.segments[-1].num if playlist.segments else None
        if latest is not None and latest != self.stream._latest_sequence:
            self.stream._latest_sequence = latest
            self.stream.last_activity = time.monotonic()
        return super().process_segments(playlist)


def _send_ttv_ad_spoof():
    """TTV-AB 23.0.2: Twitch GraphQL에 광고 시청 완료 이벤트를 전송하여 강제 480p 다운그레이드 방지."""
    import requests
    from streamlink.plugins.twitch import TwitchAPI
    payload = [
        {"operationName": "ClientSideAdEventHandling_RecordAdEvent",
         "variables": {"input": {"eventName": "video_ad_impression", "eventPayload": "{}", "radToken": ""}},
         "extensions": {"persistedQuery": {"version": 1, "sha256Hash": "7e6c69e6eb59f8ccb97ab73686f3d8b7d85a72a0298745ccd8bfc68e4054ca5b"}}},
        {"operationName": "ClientSideAdEventHandling_RecordAdEvent",
         "variables": {"input": {"eventName": "video_ad_complete", "eventPayload": "{}", "radToken": ""}},
         "extensions": {"persistedQuery": {"version": 1, "sha256Hash": "7e6c69e6eb59f8ccb97ab73686f3d8b7d85a72a0298745ccd8bfc68e4054ca5b"}}},
    ]
    try:
        requests.post("https://gql.twitch.tv/gql", json=payload,
                      headers={"Client-ID": TwitchAPI.CLIENT_ID, "Content-Type": "application/json"},
                      timeout=4)
    except Exception:
        pass


class TwitchCaptureWriter(_Writer):
    def _write_plain(self, segment, response):
        if not super()._write_plain(segment, response):
            raise StreamError("Twitch media segment could not be fully received")
        return True

    def _write_decrypt(self, segment, response, key):
        if not super()._write_decrypt(segment, response, key):
            raise StreamError("Twitch encrypted segment could not be fully received")
        return True

    def _write_into_buffer(self, iterator):
        def counted():
            for chunk in iterator:
                # The boundary is published before any new segment bytes.
                self.stream._written += len(chunk)
                yield chunk
        return super()._write_into_buffer(counted())

    def write(self, segment, result, *data):
        stream = self.stream
        stream.last_activity = time.monotonic()
        if segment.ad:
            stream.ad_active = True
            stream.excluded_ads += 1
            from app.core.config import get_settings
            if get_settings().twitch_ttv_ab_enabled and stream.excluded_ads % 5 == 1:
                # 광고 감지 시 백그라운드 스레드로 ad spoofing 신호 1회 발송
                threading.Thread(target=_send_ttv_ad_spoof, daemon=True).start()
        else:
            resumed = stream.ad_active
            if stream._written and (resumed or segment.discontinuity):
                reason = "advertisement_excluded" if resumed else "stream_discontinuity"
                with stream._boundary_lock:
                    if not stream._boundaries or stream._boundaries[-1][0] != stream._written:
                        stream._boundaries.append((stream._written, reason))
            stream.ad_active = False
            # Capture splits at the exact byte boundary instead of appending
            # incompatible timestamps and merely printing a Streamlink warning.
            if segment.discontinuity:
                segment = replace(segment, discontinuity=False)
            if self.reader.is_paused():
                self.reader.resume()
        return super().write(segment, result, *data)


class TwitchCaptureReader(_Reader):
    __worker__ = TwitchCaptureWorker
    __writer__ = TwitchCaptureWriter


TwitchCaptureStream.__reader__ = TwitchCaptureReader
