"""치지직 쿠키와 인증 상태."""

from __future__ import annotations


from fastapi import APIRouter, HTTPException

from pydantic import BaseModel, Field

from app.api.settings._shared import SETTINGS_PREFIX, SETTINGS_TAGS


# ── 요청 스키마 ──────────────────────────────────────────

router = APIRouter(prefix=SETTINGS_PREFIX, tags=SETTINGS_TAGS)


class CookieUpdateRequest(BaseModel):
    """인증 쿠키 업데이트 요청."""

    nid_aut: str = Field(..., description="NID_AUT 쿠키 값")
    nid_ses: str = Field(..., description="NID_SES 쿠키 값")


@router.put("/cookies", summary="인증 쿠키 업데이트")
async def update_cookies(req: CookieUpdateRequest):
    """치지직 인증 쿠키(NID_AUT, NID_SES)를 업데이트합니다."""
    from app.main import get_recorder_service

    service = get_recorder_service()
    return service.update_cookies(req.nid_aut, req.nid_ses)


@router.post("/cookies/test", summary="쿠키 유효성 검증")
async def test_cookies():
    """현재 설정된 쿠키로 치지직 API에 접근하여 유효성을 검증합니다."""
    import httpx

    from app.main import get_recorder_service

    service = get_recorder_service()
    auth_status = service.get_auth_status()

    if not auth_status["authenticated"]:
        raise HTTPException(
            status_code=400,
            detail="쿠키가 설정되지 않았습니다. 먼저 쿠키를 입력해주세요.",
        )

    try:
        from app.engine.auth import AuthManager

        auth = AuthManager()
        headers = auth.get_http_headers()

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://comm-api.game.naver.com/nng_main/v1/user/getUserStatus",
                headers=headers,
                timeout=10.0,
            )
            data = resp.json()

        if data.get("code") == 200:
            content = data.get("content") or {}
            from app.core.logger import logger as _logger
            _logger.debug(f"getUserStatus content keys: {list(content.keys()) if content else 'empty'}")
            return {
                "valid": True,
                "message": "쿠키 검증 성공! 로그인 상태가 확인되었습니다.",
                "user_status": content,
            }
        else:
            return {
                "valid": False,
                "message": "쿠키가 만료되었거나 유효하지 않습니다.",
            }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"쿠키 검증 중 오류 발생: {e}",
        )


@router.get("/auth", summary="인증 상태 확인")
async def get_auth_status():
    """현재 인증 상태를 확인합니다."""
    from app.main import get_recorder_service

    service = get_recorder_service()
    return service.get_auth_status()


@router.get("/cookie-status", summary="X 쿠키 유효성 상태 조회")
async def get_cookie_status():
    """X Spaces 쿠키의 유효성 상태를 반환합니다.

    쿠키는 하루 1회 자동 검증되며, 이 엔드포인트는 가장 최근 검증 결과를 반환합니다.
    프론트엔드 Settings 페이지 만료 배너에 사용됩니다.
    """
    from app.main import get_recorder_service

    service = get_recorder_service()
    conductor = service._conductor
    return {"x": conductor.get_cookie_status()}


@router.post("/cookie-status/check", summary="X 쿠키 즉시 검증")
async def check_cookie_now():
    """X Spaces 쿠키를 즉시 검증합니다 (24시간 주기 무시)."""
    from app.main import get_recorder_service

    service = get_recorder_service()
    conductor = service._conductor
    await conductor._check_x_cookie()
    return {"x": conductor.get_cookie_status()}
