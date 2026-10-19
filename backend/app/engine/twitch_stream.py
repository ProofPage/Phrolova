"""Twitch advertisement state and byte-exact capture boundaries."""
from collections import deque
from dataclasses import replace
import threading
import time

from streamlink.plugins.twitch import TwitchHLSStream
from streamlink.exceptions import StreamError


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
