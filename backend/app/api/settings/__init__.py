"""설정 API.

한 파일에 639줄, 라우트 14개가 들어 있었다. 도메인이 넷으로 뚜렷하게 갈려서
그대로 나눴다. 경로는 한 글자도 바뀌지 않는다 — prefix는 여기서만 붙이고,
각 모듈은 접두어 없는 라우터에 자기 경로만 단다.

  general.py        저장 경로·감시 주기·녹화 형식·전체 조회
  media.py          라이브 녹화·VOD 다운로드
  auth.py           쿠키와 인증 상태
  notifications.py  Discord와 알림
  _shared.py        여러 도메인이 함께 쓰는 헬퍼와 허용값
"""

from fastapi import APIRouter

from app.api.settings import auth, general, media, notifications

# prefix는 각 도메인 라우터가 들고 있다 — 빈 경로(GET /api/settings)를
# prefix 없는 라우터에는 달 수 없기 때문이다.
router = APIRouter()

# 경로가 모두 고유해서 include 순서는 매칭에 영향을 주지 않는다.
router.include_router(general.router)
router.include_router(media.router)
router.include_router(auth.router)
router.include_router(notifications.router)

__all__ = ["router"]
