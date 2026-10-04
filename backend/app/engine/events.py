"""
Rookery: SSE 이벤트 버스

프론트엔드가 구독하는 Server-Sent Events 스트림에 상태 변화를 밀어낸다.
Conductor에 섞여 있던 pub-sub 로직을 분리해 단위 테스트가 가능하게 했다.
"""

from __future__ import annotations

import asyncio
import json
from typing import Optional

from app.core.logger import logger


class EventBus:
    """SSE 구독자에게 이벤트를 브로드캐스트한다.

    구독자는 asyncio.Queue 하나씩을 들고 있으며, 큐가 가득 찬 느린 구독자는
    건너뛴다 — 한 클라이언트가 밀렸다고 녹화 루프가 막히면 안 되기 때문이다.
    """

    def __init__(self) -> None:
        self._queues: list[asyncio.Queue] = []

    @property
    def subscriber_count(self) -> int:
        return len(self._queues)

    def subscribe(self, queue: asyncio.Queue) -> None:
        """구독자 큐를 등록한다."""
        if queue not in self._queues:
            self._queues.append(queue)

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        """구독자 큐를 해제한다."""
        if queue in self._queues:
            self._queues.remove(queue)

    def publish(self, event_type: str, data: Optional[dict | list] = None) -> None:
        """모든 구독자에게 이벤트를 전달한다. 블록되지 않는다."""
        if not self._queues:
            return

        payload: dict = {"type": event_type}
        if data is not None:
            payload["data"] = data

        try:
            msg = f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        except (TypeError, ValueError) as e:
            # 직렬화 실패가 호출부(감시 루프)로 전파되면 안 된다.
            logger.error(f"SSE 이벤트 직렬화 실패 ({event_type}): {e}")
            return

        for queue in self._queues:
            try:
                queue.put_nowait(msg)
            except asyncio.QueueFull:
                # 느린 구독자는 건너뛴다. 다음 status_update로 따라잡는다.
                pass
