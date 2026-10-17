"""
Phrolova: System API (시스템 및 업데이트 관리)
"""

import sys
import os
import logging
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from urllib.parse import quote
from logging.handlers import TimedRotatingFileHandler
from app.core.logger import get_log_dir, logger

router = APIRouter(prefix="/api/system", tags=["System"])

@router.get('/media-tools')
async def media_tools_status():
    import asyncio
    from app.engine.media_tools import check_media_tool
    names = ('streamlink', 'yt-dlp', 'ffmpeg', 'ffprobe')
    values = await asyncio.gather(*(asyncio.to_thread(check_media_tool, name) for name in names))
    return dict(zip(names, values))

def _detect_environment() -> str:
    """현재 실행 환경을 감지한다."""
    # PyInstaller (Windows EXE 등)
    if getattr(sys, "frozen", False) and sys.platform == "win32":
        return "windows-exe"

    if os.environ.get("PHROLOVA_ENVIRONMENT") == "termux-proot":
        return "termux-proot"
    if sys.platform != "win32" and str(Path(sys.executable).resolve()).startswith("/data/data/"):
        return "termux-native"
    if sys.platform == "win32":
        return "windows-native"
    if sys.platform == "darwin":
        return "macos-native"
    # 그 외 (Linux Native / 개발환경 등)
    return "linux-native"

@router.get("/update")
async def get_update_status():
    """업데이트 상태 및 환경 정보를 반환한다."""
    from app.main import get_updater_service
    updater = get_updater_service()
    info = updater.get_cached_info()
    
    # 환경 정보 추가
    info["environment"] = _detect_environment()
    
    return info

@router.post("/update/check")
async def check_update_now():
    """강제로 업데이트를 즉시 확인한다."""
    from app.main import get_updater_service
    updater = get_updater_service()
    info = await updater.check_update_now()
    
    # 환경 정보 추가
    info["environment"] = _detect_environment()
    
    return info


def _get_log_dir() -> Path:
    """로그 저장 디렉토리의 절대 경로를 반환한다."""
    return get_log_dir()


@router.get("/logs", response_model=list[dict])
async def list_system_logs():
    """logs 디렉토리 내의 모든 service.log 및 service.log.YYYY-MM-DD 파일 목록을 반환한다."""
    log_dir = _get_log_dir()

    if not log_dir.exists():
        return []

    log_files = []
    # service.log* 패턴으로 매칭
    for p in log_dir.glob("service.log*"):
        if p.is_file():
            stat = p.stat()
            line_count = 0
            level_counts = {"error": 0, "warning": 0, "info": 0}
            try:
                with open(p, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line_count += 1
                        upper = line.upper()
                        if " | ERROR " in upper or " | CRITICAL " in upper:
                            level_counts["error"] += 1
                        elif " | WARN " in upper or " | WARNING " in upper:
                            level_counts["warning"] += 1
                        elif " | INFO " in upper:
                            level_counts["info"] += 1
            except Exception:
                pass

            log_files.append({
                "filename": p.name,
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "line_count": line_count,
                "error_count": level_counts["error"],
                "warning_count": level_counts["warning"],
                "info_count": level_counts["info"],
            })

    # 수정 시간 내림차순 정렬 (최신 파일이 위로)
    log_files.sort(key=lambda x: x["modified_at"], reverse=True)
    return log_files


@router.delete("/logs")
async def clear_system_logs():
    """Clear the active service log and remove its rotated backups."""
    log_dir = _get_log_dir()
    if not log_dir.exists():
        return {"message": "시스템 로그가 이미 비어 있습니다.", "cleared_files": 0}

    active_path = (log_dir / "service.log").resolve()
    file_handlers = [
        handler
        for handler in logger.handlers
        if isinstance(handler, TimedRotatingFileHandler)
        and Path(handler.baseFilename).resolve() == active_path
    ]
    log_files = [
        path
        for path in log_dir.glob("service.log*")
        if path.is_file() and path.resolve().parent == log_dir.resolve()
    ]

    cleared_files = 0
    for handler in file_handlers:
        handler.acquire()
    try:
        for path in log_files:
            if file_handlers and path.resolve() == active_path:
                continue
            path.unlink(missing_ok=True)
            cleared_files += 1

        if file_handlers:
            handler = file_handlers[0]
            if handler.stream is not None:
                handler.flush()
                handler.stream.seek(0)
                handler.stream.truncate(0)
            else:
                active_path.write_text("", encoding="utf-8")
            if active_path.exists():
                cleared_files += 1
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"시스템 로그 초기화에 실패했습니다: {exc}",
        ) from exc
    finally:
        for handler in reversed(file_handlers):
            handler.release()

    logger.info("시스템 로그 초기화 완료. 새 로그 기록을 시작합니다.")

    return {
        "message": "현재 로그와 날짜별 백업 로그를 초기화했습니다.",
        "cleared_files": cleared_files,
    }


@router.get("/logs/{filename}/export", response_class=StreamingResponse)
async def export_system_log(filename: str):
    """선택한 로그의 전체 원문을 그대로 내보냅니다. 로그는 변경하지 않습니다."""
    log_dir = _get_log_dir().resolve()
    target = (log_dir / filename).resolve()
    if (Path(filename).name != filename or target.parent != log_dir
            or not target.name.startswith("service.log") or not target.is_file()):
        raise HTTPException(status_code=400, detail="Invalid log file path")
    try:
        stream = target.open("rb")
        try:
            size = os.fstat(stream.fileno()).st_size
        except OSError:
            stream.close()
            raise
    except OSError as exc:
        raise HTTPException(status_code=500, detail="logs.couldNotExport") from exc

    def chunks():
        # 계속 추가되는 실시간 로그도 내보내기 시작 시점의 크기까지만 읽는다.
        remaining = size
        try:
            while remaining > 0:
                chunk = stream.read(min(65536, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk
        finally:
            stream.close()

    return StreamingResponse(chunks(), media_type="application/octet-stream", headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(target.name)}",
        "Cache-Control": "no-store",
    })


@router.get("/logs/{filename:path}")
async def get_system_log(filename: str, lines: int = 1000):
    """특정 로그 파일의 내용을 읽어서 반환한다. (최근 N줄 필터링 지원)"""
    log_dir = _get_log_dir()
    
    # Path Traversal 방지 보안 검증
    target_path = (log_dir / filename).resolve()
    
    try:
        is_safe = target_path.is_relative_to(log_dir)
    except ValueError:
        is_safe = False
        
    if not is_safe or not target_path.exists() or not target_path.is_file():
        raise HTTPException(status_code=400, detail="Invalid log file path")
        
    try:
        with open(target_path, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
            
        total_lines = len(all_lines)
        if lines > 0:
            returned_lines = all_lines[-lines:]
        else:
            returned_lines = all_lines
            
        content = "".join(returned_lines)
        return {
            "filename": filename,
            "content": content,
            "total_lines": total_lines,
            "lines_returned": len(returned_lines)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read log file: {str(e)}")
