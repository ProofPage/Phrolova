"""Opt-in real live time-machine soak; never part of the normal pytest suite.

Run from the backend with two live channel IDs: an older-than-one-hour
broadcast and one still younger than an hour. It records original media into
a uniquely allocated temporary directory and retains it for inspection.
"""

import argparse
import asyncio
import json
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import get_settings
from app.engine.pipeline.ytdlp import YtdlpLivePipeline
from app.engine.chzzk_continuity import ChzzkContinuityWriter
from app.engine.platform_auth import redact_media_error


async def main(args):
    settings = get_settings()
    settings.chzzk_stream_mode = "force-timemachine"
    settings.chzzk_time_machine_offset = 0
    settings.chzzk_live_cdn = "default"
    settings.save_live_preview = False
    directory = Path(tempfile.mkdtemp(prefix="phrolova-live-soak-"))
    pipes = [YtdlpLivePipeline(channel) for channel in args.channels]
    measurements = [{"segments": 0, "start": None, "end": None, "errors": [],
                     "available_seconds": None} for _ in pipes]
    transferred = 0
    transfer_lock = threading.Lock()
    http_times = {}
    original_http = ChzzkContinuityWriter.http_bytes

    def measure(writer, uri, byterange=None):
        nonlocal transferred
        before = time.monotonic()
        data = original_http(writer, uri, byterange)
        with transfer_lock:
            transferred += len(data)
            count, seconds = http_times.get(writer.stream._channel_id, (0, 0))
            http_times[writer.stream._channel_id] = (count + 1, seconds + time.monotonic() - before)
        return data

    ChzzkContinuityWriter.http_bytes = measure
    for pipe, state in zip(pipes, measurements):
        original = pipe._accept_continuity_event

        def observe(event, state=state, original=original):
            original(event)
            if event["kind"] == "start":
                state["available_seconds"] = event["available_seconds"]
            if event["kind"] == "checkpoint":
                begin = datetime.fromisoformat(event["from"])
                end = datetime.fromisoformat(event["to"])
                if state["end"] is not None and abs((begin - state["end"]).total_seconds()) > 0.02:
                    state["errors"].append("Non-contiguous live media checkpoint")
                state["start"] = state["start"] or begin
                state["end"] = end
                state["segments"] += 1
            if event["kind"] in ("gap", "boundary"):
                state["errors"].append(event.get("reason", event["kind"]))

        pipe._accept_continuity_event = observe

    started = time.monotonic()
    try:
        await asyncio.gather(*(
            pipe.start_recording(
                stream_obj="https://chzzk.naver.com/live/" + channel,
                output_dir=str(directory), filename=f"{index}.ts",
                cookie_str=(f"NID_AUT={settings.nid_aut}; NID_SES={settings.nid_ses}"
                            if settings.nid_aut and settings.nid_ses else None),
            )
            for index, (pipe, channel) in enumerate(zip(pipes, args.channels))
        ))
        assert measurements[0]["available_seconds"] == 3600
        assert 0 < measurements[1]["available_seconds"] < 3600
        print(json.dumps({
            "phase": "live-start-positions",
            "channels": [{
                "id": pipe.channel_id, "available_seconds": state["available_seconds"],
                "first_saved_utc": state["start"].isoformat() if state["start"] else None,
                "live_lag_seconds": round((datetime.now(timezone.utc) - state["end"]).total_seconds(), 2)
                if state["end"] else None,
            } for pipe, state in zip(pipes, measurements)],
        }, ensure_ascii=False), flush=True)
        previous_time, previous_bytes = time.monotonic(), transferred
        live_since = None
        caught_up = False
        live_edges = [
            pipe._readers[0].worker.live_edge
            * pipe._readers[0].stream.continuity.primary.playlist.targetduration
            for pipe in pipes
        ]
        while time.monotonic() - started < args.seconds:
            await asyncio.sleep(min(10, max(0, args.seconds - (time.monotonic() - started))))
            now = datetime.now(timezone.utc)
            elapsed = time.monotonic() - previous_time
            control_started = time.monotonic()
            await asyncio.wait_for(asyncio.to_thread(lambda: True), 2)
            print(json.dumps({
                "wall_seconds": round(time.monotonic() - started, 1),
                "control_round_trip_ms": round((time.monotonic() - control_started) * 1000, 2),
                "successful_HTTP_MBps": round((transferred - previous_bytes) / elapsed / 1024**2, 3),
                "channels": [{
                    "id": pipe.channel_id, "state": pipe.state.value,
                    "initial_available_seconds": state["available_seconds"],
                    "captured_seconds": (state["end"] - state["start"]).total_seconds()
                    if state["end"] and state["start"] else 0,
                    "live_lag_seconds": round((now - state["end"]).total_seconds(), 2)
                    if state["end"] else None,
                    "segments": state["segments"], "errors": state["errors"],
                    "segment_workers": pipe._readers[0].writer.threads,
                    "active_media_requests": len(pipe._readers[0].writer.pending_requests),
                    "mean_HTTP_seconds": round(
                        http_times[pipe.channel_id][1] / http_times[pipe.channel_id][0], 3,
                    ),
                } for pipe, state in zip(pipes, measurements)],
            }, ensure_ascii=False), flush=True)
            previous_time, previous_bytes = time.monotonic(), transferred
            assert all(not state["errors"] and not pipe._closed
                       for pipe, state in zip(pipes, measurements)), "Live recording interrupted"
            at_live_edge = all(
                state["end"] is not None
                and (now - state["end"]).total_seconds() <= edge
                for state, edge in zip(measurements, live_edges)
            )
            live_since = (live_since or time.monotonic()) if at_live_edge else None
            if live_since is not None and time.monotonic() - live_since >= args.hold:
                caught_up = True
                break
    finally:
        results = await asyncio.gather(*(pipe.stop_recording() for pipe in pipes), return_exceptions=True)
        ChzzkContinuityWriter.http_bytes = original_http
        print(json.dumps({
            "output_directory": str(directory),
            "stops": [redact_media_error(str(result)) if isinstance(result, BaseException) else "closed"
                      for result in results],
            "output_errors": [pipe.output_errors for pipe in pipes],
        }, ensure_ascii=False), flush=True)
    assert all(not pipe.output_errors for pipe in pipes)
    assert all(state["start"] is not None and state["end"] is not None and not state["errors"]
               for state in measurements)
    assert caught_up, "Live catch-up did not reach and stay at the current broadcast"
    print("PASS: live time-machine catch-up and contiguous checkpoints without a speed cap", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("channels", nargs=2)
    parser.add_argument("--seconds", type=int, default=1200)
    parser.add_argument("--hold", type=int, default=120)
    asyncio.run(main(parser.parse_args()))
