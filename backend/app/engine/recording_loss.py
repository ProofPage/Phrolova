"""Bounded capture diagnostics; sequence gaps are not claimed to be lost frames."""
from __future__ import annotations

import json
from pathlib import Path
import threading
import uuid


class RecordingLossReport:
    def __init__(self):
        self._lock = threading.Lock()
        self.transport = "hls"
        self.tracks = {}
        self.time_gaps = []
        self.omitted_ranges = 0
        self.segment_errors = 0

    def segment(self, track, number):
        if type(number) is not int or not 0 <= number < 2**64:
            self.error()
            raise ValueError("Invalid HLS media sequence number")
        with self._lock:
            state = self.tracks.setdefault(str(track), {
                "first_sequence": number, "last_sequence": number, "completed_segment_writes": 0,
                "sequence_resets": 0, "sequence_gaps": [],
            })
            previous = state["last_sequence"]
            if state["completed_segment_writes"] and number > previous + 1:
                ranges = state["sequence_gaps"]
                if len(ranges) < 64:
                    ranges.append({"first": previous + 1, "last": number - 1})
                else:
                    self.omitted_ranges += 1
            elif state["completed_segment_writes"] and number < previous:
                state["sequence_resets"] += 1
            state["last_sequence"] = number
            state["completed_segment_writes"] += 1

    def gap(self, event):
        with self._lock:
            if len(self.time_gaps) < 64:
                self.time_gaps.append({key: event.get(key) for key in ("from", "to", "reason")})
            else:
                self.omitted_ranges += 1

    def error(self):
        with self._lock:
            self.segment_errors += 1

    def snapshot(self):
        with self._lock:
            return json.loads(json.dumps({
                "version": 1, "transport": self.transport,
                "segment_tracking": "not_applicable" if self.transport == "http-flv" else "observed_writes",
                "sequence_gaps_are_not_frame_counts": True,
                "tracks": self.tracks, "time_gaps": self.time_gaps,
                "omitted_ranges": self.omitted_ranges, "segment_errors": self.segment_errors,
            }))

    def write(self, output_path, summary):
        path = Path(output_path).with_suffix(".losscheck")
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps({**self.snapshot(), **summary}, ensure_ascii=False,
                                            allow_nan=False, indent=2), encoding="utf-8")
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        return str(path)
