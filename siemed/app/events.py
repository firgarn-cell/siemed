from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, Callable, Awaitable

Listener = Callable[[dict[str, Any]], Awaitable[None] | None]


class EventBus:
    def __init__(self) -> None:
        self._listeners: dict[str, list[Listener]] = defaultdict(list)
        self._ws_clients: list[asyncio.Queue] = []

    def on(self, name: str, fn: Listener) -> None:
        self._listeners[name].append(fn)

    async def emit(self, name: str, payload: dict[str, Any] | None = None) -> None:
        data = {"event": name, **(payload or {})}
        for fn in list(self._listeners.get(name, [])):
            res = fn(data)
            if asyncio.iscoroutine(res):
                await res
        for fn in list(self._listeners.get("*", [])):
            res = fn(data)
            if asyncio.iscoroutine(res):
                await res
        dead = []
        for q in self._ws_clients:
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._ws_clients.remove(q)

    def subscribe_ws(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._ws_clients.append(q)
        return q

    def unsubscribe_ws(self, q: asyncio.Queue) -> None:
        if q in self._ws_clients:
            self._ws_clients.remove(q)


bus = EventBus()
