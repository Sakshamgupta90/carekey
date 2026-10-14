"""In-process pub/sub that feeds the live screens over Server-Sent Events."""

from __future__ import annotations

import asyncio
import json


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def publish(self, message: dict) -> None:
        """Safe to call from any thread, including FastAPI background tasks."""
        if not self._loop or not self._subscribers:
            return
        data = json.dumps(message, default=str)
        for queue in list(self._subscribers):
            self._loop.call_soon_threadsafe(_offer, queue, data)


def _offer(queue: asyncio.Queue, data: str) -> None:
    try:
        queue.put_nowait(data)
    except asyncio.QueueFull:
        pass  # a stalled screen shouldn't block everyone else
