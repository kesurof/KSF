"""In-process pub/sub for SSE streaming.

Permet à des producteurs (jobs, notifications, logs) de pousser des events
à des consommateurs SSE sans broker externe.
"""
import asyncio
import json
import logging
from collections import defaultdict
from typing import Any, AsyncIterator

logger = logging.getLogger("ksf-web.events")


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def publish(self, channel: str, event: str, data: Any = None) -> None:
        payload = {"event": event, "data": data}
        for q in list(self._subscribers.get(channel, ())):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass

    async def subscribe(self, channel: str) -> AsyncIterator[dict]:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        async with self._lock:
            self._subscribers[channel].add(q)
        try:
            while True:
                payload = await q.get()
                yield payload
        finally:
            async with self._lock:
                self._subscribers[channel].discard(q)
                if not self._subscribers[channel]:
                    self._subscribers.pop(channel, None)


bus = EventBus()


def sse_format(event: str, data: Any, event_id: str | None = None) -> bytes:
    """Format un message SSE (event:/data:/id: + blank line)."""
    lines = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    if isinstance(data, (dict, list)):
        data = json.dumps(data, default=str)
    for line in str(data).splitlines() or [""]:
        lines.append(f"data: {line}")
    return ("\n".join(lines) + "\n\n").encode("utf-8")
