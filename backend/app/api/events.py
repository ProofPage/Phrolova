import asyncio
import logging
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/api/events", tags=["events"])
logger = logging.getLogger(__name__)

@router.get("")
async def sse_events(request: Request):
    """
    Server-Sent Events(SSE) 엔드포인트.
    클라이언트 연결 시 Conductor의 event_queue에 구독을 추가하고,
    연결이 해제될 경우 큐를 안전하게 제거합니다.
    """
    from app.main import get_recorder_service
    conductor = get_recorder_service()._conductor
    queue = asyncio.Queue(maxsize=100)
    conductor.add_event_queue(queue)

    async def event_generator():
        try:
            # 연결 즉시 최초 상태값 (status_update) 전송
            try:
                import json
                initial_data = conductor.get_all_status()
                payload = {"type": "status_update", "data": initial_data}
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            except Exception as e:
                logger.error(f"SSE Initial status emit error: {e}")

            while True:
                # 클라이언트의 연결이 끊겼는지 주기적으로 체크하기 위해 wait_for 사용
                if await request.is_disconnected():
                    break
                
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=2.0)
                    yield message
                except asyncio.TimeoutError:
                    # 빈번한 타임아웃 시 keep-alive (ping) 전송으로 TCP 커넥션 유지
                    yield ": ping\n\n"
        except asyncio.CancelledError:
            logger.debug("SSE connection cancelled by client.")
        finally:
            conductor.remove_event_queue(queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
