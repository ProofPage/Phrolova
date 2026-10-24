"""기본 다운로드 실패 시에만 사용하는 독립 HLS 예비 다운로더."""
import asyncio
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

from app.engine.platform_auth import authentication_required


@lru_cache(maxsize=8)
def supports_cookie_file(binary):
    result = subprocess.run(
        [binary, "--help"], capture_output=True, timeout=10,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return result.returncode == 0 and b"--cookies " in result.stdout


def fallback_stream(info, error):
    """이미 선택된 단일 비DRM VOD만 허용한다. 다른 화질을 추측하지 않는다."""
    if authentication_required(error) or any(
        word in str(error).lower() for word in ("drm", "disk", "permission", "공간", "권한")
    ):
        return None
    items = info.get("requested_downloads") or [info]
    if len(items) != 1:
        return None
    stream = items[0]
    if (info.get("_type") == "multi_video" or info.get("is_live")
            or info.get("has_drm") or stream.get("has_drm")
            or stream.get("requested_formats") or not stream.get("url")
            or stream.get("protocol") not in ("m3u8", "m3u8_native")):
        return None
    headers = {**info.get("http_headers", {}), **stream.get("http_headers", {})}
    if any(name.lower() in ("cookie", "authorization") for name in headers):
        return None
    return {**stream, "http_headers": headers}


async def download_hls(task, stream, binary, ffmpeg, output, cookie_file=None):
    from app.engine.vod import DownloadCancelledError
    output = Path(output)
    if task.cancel_flag:
        raise DownloadCancelledError("다운로드가 취소되었습니다.")
    if cookie_file and not await asyncio.to_thread(supports_cookie_file, binary):
        raise RuntimeError("설치된 N_m3u8DL-RE는 도메인별 쿠키 파일을 지원하지 않습니다. 쿠키 파일을 지원하는 버전이 필요합니다.")
    if output.exists():
        raise FileExistsError("예비 다운로드 출력 파일이 이미 존재합니다.")
    with tempfile.TemporaryDirectory(prefix="phrolova-fallback-", dir=output.parent) as temporary:
        folder = Path(temporary)
        args = [
            binary, stream["url"], "--save-dir", str(folder), "--tmp-dir", str(folder / "parts"),
            "--save-name", "fallback", "--auto-select", "--no-log",
            "--write-meta-json", "false", "--log-level", "OFF",
            "--ffmpeg-binary-path", ffmpeg, "--mux-after-done", f"format={output.suffix[1:]}",
        ]
        for name, value in stream["http_headers"].items():
            if name.lower() in ("user-agent", "referer", "origin"):
                args.extend(["--header", f"{name}: {value}"])
        if cookie_file:
            args.extend(["--cookies", cookie_file])
        process = await asyncio.create_subprocess_exec(
            *args, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        task.process = process
        try:
            while process.returncode is None:
                if task.cancel_flag:
                    raise DownloadCancelledError("다운로드가 취소되었습니다.")
                try:
                    await asyncio.wait_for(process.wait(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
            if task.cancel_flag:
                raise DownloadCancelledError("다운로드가 취소되었습니다.")
            candidate = folder / ("fallback" + output.suffix)
            if process.returncode or not candidate.is_file() or not candidate.stat().st_size:
                raise RuntimeError(f"N_m3u8DL-RE 예비 다운로드 실패 (종료 코드: {process.returncode})")
            candidate.rename(output)
            return str(output)
        finally:
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
            task.process = None
