"""Read YouTube's signed live DASH sequences without transcoding the source."""

import threading
import time
from types import SimpleNamespace
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

from app.engine.recording_errors import RecordingError


def media_url(url):
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if (parsed.scheme != "https" or not host.endswith(".googlevideo.com")
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise RecordingError("invalid_stream", "유튜브 원본 스트림 주소를 확인하지 못했습니다.")
    return url


def sequence_url(url, sequence):
    parsed = urlsplit(media_url(url))
    query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
             if key != "sq"]
    return urlunsplit(parsed._replace(query=urlencode([*query, ("sq", str(sequence))])))


class DashReader:
    """One track, one complete fragment buffered; stop drains accepted bytes."""

    capture_format = "youtube_dash"
    MAX_FRAGMENT_BYTES = 64 * 1024 * 1024

    def __init__(self, track, resume, index):
        self.track = track
        self.resume = resume
        self.index = index
        self.session = requests.Session()
        self.session.headers.update({
            key: value for key, value in (track.get("http_headers") or {}).items()
            if key.lower() not in ("cookie", "authorization", "host")
        })
        self.url = media_url(track["url"])
        self.duration = float(track["target_duration"])
        if self.duration <= 0:
            raise RecordingError("invalid_stream", "DASH 구간 길이를 확인하지 못했습니다.")
        self.next_sequence = None
        self.buffer = b""
        self.pending_sequence = None
        self.received_duration = 0.0
        self.stop = threading.Event()
        self.is_finished = False
        self.stream = SimpleNamespace()

    def head(self):
        target = self.url
        for _ in range(3):
            with self.session.head(target, timeout=5, allow_redirects=False) as response:
                if response.is_redirect:
                    loc = response.headers.get("location")
                    if loc:
                        target = media_url(loc)
                        self.url = target
                        continue
                    raise RecordingError("invalid_stream", "유튜브 CDN 주소가 변경되었습니다.")
                response.raise_for_status()
                value = response.headers.get("X-Head-Seqnum")
                if value is None or not value.isdecimal():
                    raise RecordingError("invalid_stream", "DASH 라이브 위치를 확인하지 못했습니다.")
                return int(value)
        raise RecordingError("invalid_stream", "유튜브 CDN 리디렉션 횟수를 초과했습니다.")

    def read(self, size):
        if not self.buffer and self.pending_sequence is not None:
            # The caller has written the preceding read before asking for more.
            self.resume[self.index] = self.pending_sequence + 1
            self.received_duration += self.duration
            self.pending_sequence = None
        if not self.buffer:
            if self.stop.is_set():
                return b""
            deadline = time.monotonic() + 60
            while self.next_sequence > self.head():
                if self.stop.wait(2):
                    return b""
                if time.monotonic() >= deadline:
                    raise TimeoutError("YouTube DASH segment timeout")
            # Download a complete fragment before exposing any of it to the writer.
            chunks = []
            total = 0
            cur_url = sequence_url(self.url, self.next_sequence)
            for _ in range(3):
                with self.session.get(cur_url,
                                      timeout=5, stream=True, allow_redirects=False) as response:
                    if response.is_redirect:
                        loc = response.headers.get("location")
                        if loc:
                            self.url = media_url(loc)
                            cur_url = sequence_url(self.url, self.next_sequence)
                            continue
                        raise RecordingError("invalid_stream", "유튜브 CDN 주소가 변경되었습니다.")
                    response.raise_for_status()
                    for chunk in response.iter_content(128 * 1024):
                        total += len(chunk)
                        if total > self.MAX_FRAGMENT_BYTES:
                            raise RecordingError("invalid_stream", "DASH 구간 크기가 허용 범위를 초과했습니다.")
                        chunks.append(chunk)
                    break
            if not total:
                raise RuntimeError("YouTube DASH returned an empty segment")
            self.buffer = b"".join(chunks)
            self.pending_sequence = self.next_sequence
            self.next_sequence += 1
        data, self.buffer = self.buffer[:size], self.buffer[size:]
        return data

    def request_stop(self):
        self.stop.set()

    def close(self):
        # Do not close a socket underneath a writer; it must finish its fragment.
        self.request_stop()


class DashSession:
    def __init__(self, readers):
        self.readers = readers
        self.http = self

    def close(self):
        for reader in self.readers:
            reader.session.close()


def open_dash(tracks, resume, from_start):
    readers = []
    try:
        for index, track in enumerate(tracks):
            readers.append(DashReader(track, resume, index))
        heads = [reader.head() for reader in readers]
        # Audio and video share a media-time boundary, not independent "now"s.
        edge = min((head + 1) * reader.duration for head, reader in zip(heads, readers))
        for reader, head in zip(readers, heads):
            earliest = max(0, head + 1 - int(432000 / reader.duration))
            start = earliest if from_start else max(earliest, int(edge / reader.duration) - 1)
            reader.next_sequence = resume.get(reader.index, start)
        return DashSession(readers), readers
    except BaseException:
        DashSession(readers).close()
        raise
