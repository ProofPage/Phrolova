"""Bounded, non-destructive container inspection (never decode an entire video)."""
from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path
from typing import Any

from app.core.config import get_settings


MESSAGES = {
    "missing_file": "다운로드한 파일을 찾을 수 없습니다.",
    "empty_file": "다운로드한 파일이 비어 있습니다.",
    "access_denied": "다운로드한 파일에 접근할 수 없습니다.",
    "tool_missing": "파일 검사 도구를 찾을 수 없습니다.",
    "tool_failed": "파일 검사 도구를 실행하지 못했습니다.",
    "timeout": "파일 검사 시간이 초과되었습니다.",
    "invalid_response": "파일 정보를 확인하지 못했습니다.",
    "probe_failed": "파일 정보를 확인하지 못했습니다.",
}


class InspectionError(RuntimeError):
    def __init__(self, code: str, detail: str = "", *, stderr: str = "", returncode: int | None = None):
        super().__init__(MESSAGES[code])
        self.code = code
        self.diagnostics = {"detail": detail, "stderr": stderr, "returncode": returncode}


def probe_media(filepath: str) -> dict[str, Any]:
    path = Path(filepath).expanduser().absolute()
    try:
        size = path.stat().st_size
        if not path.is_file():
            raise InspectionError("missing_file", str(path))
        if size <= 0:
            raise InspectionError("empty_file", str(path))
        # Check actual read permission, including ACLs/root where os.access differs.
        with path.open("rb") as file:
            file.read(1)
    except FileNotFoundError as exc:
        raise InspectionError("missing_file", str(exc)) from exc
    except OSError as exc:
        raise InspectionError("access_denied", str(exc)) from exc
    settings = get_settings()
    try:
        binary = settings.resolve_ffprobe_path()
    except FileNotFoundError as exc:
        raise InspectionError("tool_missing", str(exc)) from exc
    args = [binary, "-v", "error", "-show_entries",
            "format=duration,size,format_name:stream=index,codec_type,codec_name,duration,width,height,avg_frame_rate",
            "-of", "json", str(path)]
    try:
        result = subprocess.run(args, capture_output=True, timeout=settings.file_inspection_timeout,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired as exc:
        # subprocess.run kills and waits for the child on timeout.
        raise InspectionError("timeout", str(exc), stderr=(exc.stderr or b"").decode("utf-8", "replace")) from exc
    except OSError as exc:
        raise InspectionError("tool_failed", str(exc)) from exc
    stderr = result.stderr.decode("utf-8", "replace")
    if result.returncode:
        raise InspectionError("probe_failed", "FFprobe exited unsuccessfully", stderr=stderr, returncode=result.returncode)
    try:
        parsed = json.loads(result.stdout.decode("utf-8"))
        fmt = parsed.get("format") or {}
        tracks = parsed.get("streams") or []
        if not isinstance(fmt, dict) or not isinstance(tracks, list) or not all(isinstance(track, dict) for track in tracks):
            raise ValueError("Invalid format/stream structure")
        duration = None
        # Some valid containers omit format.duration; stream duration is optional too.
        for value in [fmt.get("duration"), *(track.get("duration") for track in tracks)]:
            try:
                number = float(value)
                if math.isfinite(number) and number >= 0:
                    duration = max(duration or 0, number)
            except (TypeError, ValueError):
                continue
        return {"duration": duration, "size": size, "format_name": fmt.get("format_name", ""),
                "streams": {track.get("codec_type") for track in tracks}, "tracks": tracks,
                "diagnostics": {"stderr": stderr, "returncode": result.returncode, "binary": binary}}
    except (UnicodeError, ValueError, TypeError, AttributeError) as exc:
        raise InspectionError("invalid_response", str(exc), stderr=stderr, returncode=result.returncode) from exc
