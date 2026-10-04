"""
Rookery: 공용 HTTP 클라이언트

라이브 감지 폴링은 채널 수 × 폴링 주기만큼 반복 실행된다.
기존에는 폴링 한 번마다 httpx.AsyncClient를 새로 만들고 버렸기 때문에
매번 TCP 연결과 TLS 핸드셰이크를 다시 했다. 채널이 늘어날수록 손해가 커진다.

여기서는 커넥션 풀을 유지하는 클라이언트 하나를 공유한다.
쿠키 세션을 따로 유지해야 하는 호출(X Spaces)은 이 클라이언트를 쓰지 않고
각자 클라이언트를 만든다 — 쿠키 재킷이 섞이면 안 되기 때문이다.
"""

from __future__ import annotations

import asyncio
from typing import Optional

import httpx

from app.core.logger import logger

#: 플랫폼 API가 봇 트래픽으로 차단하지 않도록 일반 브라우저 UA를 사용한다.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

#: 라이브 상태 조회 기본 타임아웃 (초). 감시 루프를 오래 붙잡지 않도록 짧게 잡는다.
DEFAULT_TIMEOUT = 10.0

#: 커넥션 풀 상한. 감시 채널이 수십 개여도 충분하다.
_LIMITS = httpx.Limits(max_connections=32, max_keepalive_connections=16)

_client: Optional[httpx.AsyncClient] = None
#: 클라이언트를 만든 이벤트 루프. 커넥션 풀이 루프에 묶이기 때문에 추적한다.
_client_loop: Optional[asyncio.AbstractEventLoop] = None


def get_http_client() -> httpx.AsyncClient:
    """공용 AsyncClient를 반환한다 (최초 호출 시 생성).

    커넥션 풀은 생성 당시의 이벤트 루프에 묶인다. 루프가 바뀌면
    (uvicorn --reload, 테스트 등) 기존 풀은 쓸 수 없으므로 새로 만든다.
    """
    global _client, _client_loop

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if _client is not None and not _client.is_closed and _client_loop is loop:
        return _client

    # 이전 클라이언트는 루프가 이미 닫혔을 수 있어 await 없이 버린다.
    # 소켓은 GC가 정리하며, 루프가 살아있는 정상 종료 경로에서는
    # close_http_client()가 먼저 호출된다.
    _client = httpx.AsyncClient(
        timeout=DEFAULT_TIMEOUT,
        limits=_LIMITS,
        headers={"User-Agent": USER_AGENT},
    )
    _client_loop = loop
    return _client


async def close_http_client() -> None:
    """공용 클라이언트를 닫는다. 앱 종료 시 호출한다."""
    global _client, _client_loop
    client = _client
    _client = None
    _client_loop = None
    if client is not None and not client.is_closed:
        try:
            await client.aclose()
        except Exception as e:
            logger.warning(f"HTTP 클라이언트 종료 실패: {e}")
