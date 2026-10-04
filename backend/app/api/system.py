"""
Rookery: System API (시스템 및 업데이트 관리)
"""

import sys
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/system", tags=["System"])

def _detect_environment() -> str:
    """현재 실행 환경을 감지한다."""
    # PyInstaller (Windows EXE 등)
    if getattr(sys, "frozen", False):
        return "windows-exe"

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
    project_root = Path(__file__).resolve().parents[3]
    return (project_root / "logs").resolve()


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
            log_files.append({
                "filename": p.name,
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat()
            })
            
    # 수정 시간 내림차순 정렬 (최신 파일이 위로)
    log_files.sort(key=lambda x: x["modified_at"], reverse=True)
    return log_files


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
