"""X Spaces 지원.

한 파일에 763줄이 들어 있었다. 호출 방향이 엔진 → API → 쿠키 한쪽으로만
흐르는 것을 확인하고 그 층대로 나눴다.

  constants.py  엔드포인트·GraphQL 쿼리 ID·Space 상태값
  cookies.py    쿠키 파싱, 헤더 생성, 유효성 확인
  api.py        GraphQL 호출과 응답 파싱 (쿠키를 모른다)
  engine.py     상태 판단과 녹화 기동

밖에서 쓰던 이름은 여기서 그대로 내준다.
"""

from app.engine.x_spaces.constants import (
    SPACE_STATE_ENDED,
    SPACE_STATE_NOT_STARTED,
    SPACE_STATE_RUNNING,
    X_SPACES_URL,
)
from app.engine.x_spaces.cookies import verify_cookie
from app.engine.x_spaces.engine import XSpacesEngine

__all__ = [
    "SPACE_STATE_ENDED",
    "SPACE_STATE_NOT_STARTED",
    "SPACE_STATE_RUNNING",
    "X_SPACES_URL",
    "XSpacesEngine",
    "verify_cookie",
]
