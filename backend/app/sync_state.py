from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from threading import Lock


class SyncState:
    """Process-local revision used to notify every LAN client of mutations."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._revision = 0
        self._changed_at: str | None = None
        self._method: str | None = None
        self._path: str | None = None
        self._subscribers: set[asyncio.Queue[dict[str, object]]] = set()

    def publish(self, method: str, path: str) -> dict[str, object]:
        with self._lock:
            self._revision += 1
            self._changed_at = datetime.now(timezone.utc).isoformat()
            self._method = method
            self._path = path
            return self.snapshot()

    def snapshot(self) -> dict[str, object]:
        return {
            "revision": self._revision,
            "changed_at": self._changed_at,
            "method": self._method,
            "path": self._path,
        }

    def subscribe(self) -> asyncio.Queue[dict[str, object]]:
        queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=20)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, object]]) -> None:
        self._subscribers.discard(queue)

    async def broadcast(self, payload: dict[str, object]) -> None:
        for queue in tuple(self._subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                pass


sync_state = SyncState()
