"""Bounded ISO-BMFF timing parser; reads clocks, never decodes media."""

import struct


def boxes(data):
    pos = 0
    while pos + 8 <= len(data):
        size, kind = struct.unpack_from(">I4s", data, pos)
        if size < 8 or pos + size > len(data):
            return
        yield kind, data[pos + 8 : pos + size]
        pos += size


class NativeClock:
    def __init__(self):
        self.buffer = bytearray()
        self.remaining = 0
        self.kind = None
        self.body = bytearray()
        self.timescale = None
        self.first = None
        self.duration = None
        self.pending_duration = None
        self.media_seen = False
        self.video_track = None
        self.position = 0
        self.complete_media_end = 0

    def feed(self, data):
        self.buffer.extend(data)
        while self.buffer:
            if not self.remaining:
                if len(self.buffer) < 8:
                    return
                size, self.kind = struct.unpack_from(">I4s", self.buffer)
                if size == 1:
                    if len(self.buffer) < 16:
                        return
                    size = struct.unpack_from(">Q", self.buffer, 8)[0]
                    header = 16
                else:
                    header = 8
                if size < header or size > 2**40:
                    self.buffer.clear()
                    return
                del self.buffer[:header]
                self.position += header
                self.remaining = size - header
                self.body.clear()
                if not self.remaining:
                    continue
            take = min(self.remaining, len(self.buffer))
            if self.kind in (b"moov", b"moof") and len(self.body) + take <= 1024 * 1024:
                self.body.extend(self.buffer[:take])
            del self.buffer[:take]
            self.remaining -= take
            self.position += take
            if not self.remaining:
                if self.kind == b"mdat":
                    self.media_seen = True
                    self.complete_media_end = self.position
                    self.duration = self.pending_duration
                if self.kind == b"moov":
                    for kind, track in boxes(self.body):
                        if kind != b"trak":
                            continue
                        tkhd = next((v for k, v in boxes(track) if k == b"tkhd"), b"")
                        track_offset = 20 if tkhd and tkhd[0] == 1 else 12
                        media = next((v for k, v in boxes(track) if k == b"mdia"), b"")
                        parts = dict(boxes(media))
                        if parts.get(b"hdlr", b"")[8:12] != b"vide":
                            continue
                        if len(tkhd) >= track_offset + 4:
                            self.video_track = int.from_bytes(
                                tkhd[track_offset : track_offset + 4], "big"
                            )
                        header = parts.get(b"mdhd", b"")
                        offset = 20 if header and header[0] == 1 else 12
                        if len(header) >= offset + 4:
                            self.timescale = int.from_bytes(
                                header[offset : offset + 4], "big"
                            )
                elif self.kind == b"moof" and self.timescale:
                    for kind, track in boxes(self.body):
                        if kind != b"traf":
                            continue
                        tfhd = next((v for k, v in boxes(track) if k == b"tfhd"), b"")
                        if (
                            self.video_track is not None
                            and int.from_bytes(tfhd[4:8], "big") != self.video_track
                        ):
                            continue
                        tfdt = next((v for k, v in boxes(track) if k == b"tfdt"), b"")
                        if len(tfdt) < 8:
                            continue
                        timestamp = (
                            int.from_bytes(
                                tfdt[4:12] if tfdt[0] == 1 else tfdt[4:8], "big"
                            )
                            / self.timescale
                        )
                        if self.first is None:
                            self.first = timestamp
                        flags = int.from_bytes(tfhd[1:4], "big")
                        offset = 8
                        if flags & 1:
                            offset += 8
                        if flags & 2:
                            offset += 4
                        default_duration = (
                            int.from_bytes(tfhd[offset : offset + 4], "big")
                            if flags & 8
                            else 0
                        )
                        ticks = 0
                        for part, run in boxes(track):
                            if part != b"trun" or len(run) < 8:
                                continue
                            run_flags = int.from_bytes(run[1:4], "big")
                            count = int.from_bytes(run[4:8], "big")
                            pos = 8
                            if run_flags & 1:
                                pos += 4
                            if run_flags & 4:
                                pos += 4
                            stride = 4 * sum(
                                bool(run_flags & f) for f in (256, 512, 1024, 2048)
                            )
                            if run_flags & 256:
                                for sample in range(
                                    min(count, (len(run) - pos) // max(1, stride))
                                ):
                                    ticks += int.from_bytes(
                                        run[
                                            pos
                                            + sample * stride : pos
                                            + sample * stride
                                            + 4
                                        ],
                                        "big",
                                    )
                            else:
                                ticks += default_duration * count
                        delta = timestamp - self.first + ticks / self.timescale
                        if 0 <= delta < 86400 * 7:
                            self.pending_duration = max(self.duration or 0, delta)
                        break
