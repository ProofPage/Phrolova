"""Byte-exact boundaries shared by live HLS capture streams."""
from collections import deque
import threading


class CaptureBoundaryStream:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._written = 0
        self._read = 0
        self._boundaries = deque()
        self._boundary_lock = threading.Lock()

    def split_capture_data(self, data):
        """Split reader data at boundaries published before the next write."""
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


class CaptureBoundaryWriter:
    def _write_into_buffer(self, iterator):
        def counted():
            for chunk in iterator:
                self.stream._written += len(chunk)
                yield chunk
        return super()._write_into_buffer(counted())
