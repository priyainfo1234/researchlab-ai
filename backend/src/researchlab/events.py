"""Event bus: assigns sequence numbers, persists every event, fans out to live listeners."""

from __future__ import annotations

import asyncio
from collections import defaultdict

from .schemas import EventType, RunEvent, utcnow
from .store import Store


class EventBus:
    def __init__(self, store: Store) -> None:
        self._store = store
        self._seq: dict[str, int] = defaultdict(int)
        self._subs: dict[str, set[asyncio.Queue[RunEvent]]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def emit(
        self,
        run_id: str,
        type: EventType,
        message: str,
        *,
        agent: str | None = None,
        task_id: str | None = None,
        data: dict | None = None,
    ) -> RunEvent:
        async with self._lock:  # seq assignment + persistence stay ordered
            self._seq[run_id] += 1
            ev = RunEvent(
                run_id=run_id,
                seq=self._seq[run_id],
                ts=utcnow(),
                type=type,
                agent=agent,
                task_id=task_id,
                message=message,
                data=data or {},
            )
            await self._store.append_event(ev)
        for q in list(self._subs[run_id]):
            q.put_nowait(ev)
        return ev

    def subscribe(self, run_id: str) -> asyncio.Queue[RunEvent]:
        q: asyncio.Queue[RunEvent] = asyncio.Queue()
        self._subs[run_id].add(q)
        return q

    def unsubscribe(self, run_id: str, q: asyncio.Queue[RunEvent]) -> None:
        self._subs[run_id].discard(q)
        if not self._subs[run_id]:
            self._subs.pop(run_id, None)

    def forget(self, run_id: str) -> None:
        self._seq.pop(run_id, None)
