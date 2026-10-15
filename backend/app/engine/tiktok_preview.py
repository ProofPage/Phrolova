"""녹화와 이미지 미리보기가 같은 TikTok FLV 연결을 경쟁해서 열지 않게 한다."""
from collections import deque
import threading
import time


_lock = threading.Lock()
_captures = {}


class CapturePreview:
    MAX_BYTES = 4 * 1024 * 1024

    def __init__(self, channel_id):
        self.channel_id = channel_id
        self.header = b''
        self.config = {}
        self.frames = deque()
        self.size = 0
        self.updated = 0
        self.has_keyframe = False
        self.lock = threading.Lock()

    def feed(self, data, *, header=False):
        with self.lock:
            if header:
                self.header = data
                return
            kind, body = data[0] & 31, data[11:-4]
            if not body:
                return
            sequence = False
            keyframe = False
            if kind == 9:
                enhanced = bool(body[0] & 128)
                packet_type = body[0] & 15 if enhanced else body[1] if len(body) > 1 else -1
                sequence = packet_type == 0
                keyframe = (body[0] >> 4 & 7) == 1 and packet_type in (1, 3)
            elif kind == 8:
                sequence = len(body) > 1 and body[0] >> 4 == 10 and body[1] == 0
            if sequence or kind == 18:
                if len(data) <= 65536:
                    self.config[kind] = data
                return
            if keyframe:
                self.frames.clear()
                self.size = 0
                self.has_keyframe = True
            if not self.has_keyframe:
                return
            if self.size + len(data) > self.MAX_BYTES:
                self.frames.clear()
                self.size = 0
                self.has_keyframe = False
                return
            self.frames.append(data)
            self.size += len(data)
            if kind == 9:
                self.updated = time.monotonic()

    def snapshot(self):
        with self.lock:
            if not self.header or not self.has_keyframe or time.monotonic()-self.updated > 8:
                return None
            return self.header+b''.join(self.config.values())+b''.join(self.frames)

    def close(self):
        with _lock:
            if _captures.get(self.channel_id) is self:
                _captures.pop(self.channel_id, None)


def register_capture(channel_id):
    capture = CapturePreview(channel_id)
    with _lock:
        _captures[channel_id] = capture
    return capture


def capture_snapshot(channel_id):
    with _lock:
        capture = _captures.get(channel_id)
    return (True, capture.snapshot()) if capture else (False, None)
