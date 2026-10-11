# Adapted from Chzzk-Rekoda commit 50424e50b56fca13a1a071983a4ddecdcb0f6ff2.
# Copyright (c) 2024 munsy0227. MIT license: third_party/Chzzk-Rekoda-LICENSE.
# Phrolova integration uses callbacks, native Streamlink files and post-capture conversion.
"""Small, URL-free control protocol between the plugin and recorder."""

import json
import math
from datetime import datetime


EVENT_PREFIX = "PHROLOVA_CHZZK_EVENT "
KINDS = {"start", "recovery_started", "recovery_completed", "gap", "boundary", "diagnostic", "source"}
REASONS = {
    "resume_unavailable", "playlist_stalled", "playlist_unavailable",
    "broadcast_changed", "initialization_changed", "discontinuity",
    "position_unknown", "interval_unavailable", "segment_unavailable",
    "output_stalled", "broadcast_ended",
}


def valid_time(value):
    if value is None:
        return True
    if not isinstance(value, str) or len(value) > 40:
        return False
    try:
        return datetime.fromisoformat(value).tzinfo is not None
    except ValueError:
        return False


def parse_event(line):
    if not line.startswith(EVENT_PREFIX) or len(line) > 4096:
        return None
    try:
        event = json.loads(line[len(EVENT_PREFIX):])
    except (ValueError, TypeError):
        return None
    if (not isinstance(event, dict) or event.get("version") != 1
            or not isinstance(event.get("kind"), str) or event["kind"] not in KINDS
            or type(event.get("live_id")) is not int
            or not isinstance(event.get("rendition"), str)
            or len(event["rendition"]) > 32):
        return None
    if any(not valid_time(event.get(key)) for key in ("at", "from", "to", "resume_from")):
        return None
    if event["kind"] in {"gap", "boundary"} and (
            not isinstance(event.get("reason"), str) or event["reason"] not in REASONS):
        return None
    if "after_gap" in event and type(event["after_gap"]) is not bool:
        return None
    if event["kind"] == "source":
        if (any(not isinstance(event.get(key), str) for key in ("cdn", "mode", "state"))
                or event.get("cdn") not in {"korean", "akamai", "unknown"}
                or event.get("mode") not in {"hls", "llhls"}
                or event.get("state") not in {"selected", "ready", "absent", "unavailable"}):
            return None
        return {key: event[key] for key in ("version", "kind", "live_id", "rendition", "cdn", "mode", "state")}
    if event["kind"] == "diagnostic":
        if (any(not isinstance(event.get(key), str) for key in ("stage", "role", "category"))
                or event["stage"] not in {"manifest", "api", "initialization", "media"}
                or event.get("role") not in {"current", "history", "primary", "alternate"}
                or event.get("category") not in {
                    "http", "network", "timeout", "truncated", "invalid_media",
                    "initialization", "unavailable"}):
            return None
        status, sequence = event.get("status"), event.get("sequence")
        if ((status is not None and (type(status) is not int or not 100 <= status <= 599))
                or (sequence is not None and (type(sequence) is not int or sequence < 0))):
            return None
    if event["kind"] == "start":
        seconds = event.get("available_seconds")
        if ((type(event.get("requested_seconds")) not in (int, float) or not 0 <= event["requested_seconds"] <= 86400)
                or type(seconds) not in (int, float)
                or not math.isfinite(seconds) or seconds < 0):
            return None
    fields = {"version", "kind", "live_id", "rendition", "at", "from", "to",
              "resume_from", "after_gap", "reason", "requested_seconds", "available_seconds",
              "time_machine_active", "stage", "role", "category", "status", "sequence"}
    return {key: value for key, value in event.items() if key in fields}


def format_log_time(value):
    """Show segment positions in the same local timezone as the log prefix."""
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value).astimezone().isoformat(
            sep=" ", timespec="milliseconds"
        )
    except (ValueError, OverflowError, OSError):
        return None
