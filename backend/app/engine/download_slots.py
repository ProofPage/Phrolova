"""Resizable download slots; reducing the limit never interrupts active downloads."""

import asyncio
from collections import deque


class DownloadSlots:
    def __init__(self, limit: int):
        self.limit = limit
        self.active = 0
        self._waiting = deque()

    def set_limit(self, limit: int):
        if not 1 <= limit <= 10:
            raise ValueError("동시 다운로드 개수는 1~10개여야 합니다.")
        self.limit = limit
        self._wake()

    def _wake(self):
        while self._waiting and self.active < self.limit:
            future = self._waiting.popleft()
            if not future.done():
                self.active += 1
                future.set_result(True)

    async def acquire(self):
        if not self._waiting and self.active < self.limit:
            self.active += 1
            return True
        future = asyncio.get_running_loop().create_future()
        self._waiting.append(future)
        try:
            return await future
        except asyncio.CancelledError:
            if not future.cancelled():
                self.active -= 1  # Cancelled after a slot was granted.
            try:
                self._waiting.remove(future)
            except ValueError:
                pass
            self._wake()
            raise

    def release(self):
        if self.active <= 0:
            raise RuntimeError("반환할 다운로드 슬롯이 없습니다.")
        self.active -= 1
        self._wake()

    def locked(self):
        return self.active >= self.limit

    async def __aenter__(self):
        await self.acquire()

    async def __aexit__(self, *_):
        self.release()
