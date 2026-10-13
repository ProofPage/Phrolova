"""호환성을 위해 기존 detail을 보존하고 표시용 키만 추가한다."""
from starlette.exceptions import HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder

STATUS_KEYS = {
    400: "errors.invalidInput", 401: "errors.authentication", 403: "errors.authentication",
    404: "errors.notFound", 408: "errors.timeout", 409: "errors.conflict",
    422: "errors.invalidInput", 429: "errors.rateLimited", 500: "errors.server",
    502: "errors.network", 503: "errors.network", 504: "errors.timeout",
}

async def localized_http_error(_request, exc: HTTPException):
    # 서버 로그와 구버전 클라이언트가 읽는 원문 및 상태 코드는 바꾸지 않는다.
    return JSONResponse(
        {"detail": exc.detail, "message_key": STATUS_KEYS.get(exc.status_code, "errors.request")},
        status_code=exc.status_code, headers=exc.headers,
    )


async def localized_validation_error(_request, exc: RequestValidationError):
    # FastAPI의 검증 상세 구조를 유지하되 입력 오류도 같은 표시 계약을 사용한다.
    return JSONResponse(
        {"detail": jsonable_encoder(exc.errors()), "message_key": "errors.invalidInput"},
        status_code=422,
    )
