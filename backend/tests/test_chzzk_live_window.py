"""Complete one-hour live backlog and a moving live window."""

import contextlib
import struct
import threading

import pytest

from tests.test_chzzk_recording_isolation import writer
from tests.test_chzzk_continuity import CDN, INITIALIZATION, box


@pytest.mark.parametrize("initial_segments", [600, 1800])
def test_live_start_and_full_hour_roll_forward_without_duplicate_or_missing_media(initial_segments):
    with contextlib.ExitStack() as stack:
        cdn = stack.enter_context(CDN())
        media = [box(b"moof", struct.pack(">I", i)) + box(b"mdat", struct.pack(">I", i))
                 for i in range(1802)]
        cdn.playlist("primary", indices=range(2, 1802), media=media, duration=2)
        final_window = cdn.assets["/primary/1080p/list.m3u8"]
        cdn.playlist("primary", indices=range(initial_segments), media=media, duration=2, end=False)
        first_media = threading.Event()
        cdn.request_events["/primary/1080p/0.m4v"] = first_media

        def advance():
            if first_media.wait(10):
                # The live server drops the oldest two segments and adds new
                # media while the recorder is still receiving its backlog.
                cdn.assets["/primary/1080p/list.m3u8"] = final_window

        updater = threading.Thread(target=advance, daemon=True)
        updater.start()
        reader, source = writer(stack, cdn, time_machine=True)
        events = []
        source.event_callback = events.append
        reader.open()
        captured = bytearray()
        while data := reader.read(65536):
            captured.extend(data)
        updater.join(timeout=1)
        assert first_media.is_set()
        assert bytes(captured) == INITIALIZATION + b"".join(media)
        start = next(event for event in events if event["kind"] == "start")
        assert start["available_seconds"] == initial_segments * 2
        assert len([event for event in events if event["kind"] == "checkpoint"]) == 1802
        assert not any(event["kind"] in ("gap", "boundary") for event in events)
