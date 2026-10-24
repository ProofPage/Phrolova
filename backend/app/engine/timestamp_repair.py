"""Repair observed H.264/AAC TS clock resets without re-encoding media."""
from __future__ import annotations

import subprocess
import tempfile
from decimal import Decimal
from pathlib import Path

from app.core.config import get_settings


def _run(command, output=subprocess.DEVNULL):
    with tempfile.TemporaryFile() as errors:
        result = subprocess.run(
            command, stdin=subprocess.DEVNULL, stdout=output, stderr=errors,
            timeout=21600, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        errors.seek(0, 2)
        errors.seek(max(0, errors.tell() - 65536))
        detail = errors.read().decode("utf-8", "replace")
    if result.returncode:
        raise RuntimeError(f"시간축 보정 도구 실패: {detail}")
    return detail


def _rows(path, entries, *, frames=False):
    probe = get_settings().resolve_ffprobe_path()
    with tempfile.TemporaryFile(mode="w+b") as output:
        detail = _run([
            probe, "-v", "error", "-select_streams", "v:0",
            "-show_frames" if frames else "-show_packets",
            "-show_entries", entries, "-of", "compact=p=0", str(path),
        ], output)
        if detail.strip():
            raise RuntimeError(f"시간축 검사 실패: {detail}")
        output.seek(0)
        for line in output:
            row = dict(
                part.split("=", 1) for part in line.decode("utf-8").strip().split("|")
                if "=" in part
            )
            if row:
                yield row


def _frame_clock_filter(path):
    """Move only decoded presentation-order regressions by one source tick."""
    previous = None
    repairs = {}
    for row in _rows(path, "frame=pts,pkt_pos", frames=True):
        if "pts" not in row or "pkt_pos" not in row:
            raise RuntimeError("프레임 시간과 패킷 위치를 확인하지 못했습니다.")
        stamp = int(row["pts"])
        if previous is not None and stamp <= previous:
            position = row["pkt_pos"]
            if position in repairs:
                raise RuntimeError("하나의 패킷에 여러 시간축 보정이 필요합니다.")
            repairs[position] = previous + 1 - stamp
            stamp = previous + 1
        previous = stamp
    if previous is None:
        raise RuntimeError("시간축을 검사할 영상 프레임이 없습니다.")
    if not repairs:
        return None, 0
    expressions = []
    for index, row in enumerate(_rows(path, "packet=pos")):
        if row.get("pos") in repairs:
            expressions.append(f"{repairs.pop(row['pos'])}*eq(N\\,{index})")
    if repairs:
        raise RuntimeError("보정할 프레임과 원본 패킷을 대응하지 못했습니다.")
    return "setts=pts=PTS+" + "+".join(expressions), len(expressions)


def repair_ts_clock(source, candidate, media):
    """Replace only the caller-owned unpublished candidate; preserve source TS.

    Independent demuxers prevent an audio reset from shifting the video clock
    a second time. Original stream start offsets survive the final remux.
    Unsupported layouts retain the existing warning instead of guessing.
    """
    tracks = media["tracks"]
    video = [t for t in tracks if t.get("codec_type") == "video"]
    audio = [t for t in tracks if t.get("codec_type") == "audio"]
    if (len(video) != 1 or len(audio) != 1
            or video[0].get("codec_name") != "h264"
            or audio[0].get("codec_name") != "aac"):
        return {"applied": False, "reason": "unsupported_stream_layout"}
    ordered = [video[0], audio[0]]
    starts = [Decimal(t["start_time"]) for t in ordered]
    if not all(value.is_finite() for value in starts):
        raise RuntimeError("원본 스트림 시작 시간을 확인하지 못했습니다.")
    origin = min(starts)
    source, candidate = Path(source), Path(candidate)
    if source.resolve() == candidate.resolve():
        raise RuntimeError("원본을 시간축 보정 결과로 덮어쓸 수 없습니다.")
    ffmpeg = get_settings().resolve_ffmpeg_path()
    prefix = [ffmpeg, "-hide_banner", "-v", "warning", "-nostdin", "-n"]
    before = (source.stat().st_size, source.stat().st_mtime_ns)
    with tempfile.TemporaryDirectory(prefix=".phrolova-clock-", dir=candidate.parent) as folder:
        parts = [Path(folder) / "video.mkv", Path(folder) / "audio.mka"]
        for track, part in zip(ordered, parts):
            _run(prefix + ["-i", str(source), "-map", f"0:{track['index']}",
                           "-c", "copy", "-f", "matroska", str(part)])
        expression, adjusted = _frame_clock_filter(parts[0])
        repaired = Path(folder) / ("repaired" + candidate.suffix)
        command = list(prefix)
        for start, part in zip(starts, parts):
            command += ["-itsoffset", str(start - origin), "-i", str(part)]
        command += ["-map", "0:v:0", "-map", "1:a:0", "-c", "copy"]
        if expression:
            command += ["-bsf:v:0", expression]
        if candidate.suffix == ".mp4":
            command += ["-movflags", "+faststart"]
        _run(command + [str(repaired)])
        # Preserve the demuxer's clock; a guessed encoder frame rate can itself
        # round distinct VFR timestamps to the same null-muxer tick.
        detail = _run([
            ffmpeg, "-nostdin", "-v", "error", "-xerror", "-err_detect", "explode",
            "-i", str(repaired), "-map", "0:v?", "-map", "0:a?",
            "-enc_time_base", "demux", "-f", "null", "-",
        ])
        if detail.strip():
            raise RuntimeError(f"시간축 보정 결과의 전체 디코딩 검사 실패: {detail}")
        if (source.stat().st_size, source.stat().st_mtime_ns) != before:
            raise RuntimeError("시간축 보정 중 원본 파일이 변경되었습니다.")
        repaired.replace(candidate)
    return {
        "applied": True, "method": "independent_stream_clocks",
        "adjusted_video_frames": adjusted, "reencoded": False,
        "stream_start_offsets_seconds": [str(start - origin) for start in starts],
        "full_decode": "passed",
    }
