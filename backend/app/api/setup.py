"""
Rookery: 초기 설정 API
최초 실행 감지 및 마법사 완료 처리를 담당한다.

[설계 원칙]
- .env 파일의 존재 여부만으로 초기 설정 완료를 판단한다.
- 신규 사용자: exe 실행 → .env 없음 → 마법사 표시
- 기존 사용자: exe + .env 함께 이동 → 기존 설정값 그대로 실행
- 초기화 원할 때: .env 삭제 후 실행 → 마법사 다시 표시
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.logger import logger
from app.core.utils import _get_env_path, update_env_file as _update_env_file

router = APIRouter(prefix="/api/setup", tags=["Setup"])


def is_setup_complete() -> bool:
    """.env 파일이 존재하고 필수 키(DOWNLOAD_DIR)가 설정돼 있으면 초기 설정 완료로 간주한다."""
    env_path = _get_env_path()
    if not env_path.exists():
        return False
    # 빈 파일이거나 DOWNLOAD_DIR가 없으면 미완성으로 판단
    content = env_path.read_text(encoding="utf-8")
    return any(line.startswith("DOWNLOAD_DIR=") and len(line.split("=", 1)) > 1 and line.split("=", 1)[1].strip()
               for line in content.splitlines())


# ── 요청 스키마 ──────────────────────────────────────────

class SetupCompleteRequest(BaseModel):
    """초기 설정 완료 요청."""

    # Step 1: 기본 설정
    download_dir: str = Field(..., description="녹화 저장 경로")
    live_format: str = Field("ts", description="라이브 녹화 포맷 (ts, mp4, mkv)")
    recording_quality: str = Field("best", description="녹화 품질 (best, 1080p, 720p, 480p)")

    # Step 2: 치지직 인증 (선택)
    nid_aut: Optional[str] = Field(None, description="NID_AUT 쿠키 (선택)")
    nid_ses: Optional[str] = Field(None, description="NID_SES 쿠키 (선택)")


# ── 엔드포인트 ───────────────────────────────────────────

@router.get("/status", summary="초기 설정 완료 여부 확인")
async def get_setup_status():
    """초기 설정이 필요한지 반환한다."""
    return {
        "needs_setup": not is_setup_complete(),
        # Docker 지원은 걷어냈지만 필드는 남긴다. 이미 설치된 구버전 화면이
        # 이 키를 읽으므로, 없애면 그쪽에서 undefined를 만난다.
        "is_docker": False,
    }


@router.post("/complete", summary="초기 설정 완료 처리")
async def complete_setup(req: SetupCompleteRequest):
    """
    마법사 완료 시 설정을 .env에 저장한다.
    이후 서버 재시작 없이 in-memory 설정도 즉시 반영한다.
    """
    VALID_FORMATS = {"ts", "mp4", "mkv"}
    VALID_QUALITIES = {"best", "1080p", "720p", "480p"}

    fmt = req.live_format.lower()
    quality = req.recording_quality.lower()

    if fmt not in VALID_FORMATS:
        raise HTTPException(status_code=400, detail=f"지원하지 않는 포맷: {fmt}")
    if quality not in VALID_QUALITIES:
        raise HTTPException(status_code=400, detail=f"지원하지 않는 품질: {quality}")

    download_dir = req.download_dir

    # 저장 경로 생성
    save_dir = Path(download_dir)
    save_dir.mkdir(parents=True, exist_ok=True)

    # .env 파일에 설정 저장 (이 파일이 생성되면 곧 초기설정 완료를 의미)
    env_updates: dict[str, str] = {
        "DOWNLOAD_DIR": download_dir,
        "LIVE_FORMAT": fmt,
        "RECORDING_QUALITY": quality,
    }
    if req.nid_aut and req.nid_ses:
        env_updates["NID_AUT"] = str(req.nid_aut)
        env_updates["NID_SES"] = str(req.nid_ses)

    _update_env_file(env_updates)

    # in-memory 설정 즉시 반영
    settings = get_settings()
    settings.download_dir = download_dir
    settings.live_format = fmt
    settings.recording_quality = quality
    if req.nid_aut and req.nid_ses:
        settings.nid_aut = req.nid_aut
        settings.nid_ses = req.nid_ses

    # RecorderService의 AuthManager 인스턴스도 즉시 업데이트
    if req.nid_aut and req.nid_ses:
        try:
            from app.main import get_recorder_service
            service = get_recorder_service()
            service.update_cookies(req.nid_aut, req.nid_ses)
        except Exception:
            pass  # 서비스 미초기화 상태면 무시 (Settings에 이미 반영됨)

    logger.info(f"✅ 초기 설정 완료. .env 생성됨: {_get_env_path()}")
    return {"success": True, "message": "초기 설정이 완료되었습니다."}
