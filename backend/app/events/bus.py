"""Job event bus: Redis streams in production, in-process queues for dev/tests.

Event = {"id": stream id, "type": status|progress|metric|log|end, "ts": iso, "data": {...}}
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, Protocol

from app.core.config import get_settings

MAXLEN = 10_000
REPLAY = 200


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class EventBus(Protocol):
    async def publish(self, job_id: int, type_: str, data: dict[str, Any]) -> str: ...
    async def replay(self, job_id: int, limit: int = REPLAY) -> list[dict[str, Any]]: ...
    def subscribe(self, job_id: int, last_id: str | None = None) -> AsyncIterator[dict[str, Any]]: ...
    async def close(self) -> None: ...


class MemoryEventBus:
    def __init__(self) -> None:
        self._buffers: dict[int, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=MAXLEN))
        self._queues: dict[int, list[asyncio.Queue[dict[str, Any]]]] = defaultdict(list)
        self._seq = 0

    async def publish(self, job_id: int, type_: str, data: dict[str, Any]) -> str:
        self._seq += 1
        ev = {"id": f"{int(time.time() * 1000)}-{self._seq}", "type": type_, "ts": _now_iso(), "data": data}
        self._buffers[job_id].append(ev)
        for q in list(self._queues[job_id]):
            q.put_nowait(ev)
        return ev["id"]

    async def replay(self, job_id: int, limit: int = REPLAY) -> list[dict[str, Any]]:
        return list(self._buffers[job_id])[-limit:]

    async def subscribe(self, job_id: int, last_id: str | None = None) -> AsyncIterator[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._queues[job_id].append(q)
        try:
            for ev in await self.replay(job_id):
                if last_id is None or ev["id"] > last_id:
                    yield ev
            while True:
                ev = await q.get()
                yield ev
                if ev["type"] == "end":
                    return
        finally:
            self._queues[job_id].remove(q)

    async def close(self) -> None:
        return None


class RedisEventBus:
    def __init__(self, url: str) -> None:
        import redis.asyncio as redis

        self._r = redis.from_url(url, decode_responses=True)

    @staticmethod
    def _key(job_id: int) -> str:
        return f"job:{job_id}:events"

    async def publish(self, job_id: int, type_: str, data: dict[str, Any]) -> str:
        return await self._r.xadd(
            self._key(job_id),
            {"type": type_, "ts": _now_iso(), "data": json.dumps(data, ensure_ascii=False)},
            maxlen=MAXLEN,
            approximate=True,
        )

    @staticmethod
    def _decode(sid: str, fields: dict[str, str]) -> dict[str, Any]:
        return {"id": sid, "type": fields["type"], "ts": fields["ts"], "data": json.loads(fields["data"])}

    async def replay(self, job_id: int, limit: int = REPLAY) -> list[dict[str, Any]]:
        rows = await self._r.xrevrange(self._key(job_id), count=limit)
        return [self._decode(sid, f) for sid, f in reversed(rows)]

    async def subscribe(self, job_id: int, last_id: str | None = None) -> AsyncIterator[dict[str, Any]]:
        cursor = last_id
        if cursor is None:
            for ev in await self.replay(job_id):
                yield ev
                cursor = ev["id"]
            cursor = cursor or "0-0"
        while True:
            rows = await self._r.xread({self._key(job_id): cursor}, block=15_000, count=100)
            if not rows:
                yield {"id": cursor, "type": "keepalive", "ts": _now_iso(), "data": {}}
                continue
            for _key, entries in rows:
                for sid, fields in entries:
                    ev = self._decode(sid, fields)
                    cursor = sid
                    yield ev
                    if ev["type"] == "end":
                        return

    async def close(self) -> None:
        await self._r.aclose()


_bus: EventBus | None = None


def get_bus() -> EventBus:
    global _bus
    if _bus is None:
        url = get_settings().redis_url
        _bus = RedisEventBus(url) if url else MemoryEventBus()
    return _bus


def reset_bus() -> None:
    global _bus
    _bus = None
