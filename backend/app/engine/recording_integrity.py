"""Verify the saved file, not the unobserved source broadcast."""
import hashlib
import subprocess
from pathlib import Path

from app.core.config import get_settings
from app.engine.media_inspection import probe_media


def capture_assessment(report):
    if not report or not any(track.get("completed_segment_writes", 0) for track in report.get("tracks", {}).values()):
        return "unknown"
    if (report.get("segment_errors") or report.get("omitted_ranges") or report.get("time_gaps")
            or any(track.get("sequence_gaps") or track.get("sequence_resets") for track in report["tracks"].values())):
        return "observed_discontinuities"
    return "no_observed_discontinuities"


def verify_recording(filepath):
    path = Path(filepath)
    before = path.stat()
    media = probe_media(str(path))
    if not (media["streams"] & {"video", "audio"}):
        raise ValueError("검사 가능한 영상 또는 음성 트랙이 없습니다.")
    # -xerror makes decode errors fail; stderr alone is not evidence of loss.
    result = subprocess.run(
        [get_settings().resolve_ffmpeg_path(), "-nostdin", "-v", "error",
         "-xerror", "-err_detect", "explode", "-i", str(path),
         "-map", "0:v?", "-map", "0:a?", "-enc_time_base", "demux", "-f", "null", "-"],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=21600,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("검사 중 파일이 변경되었습니다. 다시 검사하세요.")
    from app.engine.platform_auth import redact_media_error
    return {
        "scope": "saved_file_only",
        "sha256": digest.hexdigest(),
        "size_bytes": after.st_size,
        "full_decode": "passed" if result.returncode == 0 and not result.stderr.strip() else "failed",
        "returncode": result.returncode,
        "detail": redact_media_error(result.stderr.decode("utf-8", "replace")[-4000:]),
        "broadcast_completeness": "unverified",
        "limitation": "전체 디코딩 성공은 저장 파일의 검사 결과입니다. 수신하지 못한 방송 구간이나 원본과의 완전 일치는 증명하지 않습니다.",
    }
